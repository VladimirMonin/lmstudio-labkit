from __future__ import annotations

from pathlib import Path

from lmstudio_labkit.preflight import preflight_config

from lmstudio_labkit import preflight as preflight_module


class _FakeSocket:
    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"data":[{"id":"google/gemma-4-e2b"},{"id":"google/gemma-4-e4b"}]}'


def test_preflight_accepts_l3_16_live_config_without_core_runner_generation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    http_methods: list[str] = []

    monkeypatch.setattr(
        preflight_module.socket,
        "create_connection",
        lambda address, timeout=None: _FakeSocket(),
    )

    def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
        http_methods.append(req.get_method())
        return _FakeResponse()

    monkeypatch.setattr(preflight_module.urllib_request, "urlopen", fake_urlopen)

    result = preflight_config(
        Path(
            "experiments/lmstudio/structured_matrix/configs/matrix.live_small_text_remote.e2b_e4b.yaml"
        ),
        base_url="http://127.0.0.1:1234",
    ).as_dict()

    assert result["status"] == "pass"
    assert result["run_id"] == "matrix_live_small_text_remote_e2b_e4b"
    assert result["planned_request_count"] == 2
    assert result["checks"]["plan_build"] == "pass"
    assert http_methods == ["GET", "GET"]
