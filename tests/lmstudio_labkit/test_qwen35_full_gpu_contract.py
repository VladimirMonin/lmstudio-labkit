from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from lmstudio_labkit.qwen35_full_gpu import (
    Qwen35ArtifactExecutionPin,
    Qwen35ArtifactFilePin,
    Qwen35FullGPUController,
    Qwen35MatrixError,
    Qwen35MatrixManifest,
    load_qwen35_full_gpu_manifest,
)

MANIFEST_PATH = Path("experiments/lmstudio/qwen35_full_gpu/launch_manifest.json")


def _digest(path: Path = MANIFEST_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> Qwen35MatrixManifest:
    return load_qwen35_full_gpu_manifest(
        MANIFEST_PATH,
        expected_sha256=_digest(),
        repo_root=Path("."),
    )


@dataclass
class FullGPUHost:
    manifest: Qwen35MatrixManifest
    fail_groups: frozenset[tuple[str, int, int]] = frozenset()
    cleanup_verified: bool = True
    identity_mismatch_model: str | None = None
    raise_row_id: str | None = None
    loaded: int = 0
    active_model: str | None = None
    active_context: int | None = None
    active_parallel: int | None = None
    load_calls: list[dict[str, object]] = field(default_factory=list)
    inference_rows: list[str] = field(default_factory=list)
    lifecycle: list[str] = field(default_factory=list)
    artifact_pins: Mapping[str, Qwen35ArtifactExecutionPin] = field(default_factory=dict)

    def _pin(self, model_id: str):
        return next(pin for pin in self.manifest.models if pin.model_id == model_id)

    def model_metadata(self, *, model_id: str) -> Mapping[str, object] | None:
        self.lifecycle.append(f"metadata:{model_id}")
        value = dict(self._pin(model_id).identity_snapshot)
        if self.identity_mismatch_model == model_id:
            size_bytes = value["size_bytes"]
            assert isinstance(size_bytes, int)
            value["size_bytes"] = size_bytes + 1
        execution_pin = self.artifact_pins[model_id]
        value["artifact_evidence"] = {
            "status": "verified",
            "variant": execution_pin.variant,
            "pin_sha256": execution_pin.pin_sha256,
            "file_count": len(execution_pin.files),
        }
        return value

    def count_all_loaded_instances(self) -> int | None:
        self.lifecycle.append("count_global")
        return self.loaded

    def observe_global_zero(
        self, *, phase: str, model_id: str | None, load_group: str | None
    ) -> Mapping[str, object]:
        del model_id, load_group
        self.lifecycle.append(f"zero:{phase}")
        return {
            "phase": phase,
            "lms_ps_loaded_total": self.loaded,
            "api_loaded_total": self.loaded,
            "global_zero_verified": self.loaded == 0,
        }

    def load_model_full_gpu(
        self,
        *,
        model_id: str,
        context_length: int,
        parallel: int,
        gpu: str,
        echo_load_config: bool,
    ) -> object:
        assert self.loaded == 0
        assert gpu == "max"
        assert echo_load_config is True
        self.loaded = 1
        self.active_model = model_id
        self.active_context = context_length
        self.active_parallel = parallel
        call = {
            "model_id": model_id,
            "context_length": context_length,
            "parallel": parallel,
            "gpu": gpu,
            "echo_load_config": echo_load_config,
        }
        self.load_calls.append(call)
        self.lifecycle.append(f"load:{model_id}:{context_length}:{parallel}")
        failed = (model_id, context_length, parallel) in self.fail_groups
        return {
            "load_verified": True,
            "applied_load_config": {
                "context_length": context_length,
                "parallel": parallel,
                "gpu": "max" if not failed else "0.5",
                "gpu_offload_ratio": 1.0 if not failed else 0.5,
                "resource_guardrail_downgrade": False,
            },
        }

    def materialized_model_metadata(self, *, model_id: str) -> Mapping[str, object] | None:
        assert self.active_model == model_id
        return {
            "key": model_id,
            "loaded_instances": [
                {
                    "id": model_id,
                    "load_config": {
                        "context_length": self.active_context,
                        "parallel": self.active_parallel,
                    },
                }
            ],
        }

    def gpu_observation(self, *, model_id: str) -> Mapping[str, object] | None:
        assert self.active_model == model_id
        failed = (model_id, self.active_context, self.active_parallel) in self.fail_groups
        return {
            "model_key": model_id,
            "instance_id": model_id,
            "gpu_offload_ratio": 0.5 if failed else 1.0,
            "gpu_layers": 20 if failed else 40,
            "total_layers": 40,
            "kv_cache_gpu_supported": True,
            "kv_cache_gpu": True,
            "cpu_fallback": False,
            "resource_guardrail_downgrade": False,
            "memory_thrash_observed": False,
            "runtime_telemetry_available": True,
            "runtime_telemetry_source": "installed_sdk_runtime_log_proc_v2",
            "runtime_telemetry_authoritative": True,
            "runtime_telemetry_model_key": model_id,
            "runtime_telemetry_instance_id": model_id,
            "runtime_telemetry_sha256": "4" * 64,
            "runtime_instance_reference": "instance-ref-contract",
            "authoritative_instance_reference": "instance-ref-contract",
            "runtime_pid": 4242,
            "runtime_process_start_ticks": 991,
            "observed_gpu_memory_mb": 4096,
        }

    def execute_matrix_row(
        self, *, row: Mapping[str, object], timeout_s: float
    ) -> Mapping[str, object]:
        assert self.loaded == 1
        assert timeout_s == 120.0
        row_id = str(row["row_id"])
        self.inference_rows.append(row_id)
        if self.raise_row_id == row_id:
            raise RuntimeError("synthetic transport failure")
        strict = row["request_kind"] in {
            "strict_json_canary",
            "structured_text",
            "strict_simple",
            "strict_medium",
            "strict_ui_repeat",
        }
        endpoint = "/v1/chat/completions" if strict else "/api/v1/chat"
        payload: dict[str, object] = {
            "model": row["model_id"],
            "stream": False,
            "temperature": 0.0,
        }
        if strict:
            payload["response_format"] = {"type": "json_schema"}
        else:
            payload["store"] = row["request_kind"] in {
                "warm_prefix",
                "prefix_reuse",
                "session_reuse",
            }
        if row["reasoning"] != "omitted":
            payload["reasoning"] = row["reasoning"]
        response = (
            {"choices": [{"message": {"content": '{"id":1,"text":"ok"}'}}]}
            if strict
            else {"output_text": "synthetic"}
        )
        exchanges = []
        for slot in range(2 if row["request_kind"] == "parallel_pair" else 1):
            outbound = json.dumps(
                {**payload, "worker_slot": slot}, sort_keys=True, separators=(",", ":")
            ).encode()
            raw = json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
            exchanges.append(
                {
                    "endpoint": endpoint,
                    "worker_slot": slot,
                    "http_status": 200,
                    "outbound_bytes_b64": base64.b64encode(outbound).decode(),
                    "outbound_sha256": hashlib.sha256(outbound).hexdigest(),
                    "raw_response_bytes_b64": base64.b64encode(raw).decode(),
                    "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        return {"exchanges": exchanges, "runtime": {"finish_reason": "stop"}}

    def cleanup_model(self, *, model_id: str) -> object:
        assert self.active_model == model_id
        self.lifecycle.append(f"cleanup:{model_id}")
        if self.cleanup_verified:
            self.loaded = 0
            self.active_model = None
            self.active_context = None
            self.active_parallel = None
        return {"cleanup_verified": self.cleanup_verified}


def _artifact_pins(
    manifest: Qwen35MatrixManifest, tmp_path: Path
) -> Mapping[str, Qwen35ArtifactExecutionPin]:
    result: dict[str, Qwen35ArtifactExecutionPin] = {}
    root = tmp_path / "artifacts"
    root.mkdir(exist_ok=True)
    for model_pin in manifest.models:
        file_pins = []
        required_names = model_pin.artifact_identity["required_file_names"]
        assert isinstance(required_names, list)
        for name in required_names:
            path = root / str(name)
            path.write_bytes((model_pin.model_id + str(name)).encode())
            file_pins.append(
                Qwen35ArtifactFilePin(
                    path.resolve(),
                    hashlib.sha256(os.fsencode(path.resolve())).hexdigest(),
                    path.stat().st_size,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        variant = model_pin.variant_identity.get("selected_variant") or model_pin.model_id
        unsigned = {
            "model_id": model_pin.model_id,
            "variant": str(variant),
            "files": [
                {
                    "path": str(file_pin.path),
                    "path_sha256": file_pin.path_sha256,
                    "size_bytes": file_pin.size_bytes,
                    "sha256": file_pin.sha256,
                }
                for file_pin in file_pins
            ],
        }
        pin_sha256 = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result[model_pin.model_id] = Qwen35ArtifactExecutionPin(
            model_pin.model_id, str(variant), tuple(file_pins), pin_sha256
        )
    return result


def _controller(tmp_path: Path, host: FullGPUHost) -> Qwen35FullGPUController:
    artifact_pins = _artifact_pins(host.manifest, tmp_path)
    host.artifact_pins = artifact_pins
    return Qwen35FullGPUController(
        manifest=host.manifest,
        host=host,
        private_root=tmp_path / "owner-only",
        artifact_pins=artifact_pins,
        allow_model_loads=True,
    )


def test_manifest_freezes_exact_two_model_66_call_schedule() -> None:
    manifest = _manifest()

    assert len(manifest.rows) == 66
    assert manifest.max_inference_calls == 68
    assert manifest.max_inference_calls <= 80
    assert [pin.model_id for pin in manifest.models] == [
        "qwen/qwen3.5-4b",
        "qwen3.5-9b-mtp",
    ]
    assert [pin.identity_sha256 for pin in manifest.models] == [
        "56f7b03df4f2920efbc875ad2ddeef03e1454e50a267aa5aa9a482e2eec39b09",
        "204e9b63b642cd589c1002e5fb8fb2695d7b6b70916dfc4f51d0e9f8d02ef78f",
    ]
    assert [pin.reasoning_modes for pin in manifest.models] == [("off", "on"), ("omitted",)]
    assert sum(row.model_id == manifest.models[0].model_id for row in manifest.rows) == 36
    assert sum(row.model_id == manifest.models[1].model_id for row in manifest.rows) == 30
    assert sum(row.lane == "strict_structured_vision" for row in manifest.rows) == 26
    assert sum(row.context_length == 16384 for row in manifest.rows) == 8
    assert sum(row.parallel == 2 for row in manifest.rows) == 2


def test_manifest_requires_external_digest_and_reusable_source_hashes(tmp_path: Path) -> None:
    with pytest.raises(Qwen35MatrixError, match="manifest digest pin"):
        load_qwen35_full_gpu_manifest(
            MANIFEST_PATH,
            expected_sha256="0" * 64,
            repo_root=Path("."),
        )

    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["reuse_bindings"]["vision_runner"]["sha256"] = "0" * 64
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Qwen35MatrixError, match="binding digest mismatch"):
        load_qwen35_full_gpu_manifest(
            changed,
            expected_sha256=_digest(changed),
            repo_root=Path("."),
        )


def test_manifest_rejects_call_67_even_when_digest_is_recomputed(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["rows"].append(dict(payload["rows"][-1]))
    payload["rows"][-1]["ordinal"] = 67
    payload["rows"][-1]["row_id"] = "q35-67"
    unsigned = {key: value for key, value in payload["rows"][-1].items() if key != "row_sha256"}
    payload["rows"][-1]["row_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    payload["max_inference_calls"] = 67
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Qwen35MatrixError, match="exact 66-row/68-call schedule"):
        load_qwen35_full_gpu_manifest(
            changed,
            expected_sha256=_digest(changed),
            repo_root=Path("."),
        )


def test_controller_executes_all_rows_serially_with_full_gpu_and_owner_only_capture(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    host = FullGPUHost(manifest)

    result = _controller(tmp_path, host).run()

    assert result.cumulative_inference_calls == 68
    assert result.final_loaded_global_count == 0
    assert host.inference_rows == [row.row_id for row in manifest.rows]
    assert len(host.load_calls) == 14
    assert all(call["gpu"] == "max" for call in host.load_calls)
    assert all(call["echo_load_config"] is True for call in host.load_calls)
    assert host.loaded == 0
    assert all(row.status == "executed" for row in result.rows)
    assert all(
        row.accepted is False and row.reason == "content_fidelity_adjudication_required"
        for row in result.rows
        if next(item for item in manifest.rows if item.row_id == row.row_id).lane
        == "structured_text"
        and row.reason != "controller_validation_failed"
    )
    assert all(
        row.reason == "manual_pixel_adjudication_required"
        for row in result.rows
        if next(item for item in manifest.rows if item.row_id == row.row_id).lane
        == "strict_structured_vision"
    )

    private_root = tmp_path / "owner-only"
    assert os.stat(private_root).st_mode & 0o777 == 0o700
    private_files = [path for path in private_root.iterdir() if path.is_file()]
    assert len([path for path in private_files if path.name.startswith("call-")]) == 66
    assert len([path for path in private_files if path.name.startswith("load-")]) == 14
    assert len([path for path in private_files if path.name.startswith("attestation-")]) == 14
    assert len([path for path in private_files if path.name.startswith("zero-initial-")]) == 14
    assert len([path for path in private_files if path.name.startswith("zero-final-")]) == 14
    assert (private_root / "zero-matrix-final.json").is_file()
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in private_files)
    first_capture = json.loads(
        next(path for path in private_files if path.name.startswith("call-01-")).read_text(
            encoding="utf-8"
        )
    )
    assert first_capture["actual_inference_calls"] == 1
    assert first_capture["exchanges"][0]["endpoint"] == "/v1/chat/completions"
    assert first_capture["manifest_sha256"] == manifest.manifest_sha256


def test_base_full_gpu_failure_stop_gates_model_without_inference(tmp_path: Path) -> None:
    manifest = _manifest()
    blocked_model = manifest.models[1].model_id
    host = FullGPUHost(manifest, fail_groups=frozenset({(blocked_model, 8192, 1)}))

    result = _controller(tmp_path, host).run()

    blocked = [
        row
        for row in result.rows
        if row.row_id in {item.row_id for item in manifest.rows if item.model_id == blocked_model}
    ]
    assert result.cumulative_inference_calls == 37
    assert len(host.inference_rows) == 36
    assert all(row.status == "stop_gated" for row in blocked)
    assert all(row.inference_call_index is None for row in blocked)
    assert host.loaded == 0
    assert result.final_loaded_global_count == 0


def test_16k_and_parallel2_materialization_failures_are_explicit_zero_call_rows(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    failures = frozenset(
        (pin.model_id, context, parallel)
        for pin in manifest.models
        for context, parallel in ((16384, 1), (8192, 2))
    )
    host = FullGPUHost(manifest, fail_groups=failures)

    result = _controller(tmp_path, host).run()

    gated_ids = {
        row.row_id
        for row in manifest.rows
        if row.condition in {"context_16k_full_gpu", "parallel2_full_gpu"}
    }
    assert len(gated_ids) == 10
    assert result.cumulative_inference_calls == 56
    assert all(
        row.status == "stop_gated" and row.inference_call_index is None
        for row in result.rows
        if row.row_id in gated_ids
    )
    assert host.loaded == 0


def test_resume_executes_only_missing_rows_and_preserves_cumulative_ceiling(tmp_path: Path) -> None:
    manifest = _manifest()
    host = FullGPUHost(manifest)
    private_root = tmp_path / "owner-only"
    private_root.mkdir(mode=0o700)
    completed = manifest.rows[:2]
    ledger = private_root / "qwen35-full-gpu-progress.jsonl"
    records = []
    for index, row in enumerate(completed, start=1):
        capture = private_root / f"call-{row.ordinal:02d}-{row.row_id}.json"
        capture.write_text(
            json.dumps(
                {
                    "manifest_sha256": manifest.manifest_sha256,
                    "row_sha256": row.row_sha256,
                    "inference_call_index": index,
                    "actual_inference_calls": 1,
                    "exchanges": [{}],
                    "controller_verdicts": {
                        "transport": "pass",
                        "response_surface": "pass",
                        "raw_parse": "pass",
                        "schema": "pass",
                        "business": "pass",
                        "semantic": "pass",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(capture, 0o600)
        records.append(
            {
                "manifest_sha256": manifest.manifest_sha256,
                "row_id": row.row_id,
                "row_sha256": row.row_sha256,
                "status": "executed",
                "inference_call_index": index,
                "accepted": index == 1,
                "reason": None if index == 1 else "content_fidelity_adjudication_required",
                "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
                "actual_inference_calls": 1,
            }
        )
    ledger.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records
        ),
        encoding="utf-8",
    )
    os.chmod(ledger, 0o600)
    prior_group_capture = private_root / "load-02-structured-8k-p1.json"
    prior_group_capture.write_text("{}\n", encoding="utf-8")
    os.chmod(prior_group_capture, 0o600)

    result = _controller(tmp_path, host).run()

    assert [row.status for row in result.rows[:2]] == ["resumed", "resumed"]
    assert result.cumulative_inference_calls == 68
    assert len(host.inference_rows) == 64
    assert not {row.row_id for row in completed} & set(host.inference_rows)
    assert (private_root / "load-02-structured-8k-p1-resume-2.json").exists()
    final_records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(final_records) == 66
    assert len({record["row_id"] for record in final_records}) == 66


def test_controller_rejects_active_lock_before_host_action(tmp_path: Path) -> None:
    manifest = _manifest()
    host = FullGPUHost(manifest)
    private_root = tmp_path / "owner-only"
    private_root.mkdir(mode=0o700)
    (private_root / "qwen35-full-gpu.lock").write_text("active", encoding="utf-8")

    with pytest.raises(Qwen35MatrixError, match="active exclusive lock"):
        _controller(tmp_path, host).run()

    assert host.lifecycle == []
    assert host.inference_rows == []


def test_controller_rejects_identity_drift_before_load(tmp_path: Path) -> None:
    manifest = _manifest()
    host = FullGPUHost(manifest, identity_mismatch_model=manifest.models[0].model_id)

    with pytest.raises(Qwen35MatrixError, match="identity hash mismatch"):
        _controller(tmp_path, host).run()

    assert host.load_calls == []
    assert host.inference_rows == []


def test_controller_rejects_capture_inside_repository(tmp_path: Path) -> None:
    manifest = _manifest()
    host = FullGPUHost(manifest)
    artifact_pins = _artifact_pins(manifest, tmp_path)
    host.artifact_pins = artifact_pins
    controller = Qwen35FullGPUController(
        manifest=manifest,
        host=host,
        private_root=Path("experiments/lmstudio/qwen35_full_gpu/owner-only"),
        artifact_pins=artifact_pins,
        allow_model_loads=True,
    )

    with pytest.raises(Qwen35MatrixError, match="outside the repository"):
        controller.run()

    assert host.lifecycle == []


def test_cleanup_failure_stops_matrix_and_preserves_lock_cleanup(tmp_path: Path) -> None:
    manifest = _manifest()
    host = FullGPUHost(manifest, cleanup_verified=False)
    controller = _controller(tmp_path, host)

    with pytest.raises(Qwen35MatrixError, match="cleanup or global-zero"):
        controller.run()

    assert not (tmp_path / "owner-only" / "qwen35-full-gpu.lock").exists()
    assert len(host.inference_rows) == 1


def test_transport_exception_fails_closed_when_exact_exchange_is_unavailable(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    host = FullGPUHost(manifest, raise_row_id=manifest.rows[0].row_id)

    with pytest.raises(Qwen35MatrixError, match="before exact outbound and raw response capture"):
        _controller(tmp_path, host).run()

    assert host.loaded == 0
    assert not (tmp_path / "owner-only" / "qwen35-full-gpu.lock").exists()
    capture = json.loads(
        (tmp_path / "owner-only" / "call-01-q35-01.json").read_text(encoding="utf-8")
    )
    assert capture["transport_error_category"] == "RuntimeError"
    assert "synthetic transport failure" not in json.dumps(capture)


def test_resume_stop_gates_incomplete_stateful_group_without_replay_or_double_count(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    interrupted_row = manifest.rows[14]
    first_host = FullGPUHost(manifest, raise_row_id=interrupted_row.row_id)

    with pytest.raises(Qwen35MatrixError, match="before exact outbound"):
        _controller(tmp_path, first_host).run()

    assert first_host.inference_rows[-1] == interrupted_row.row_id
    interrupted_capture = (
        tmp_path
        / "owner-only"
        / f"call-{interrupted_row.ordinal:02d}-{interrupted_row.row_id}.json"
    )
    interrupted_capture.unlink()
    resumed_host = FullGPUHost(manifest)

    result = _controller(tmp_path, resumed_host).run()

    stateful_tail = {row.row_id for row in manifest.rows[14:17]}
    assert not stateful_tail & set(resumed_host.inference_rows)
    assert result.cumulative_inference_calls == 65
    assert all(
        item.status == "stop_gated" or item.status == "resumed" for item in result.rows[14:17]
    )
    ledger = tmp_path / "owner-only" / "qwen35-full-gpu-progress.jsonl"
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [record["reason"] for record in records[14:17]] == [
        "stateful_group_resume_not_reconstructable"
    ] * 3
