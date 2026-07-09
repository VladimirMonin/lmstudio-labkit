from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from lmstudio_labkit.cli import main as cli_main

LIVE_CONFIG = "experiments/lmstudio/structured_matrix/configs/matrix.live_small_text.e2b_e4b.yaml"


def _write_config(path: Path, *, safety: dict[str, object]) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "run_id": "cli_live_guards",
                "models": [
                    {
                        "model_key": "fake",
                        "model_id": "fake/text",
                        "supported_modalities": ["text"],
                        "supported_context_tiers": ["8192"],
                    }
                ],
                "tasks": [
                    {
                        "task_id": "t",
                        "family": "blocks",
                        "modality": "text",
                        "prompt": "Synthetic",
                        "schema_family": "blocks",
                        "expected_ids": [0],
                        "expected_output": {"blocks": [{"id": 0, "text": "Synthetic"}]},
                    }
                ],
                "axes": {
                    "modality": ["text"],
                    "language": ["en_en"],
                    "structure_complexity": ["simple"],
                    "volume": ["single"],
                    "context_tier": ["8192"],
                    "schema_variant": ["hardened_const"],
                    "retry_policy": ["off"],
                },
                "repeats": 1,
                "safety": safety,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_live_profile_requires_live_flag(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="profile live-small requires --live"):
        cli_main(
            [
                "run",
                "--config",
                LIVE_CONFIG,
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
            ]
        )


def test_live_profile_requires_config_live_true(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "offline.yaml",
        safety={"live": False, "allow_model_downloads": False},
    )

    with pytest.raises(SystemExit, match="safety.live=true"):
        cli_main(
            [
                "run",
                "--config",
                str(config),
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
                "--live",
            ]
        )


def test_live_profile_requires_allow_model_loads_when_config_allows_loads(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit, match="CLI requires --allow-model-loads"):
        cli_main(
            [
                "run",
                "--config",
                LIVE_CONFIG,
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
                "--live",
            ]
        )


class _NoNetworkHostRunner:
    context_lengths: list[int] = []

    def __init__(self, *, base_url: str, allow_remote_base_url: bool = False) -> None:
        self.base_url = base_url
        self.allow_remote_base_url = allow_remote_base_url
        self.loaded = False

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.loaded = True
        self.context_lengths.append(context_length)
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(
        self,
        *,
        endpoint_path: str,
        model_id: str,
        messages: object,
        response_format: object,
        temperature: float,
        timeout_s: float,
    ) -> object:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"blocks":[{"id":0,"text":"Первый синтетический блок."},{"id":1,"text":"Второй синтетический блок."}]}'
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 16},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.loaded = False
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        return 1 if self.loaded else 0


def test_operator_live_managed_path_runs_with_explicit_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lmstudio_labkit.cli as cli

    _NoNetworkHostRunner.context_lengths = []
    monkeypatch.setattr(cli, "LocalLMStudioHostRunner", _NoNetworkHostRunner)

    assert (
        cli_main(
            [
                "run",
                "--config",
                LIVE_CONFIG,
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
                "--live",
                "--operator-live-managed",
                "--allow-model-loads",
            ]
        )
        == 0
    )

    run_dir = tmp_path / "matrix_live_small_text_e2b_e4b"
    planner_summary = (run_dir / "planner_summary.json").read_text(encoding="utf-8")
    cell_results = (run_dir / "cell_results.jsonl").read_text(encoding="utf-8")
    assert '"live": true' in planner_summary
    assert '"production_default": false' in planner_summary
    assert "Первый синтетический блок" not in cell_results
    assert "response_hash" in cell_results
    assert _NoNetworkHostRunner.context_lengths == [8192, 8192]


def test_operator_live_managed_passes_single_config_context_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lmstudio_labkit.cli as cli

    config = _write_config(
        tmp_path / "live_16k.yaml",
        safety={
            "live": True,
            "allow_model_downloads": False,
            "allow_model_loads": True,
            "allow_remote_base_url": False,
            "max_context_tier": 16384,
            "max_requests": 1,
        },
    )
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["axes"]["context_tier"] = ["16384"]
    payload["models"][0]["supported_context_tiers"] = ["16384"]
    config.write_text(yaml.safe_dump(payload), encoding="utf-8")

    _NoNetworkHostRunner.context_lengths = []
    monkeypatch.setattr(cli, "LocalLMStudioHostRunner", _NoNetworkHostRunner)

    assert (
        cli_main(
            [
                "run",
                "--config",
                str(config),
                "--output-root",
                str(tmp_path),
                "--profile",
                "live-small",
                "--live",
                "--operator-live-managed",
                "--allow-model-loads",
            ]
        )
        == 0
    )
    assert _NoNetworkHostRunner.context_lengths == [16384]


def test_local_host_runner_rejects_remote_without_explicit_allow() -> None:
    from lmstudio_labkit.managed_executor import LocalLMStudioHostRunner

    from lmstudio_labkit import ManagedExecutorError

    with pytest.raises(ManagedExecutorError, match="allow_remote_base_url"):
        LocalLMStudioHostRunner(base_url="https://example.invalid")

    assert (
        LocalLMStudioHostRunner(
            base_url="https://example.invalid", allow_remote_base_url=True
        ).base_url
        == "https://example.invalid"
    )
