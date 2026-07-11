from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from lmstudio_labkit.managed_executor import (
    _native_image_input,
    _validate_native_image_input,
)

from lmstudio_labkit import (
    LocalFailureForensics,
    LocalLMStudioHostRunner,
    ManagedExecutorError,
)


class _SSEHeaders:
    def get_content_type(self) -> str:
        return "text/event-stream"


class _SSEResponse:
    status = 200
    headers = _SSEHeaders()

    def __enter__(self) -> _SSEResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return (
            b"event: reasoning.delta\n"
            b'data: {"type":"reasoning.delta","delta":"private thought"}\n\n'
            b"event: message.delta\n"
            b'data: {"type":"message.delta","delta":"{\\"id\\":1}"}\n\n'
            b"event: chat.end\n"
            b'data: {"type":"chat.end","result":{"stats":{"total_output_tokens":8,"reasoning_output_tokens":4},"stop_reason":"eos"}}\n\n'
        )


class _JSONResponse:
    status = 200

    class _Headers:
        def get_content_type(self) -> str:
            return "application/json"

    headers = _Headers()

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> _JSONResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_native_diagnostic_requires_explicit_opt_in() -> None:
    runner = LocalLMStudioHostRunner()

    with pytest.raises(ManagedExecutorError, match="allow_native_diagnostics=true"):
        runner.native_chat_diagnostic(
            model_id="mock/text",
            messages=({"role": "user", "content": "Synthetic request"},),
            reasoning="off",
            max_output_tokens=1024,
            timeout_s=15.0,
        )


@pytest.mark.parametrize("cap", [0, 512, 1536, 10000])
def test_native_diagnostic_rejects_caps_outside_bounded_staircase(cap: int) -> None:
    runner = LocalLMStudioHostRunner(allow_native_diagnostics=True)

    with pytest.raises(ManagedExecutorError, match="1024, 2048, 3072, 4096, 6144, 8192"):
        runner.native_chat_diagnostic(
            model_id="mock/text",
            messages=({"role": "user", "content": "Synthetic request"},),
            reasoning="off",
            max_output_tokens=cap,
            timeout_s=15.0,
        )


def test_native_diagnostic_rejects_undocumented_reasoning_value() -> None:
    runner = LocalLMStudioHostRunner(allow_native_diagnostics=True)

    with pytest.raises(ManagedExecutorError, match="off, on, low, medium, high"):
        runner.native_chat_diagnostic(
            model_id="mock/text",
            messages=({"role": "user", "content": "Synthetic request"},),
            reasoning="invented",
            max_output_tokens=1024,
            timeout_s=15.0,
        )


def test_native_diagnostic_requires_enabled_private_forensics_before_request() -> None:
    runner = LocalLMStudioHostRunner(allow_native_diagnostics=True)

    with pytest.raises(ManagedExecutorError, match="enabled local failure forensics"):
        runner.native_chat_diagnostic(
            model_id="mock/text",
            messages=({"role": "user", "content": "Synthetic request"},),
            reasoning="off",
            max_output_tokens=1024,
            timeout_s=15.0,
        )


def test_native_diagnostic_serializes_route_controls_and_captures_private_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[dict[str, Any]] = []
    fixture = Path(__file__).parents[2] / (
        "experiments/lmstudio/structured_matrix/datasets/image/gemma_vision/"
        "fixtures/ui_settings_ru_001.png"
    )
    image_data_url = "data:image/png;base64," + base64.b64encode(fixture.read_bytes()).decode(
        "ascii"
    )

    def fake_urlopen(req: object, timeout: float | None = None) -> _SSEResponse | _JSONResponse:
        if req.full_url.endswith("/api/v1/models"):  # type: ignore[attr-defined]
            requests.append(
                {
                    "url": req.full_url,  # type: ignore[attr-defined]
                    "method": req.get_method(),  # type: ignore[attr-defined]
                    "timeout": timeout,
                }
            )
            return _JSONResponse(
                {
                    "models": [
                        {
                            "key": "mock/text",
                            "capabilities": {
                                "reasoning": {
                                    "allowed_options": ["off", "on"],
                                    "default": "on",
                                }
                            },
                        }
                    ]
                }
            )
        requests.append(
            {
                "url": req.full_url,  # type: ignore[attr-defined]
                "headers": dict(req.header_items()),  # type: ignore[attr-defined]
                "payload": json.loads(req.data.decode("utf-8")),  # type: ignore[attr-defined]
                "timeout": timeout,
            }
        )
        return _SSEResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    repo = tmp_path / "repo"
    repo.mkdir()
    forensics = LocalFailureForensics(tmp_path / "private", repo_root=repo, enabled=True)
    runner = LocalLMStudioHostRunner(
        allow_native_diagnostics=True,
        failure_forensics=forensics,
    )

    result = runner.native_chat_diagnostic(
        model_id="mock/text",
        messages=({"role": "user", "content": "Synthetic request"},),
        reasoning="on",
        max_output_tokens=2048,
        timeout_s=15.0,
        request_id="native-cell",
        attempt_index=2,
        context_length=16384,
        image_data_url=image_data_url,
    )

    assert requests == [
        {
            "url": "http://127.0.0.1:1234/api/v1/models",
            "method": "GET",
            "timeout": 120.0,
        },
        {
            "url": "http://127.0.0.1:1234/api/v1/chat",
            "headers": {
                "Content-type": "application/json",
                "Accept": "text/event-stream",
            },
            "payload": {
                "model": "mock/text",
                "input": [
                    {"type": "text", "content": "Synthetic request"},
                    {"type": "image", "data_url": image_data_url},
                ],
                "reasoning": "on",
                "max_output_tokens": 2048,
                "temperature": 0.0,
                "stream": True,
                "store": False,
            },
            "timeout": 15.0,
        },
    ]
    native_payload = requests[1]["payload"]
    assert native_payload["input"][0]["type"] == "text"
    assert native_payload["input"][1]["data_url"].startswith("data:image/png;base64,")
    assert native_payload["input"][1]["data_url"].partition(",")[2]
    assert "messages" not in native_payload
    assert result.reasoning_text == "private thought"
    assert result.message_text == '{"id":1}'
    assert result.reasoning_allowed_options == ("off", "on")
    assert result.reasoning_default == "on"
    assert result.forensics_handle is not None
    private_payload = json.loads(result.forensics_handle.path.read_text(encoding="utf-8"))
    assert private_payload["raw"]["sse_frames"][0]["event"] == "reasoning.delta"
    assert private_payload["attempt"]["context_length"] == 16384
    manifest = forensics.safe_manifest_entry(result.forensics_handle)
    assert "private thought" not in json.dumps(manifest)
    assert "Synthetic request" not in result.forensics_handle.path.read_text(encoding="utf-8")


def test_native_diagnostic_supports_omitted_reasoning_and_higher_review_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[dict[str, Any]] = []

    def fake_urlopen(req: object, timeout: float | None = None) -> _SSEResponse:
        requests.append(
            {
                "url": req.full_url,  # type: ignore[attr-defined]
                "payload": json.loads(req.data.decode("utf-8")),  # type: ignore[attr-defined]
                "timeout": timeout,
            }
        )
        return _SSEResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = LocalLMStudioHostRunner(
        allow_native_diagnostics=True,
        failure_forensics=LocalFailureForensics(
            tmp_path / "private",
            repo_root=repo,
            enabled=True,
        ),
    )

    result = runner.native_chat_diagnostic(
        model_id="mock/unknown-reasoning",
        messages=({"role": "user", "content": "Synthetic request"},),
        reasoning=None,
        max_output_tokens=8192,
        timeout_s=15.0,
    )

    assert requests[0]["url"].endswith("/api/v1/chat")
    assert requests[0]["payload"]["max_output_tokens"] == 8192
    assert "reasoning" not in requests[0]["payload"]
    assert result.reasoning_allowed_options == ()
    assert result.reasoning_default is None


def test_native_image_input_rejects_multiple_user_prompts() -> None:
    with pytest.raises(ManagedExecutorError, match="exactly one non-empty user prompt"):
        _native_image_input(
            [{"type": "text", "content": "first"}, {"type": "text", "content": "second"}],
            "data:image/png;base64,ignored",
        )


@pytest.mark.parametrize(
    ("native_input", "message"),
    [
        (
            [
                {"type": "message", "content": "prompt"},
                {"type": "image", "data_url": "data:image/png;base64,ignored"},
            ],
            "text first",
        ),
        (
            [
                {"type": "image", "data_url": "data:image/png;base64,ignored"},
                {"type": "text", "content": "prompt"},
            ],
            "exact text item",
        ),
        (
            [
                {"type": "text", "content": "prompt"},
                {"type": "image", "data_url": "data:image/png;base64,ignored"},
                {"type": "image", "data_url": "data:image/png;base64,ignored"},
            ],
            "exactly one image",
        ),
        (
            [
                {"type": "text", "content": "prompt"},
                {"type": "image", "url": "data:image/png;base64,ignored"},
            ],
            "exact image item",
        ),
        (
            [
                {"type": "text", "content": "prompt"},
                {"type": "image", "data_url": "data:image/webp;base64,ignored"},
            ],
            "PNG data URL",
        ),
        (
            [
                {"type": "text", "content": "prompt"},
                {"type": "image", "data_url": "bare-base64"},
            ],
            "PNG data URL",
        ),
    ],
)
def test_native_image_input_validator_fails_closed(native_input: object, message: str) -> None:
    with pytest.raises(ManagedExecutorError, match=message):
        _validate_native_image_input(native_input)


def test_native_diagnostic_rejects_reasoning_not_advertised_by_exact_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []

    def fake_urlopen(req: object, timeout: float | None = None) -> _JSONResponse:
        del timeout
        requests.append(req.full_url)  # type: ignore[attr-defined]
        return _JSONResponse(
            {
                "models": [
                    {
                        "key": "mock/text",
                        "capabilities": {
                            "reasoning": {
                                "allowed_options": ["on"],
                                "default": "on",
                            }
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = LocalLMStudioHostRunner(
        allow_native_diagnostics=True,
        failure_forensics=LocalFailureForensics(
            tmp_path / "private",
            repo_root=repo,
            enabled=True,
        ),
    )

    with pytest.raises(ManagedExecutorError, match="not advertised by exact model mock/text"):
        runner.native_chat_diagnostic(
            model_id="mock/text",
            messages=({"role": "user", "content": "Synthetic request"},),
            reasoning="off",
            max_output_tokens=1024,
            timeout_s=15.0,
        )

    assert requests == ["http://127.0.0.1:1234/api/v1/models"]


def test_local_runner_reports_global_loaded_count_and_exact_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(req: object, timeout: float | None = None) -> _JSONResponse:
        del req, timeout
        return _JSONResponse(
            {
                "models": [
                    {
                        "key": "mock/text",
                        "capabilities": {"reasoning": {"allowed_options": ["off", "on"]}},
                        "loaded_instances": [{"id": "instance-a"}],
                    },
                    {
                        "key": "mock/other",
                        "loaded_instances": [{"id": "instance-b"}],
                    },
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    runner = LocalLMStudioHostRunner()

    assert runner.count_all_loaded_instances() == 2
    metadata = runner.model_metadata(model_id="mock/text")
    assert metadata is not None
    assert metadata["key"] == "mock/text"
    assert runner.model_metadata(model_id="mock/missing") is None
