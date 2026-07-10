from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lmstudio_labkit import LocalFailureForensics, LocalLMStudioHostRunner, ManagedExecutorError


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


@pytest.mark.parametrize("cap", [0, 512, 1536, 8192])
def test_native_diagnostic_rejects_caps_outside_bounded_staircase(cap: int) -> None:
    runner = LocalLMStudioHostRunner(allow_native_diagnostics=True)

    with pytest.raises(ManagedExecutorError, match="1024, 2048, 3072, 4096"):
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
        image_data_url="data:image/png;base64,cHVibGljLXNhZmU=",
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
                    {"type": "image", "data_url": "data:image/png;base64,cHVibGljLXNhZmU="},
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
