from __future__ import annotations

import json
from typing import Any
from urllib import request as urllib_request

from lmstudio_labkit.preflight import preflight_lmstudio_readonly

from lmstudio_labkit import preflight as preflight_module


class _FakeSocket:
    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_preflight_lmstudio_readonly_uses_only_tcp_and_allowed_get_model_endpoints(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    tcp_calls: list[tuple[str, int, float | None]] = []
    http_requests: list[urllib_request.Request] = []

    def fake_create_connection(
        address: tuple[str, int], timeout: float | None = None
    ) -> _FakeSocket:
        host, port = address
        tcp_calls.append((host, port, timeout))
        return _FakeSocket()

    def fake_urlopen(req: urllib_request.Request, timeout: float | None = None) -> _FakeResponse:
        assert timeout == 3.0
        http_requests.append(req)
        return _FakeResponse({"data": [{"id": "fake-model"}]})

    monkeypatch.setattr(preflight_module.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(preflight_module.urllib_request, "urlopen", fake_urlopen)

    result = preflight_lmstudio_readonly("http://127.0.0.1:1234")

    assert result["status"] == "pass"
    assert tcp_calls == [("127.0.0.1", 1234, 1.0)]
    assert [req.get_method() for req in http_requests] == ["GET", "GET"]
    assert [req.full_url for req in http_requests] == [
        "http://127.0.0.1:1234/v1/models",
        "http://127.0.0.1:1234/api/v1/models",
    ]
    assert result["model_counts"] == {"/v1/models": 1, "/api/v1/models": 1}


def test_preflight_lmstudio_readonly_does_not_call_mutating_generation_or_download_endpoints(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    http_requests: list[urllib_request.Request] = []

    monkeypatch.setattr(
        preflight_module.socket,
        "create_connection",
        lambda address, timeout=None: _FakeSocket(),
    )

    def fake_urlopen(req: urllib_request.Request, timeout: float | None = None) -> _FakeResponse:
        http_requests.append(req)
        return _FakeResponse({"models": []})

    monkeypatch.setattr(preflight_module.urllib_request, "urlopen", fake_urlopen)

    preflight_lmstudio_readonly("http://localhost:1234")

    requested_urls = [req.full_url for req in http_requests]
    serialized_requests = json.dumps(
        [{"method": req.get_method(), "url": req.full_url} for req in http_requests],
        sort_keys=True,
    )
    assert requested_urls == [
        "http://localhost:1234/v1/models",
        "http://localhost:1234/api/v1/models",
    ]
    assert all(req.get_method() == "GET" for req in http_requests)
    assert "POST" not in serialized_requests
    assert "/v1/chat/completions" not in serialized_requests
    assert "/v1/responses" not in serialized_requests
    assert "/v1/completions" not in serialized_requests
    assert "/v1/embeddings" not in serialized_requests
    assert "/api/v1/chat" not in serialized_requests
    assert "load" not in serialized_requests.lower()
    assert "unload" not in serialized_requests.lower()
    assert "download" not in serialized_requests.lower()


def test_preflight_lmstudio_readonly_persists_safe_endpoint_classification_only(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setattr(
        preflight_module.socket,
        "create_connection",
        lambda address, timeout=None: _FakeSocket(),
    )
    monkeypatch.setattr(
        preflight_module.urllib_request,
        "urlopen",
        lambda req, timeout=None: _FakeResponse({"data": []}),
    )

    result = preflight_lmstudio_readonly("http://127.0.0.1:1234/private/path")
    serialized = json.dumps(result, sort_keys=True)

    assert result["base_url_kind"] == "local"
    assert result["base_url_scheme"] == "http"
    assert "base_url" not in result
    assert "base_url_host" not in result
    assert "host" not in result
    assert "url" not in result
    assert "127.0.0.1" not in serialized
    assert "localhost" not in serialized
    assert "1234" not in serialized
    assert "private/path" not in serialized
