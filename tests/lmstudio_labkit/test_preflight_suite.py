from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

from lmstudio_labkit.suites import preflight_suite

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


def write_config(path: Path, run_id: str) -> None:
    path.write_text(
        f"""
run_id: {run_id}
models:
  - model_key: fake
    model_id: fake/text
    supported_modalities: [text]
tasks:
  - task_id: t
    family: simple_flat
    modality: text
    language: en_en
    prompt: Synthetic prompt
    expected_output:
      id: ok
      text: Synthetic response
axes:
  modality: [text]
  language: [en_en]
  structure_complexity: [simple]
  volume: [single]
  context_tier: [8192]
  schema_variant: [baseline_loose]
  retry_policy: [off]
safety:
  max_requests: 1
""".lstrip(),
        encoding="utf-8",
    )


def write_suite(path: Path, configs: list[Path]) -> None:
    config_lines = "\n".join(f"  - config: {config.name}" for config in configs)
    path.write_text(
        f"""
suite_id: readonly_preflight_suite
configs:
{config_lines}
""".lstrip(),
        encoding="utf-8",
    )


def test_preflight_suite_propagates_readonly_lmstudio_checks_to_each_config(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    configs = [tmp_path / "matrix_a.yaml", tmp_path / "matrix_b.yaml"]
    for index, config in enumerate(configs):
        write_config(config, f"suite_readonly_{index}")
    suite = tmp_path / "suite.yaml"
    write_suite(suite, configs)
    http_requests: list[urllib_request.Request] = []

    monkeypatch.setattr(
        preflight_module.socket,
        "create_connection",
        lambda address, timeout=None: _FakeSocket(),
    )

    def fake_urlopen(req: urllib_request.Request, timeout: float | None = None) -> _FakeResponse:
        http_requests.append(req)
        return _FakeResponse({"data": [{"id": "fake-model"}]})

    monkeypatch.setattr(preflight_module.urllib_request, "urlopen", fake_urlopen)

    result = preflight_suite(suite, base_url="http://127.0.0.1:1234")

    assert result["status"] == "pass"
    assert result["config_count"] == 2
    assert [req.get_method() for req in http_requests] == ["GET", "GET", "GET", "GET"]
    assert [req.full_url.rsplit(":1234", maxsplit=1)[1] for req in http_requests] == [
        "/v1/models",
        "/api/v1/models",
        "/v1/models",
        "/api/v1/models",
    ]
    assert all(item["lmstudio"]["base_url_kind"] == "local" for item in result["results"])
    assert all(item["lmstudio"]["base_url_scheme"] == "http" for item in result["results"])


def test_preflight_suite_result_does_not_persist_full_base_url_host_or_port(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    config = tmp_path / "matrix.yaml"
    suite = tmp_path / "suite.yaml"
    write_config(config, "suite_safe_endpoint_metadata")
    write_suite(suite, [config])

    monkeypatch.setattr(
        preflight_module.socket,
        "create_connection",
        lambda address, timeout=None: _FakeSocket(),
    )
    monkeypatch.setattr(
        preflight_module.urllib_request,
        "urlopen",
        lambda req, timeout=None: _FakeResponse({"models": []}),
    )

    result = preflight_suite(suite, base_url="http://localhost:1234/private/lmstudio")
    serialized = json.dumps(result, sort_keys=True)

    assert result["status"] == "pass"
    lmstudio = result["results"][0]["lmstudio"]
    assert lmstudio["base_url_kind"] == "local"
    assert lmstudio["base_url_scheme"] == "http"
    assert "base_url" not in lmstudio
    assert "base_url_host" not in lmstudio
    assert "localhost" not in serialized
    assert "127.0.0.1" not in serialized
    assert "1234" not in serialized
    assert "private/lmstudio" not in serialized
