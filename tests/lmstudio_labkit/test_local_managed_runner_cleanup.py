from __future__ import annotations

import io
import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError

import pytest
from lmstudio_labkit.managed_executor import LocalLMStudioHostRunner, ManagedExecutorError


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_local_runner_unloads_visible_instance_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []
    model_payload = {
        "models": [
            {
                "key": "google/gemma-4-e2b",
                "loaded_instances": [
                    {"id": "google/gemma-4-e2b"},
                    {"id": "google/gemma-4-e2b:2"},
                ],
            }
        ]
    }

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        path = str(req.full_url).removeprefix("http://127.0.0.1:1234")  # type: ignore[attr-defined]
        data = getattr(req, "data", None)
        payload = json.loads(data.decode("utf-8")) if data else None
        calls.append((path, payload))
        if path == "/api/v1/models":
            return _FakeResponse(model_payload)
        assert path == "/api/v1/models/unload"
        assert payload in [
            {"instance_id": "google/gemma-4-e2b"},
            {"instance_id": "google/gemma-4-e2b:2"},
        ]
        model_payload["models"] = [{"key": "google/gemma-4-e2b", "loaded_instances": []}]
        return _FakeResponse({"status": "unloaded"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    runner = LocalLMStudioHostRunner()
    result = runner.cleanup_model(model_id="google/gemma-4-e2b")

    assert result == {"cleanup_verified": True}
    assert calls == [
        ("/api/v1/models", None),
        ("/api/v1/models/unload", {"instance_id": "google/gemma-4-e2b"}),
        ("/api/v1/models/unload", {"instance_id": "google/gemma-4-e2b:2"}),
        ("/api/v1/models", None),
    ]


def test_local_runner_reports_nested_safe_http_error_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(req: object, timeout: float | None = None) -> object:
        raise HTTPError(
            url="http://127.0.0.1:1234/api/v1/models/unload",
            code=400,
            msg="Bad Request",
            hdrs=Message(),
            fp=io.BytesIO(
                b'{"error":{"message":"Missing required field instance_id",'
                b'"type":"invalid_request","code":"missing_required_parameter",'
                b'"param":"instance_id"}}'
            ),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    runner = LocalLMStudioHostRunner()
    with pytest.raises(ManagedExecutorError) as error:
        runner._request_json("/api/v1/models/unload", {"model": "m"}, 1.0)

    message = str(error.value)
    assert "LM Studio HTTP error: 400 at /api/v1/models/unload" in message
    assert "message='Missing required field instance_id'" in message
    assert "param='instance_id'" in message
    assert "type='invalid_request'" in message


@pytest.mark.parametrize("max_tokens", [1, 1024, 32768])
def test_local_runner_serializes_explicit_max_tokens_unchanged(
    monkeypatch: pytest.MonkeyPatch, max_tokens: int
) -> None:
    payloads: list[dict[str, object]] = []

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        data = getattr(req, "data", None)
        assert isinstance(data, bytes)
        payloads.append(json.loads(data.decode("utf-8")))
        return _FakeResponse({"choices": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    runner = LocalLMStudioHostRunner()
    runner.chat_completion(
        endpoint_path="/v1/chat/completions",
        model_id="mock/text",
        messages=({"role": "user", "content": "Synthetic request"},),
        response_format={"type": "json_schema"},
        max_tokens=max_tokens,
        temperature=0.0,
        timeout_s=15.0,
    )

    assert payloads[0]["max_tokens"] == max_tokens


def test_local_runner_omits_max_tokens_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict[str, object]] = []

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        data = getattr(req, "data", None)
        assert isinstance(data, bytes)
        payloads.append(json.loads(data.decode("utf-8")))
        return _FakeResponse({"choices": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    runner = LocalLMStudioHostRunner()
    runner.chat_completion(
        endpoint_path="/v1/chat/completions",
        model_id="mock/text",
        messages=({"role": "user", "content": "Synthetic request"},),
        response_format={"type": "json_schema"},
        temperature=0.0,
        timeout_s=15.0,
    )

    assert "max_tokens" not in payloads[0]
