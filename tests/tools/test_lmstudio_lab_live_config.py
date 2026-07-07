from __future__ import annotations

import socket
from pathlib import Path

import pytest
import yaml

from tools import lmstudio_lab


def _example_config_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "experiments"
        / "lmstudio"
        / "examples"
        / "live_json_smoke.example.yaml"
    )


def _write_live_config(tmp_path: Path, payload: dict) -> Path:
    config_path = tmp_path / "live.yaml"
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config_path


def _valid_payload() -> dict:
    return {
        "experiment_id": "live-json-test",
        "hardware_profile": "local_manual",
        "models": [
            {
                "key": "local_placeholder",
                "model_id": "placeholder/local-model",
                "load": {
                    "context_length": [8192],
                    "parallel": [1],
                },
            }
        ],
        "modes": ["json_schema_single"],
        "datasets": ["blocks_json_small"],
        "repeats": 1,
        "warmup_runs": 0,
        "privacy": {
            "store_prompt_text": False,
            "store_response_text": False,
            "store_prompt_hash": True,
        },
    }


def test_load_live_smoke_config_requires_explicit_live_flag() -> None:
    config_path = _example_config_path()

    with pytest.raises(ValueError, match="--live") as excinfo:
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=False)

    assert str(config_path) not in str(excinfo.value)


def test_load_live_smoke_config_accepts_example_file() -> None:
    config = lmstudio_lab.load_live_smoke_config(_example_config_path(), live_enabled=True)

    assert config.experiment_id == "live_json_smoke"
    assert config.hardware_profile == "local_manual"
    assert config.lmstudio_base_url == "http://127.0.0.1:1234"
    assert config.allow_remote is False
    assert config.modes == ("json_schema_single",)
    assert config.datasets == ("blocks_json_small",)
    assert config.repeats == 1
    assert config.warmup_runs == 0
    assert config.privacy == lmstudio_lab.LivePrivacyConfig(
        store_prompt_text=False,
        store_response_text=False,
        store_prompt_hash=True,
    )

    assert config.models == (
        lmstudio_lab.LiveModelConfig(
            key="local_placeholder",
            model_id="placeholder/local-model",
            load={
                "context_length": (8192,),
                "parallel": (1,),
            },
        ),
    )


def test_load_live_smoke_config_defaults_base_url_to_localhost(tmp_path: Path) -> None:
    config_path = _write_live_config(tmp_path, _valid_payload())

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.lmstudio_base_url == "http://127.0.0.1:1234"
    assert lmstudio_lab.is_local_lmstudio_base_url(config.lmstudio_base_url) is True


@pytest.mark.parametrize(
    "base_url",
    (
        "http://localhost:1234",
        "http://[::1]:1234",
    ),
)
def test_load_live_smoke_config_accepts_localhost_aliases(
    tmp_path: Path,
    base_url: str,
) -> None:
    payload = _valid_payload()
    payload["lmstudio_base_url"] = base_url
    config_path = _write_live_config(tmp_path, payload)

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.lmstudio_base_url == base_url
    assert lmstudio_lab.is_local_lmstudio_base_url(config.lmstudio_base_url) is True


def test_load_live_smoke_config_rejects_remote_url_without_allow_remote(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["lmstudio_base_url"] = "https://remote.invalid:1234"
    config_path = _write_live_config(tmp_path, payload)

    with pytest.raises(ValueError, match="allow_remote"):
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)


def test_load_live_smoke_config_accepts_remote_url_with_allow_remote(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["lmstudio_base_url"] = "https://remote.invalid:1234"
    payload["allow_remote"] = True
    config_path = _write_live_config(tmp_path, payload)

    config = lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)

    assert config.allow_remote is True
    assert config.lmstudio_base_url == "https://remote.invalid:1234"


@pytest.mark.parametrize(
    ("base_url", "error_fragment"),
    (
        ("ftp://127.0.0.1:1234", "lmstudio_base_url must use http or https"),
        ("http:///missing-host", "lmstudio_base_url must include a hostname"),
    ),
)
def test_load_live_smoke_config_rejects_invalid_base_urls(
    tmp_path: Path,
    base_url: str,
    error_fragment: str,
) -> None:
    payload = _valid_payload()
    payload["lmstudio_base_url"] = base_url
    config_path = _write_live_config(tmp_path, payload)

    with pytest.raises(ValueError, match=error_fragment):
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)


def test_load_live_smoke_config_requires_model_id(tmp_path: Path) -> None:
    payload = _valid_payload()
    del payload["models"][0]["model_id"]
    config_path = _write_live_config(tmp_path, payload)

    with pytest.raises(ValueError, match=r"models\[\]\.model_id is required"):
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)


def test_load_live_smoke_config_rejects_non_synthetic_dataset(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    dataset_dir = datasets_root / "private_dataset"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "dataset_id": "private_dataset",
                "kind": "blocks_json",
                "privacy": "private",
                "items_count": 1,
                "chars": 20,
                "estimated_input_tokens": 6,
                "actual_input_tokens": None,
                "estimate_error_ratio": None,
                "content_hash": "sha256:private-dataset",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    payload = _valid_payload()
    payload["datasets"] = ["private_dataset"]
    config_path = _write_live_config(tmp_path, payload)

    with pytest.raises(ValueError, match="synthetic privacy"):
        lmstudio_lab.load_live_smoke_config(
            config_path,
            live_enabled=True,
            datasets_root=datasets_root,
        )


@pytest.mark.parametrize(
    ("field_name", "field_value", "error_fragment"),
    (
        ("store_prompt_text", True, "privacy.store_prompt_text must remain false"),
        ("store_response_text", True, "privacy.store_response_text must remain false"),
        ("store_prompt_hash", False, "privacy.store_prompt_hash must remain true"),
    ),
)
def test_load_live_smoke_config_enforces_strict_privacy(
    tmp_path: Path,
    field_name: str,
    field_value: bool,
    error_fragment: str,
) -> None:
    payload = _valid_payload()
    payload["privacy"][field_name] = field_value
    config_path = _write_live_config(tmp_path, payload)

    with pytest.raises(ValueError, match=error_fragment):
        lmstudio_lab.load_live_smoke_config(config_path, live_enabled=True)


def test_load_live_smoke_config_never_calls_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden_create_connection(*args, **kwargs):
        raise AssertionError("network call attempted via create_connection")

    def _forbidden_connect(self, *args, **kwargs):
        raise AssertionError("network call attempted via socket.connect")

    monkeypatch.setattr(socket, "create_connection", _forbidden_create_connection)
    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)

    config = lmstudio_lab.load_live_smoke_config(_example_config_path(), live_enabled=True)

    assert config.experiment_id == "live_json_smoke"
