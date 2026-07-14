from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from lmstudio_labkit.qwen35_full_gpu import (
    Qwen35ArtifactExecutionPin,
    Qwen35ArtifactFilePin,
    Qwen35FullGPUController,
    Qwen35MatrixError,
    Qwen35MatrixManifest,
    load_qwen35_adjudication_ledger,
    load_qwen35_artifact_execution_pins,
    load_qwen35_full_gpu_manifest,
    write_qwen35_artifact_execution_pins,
)
from lmstudio_labkit.qwen35_full_gpu_host import (
    LocalQwen35FullGPUHost,
    _parse_installed_runtime_telemetry,
)

from lmstudio_labkit import qwen35_full_gpu_host as qwen_host_module

MANIFEST_PATH = Path("experiments/lmstudio/qwen35_full_gpu/launch_manifest.json")


def _manifest() -> Qwen35MatrixManifest:
    return load_qwen35_full_gpu_manifest(
        MANIFEST_PATH,
        expected_sha256=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        repo_root=Path("."),
    )


@dataclass
class MaterializationHost:
    manifest: Qwen35MatrixManifest
    global_after_load: int = 1
    instance_model: str | None = None
    loaded: int = 0
    inference_calls: int = 0
    artifact_pins: Mapping[str, Qwen35ArtifactExecutionPin] | None = None

    def _pin(self, model_id: str):
        return next(pin for pin in self.manifest.models if pin.model_id == model_id)

    def model_metadata(self, *, model_id: str) -> Mapping[str, object]:
        assert self.artifact_pins is not None
        execution_pin = self.artifact_pins[model_id]
        return {
            **self._pin(model_id).identity_snapshot,
            "artifact_evidence": {
                "status": "verified",
                "variant": execution_pin.variant,
                "pin_sha256": execution_pin.pin_sha256,
                "file_count": len(execution_pin.files),
            },
        }

    def count_all_loaded_instances(self) -> int:
        return self.loaded

    def observe_global_zero(
        self, *, phase: str, model_id: str | None, load_group: str | None
    ) -> Mapping[str, object]:
        del model_id, load_group
        return {
            "phase": phase,
            "lms_ps_loaded_total": self.loaded,
            "api_loaded_total": self.loaded,
            "global_zero_verified": self.loaded == 0,
        }

    def load_model_full_gpu(self, **kwargs: object) -> object:
        self.loaded = self.global_after_load
        return {
            "load_verified": True,
            "applied_load_config": {
                "gpu": "max",
                "gpu_offload_ratio": 1.0,
                "context_length": kwargs["context_length"],
                "parallel": kwargs["parallel"],
                "resource_guardrail_downgrade": False,
            },
        }

    def materialized_model_metadata(self, *, model_id: str) -> Mapping[str, object]:
        return {
            "key": model_id,
            "loaded_instances": [
                {
                    "id": self.instance_model or model_id,
                    "load_config": {
                        "context_length": 8192,
                        "parallel": 1,
                    },
                }
            ],
        }

    def gpu_observation(self, *, model_id: str) -> Mapping[str, object]:
        return {
            "model_key": model_id,
            "instance_id": model_id,
            "gpu_offload_ratio": 1.0,
            "gpu_layers": 40,
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
            "runtime_instance_reference": "instance-ref-4b",
            "authoritative_instance_reference": "instance-ref-4b",
            "runtime_pid": 4242,
            "runtime_process_start_ticks": 991,
        }

    def execute_matrix_row(self, *, row: Mapping[str, object], timeout_s: float):
        expected = 2 if row["request_kind"] == "parallel_pair" else 1
        self.inference_calls += expected
        exchanges = []
        for index in range(expected):
            strict = row["request_kind"] in {
                "strict_json_canary",
                "structured_text",
                "strict_simple",
                "strict_medium",
                "strict_ui_repeat",
            }
            request_payload = {
                "model": row["model_id"],
                "stream": False,
                "slot": index,
            }
            if strict:
                request_payload["response_format"] = {"type": "json_schema"}
                request_payload["temperature"] = 0.0
            else:
                request_payload["store"] = row["request_kind"] in {
                    "warm_prefix",
                    "prefix_reuse",
                    "session_reuse",
                }
            if row["reasoning"] != "omitted":
                request_payload["reasoning"] = row["reasoning"]
            outbound = json.dumps(
                request_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            response = json.dumps(
                {"choices": [{"message": {"content": '{"id":1,"text":"ok"}'}}]},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            exchanges.append(
                {
                    "endpoint": "/v1/chat/completions" if strict else "/api/v1/chat",
                    "outbound_bytes_b64": base64.b64encode(outbound).decode(),
                    "outbound_sha256": hashlib.sha256(outbound).hexdigest(),
                    "raw_response_bytes_b64": base64.b64encode(response).decode(),
                    "raw_response_sha256": hashlib.sha256(response).hexdigest(),
                    "http_status": 200,
                }
            )
        return {
            "http_call_count": expected,
            "exchanges": exchanges,
            "verdicts": {
                "transport": "pass",
                "response_surface": "pass",
                "raw_parse": "pass",
                "schema": "pass",
                "business": "pass",
                "semantic": "pass",
                "manual_pixel": "not_applicable",
            },
            "runtime": {},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.loaded = 0
        return {"cleanup_verified": True}


def _artifact_pins(
    manifest: Qwen35MatrixManifest, tmp_path: Path
) -> Mapping[str, Qwen35ArtifactExecutionPin]:
    result: dict[str, Qwen35ArtifactExecutionPin] = {}
    for model_pin in manifest.models:
        path = (tmp_path / f"{model_pin.model_id.replace('/', '-')}.gguf").resolve()
        file_pin = Qwen35ArtifactFilePin(path, "1" * 64, 1, "2" * 64)
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
            ],
        }
        pin_sha256 = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result[model_pin.model_id] = Qwen35ArtifactExecutionPin(
            model_pin.model_id, str(variant), (file_pin,), pin_sha256
        )
    return result


def _controller(tmp_path: Path, host: MaterializationHost) -> Qwen35FullGPUController:
    artifact_pins = _artifact_pins(host.manifest, tmp_path)
    host.artifact_pins = artifact_pins
    return Qwen35FullGPUController(
        manifest=host.manifest,
        host=host,
        private_root=tmp_path / "owner-only",
        artifact_pins=artifact_pins,
        allow_model_loads=True,
    )


def test_manifest_accounts_parallel_fanout_as_68_actual_http_calls() -> None:
    manifest = _manifest()
    assert len(manifest.rows) == 66
    assert manifest.max_inference_calls == 68
    assert sum(2 if row.request_kind == "parallel_pair" else 1 for row in manifest.rows) == 68


@pytest.mark.parametrize(
    ("global_after_load", "instance_model"),
    [
        (2, None),
        (1, "other/model"),
    ],
)
def test_post_load_materialization_requires_global_one_and_instance_identity(
    tmp_path: Path, global_after_load: int, instance_model: str | None
) -> None:
    manifest = _manifest()
    host = MaterializationHost(
        manifest,
        global_after_load=global_after_load,
        instance_model=instance_model,
    )
    result = _controller(tmp_path, host).run()
    assert host.inference_calls == 0
    assert host.loaded == 0
    assert all(row.status == "stop_gated" for row in result.rows)


def test_controller_accepts_installed_loaded_instance_config_shape(tmp_path: Path) -> None:
    class InstalledConfigHost(MaterializationHost):
        def materialized_model_metadata(self, *, model_id: str) -> Mapping[str, object]:
            return {
                "key": model_id,
                "loaded_instances": [
                    {
                        "id": model_id,
                        "config": {
                            "context_length": 8192,
                            "parallel": 1,
                            "offload_kv_cache_to_gpu": True,
                            "gpu": {"ratio": 1.0},
                        },
                    }
                ],
            }

    manifest = _manifest()
    host = InstalledConfigHost(manifest)

    result = _controller(tmp_path, host).run()

    assert result.rows[0].status == "executed"
    assert host.inference_calls > 0
    assert host.loaded == 0


def test_resume_rejects_missing_or_digest_mismatched_capture(tmp_path: Path) -> None:
    manifest = _manifest()
    host = MaterializationHost(manifest)
    root = tmp_path / "owner-only"
    root.mkdir(mode=0o700)
    row = manifest.rows[0]
    ledger = root / "qwen35-full-gpu-progress.jsonl"
    record = {
        "manifest_sha256": manifest.manifest_sha256,
        "row_id": row.row_id,
        "row_sha256": row.row_sha256,
        "status": "executed",
        "inference_call_index": 1,
        "actual_inference_calls": 1,
        "accepted": True,
        "reason": None,
        "capture_path": f"call-{row.ordinal:02d}-{row.row_id}.json",
        "capture_sha256": "0" * 64,
    }
    ledger.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    os.chmod(ledger, 0o600)

    with pytest.raises(Qwen35MatrixError, match="capture digest"):
        _controller(tmp_path, host).run()
    assert host.inference_calls == 0


class RecordingHost(LocalQwen35FullGPUHost):
    def __init__(self, manifest: Qwen35MatrixManifest, private_root: Path) -> None:
        super().__init__(manifest=manifest, private_root=private_root)
        self.requests: list[tuple[str, bytes]] = []

    def _request_exact(
        self, path: str, outbound: bytes, timeout_s: float
    ) -> tuple[int, str, bytes]:
        outbound_sha256 = hashlib.sha256(outbound).hexdigest()
        reserved = [
            json.loads(record.read_text(encoding="utf-8"))
            for record in self.private_root.glob("attempt-*-request.json")
        ]
        assert any(record.get("outbound_sha256") == outbound_sha256 for record in reserved)
        self.requests.append((path, outbound))
        if path == "/api/v1/chat":
            return (
                200,
                "application/json",
                json.dumps(
                    {
                        "response_id": "resp_response_1",
                        "output_text": "ok",
                        "finish_reason": "stop",
                    }
                ).encode(),
            )
        return (
            200,
            "application/json",
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {"content": '{"id":1,"text":"ok"}'},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ).encode(),
        )


def test_production_host_binds_exact_routes_bytes_and_parallel_fanout(tmp_path: Path) -> None:
    manifest = _manifest()
    private_root = tmp_path / "owner-only"
    private_root.mkdir(mode=0o700)
    host = RecordingHost(manifest, private_root)
    strict_row = manifest.rows[0]
    parallel_row = next(row for row in manifest.rows if row.request_kind == "parallel_pair")

    strict = host.execute_matrix_row(row=strict_row.binding(), timeout_s=10)
    parallel = host.execute_matrix_row(row=parallel_row.binding(), timeout_s=10)

    assert strict["http_call_count"] == 1
    assert parallel["http_call_count"] == 2
    assert [path for path, _payload in host.requests] == [
        "/v1/chat/completions",
        "/api/v1/chat",
        "/api/v1/chat",
    ]
    for result in (strict, parallel):
        for exchange in result["exchanges"]:
            outbound = base64.b64decode(exchange["outbound_bytes_b64"], validate=True)
            raw = base64.b64decode(exchange["raw_response_bytes_b64"], validate=True)
            assert hashlib.sha256(outbound).hexdigest() == exchange["outbound_sha256"]
            assert hashlib.sha256(raw).hexdigest() == exchange["raw_response_sha256"]


def test_session_reuse_binds_only_native_response_id(tmp_path: Path) -> None:
    manifest = _manifest()
    private_root = tmp_path / "owner-only"
    private_root.mkdir(mode=0o700)
    host = RecordingHost(manifest, private_root)
    warm = next(
        row
        for row in manifest.rows
        if row.model_id == "qwen/qwen3.5-4b"
        and row.context_length == 8192
        and row.request_kind == "warm_prefix"
    )
    session = next(
        row
        for row in manifest.rows
        if row.model_id == warm.model_id
        and row.context_length == warm.context_length
        and row.request_kind == "session_reuse"
    )

    host.execute_matrix_row(row=warm.binding(), timeout_s=10)
    host.execute_matrix_row(row=session.binding(), timeout_s=10)

    session_payload = json.loads(host.requests[-1][1])
    assert session_payload["previous_response_id"] == "resp_response_1"


def test_compat_completion_id_never_contaminates_session_reuse(tmp_path: Path) -> None:
    manifest = _manifest()
    private_root = tmp_path / "owner-only"
    private_root.mkdir(mode=0o700)
    host = RecordingHost(manifest, private_root)
    strict = next(
        row
        for row in manifest.rows
        if row.model_id == "qwen/qwen3.5-4b" and row.request_kind == "strict_json_canary"
    )
    session = next(
        row
        for row in manifest.rows
        if row.model_id == strict.model_id
        and row.context_length == strict.context_length
        and row.request_kind == "session_reuse"
    )

    host.execute_matrix_row(row=strict.binding(), timeout_s=10)

    with pytest.raises(Qwen35MatrixError, match="no bound previous response id"):
        host.execute_matrix_row(row=session.binding(), timeout_s=10)


def test_production_host_fails_closed_when_artifact_hash_is_unavailable(tmp_path: Path) -> None:
    manifest = _manifest()
    host = LocalQwen35FullGPUHost(manifest=manifest, private_root=tmp_path / "owner-only")
    metadata = dict(manifest.models[1].identity_snapshot)
    assert host._artifact_evidence(manifest.models[1], metadata)["status"] == "unavailable"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_external_artifact_pin_manifest_binds_paths_sizes_hashes_and_file_order(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    models = []
    for model_pin in manifest.models:
        required_names = model_pin.artifact_identity["required_file_names"]
        assert isinstance(required_names, list)
        files = []
        for name in required_names:
            path = (tmp_path / str(name)).resolve()
            path.write_bytes((model_pin.model_id + str(name)).encode())
            files.append(
                {
                    "path": str(path),
                    "path_sha256": hashlib.sha256(os.fsencode(path)).hexdigest(),
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        unsigned = {
            "model_id": model_pin.model_id,
            "variant": model_pin.variant_identity.get("selected_variant") or model_pin.model_id,
            "files": files,
        }
        models.append({**unsigned, "pin_sha256": _canonical_sha256(unsigned)})
    pin_path = tmp_path / "artifact-pins.json"
    pin_path.write_text(
        json.dumps({"manifest_sha256": manifest.manifest_sha256, "models": models}),
        encoding="utf-8",
    )
    os.chmod(pin_path, 0o600)
    digest = hashlib.sha256(pin_path.read_bytes()).hexdigest()

    loaded = load_qwen35_artifact_execution_pins(
        pin_path, expected_sha256=digest, manifest=manifest
    )

    assert tuple(loaded) == tuple(pin.model_id for pin in manifest.models)
    assert [file.path.name for file in loaded[manifest.models[0].model_id].files] == [
        "Qwen3.5-4B-Q4_K_M.gguf",
        "mmproj-Qwen3.5-4B-BF16.gguf",
    ]
    loaded[manifest.models[0].model_id].files[0].path.write_bytes(b"substituted")
    with pytest.raises(Qwen35MatrixError, match="size pin|file digest"):
        load_qwen35_artifact_execution_pins(pin_path, expected_sha256=digest, manifest=manifest)


def test_external_artifact_pins_allow_independent_four_b_attestation(tmp_path: Path) -> None:
    manifest = _manifest()
    model_pin = manifest.models[0]
    files = []
    required_names = model_pin.artifact_identity["required_file_names"]
    assert isinstance(required_names, list)
    for name in required_names:
        path = (tmp_path / str(name)).resolve()
        path.write_bytes((model_pin.model_id + str(name)).encode())
        files.append(
            {
                "path": str(path),
                "path_sha256": hashlib.sha256(os.fsencode(path)).hexdigest(),
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    unsigned = {
        "model_id": model_pin.model_id,
        "variant": model_pin.variant_identity["selected_variant"],
        "files": files,
    }
    payload = {
        "manifest_sha256": manifest.manifest_sha256,
        "models": [{**unsigned, "pin_sha256": _canonical_sha256(unsigned)}],
    }
    pin_path = tmp_path / "four-b-only-pins.json"
    pin_path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(pin_path, 0o600)

    loaded = load_qwen35_artifact_execution_pins(
        pin_path,
        expected_sha256=hashlib.sha256(pin_path.read_bytes()).hexdigest(),
        manifest=manifest,
    )

    assert tuple(loaded) == ("qwen/qwen3.5-4b",)


def test_owner_pin_generation_is_exact_manifest_bound_and_rejects_stale_binding(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    owner = tmp_path / "owner"
    owner.mkdir(mode=0o700)
    model_pin = manifest.models[0]
    required_names = model_pin.artifact_identity["required_file_names"]
    assert isinstance(required_names, list)
    paths = []
    for name in required_names:
        path = owner / str(name)
        path.write_bytes(str(name).encode())
        paths.append(path)
    pin_path = owner / "artifact-pins.json"
    digest = write_qwen35_artifact_execution_pins(
        pin_path, manifest=manifest, artifact_paths={model_pin.model_id: paths}
    )
    assert os.stat(pin_path).st_mode & 0o777 == 0o600
    loaded = load_qwen35_artifact_execution_pins(
        pin_path, expected_sha256=digest, manifest=manifest
    )
    assert loaded[model_pin.model_id].model_id == model_pin.model_id
    stale = json.loads(pin_path.read_text(encoding="utf-8"))
    stale["manifest_sha256"] = "0" * 64
    pin_path.write_text(json.dumps(stale), encoding="utf-8")
    stale_digest = hashlib.sha256(pin_path.read_bytes()).hexdigest()
    with pytest.raises(Qwen35MatrixError, match="not bound to the launch manifest"):
        load_qwen35_artifact_execution_pins(
            pin_path, expected_sha256=stale_digest, manifest=manifest
        )


def test_python_m_boundary_accepts_valid_pin_and_rejects_forged_pin(tmp_path: Path) -> None:
    manifest = _manifest()
    model_pin = manifest.models[0]
    owner = tmp_path / "owner"
    owner.mkdir(mode=0o700)
    required_names = model_pin.artifact_identity["required_file_names"]
    assert isinstance(required_names, list)
    artifact_paths = []
    for name in required_names:
        path = owner / str(name)
        path.write_bytes(str(name).encode())
        artifact_paths.append(path)

    manifest_sha256 = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    pin_path = owner / "artifact-pins.json"
    pin_command = [
        sys.executable,
        "-m",
        "lmstudio_labkit.qwen35_full_gpu",
        "pin-artifacts",
        "--manifest",
        str(MANIFEST_PATH),
        "--manifest-sha256",
        manifest_sha256,
        "--repo-root",
        str(Path.cwd()),
        "--output",
        str(pin_path),
    ]
    for artifact_path in artifact_paths:
        pin_command.extend(["--artifact", f"{model_pin.model_id}={artifact_path}"])
    generated = subprocess.run(pin_command, check=False, capture_output=True, text=True)
    assert generated.returncode == 0, generated.stderr
    pin_sha256 = hashlib.sha256(pin_path.read_bytes()).hexdigest()

    document = {"models": [{**model_pin.identity_snapshot, "loaded_instances": []}]}
    response_bytes = json.dumps(document).encode()

    class ModelsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.path == "/api/v1/models"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelsHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_log = tmp_path / "lms.log"
    fake_lms = fake_bin / "lms"
    fake_lms.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LMS_FAKE_LOG"\n'
        'if [ "$1" = "ps" ]; then printf "[]"; exit 0; fi\nexit 2\n',
        encoding="utf-8",
    )
    fake_lms.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "LMS_FAKE_LOG": str(fake_log),
    }

    def run_command(
        pins: Path, pins_sha256: str, capture_name: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "lmstudio_labkit.qwen35_full_gpu",
                "run",
                "--manifest",
                str(MANIFEST_PATH),
                "--manifest-sha256",
                manifest_sha256,
                "--repo-root",
                str(Path.cwd()),
                "--private-root",
                str(owner / capture_name),
                "--artifact-pins",
                str(pins),
                "--artifact-pins-sha256",
                pins_sha256,
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout",
                "5",
                "--allow-model-loads",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    try:
        valid = run_command(pin_path, pin_sha256, "valid-capture")
        assert valid.returncode == 0, valid.stderr
        summary = json.loads(valid.stdout)
        assert summary["cumulative_inference_calls"] == 0
        assert summary["final_loaded_global_count"] == 0
        valid_lms_log = fake_log.read_text(encoding="utf-8")
        assert "load qwen/qwen3.5-4b --gpu max --context-length 8192 --parallel 1 --yes" in (
            valid_lms_log
        )

        forged_path = owner / "forged-artifact-pins.json"
        forged = json.loads(pin_path.read_text(encoding="utf-8"))
        forged["models"][0]["pin_sha256"] = "0" * 64
        forged_path.write_text(json.dumps(forged), encoding="utf-8")
        forged_path.chmod(0o600)
        forged_result = run_command(
            forged_path,
            hashlib.sha256(forged_path.read_bytes()).hexdigest(),
            "forged-capture",
        )
        assert forged_result.returncode != 0
        assert "artifact execution pin binding is invalid" in forged_result.stderr
        assert fake_log.read_text(encoding="utf-8") == valid_lms_log
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_disagreeing_lms_and_api_zero_evidence_blocks_before_load(tmp_path: Path) -> None:
    class DisagreeingZeroHost(MaterializationHost):
        def observe_global_zero(
            self, *, phase: str, model_id: str | None, load_group: str | None
        ) -> Mapping[str, object]:
            del phase, model_id, load_group
            return {
                "lms_ps_loaded_total": 1,
                "api_loaded_total": 0,
                "global_zero_verified": False,
            }

    manifest = _manifest()
    host = DisagreeingZeroHost(manifest)
    with pytest.raises(Qwen35MatrixError, match="verified global zero"):
        _controller(tmp_path, host).run()
    assert host.inference_calls == 0
    evidence = next((tmp_path / "owner-only").glob("zero-initial-*.json"))
    assert json.loads(evidence.read_text())["lms_ps_loaded_total"] == 1


@pytest.mark.parametrize(
    "missing_field", ["resource_guardrail_downgrade", "memory_thrash_observed"]
)
def test_missing_downgrade_or_thrash_evidence_stop_gates_before_inference(
    tmp_path: Path, missing_field: str
) -> None:
    class MissingObservationHost(MaterializationHost):
        def gpu_observation(self, *, model_id: str) -> Mapping[str, object]:
            observed = dict(super().gpu_observation(model_id=model_id))
            observed.pop(missing_field)
            return observed

    manifest = _manifest()
    host = MissingObservationHost(manifest)
    result = _controller(tmp_path, host).run()
    assert host.inference_calls == 0
    assert all(row.status == "stop_gated" for row in result.rows)
    attestation = json.loads(next((tmp_path / "owner-only").glob("attestation-*.json")).read_text())
    assert attestation["verified"] is False
    assert attestation["evidence"][f"{missing_field}_false"] is False


def test_production_host_parses_installed_config_but_ignores_undocumented_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    host = LocalQwen35FullGPUHost(manifest=manifest, private_root=tmp_path / "owner-only")
    model_id = manifest.models[0].model_id
    model = {
        "key": model_id,
        "loaded_instances": [
            {
                "id": "installed-instance-1",
                "model_key": model_id,
                "config": {
                    "context_length": 8192,
                    "parallel": 1,
                    "offload_kv_cache_to_gpu": True,
                    "gpu": {"ratio": "max"},
                },
                "runtime_telemetry": {
                    "gpu_layers": 40,
                    "total_layers": 40,
                    "cpu_fallback": False,
                    "resource_guardrail_downgrade": False,
                    "memory_thrash_observed": False,
                },
            }
        ],
    }
    monkeypatch.setattr(
        LocalQwen35FullGPUHost,
        "materialized_model_metadata",
        lambda self, *, model_id: model,
    )

    observed = host.gpu_observation(model_id=model_id)

    assert observed is not None
    assert observed["context_length"] == 8192
    assert observed["parallel"] == 1
    assert observed["gpu_offload_ratio"] == 1.0
    assert observed["model_key"] == model_id
    assert observed["instance_id"] == "installed-instance-1"
    assert observed["gpu_layers"] is None
    assert observed["total_layers"] is None
    assert observed["kv_cache_gpu"] is True
    assert observed["cpu_fallback"] is None
    assert observed["resource_guardrail_downgrade"] is None
    assert observed["memory_thrash_observed"] is None
    assert observed["runtime_telemetry_available"] is False
    assert observed["runtime_telemetry_source"] is None
    assert observed["runtime_telemetry_authoritative"] is False
    assert observed["runtime_telemetry_sha256"] is None
    unavailable_reason = observed["runtime_telemetry_unavailable_reason"]
    assert isinstance(unavailable_reason, str)
    assert unavailable_reason == "installed_runtime_log_capture_unavailable_or_incomplete"


def test_production_host_does_not_infer_positive_runtime_facts_from_ratio_or_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    host = LocalQwen35FullGPUHost(manifest=manifest, private_root=tmp_path / "owner-only")
    model_id = manifest.models[0].model_id
    model = {
        "key": model_id,
        "loaded_instances": [
            {
                "id": "installed-instance-1",
                "model_key": model_id,
                "status": "idle",
                "config": {
                    "context_length": 8192,
                    "parallel": 1,
                    "offload_kv_cache_to_gpu": True,
                    "gpu": {"ratio": 1.0},
                },
            }
        ],
    }
    monkeypatch.setattr(
        LocalQwen35FullGPUHost,
        "materialized_model_metadata",
        lambda self, *, model_id: model,
    )

    observed = host.gpu_observation(model_id=model_id)

    assert observed is not None
    assert observed["gpu_offload_ratio"] == 1.0
    assert observed["cpu_fallback"] is None
    assert observed["resource_guardrail_downgrade"] is None
    assert observed["memory_thrash_observed"] is None
    assert observed["runtime_telemetry_available"] is False
    assert observed["runtime_telemetry_source"] is None
    assert observed["runtime_telemetry_authoritative"] is False


def _runtime_event(
    *,
    timestamp: int,
    message: str,
    model_identifier: str = "qwen/qwen3.5-4b",
    instance_reference: str = "instance-ref-4b",
    pid: int = 4242,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "data": {
            "type": "runtime.log",
            "level": "info",
            "message": message,
            "engineName": "llama.cpp",
            "engineVersion": "2.23.1",
            "engineType": "llm_engine",
            "modelIdentifier": model_identifier,
            "instanceReference": instance_reference,
            "pid": pid,
        },
    }


def _stable_process_samples(pid: int = 4242) -> list[dict[str, int]]:
    return [
        {
            "timestamp_ms": timestamp,
            "pid": pid,
            "process_start_ticks": 991,
            "major_faults": 7,
            "vm_swap_kib": 0,
        }
        for timestamp in (1_100, 1_500, 1_900)
    ]


def test_installed_runtime_log_adapter_accepts_exact_complete_identity_bound_capture() -> None:
    events = [
        _runtime_event(
            timestamp=1_200,
            message="load_tensors: offloading 40 repeating layers to GPU",
        ),
        _runtime_event(
            timestamp=1_300,
            message="load_tensors: offloading output layer to GPU",
        ),
        _runtime_event(
            timestamp=1_400,
            message="load_tensors: offloaded 41/41 layers to GPU",
        ),
    ]

    telemetry = _parse_installed_runtime_telemetry(
        events,
        model_id="qwen/qwen3.5-4b",
        instance_id="qwen/qwen3.5-4b",
        capture_started_ms=1_000,
        capture_ended_ms=2_000,
        process_samples=_stable_process_samples(),
        authoritative_instance_reference="instance-ref-4b",
    )

    assert telemetry["runtime_telemetry_authoritative"] is True
    assert telemetry["runtime_telemetry_source"] == "installed_sdk_runtime_log_proc_v2"
    assert telemetry["runtime_telemetry_model_key"] == "qwen/qwen3.5-4b"
    assert telemetry["runtime_telemetry_instance_id"] == "qwen/qwen3.5-4b"
    assert telemetry["runtime_instance_reference"] == "instance-ref-4b"
    assert telemetry["runtime_pid"] == 4242
    assert telemetry["gpu_layers"] == telemetry["total_layers"] == 41
    assert telemetry["cpu_fallback"] is None
    assert telemetry["resource_guardrail_downgrade"] is None
    assert telemetry["cpu_fallback_authority_available"] is False
    assert telemetry["resource_downgrade_authority_available"] is False
    assert telemetry["cpu_fallback_unavailable_reason"] == (
        "installed_sdk_runtime_contract_has_no_explicit_negative_state"
    )
    assert telemetry["resource_downgrade_unavailable_reason"] == (
        "installed_sdk_runtime_contract_has_no_explicit_negative_state"
    )
    assert telemetry["memory_thrash_observed"] is False


def test_installed_runtime_log_adapter_rejects_same_model_foreign_instance_reference() -> None:
    telemetry = _parse_installed_runtime_telemetry(
        [
            _runtime_event(
                timestamp=1_400,
                message="load_tensors: offloaded 41/41 layers to GPU",
                instance_reference="foreign-instance-ref",
            )
        ],
        model_id="qwen/qwen3.5-4b",
        instance_id="qwen/qwen3.5-4b",
        capture_started_ms=1_000,
        capture_ended_ms=2_000,
        process_samples=_stable_process_samples(),
        authoritative_instance_reference="instance-ref-4b",
    )

    assert telemetry["runtime_telemetry_authoritative"] is False
    assert telemetry["runtime_telemetry_unavailable_reason"] == (
        "runtime_instance_reference_does_not_match_installed_sdk"
    )
    assert telemetry["gpu_layers"] is None


def test_production_host_binds_content_addressed_runtime_capture_to_native_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    model_id = manifest.models[0].model_id
    host = LocalQwen35FullGPUHost(manifest=manifest, private_root=tmp_path / "owner-only")
    model = {
        "key": model_id,
        "loaded_instances": [
            {
                "id": model_id,
                "config": {
                    "context_length": 8192,
                    "parallel": 1,
                    "offload_kv_cache_to_gpu": True,
                },
            }
        ],
    }
    monkeypatch.setattr(
        LocalQwen35FullGPUHost,
        "materialized_model_metadata",
        lambda self, *, model_id: model,
    )
    host._runtime_capture_by_model[model_id] = {
        "capture_started_ms": 1_000,
        "capture_ended_ms": 2_000,
        "capture_sha256": "a" * 64,
        "events": [
            _runtime_event(
                timestamp=1_400,
                message="load_tensors: offloaded 41/41 layers to GPU",
            )
        ],
        "process_samples": _stable_process_samples(),
        "authoritative_instance": {
            "identifier": model_id,
            "modelKey": model_id,
            "instanceReference": "instance-ref-4b",
            "info": {
                "identifier": model_id,
                "instanceReference": "instance-ref-4b",
            },
        },
    }

    observed = host.gpu_observation(model_id=model_id)

    assert observed is not None
    assert observed["gpu_layers"] == observed["total_layers"] == 41
    assert observed["runtime_telemetry_authoritative"] is True
    assert observed["runtime_telemetry_instance_id"] == model_id
    assert observed["runtime_telemetry_sha256"] == "a" * 64


@pytest.mark.parametrize(
    ("events", "samples"),
    [
        ([], _stable_process_samples()),
        (
            [
                _runtime_event(
                    timestamp=900,
                    message="load_tensors: offloaded 41/41 layers to GPU",
                )
            ],
            _stable_process_samples(),
        ),
        (
            [
                _runtime_event(
                    timestamp=1_400,
                    message="load_tensors: offloaded 41/41 layers to GPU",
                    model_identifier="foreign/model",
                )
            ],
            _stable_process_samples(),
        ),
        (
            [
                _runtime_event(
                    timestamp=1_400,
                    message="load_tensors: offloaded 20/41 layers to GPU",
                )
            ],
            _stable_process_samples(),
        ),
        (
            [
                _runtime_event(
                    timestamp=1_400,
                    message="load_tensors: offloaded 41/41 layers to GPU",
                )
            ],
            _stable_process_samples(pid=9999),
        ),
    ],
)
def test_installed_runtime_log_adapter_fails_closed_for_missing_stale_foreign_or_partial_capture(
    events: list[dict[str, object]], samples: list[dict[str, int]]
) -> None:
    telemetry = _parse_installed_runtime_telemetry(
        events,
        model_id="qwen/qwen3.5-4b",
        instance_id="qwen/qwen3.5-4b",
        capture_started_ms=1_000,
        capture_ended_ms=2_000,
        process_samples=samples,
        authoritative_instance_reference="instance-ref-4b",
    )

    assert telemetry["runtime_telemetry_authoritative"] is False
    assert telemetry["gpu_layers"] is None
    assert telemetry["total_layers"] is None
    assert telemetry["cpu_fallback"] is None
    assert telemetry["resource_guardrail_downgrade"] is None
    assert telemetry["memory_thrash_observed"] is None


def test_installed_runtime_log_adapter_rejects_cpu_fallback_and_process_thrash() -> None:
    events = [
        _runtime_event(
            timestamp=1_400,
            message="load_tensors: offloaded 41/41 layers to GPU",
        ),
        _runtime_event(
            timestamp=1_450,
            message="tensor cannot use preferred buffer type CUDA0, using CPU instead",
        ),
    ]
    samples = _stable_process_samples()
    samples[-1]["major_faults"] = 8

    telemetry = _parse_installed_runtime_telemetry(
        events,
        model_id="qwen/qwen3.5-4b",
        instance_id="qwen/qwen3.5-4b",
        capture_started_ms=1_000,
        capture_ended_ms=2_000,
        process_samples=samples,
        authoritative_instance_reference="instance-ref-4b",
    )

    assert telemetry["runtime_telemetry_authoritative"] is True
    assert telemetry["gpu_layers"] == telemetry["total_layers"] == 41
    assert telemetry["cpu_fallback"] is True
    assert telemetry["memory_thrash_observed"] is True


@pytest.mark.parametrize("missing_field", ["gpu_layers", "total_layers"])
def test_ratio_only_without_authoritative_layer_counts_stop_gates_before_inference(
    tmp_path: Path, missing_field: str
) -> None:
    class MissingLayerCountHost(MaterializationHost):
        def gpu_observation(self, *, model_id: str) -> Mapping[str, object]:
            observed = dict(super().gpu_observation(model_id=model_id))
            observed.pop(missing_field)
            return observed

    manifest = _manifest()
    host = MissingLayerCountHost(manifest)

    result = _controller(tmp_path, host).run()

    assert host.inference_calls == 0
    assert all(row.status == "stop_gated" for row in result.rows)
    attestation = json.loads(next((tmp_path / "owner-only").glob("attestation-*.json")).read_text())
    assert attestation["verified"] is False
    assert attestation["evidence"]["authoritative_all_layers_gpu"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_telemetry_authoritative", False),
        ("runtime_telemetry_source", "untrusted:self_reported"),
        ("runtime_telemetry_sha256", None),
    ],
)
def test_untrusted_layer_telemetry_stop_gates_before_inference(
    tmp_path: Path, field: str, value: object
) -> None:
    class UntrustedTelemetryHost(MaterializationHost):
        def gpu_observation(self, *, model_id: str) -> Mapping[str, object]:
            observed = dict(super().gpu_observation(model_id=model_id))
            observed[field] = value
            return observed

    manifest = _manifest()
    host = UntrustedTelemetryHost(manifest)

    result = _controller(tmp_path, host).run()

    assert host.inference_calls == 0
    assert all(row.status == "stop_gated" for row in result.rows)
    attestation = json.loads(next((tmp_path / "owner-only").glob("attestation-*.json")).read_text())
    assert attestation["verified"] is False
    assert attestation["evidence"]["runtime_telemetry_authority_validated"] is False
    assert attestation["evidence"]["authoritative_all_layers_gpu"] is False


def test_installed_sdk_snapshot_requires_exact_list_loaded_and_get_model_info_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    model_id = manifest.models[0].model_id
    host = LocalQwen35FullGPUHost(manifest=manifest, private_root=tmp_path / "owner-only")

    def fake_run(
        argv: list[str], *, check: bool, capture_output: bool, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        assert argv[:3] == ["node", "--input-type=module", "-e"]
        assert argv[-1] == model_id
        assert check is False and capture_output is True and timeout == 10.0
        value = {
            "identifier": model_id,
            "modelKey": model_id,
            "instanceReference": "sdk-instance-ref",
            "info": {
                "identifier": model_id,
                "instanceReference": "sdk-instance-ref",
            },
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps([value]).encode(), b"")

    monkeypatch.setattr(qwen_host_module.subprocess, "run", fake_run)

    snapshot = host._capture_authoritative_loaded_instance(model_id=model_id)

    assert snapshot["available"] is True
    instance = snapshot["instance"]
    module_sha256 = snapshot["module_sha256"]
    assert isinstance(instance, Mapping)
    assert instance["instanceReference"] == "sdk-instance-ref"
    assert isinstance(module_sha256, str) and len(module_sha256) == 64


def test_installed_lms_load_contract_uses_gpu_max_and_captures_exact_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    root = tmp_path / "owner-only"
    observed: list[list[str]] = []

    def fake_run(
        argv: list[str], *, check: bool, capture_output: bool, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        assert next(root.glob("lifecycle-*-load-request.json")).exists()
        assert check is False
        assert capture_output is True
        assert timeout == 17.0
        observed.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"loaded\n", b"")

    monkeypatch.setattr(qwen_host_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        LocalQwen35FullGPUHost,
        "_start_runtime_log_capture",
        lambda self, *, model_id: None,
    )
    host = LocalQwen35FullGPUHost(
        manifest=manifest,
        private_root=root,
        default_timeout_s=17.0,
        lms_executable="/installed/bin/lms",
    )

    result = host.load_model_full_gpu(
        model_id="qwen/qwen3.5-4b",
        context_length=8192,
        parallel=1,
        gpu="max",
        echo_load_config=True,
    )

    assert isinstance(result, Mapping)
    assert observed == [
        [
            "/installed/bin/lms",
            "load",
            "qwen/qwen3.5-4b",
            "--gpu",
            "max",
            "--context-length",
            "8192",
            "--parallel",
            "1",
            "--yes",
        ]
    ]
    assert result["load_verified"] is True
    assert result["requested_load_config"] == {
        "context_length": 8192,
        "parallel": 1,
        "gpu": "max",
        "gpu_offload_ratio": 1.0,
    }
    request_record = json.loads(next(root.glob("lifecycle-*-load-request.json")).read_text())
    response_record = json.loads(next(root.glob("lifecycle-*-load-response.json")).read_text())
    argv_bytes = base64.b64decode(request_record["argv_bytes_b64"], validate=True)
    stdout = base64.b64decode(response_record["stdout_bytes_b64"], validate=True)
    assert hashlib.sha256(argv_bytes).hexdigest() == request_record["argv_sha256"]
    assert stdout == b"loaded\n"
    assert response_record["returncode"] == 0
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in root.iterdir())


def test_process_monitor_starts_before_load_and_remains_active_through_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    root = tmp_path / "owner-only"
    sentinel = {"monitor": "started_before_load"}
    transitions: list[str] = []

    def fake_start(self: LocalQwen35FullGPUHost, *, model_id: str) -> Mapping[str, object]:
        transitions.append(f"start:{model_id}")
        return sentinel

    def fake_run(
        argv: list[str], *, check: bool, capture_output: bool, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        del check, capture_output, timeout
        transitions.append("load")
        return subprocess.CompletedProcess(argv, 0, b"loaded\n", b"")

    def fake_finish(
        self: LocalQwen35FullGPUHost,
        *,
        model_id: str,
        capture: Mapping[str, object] | None,
    ) -> None:
        assert capture is sentinel
        transitions.append(f"finish:{model_id}")

    monkeypatch.setattr(LocalQwen35FullGPUHost, "_start_runtime_log_capture", fake_start)
    monkeypatch.setattr(LocalQwen35FullGPUHost, "_finish_runtime_log_capture", fake_finish)
    monkeypatch.setattr(qwen_host_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        LocalQwen35FullGPUHost,
        "materialized_model_metadata",
        lambda self, *, model_id: None,
    )
    host = LocalQwen35FullGPUHost(manifest=manifest, private_root=root)

    host.load_model_full_gpu(
        model_id="qwen/qwen3.5-4b",
        context_length=8192,
        parallel=1,
        gpu="max",
        echo_load_config=True,
    )

    assert transitions == ["start:qwen/qwen3.5-4b", "load"]
    assert host._active_runtime_capture_by_model["qwen/qwen3.5-4b"] is sentinel
    assert host.gpu_observation(model_id="qwen/qwen3.5-4b") is None
    assert transitions == [
        "start:qwen/qwen3.5-4b",
        "load",
        "finish:qwen/qwen3.5-4b",
    ]
    assert host._active_runtime_capture_by_model == {}


def test_installed_lms_load_nonzero_exit_is_captured_and_not_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    root = tmp_path / "owner-only"

    def fake_run(
        argv: list[str], *, check: bool, capture_output: bool, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        del check, capture_output, timeout
        return subprocess.CompletedProcess(argv, 2, b"", b"installed cli rejected request\n")

    monkeypatch.setattr(qwen_host_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        LocalQwen35FullGPUHost,
        "_start_runtime_log_capture",
        lambda self, *, model_id: None,
    )
    host = LocalQwen35FullGPUHost(manifest=manifest, private_root=root)

    result = host.load_model_full_gpu(
        model_id="qwen/qwen3.5-4b",
        context_length=8192,
        parallel=1,
        gpu="max",
        echo_load_config=True,
    )

    assert isinstance(result, Mapping)
    assert result["load_verified"] is False
    response = json.loads(next(root.glob("lifecycle-*-load-response.json")).read_text())
    stderr = base64.b64decode(response["stderr_bytes_b64"], validate=True)
    assert stderr == b"installed cli rejected request\n"
    assert hashlib.sha256(stderr).hexdigest() == response["stderr_sha256"]
    assert response["returncode"] == 2


def test_missing_nine_b_attestation_does_not_block_attested_four_b(tmp_path: Path) -> None:
    manifest = _manifest()
    host = MaterializationHost(manifest)
    all_pins = _artifact_pins(manifest, tmp_path)
    four_b_pins = {manifest.models[0].model_id: all_pins[manifest.models[0].model_id]}
    host.artifact_pins = four_b_pins
    controller = Qwen35FullGPUController(
        manifest=manifest,
        host=host,
        private_root=tmp_path / "owner-only",
        artifact_pins=four_b_pins,
        allow_model_loads=True,
    )

    result = controller.run()

    four_b_rows = result.rows[:36]
    nine_b_rows = result.rows[36:]
    assert four_b_rows[0].status == "executed"
    assert all(row.status in {"executed", "stop_gated"} for row in four_b_rows)
    assert all(
        row.status == "stop_gated" and row.reason == "execution_identity_unavailable"
        for row in nine_b_rows
    )
    assert host.inference_calls > 0
    assert result.cumulative_inference_calls == host.inference_calls
    assert result.final_loaded_global_count == 0


class FailingExchangeHost(RecordingHost):
    failure: str = "transport"

    def _request_exact(
        self, path: str, outbound: bytes, timeout_s: float
    ) -> tuple[int, str, bytes]:
        assert len(list(self.private_root.glob("attempt-*-request.json"))) == len(self.requests) + 1
        self.requests.append((path, outbound))
        if self.failure == "transport":
            raise RuntimeError("synthetic private transport detail")
        if self.failure == "non_200":
            return 503, "text/plain", b"temporary private upstream detail"
        return 200, "application/json", b"{malformed"


@pytest.mark.parametrize(
    ("failure", "response_available", "expected_status"),
    [
        ("transport", False, None),
        ("non_200", True, 503),
        ("malformed", True, 200),
    ],
)
def test_production_attempt_evidence_is_fsynced_before_send_and_preserves_failures(
    tmp_path: Path,
    failure: str,
    response_available: bool,
    expected_status: int | None,
) -> None:
    manifest = _manifest()
    root = tmp_path / "owner-only"
    root.mkdir(mode=0o700)
    host = FailingExchangeHost(manifest, root)
    host.failure = failure
    row = manifest.rows[0]

    result = host.execute_matrix_row(row=row.binding(), timeout_s=10)

    exchanges = result["exchanges"]
    assert isinstance(exchanges, list)
    exchange = exchanges[0]
    assert isinstance(exchange, Mapping)
    request_evidence = next(root.glob("attempt-*-request.json"))
    response_evidence = next(root.glob("attempt-*-response.json"))
    request_record = json.loads(request_evidence.read_text(encoding="utf-8"))
    response_record = json.loads(response_evidence.read_text(encoding="utf-8"))
    assert request_record["state"] == "reserved_before_send"
    assert request_record["outbound_bytes_b64"] == exchange["outbound_bytes_b64"]
    assert response_record["response_available"] is response_available
    assert response_record.get("http_status") == expected_status
    assert os.stat(request_evidence).st_mode & 0o777 == 0o600
    assert os.stat(response_evidence).st_mode & 0o777 == 0o600
    if failure == "transport":
        assert response_record["transport_error_category"] == "RuntimeError"
        assert "synthetic private transport detail" not in json.dumps(response_record)
    else:
        raw = base64.b64decode(response_record["raw_response_bytes_b64"], validate=True)
        assert hashlib.sha256(raw).hexdigest() == response_record["raw_response_sha256"]


def test_resume_rejects_non_contiguous_progress_before_host_action(tmp_path: Path) -> None:
    manifest = _manifest()
    host = MaterializationHost(manifest)
    root = tmp_path / "owner-only"
    root.mkdir(mode=0o700)
    row = manifest.rows[1]
    ledger = root / "qwen35-full-gpu-progress.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "manifest_sha256": manifest.manifest_sha256,
                "row_id": row.row_id,
                "row_sha256": row.row_sha256,
                "status": "stop_gated",
                "inference_call_index": None,
                "accepted": None,
                "reason": "synthetic_stop_gate",
                "capture_sha256": None,
                "actual_inference_calls": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(ledger, 0o600)

    with pytest.raises(Qwen35MatrixError, match="contiguous manifest prefix"):
        _controller(tmp_path, host).run()
    assert host.inference_calls == 0


def test_parallel_failure_preserves_both_reserved_actual_attempts(tmp_path: Path) -> None:
    manifest = _manifest()
    root = tmp_path / "owner-only"
    root.mkdir(mode=0o700)
    host = FailingExchangeHost(manifest, root)
    host.failure = "transport"
    row = next(item for item in manifest.rows if item.request_kind == "parallel_pair")

    result = host.execute_matrix_row(row=row.binding(), timeout_s=10)

    exchanges = result["exchanges"]
    assert isinstance(exchanges, list)
    assert len(exchanges) == 2
    requests = [json.loads(path.read_text()) for path in root.glob("attempt-*-request.json")]
    responses = [json.loads(path.read_text()) for path in root.glob("attempt-*-response.json")]
    assert sorted(item["attempt_index"] for item in requests) == [1, 2]
    assert sorted(item["attempt_index"] for item in responses) == [1, 2]
    assert all(item["response_available"] is False for item in responses)


def test_post_execution_adjudication_ledger_is_capture_bound_and_dimension_typed(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    root = tmp_path / "owner-only"
    root.mkdir(mode=0o700)
    row = next(item for item in manifest.rows if item.lane == "structured_text")
    capture = root / f"call-{row.ordinal:02d}-{row.row_id}.json"
    capture.write_text("{}\n", encoding="utf-8")
    os.chmod(capture, 0o600)
    record = {
        "manifest_sha256": manifest.manifest_sha256,
        "row_id": row.row_id,
        "row_sha256": row.row_sha256,
        "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
        "dimension": "structured_text_content_fidelity",
        "semantic_pass": True,
        "reason_code": "content_preserved",
    }
    ledger = root / "qwen35-full-gpu-adjudications.jsonl"
    ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
    os.chmod(ledger, 0o600)

    loaded = load_qwen35_adjudication_ledger(ledger, manifest=manifest, private_root=root)
    assert loaded[row.row_id]["semantic_pass"] is True
    record["dimension"] = "vision_pixel_content_fidelity"
    ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(Qwen35MatrixError, match="dimension"):
        load_qwen35_adjudication_ledger(ledger, manifest=manifest, private_root=root)


@pytest.mark.parametrize("response_persisted", [False, True])
def test_interrupted_attempt_resume_reconstructs_without_resend_at_evidence_boundaries(
    tmp_path: Path, response_persisted: bool
) -> None:
    manifest = _manifest()
    host = MaterializationHost(manifest)
    controller = _controller(tmp_path, host)
    controller._prepare_private_root()
    root = tmp_path / "owner-only"
    row = manifest.rows[0]
    outbound = json.dumps(
        {
            "model": row.model_id,
            "stream": False,
            "temperature": 0.0,
            "reasoning": "off",
            "response_format": {"type": "json_schema"},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request_record = {
        "manifest_sha256": manifest.manifest_sha256,
        "row_id": row.row_id,
        "row_sha256": row.row_sha256,
        "attempt_index": 1,
        "worker_slot": 0,
        "endpoint": "/v1/chat/completions",
        "outbound_bytes_b64": base64.b64encode(outbound).decode(),
        "outbound_sha256": hashlib.sha256(outbound).hexdigest(),
        "state": "reserved_before_send",
    }
    request_path = root / "attempt-q35-01-slot-0-request.json"
    request_path.write_text(json.dumps(request_record) + "\n", encoding="utf-8")
    os.chmod(request_path, 0o600)
    if response_persisted:
        raw = json.dumps(
            {"choices": [{"message": {"content": '{"id":1,"text":"ok"}'}}]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        response_record = {
            "manifest_sha256": manifest.manifest_sha256,
            "row_id": row.row_id,
            "attempt_index": 1,
            "worker_slot": 0,
            "response_available": True,
            "http_status": 200,
            "content_type": "application/json",
            "raw_response_bytes_b64": base64.b64encode(raw).decode(),
            "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
            "latency_ms": 1.0,
        }
        response_path = root / "attempt-q35-01-slot-0-response.json"
        response_path.write_text(json.dumps(response_record) + "\n", encoding="utf-8")
        os.chmod(response_path, 0o600)
    ledger = root / "qwen35-full-gpu-progress.jsonl"

    reconciled = controller._reconcile_orphan_attempts(ledger, {})

    assert list(reconciled) == [row.row_id]
    assert reconciled[row.row_id]["actual_inference_calls"] == 1
    assert host.inference_calls == 0
    assert (root / "call-01-q35-01.json").is_file()
    if response_persisted:
        assert reconciled[row.row_id]["accepted"] is True
    else:
        assert reconciled[row.row_id]["accepted"] is False
        assert reconciled[row.row_id]["reason"] == "transport_error"

    ledger.unlink()
    after_capture_before_progress = controller._reconcile_orphan_attempts(ledger, {})
    assert list(after_capture_before_progress) == [row.row_id]
    persisted = controller._read_progress(ledger)
    after_progress = controller._reconcile_orphan_attempts(ledger, persisted)
    assert after_progress == persisted
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_resume_accepts_exact_production_capture_when_progress_write_was_interrupted(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    root = tmp_path / "owner-only"
    root.mkdir(mode=0o700)
    host = RecordingHost(manifest, root)
    controller = Qwen35FullGPUController(
        manifest=manifest,
        host=host,
        private_root=root,
        artifact_pins=_artifact_pins(manifest, tmp_path),
        allow_model_loads=True,
    )
    row = manifest.rows[0]

    result, actual_calls = controller._execute_row(row, inference_call_index=1)

    assert result.accepted is True
    assert actual_calls == 1
    ledger = root / "qwen35-full-gpu-progress.jsonl"
    reconciled = controller._reconcile_orphan_attempts(ledger, {})
    assert reconciled[row.row_id]["accepted"] is True
    assert len(host.requests) == 1


def test_resume_reapplies_capture_bound_structured_content_adjudication(tmp_path: Path) -> None:
    manifest = _manifest()
    host = MaterializationHost(manifest)
    controller = _controller(tmp_path, host)
    controller._prepare_private_root()
    row = next(item for item in manifest.rows if item.lane == "structured_text")
    capture = controller._write_private_json(
        f"call-{row.ordinal:02d}-{row.row_id}.json",
        {
            "manifest_sha256": manifest.manifest_sha256,
            "row_sha256": row.row_sha256,
            "inference_call_index": 2,
            "actual_inference_calls": 1,
            "exchanges": [{}],
            "runtime": {},
            "controller_verdicts": {
                "transport": "pass",
                "response_surface": "pass",
                "raw_parse": "pass",
                "schema": "pass",
                "business": "pass",
                "semantic": "pass",
            },
        },
    )
    capture_sha256 = hashlib.sha256(capture.read_bytes()).hexdigest()
    controller.adjudications = {
        row.row_id: {
            "row_sha256": row.row_sha256,
            "capture_sha256": capture_sha256,
            "dimension": "structured_text_content_fidelity",
            "semantic_pass": True,
            "reason_code": "content_preserved",
        }
    }
    prior = {
        "status": "executed",
        "inference_call_index": 2,
        "accepted": False,
        "reason": "content_fidelity_adjudication_required",
        "capture_sha256": capture_sha256,
    }

    resumed = controller._resumed_result(row, prior)

    assert resumed.accepted is True
    assert resumed.reason is None
