from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from tools.lmstudio_lab.l3_38_followup import (
    DEFAULT_CONTRACT,
    _load_verified_once,
    _preflight_phase,
    execution_plan,
    load_contract,
    main,
)


class _LoadHost:
    def __init__(self, *, applied_context: int) -> None:
        self.applied_context = applied_context
        self.loaded = 0
        self.cleanup_calls = 0

    def count_all_loaded_instances(self) -> int:
        return self.loaded

    def count_loaded_instances(self, *, model_id: str) -> int:
        del model_id
        return self.loaded

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        del model_id, context_length, parallel
        self.loaded = 1
        return {
            "load_verified": True,
            "applied_load_config": {
                "context_length": self.applied_context,
                "parallel": 1,
            },
        }

    def cleanup_model(self, *, model_id: str) -> object:
        del model_id
        self.cleanup_calls += 1
        self.loaded = 0
        return {"cleanup_verified": True}


class _MetadataHost:
    def __init__(self, metadata: object) -> None:
        self.metadata = metadata

    def model_metadata(self, *, model_id: str) -> object:
        del model_id
        return self.metadata


def test_l3_38_contract_is_bounded_serial_and_strict_probe_disabled() -> None:
    contract = load_contract(DEFAULT_CONTRACT)
    plan = execution_plan(contract)

    assert plan["ordered_launch"] == [
        "moe_8k",
        "moe_16k",
        "e4b_vision",
        "repeated_context_12b",
    ]
    assert plan["maximum_generation_rows"] == 13
    assert plan["strict_generation_rows"] == 0
    assert plan["phases"]["moe_8k"]["expected_rows"] == 2
    assert plan["phases"]["moe_16k"]["conditional"] is True
    assert plan["phases"]["e4b_vision"]["expected_rows"] == 3
    assert plan["phases"]["repeated_context_12b"]["expected_rows"] == 6


def test_l3_38_yaml_preserves_reasoning_strings() -> None:
    contract = load_contract(DEFAULT_CONTRACT)
    phases = contract["phases"]

    assert contract["execution"]["retries"] == "off"
    assert phases["moe_8k"]["reasoning_modes"] == ["off", "on"]
    assert phases["e4b_vision"]["reasoning"] == "off"
    assert phases["repeated_context_12b"]["reasoning"] == "off"


def test_l3_38_contract_rejects_enabled_strict_probe(tmp_path: Path) -> None:
    payload = yaml.safe_load(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    payload["phases"]["strict_json_investigation"]["probe_enabled"] = True
    path = tmp_path / "unsafe.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="strict JSON generation must remain disabled"):
        load_contract(path)


@pytest.mark.parametrize(
    ("phase", "field", "unsafe_value", "message"),
    [
        ("e4b_vision", "stop_on_first_failed_gate", False, "text-before-image gate"),
        ("repeated_context_12b", "reasoning", "on", "bounded reasoning-off contract"),
        ("repeated_context_12b", "requests_per_comparison", 4, "bounded reasoning-off contract"),
        (
            "strict_json_investigation",
            "request_reasoning_control",
            "off",
            "strict JSON generation must remain disabled",
        ),
    ],
)
def test_l3_38_contract_rejects_weakened_phase_gates(
    tmp_path: Path,
    phase: str,
    field: str,
    unsafe_value: object,
    message: str,
) -> None:
    payload = yaml.safe_load(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    payload["phases"][phase][field] = unsafe_value
    path = tmp_path / "unsafe.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_contract(path)


def test_l3_38_phase_preflight_checks_exact_reasoning_and_vision_before_load() -> None:
    reasoning = {"allowed_options": ["off", "on"], "default": "on"}
    metadata = {
        "key": "mock/model",
        "capabilities": {"vision": True, "reasoning": reasoning},
    }
    host = _MetadataHost(metadata)

    _preflight_phase(
        host,  # type: ignore[arg-type]
        phase_name="e4b_vision",
        phase={"model_id": "mock/model", "reasoning": "off"},
    )

    reasoning["allowed_options"] = ["on"]
    with pytest.raises(RuntimeError, match="does not advertise every requested reasoning mode"):
        _preflight_phase(
            host,  # type: ignore[arg-type]
            phase_name="e4b_vision",
            phase={"model_id": "mock/model", "reasoning": "off"},
        )


def test_l3_38_live_run_requires_two_explicit_flags(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="requires both --live and --allow-model-loads"):
        main(
            [
                "--contract",
                str(DEFAULT_CONTRACT),
                "run",
                "--phase",
                "moe_8k",
                "--base-url",
                "http://127.0.0.1:1234",
                "--private-dir",
                str(tmp_path / "private"),
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )


def test_l3_38_16k_requires_interpretable_8k_summary(tmp_path: Path) -> None:
    bad_prior = tmp_path / "prior.json"
    bad_prior.write_text(json.dumps({"phase": "moe_8k", "interpretable_pair": False}))

    with pytest.raises(ValueError, match="interpretable moe_8k prior summary"):
        from tools.lmstudio_lab.l3_38_followup import run_phase

        run_phase(
            contract=load_contract(DEFAULT_CONTRACT),
            phase_name="moe_16k",
            base_url="http://127.0.0.1:1234",
            private_dir=tmp_path / "private",
            prior_summary=bad_prior,
        )


def test_l3_38_load_gate_cleans_up_applied_context_mismatch() -> None:
    host = _LoadHost(applied_context=8192)

    with pytest.raises(RuntimeError, match="applied model context"):
        _load_verified_once(
            host,  # type: ignore[arg-type]
            model_id="mock/model",
            context_length=16384,
        )

    assert host.cleanup_calls == 1
    assert host.loaded == 0
