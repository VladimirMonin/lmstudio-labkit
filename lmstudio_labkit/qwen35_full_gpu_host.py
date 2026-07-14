"""Executable local LM Studio host for the frozen Qwen 3.5 full-GPU matrix."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from .qwen35_full_gpu import (
    Qwen35ArtifactExecutionPin,
    Qwen35MatrixError,
    Qwen35MatrixManifest,
    Qwen35ModelPin,
    _canonical_artifact_execution_pin,
)
from .schema_builders import build_blocks_schema, build_simple_flat_schema
from .validation import validate_json_schema

_STRICT_ROUTE = "/v1/chat/completions"
_NATIVE_ROUTE = "/api/v1/chat"
_NATIVE_MODELS_ROUTE = "/api/v1/models"
_INSTALLED_SDK_MODULE = (
    Path.home()
    / ".lmstudio/extensions/plugins/lmstudio/js-code-sandbox/node_modules/@lmstudio/sdk/dist/index.mjs"
)
_NEGATIVE_CAPABILITY_UNAVAILABLE = "installed_sdk_runtime_contract_has_no_explicit_negative_state"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


_FULL_GPU_LAYERS_RE = re.compile(r"\boffloaded\s+(\d+)/(\d+)\s+layers\s+to\s+GPU\b")
_CPU_FALLBACK_RE = re.compile(
    r"(?i)(?:using CPU instead|fallback to CPU|offloaded\s+\d+/\d+\s+layers\s+to\s+CPU)"
)
_RESOURCE_DOWNGRADE_RE = re.compile(
    r"(?i)(?:guardrail.*(?:downgrad|reduc)|(?:downgrad|reduc).*(?:GPU|offload)|"
    r"failed to allocate|out of memory|insufficient (?:VRAM|memory))"
)


def _unavailable_runtime_telemetry(reason: str) -> dict[str, object]:
    return {
        "gpu_layers": None,
        "total_layers": None,
        "cpu_fallback": None,
        "resource_guardrail_downgrade": None,
        "memory_thrash_observed": None,
        "runtime_telemetry_available": False,
        "runtime_telemetry_source": None,
        "runtime_telemetry_authoritative": False,
        "runtime_telemetry_unavailable_reason": reason,
        "runtime_telemetry_model_key": None,
        "runtime_telemetry_instance_id": None,
        "runtime_instance_reference": None,
        "authoritative_instance_reference": None,
        "runtime_pid": None,
        "runtime_process_start_ticks": None,
        "cpu_fallback_authority_available": False,
        "cpu_fallback_unavailable_reason": _NEGATIVE_CAPABILITY_UNAVAILABLE,
        "resource_downgrade_authority_available": False,
        "resource_downgrade_unavailable_reason": _NEGATIVE_CAPABILITY_UNAVAILABLE,
    }


def _parse_installed_runtime_telemetry(
    events: Sequence[Mapping[str, object]],
    *,
    model_id: str,
    instance_id: str,
    capture_started_ms: int,
    capture_ended_ms: int,
    process_samples: Sequence[Mapping[str, object]],
    authoritative_instance_reference: str,
) -> dict[str, object]:
    """Parse an identity-bound installed runtime-log and process telemetry capture."""

    if (
        model_id != instance_id
        or capture_started_ms >= capture_ended_ms
        or not authoritative_instance_reference
    ):
        return _unavailable_runtime_telemetry("runtime_capture_identity_or_window_invalid")
    bound: list[tuple[int, Mapping[str, object]]] = []
    for event in events:
        timestamp = event.get("timestamp")
        data = event.get("data")
        if (
            not isinstance(timestamp, int)
            or isinstance(timestamp, bool)
            or not capture_started_ms <= timestamp <= capture_ended_ms
            or not isinstance(data, Mapping)
            or data.get("type") != "runtime.log"
            or data.get("modelIdentifier") != model_id
        ):
            continue
        bound.append((timestamp, data))
    if not bound:
        return _unavailable_runtime_telemetry("identity_bound_runtime_events_missing")

    identity = {
        (
            data.get("instanceReference"),
            data.get("pid"),
            data.get("engineName"),
            data.get("engineVersion"),
            data.get("engineType"),
        )
        for _, data in bound
    }
    if len(identity) != 1:
        return _unavailable_runtime_telemetry("runtime_event_identity_is_inconsistent")
    instance_reference, pid, engine_name, engine_version, engine_type = next(iter(identity))
    if (
        not isinstance(instance_reference, str)
        or not instance_reference
        or not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or engine_name != "llama.cpp"
        or not isinstance(engine_version, str)
        or not engine_version
        or not isinstance(engine_type, str)
        or not engine_type
    ):
        return _unavailable_runtime_telemetry("runtime_event_identity_is_incomplete")
    if instance_reference != authoritative_instance_reference:
        return _unavailable_runtime_telemetry(
            "runtime_instance_reference_does_not_match_installed_sdk"
        )

    messages = [data.get("message") for _, data in bound]
    if any(not isinstance(message, str) for message in messages):
        return _unavailable_runtime_telemetry("runtime_event_message_is_invalid")
    trusted_messages = [cast(str, message) for message in messages]
    layer_matches = [
        match
        for message in trusted_messages
        for match in [_FULL_GPU_LAYERS_RE.search(message)]
        if match is not None
    ]
    if len(layer_matches) != 1:
        return _unavailable_runtime_telemetry("single_terminal_layer_count_missing")
    gpu_layers, total_layers = (int(value) for value in layer_matches[0].groups())
    if gpu_layers <= 0 or gpu_layers != total_layers:
        return _unavailable_runtime_telemetry("all_layer_gpu_offload_not_proven")

    if len(process_samples) < 3:
        return _unavailable_runtime_telemetry("runtime_process_samples_incomplete")
    sample_pids = {sample.get("pid") for sample in process_samples}
    sample_starts = {sample.get("process_start_ticks") for sample in process_samples}
    raw_sample_times = [sample.get("timestamp_ms") for sample in process_samples]
    raw_major_faults = [sample.get("major_faults") for sample in process_samples]
    raw_swap_values = [sample.get("vm_swap_kib") for sample in process_samples]
    integer_series = all(
        isinstance(value, int) and not isinstance(value, bool)
        for values in (raw_sample_times, raw_major_faults, raw_swap_values)
        for value in values
    )
    if not integer_series:
        return _unavailable_runtime_telemetry("runtime_process_samples_untrusted")
    sample_times = [cast(int, value) for value in raw_sample_times]
    major_faults = [cast(int, value) for value in raw_major_faults]
    swap_values = [cast(int, value) for value in raw_swap_values]
    if (
        sample_pids != {pid}
        or len(sample_starts) != 1
        or next(iter(sample_starts), None) in {None, 0}
        or sample_times != sorted(sample_times)
        or sample_times[-1] - sample_times[0] < 500
        or not all(capture_started_ms <= value <= capture_ended_ms for value in sample_times)
        or any(value < 0 for value in major_faults)
        or any(value < 0 for value in swap_values)
    ):
        return _unavailable_runtime_telemetry("runtime_process_samples_untrusted")

    cpu_fallback_observed = any(_CPU_FALLBACK_RE.search(message) for message in trusted_messages)
    resource_downgrade_observed = any(
        _RESOURCE_DOWNGRADE_RE.search(message) for message in trusted_messages
    )
    memory_thrash = any(value > 0 for value in swap_values) or major_faults[-1] > major_faults[0]
    return {
        "gpu_layers": gpu_layers,
        "total_layers": total_layers,
        "cpu_fallback": True if cpu_fallback_observed else None,
        "resource_guardrail_downgrade": True if resource_downgrade_observed else None,
        "memory_thrash_observed": memory_thrash,
        "runtime_telemetry_available": True,
        "runtime_telemetry_source": "installed_sdk_runtime_log_proc_v2",
        "runtime_telemetry_authoritative": True,
        "runtime_telemetry_unavailable_reason": None,
        "runtime_telemetry_model_key": model_id,
        "runtime_telemetry_instance_id": instance_id,
        "runtime_instance_reference": instance_reference,
        "authoritative_instance_reference": authoritative_instance_reference,
        "runtime_pid": pid,
        "runtime_process_start_ticks": next(iter(sample_starts)),
        "cpu_fallback_authority_available": False,
        "cpu_fallback_unavailable_reason": _NEGATIVE_CAPABILITY_UNAVAILABLE,
        "resource_downgrade_authority_available": False,
        "resource_downgrade_unavailable_reason": _NEGATIVE_CAPABILITY_UNAVAILABLE,
        "runtime_engine_name": engine_name,
        "runtime_engine_version": engine_version,
        "runtime_engine_type": engine_type,
    }


@dataclass(slots=True)
class LocalQwen35FullGPUHost:
    """Bind every manifest row to exact local routes and byte-preserving evidence."""

    manifest: Qwen35MatrixManifest
    private_root: Path
    artifact_pins: Mapping[str, Qwen35ArtifactExecutionPin] = field(default_factory=dict)
    base_url: str = "http://127.0.0.1:1234"
    default_timeout_s: float = 900.0
    lms_executable: str = "lms"
    _previous_response_ids: dict[tuple[str, int], str] = field(default_factory=dict, init=False)
    _asset_cache: dict[str, object] = field(default_factory=dict, init=False)
    _attempt_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _runtime_capture_by_model: dict[str, Mapping[str, object]] = field(
        default_factory=dict, init=False
    )
    _active_runtime_capture_by_model: dict[str, Mapping[str, object]] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise Qwen35MatrixError("Qwen production host requires a loopback LM Studio URL")
        self.private_root = self.private_root.resolve()

    def model_metadata(self, *, model_id: str) -> Mapping[str, object] | None:
        document = self._request_json("GET", _NATIVE_MODELS_ROUTE, None, self.default_timeout_s)
        model = self._exact_model(document, model_id)
        if model is None:
            return None
        pin = self._pin(model_id)
        return {**model, "artifact_evidence": self._artifact_evidence(pin, model)}

    def count_all_loaded_instances(self) -> int | None:
        document = self._request_json("GET", _NATIVE_MODELS_ROUTE, None, self.default_timeout_s)
        return self._count_loaded_document(document)

    def observe_global_zero(
        self, *, phase: str, model_id: str | None, load_group: str | None
    ) -> Mapping[str, object]:
        argv = [self.lms_executable, "ps", "--json"]
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                timeout=self.default_timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                "manifest_sha256": self.manifest.manifest_sha256,
                "phase": phase,
                "model_id": model_id,
                "load_group": load_group,
                "global_zero_verified": False,
                "error_category": type(error).__name__,
            }
        try:
            lms_models = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            lms_models = None
        lms_total = len(lms_models) if isinstance(lms_models, list) else None
        api_document, api_raw = self._request_json_with_raw(
            "GET", _NATIVE_MODELS_ROUTE, None, self.default_timeout_s
        )
        api_total = self._count_loaded_document(api_document)
        return {
            "manifest_sha256": self.manifest.manifest_sha256,
            "phase": phase,
            "model_id": model_id,
            "load_group": load_group,
            "lms_ps_argv": argv,
            "lms_ps_returncode": completed.returncode,
            "lms_ps_stdout_bytes_b64": _safe_b64(completed.stdout),
            "lms_ps_stdout_sha256": _sha256(completed.stdout),
            "lms_ps_stderr_bytes_b64": _safe_b64(completed.stderr),
            "lms_ps_stderr_sha256": _sha256(completed.stderr),
            "lms_ps_loaded_total": lms_total,
            "api_route": _NATIVE_MODELS_ROUTE,
            "api_response_bytes_b64": _safe_b64(api_raw),
            "api_response_sha256": _sha256(api_raw),
            "api_loaded_total": api_total,
            "global_zero_verified": completed.returncode == 0 and lms_total == 0 and api_total == 0,
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
        if gpu != "max" or echo_load_config is not True:
            raise Qwen35MatrixError("Qwen production load must request explicit full GPU echo")
        argv = [
            self.lms_executable,
            "load",
            model_id,
            "--gpu",
            "max",
            "--context-length",
            str(context_length),
            "--parallel",
            str(parallel),
            "--yes",
        ]
        requested = {
            "context_length": context_length,
            "parallel": parallel,
            "gpu": "max",
            "gpu_offload_ratio": 1.0,
        }
        invocation = _canonical_bytes({"argv": argv})
        request_path = self._write_lifecycle_record(
            "load",
            "request",
            {
                "argv_bytes_b64": _safe_b64(invocation),
                "argv_sha256": _sha256(invocation),
                "requested_load_config": requested,
                "state": "reserved_before_execute",
            },
        )
        runtime_capture = self._start_runtime_log_capture(model_id=model_id)
        if isinstance(runtime_capture, Mapping):
            self._active_runtime_capture_by_model[model_id] = runtime_capture
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                timeout=self.default_timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self._finish_runtime_log_capture(
                model_id=model_id,
                capture=self._active_runtime_capture_by_model.pop(model_id, runtime_capture),
            )
            self._write_lifecycle_record(
                "load",
                "response",
                {
                    "request_record": request_path.name,
                    "response_available": False,
                    "error_category": type(error).__name__,
                    "latency_ms": round((time.monotonic() - started) * 1000, 3),
                },
            )
            raise Qwen35MatrixError("Qwen installed lms load transport failed") from error
        stdout = completed.stdout
        stderr = completed.stderr
        self._write_lifecycle_record(
            "load",
            "response",
            {
                "request_record": request_path.name,
                "response_available": True,
                "returncode": completed.returncode,
                "stdout_bytes_b64": _safe_b64(stdout),
                "stdout_sha256": _sha256(stdout),
                "stderr_bytes_b64": _safe_b64(stderr),
                "stderr_sha256": _sha256(stderr),
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
            },
        )
        return {
            "load_verified": completed.returncode == 0,
            "transport": "lms_cli_load_gpu_max",
            "requested_load_config": requested,
            "invocation_sha256": _sha256(invocation),
            "stdout_sha256": _sha256(stdout),
            "stderr_sha256": _sha256(stderr),
            "returncode": completed.returncode,
        }

    def materialized_model_metadata(self, *, model_id: str) -> Mapping[str, object] | None:
        document = self._request_json("GET", _NATIVE_MODELS_ROUTE, None, self.default_timeout_s)
        return self._exact_model(document, model_id)

    def gpu_observation(self, *, model_id: str) -> Mapping[str, object] | None:
        try:
            model = self.materialized_model_metadata(model_id=model_id)
        finally:
            active_capture = self._active_runtime_capture_by_model.pop(model_id, None)
            if active_capture is not None:
                self._finish_runtime_log_capture(model_id=model_id, capture=active_capture)
        if model is None:
            return None
        if model.get("key") != model_id:
            return None
        instances = model.get("loaded_instances", model.get("instances"))
        if not isinstance(instances, Sequence) or isinstance(instances, (str, bytes, bytearray)):
            return None
        if len(instances) != 1 or not isinstance(instances[0], Mapping):
            return None
        instance = instances[0]
        instance_id = instance.get("id", instance.get("instance_id"))
        if not isinstance(instance_id, str) or not instance_id:
            return None
        config = instance.get("config", instance.get("load_config", instance.get("loadConfig")))
        if not isinstance(config, Mapping):
            return None
        ratio = self._first_number(config, "gpu_offload_ratio", "gpuOffloadRatio", "offload_ratio")
        nested_gpu = config.get("gpu")
        if ratio is None and isinstance(nested_gpu, Mapping):
            ratio = self._first_number(nested_gpu, "ratio")
            if nested_gpu.get("ratio") == "max":
                ratio = 1.0
        kv_cache_gpu = config.get(
            "offload_kv_cache_to_gpu",
            config.get(
                "offloadKVCacheToGpu",
                config.get("kv_cache_gpu", config.get("kvCacheOnGpu")),
            ),
        )
        telemetry = _unavailable_runtime_telemetry(
            "installed_runtime_log_capture_unavailable_or_incomplete"
        )
        telemetry_sha256 = None
        capture = self._runtime_capture_by_model.get(model_id)
        if isinstance(capture, Mapping):
            events = capture.get("events")
            samples = capture.get("process_samples")
            started_ms = capture.get("capture_started_ms")
            ended_ms = capture.get("capture_ended_ms")
            candidate_sha256 = capture.get("capture_sha256")
            authoritative_instance = capture.get("authoritative_instance")
            authoritative_reference = (
                authoritative_instance.get("instanceReference")
                if isinstance(authoritative_instance, Mapping)
                else None
            )
            if (
                isinstance(events, Sequence)
                and not isinstance(events, (str, bytes, bytearray))
                and all(isinstance(event, Mapping) for event in events)
                and isinstance(samples, Sequence)
                and not isinstance(samples, (str, bytes, bytearray))
                and all(isinstance(sample, Mapping) for sample in samples)
                and isinstance(started_ms, int)
                and isinstance(ended_ms, int)
                and isinstance(candidate_sha256, str)
                and isinstance(authoritative_reference, str)
                and authoritative_reference
            ):
                telemetry = _parse_installed_runtime_telemetry(
                    events,
                    model_id=model_id,
                    instance_id=instance_id,
                    capture_started_ms=started_ms,
                    capture_ended_ms=ended_ms,
                    process_samples=samples,
                    authoritative_instance_reference=authoritative_reference,
                )
                telemetry_sha256 = candidate_sha256
        return {
            "model_key": model_id,
            "instance_id": instance_id,
            "context_length": self._first_int(config, "context_length", "contextLength"),
            "parallel": self._first_int(config, "parallel", "n_parallel", "maxParallelPredictions"),
            "gpu_offload_ratio": ratio,
            "gpu_layers": telemetry["gpu_layers"],
            "total_layers": telemetry["total_layers"],
            "kv_cache_gpu_supported": True if kv_cache_gpu is not None else None,
            "kv_cache_gpu": kv_cache_gpu,
            "cpu_fallback": telemetry["cpu_fallback"],
            "resource_guardrail_downgrade": telemetry["resource_guardrail_downgrade"],
            "memory_thrash_observed": telemetry["memory_thrash_observed"],
            "runtime_telemetry_available": telemetry["runtime_telemetry_available"],
            "runtime_telemetry_source": telemetry["runtime_telemetry_source"],
            "runtime_telemetry_authoritative": telemetry["runtime_telemetry_authoritative"],
            "runtime_telemetry_unavailable_reason": telemetry[
                "runtime_telemetry_unavailable_reason"
            ],
            "runtime_telemetry_model_key": telemetry["runtime_telemetry_model_key"],
            "runtime_telemetry_instance_id": telemetry["runtime_telemetry_instance_id"],
            "runtime_instance_reference": telemetry["runtime_instance_reference"],
            "authoritative_instance_reference": telemetry["authoritative_instance_reference"],
            "runtime_pid": telemetry["runtime_pid"],
            "runtime_process_start_ticks": telemetry["runtime_process_start_ticks"],
            "cpu_fallback_authority_available": telemetry["cpu_fallback_authority_available"],
            "cpu_fallback_unavailable_reason": telemetry["cpu_fallback_unavailable_reason"],
            "resource_downgrade_authority_available": telemetry[
                "resource_downgrade_authority_available"
            ],
            "resource_downgrade_unavailable_reason": telemetry[
                "resource_downgrade_unavailable_reason"
            ],
            "observed_config_sha256": _sha256(_canonical_bytes(config)),
            "runtime_telemetry_sha256": telemetry_sha256,
        }

    def _start_runtime_log_capture(self, *, model_id: str) -> Mapping[str, object] | None:
        self.private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.private_root, 0o700)
        nonce = time.time_ns()
        stdout_path = self.private_root / f".runtime-log-{nonce}.stdout"
        stderr_path = self.private_root / f".runtime-log-{nonce}.stderr"
        stdout_handle = open(stdout_path, "xb", buffering=0)
        stderr_handle = open(stderr_path, "xb", buffering=0)
        argv = [self.lms_executable, "log", "stream", "-s", "runtime", "--json"]
        started_ms = time.time_ns() // 1_000_000
        try:
            process = subprocess.Popen(
                argv,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
            )
        except OSError:
            stdout_handle.close()
            stderr_handle.close()
            stdout_path.unlink(missing_ok=True)
            stderr_path.unlink(missing_ok=True)
            return None
        finally:
            stdout_handle.close()
            stderr_handle.close()
        deadline = time.monotonic() + min(5.0, self.default_timeout_s)
        ready = False
        while time.monotonic() < deadline and process.poll() is None:
            if b"Streaming logs from LM Studio" in stdout_path.read_bytes():
                ready = True
                break
            time.sleep(0.05)
        if not ready:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            stdout_path.unlink(missing_ok=True)
            stderr_path.unlink(missing_ok=True)
            return None
        stop_event = threading.Event()
        process_samples: list[Mapping[str, object]] = []
        monitor_started_ms = time.time_ns() // 1_000_000
        monitor = threading.Thread(
            target=self._monitor_runtime_process,
            args=(stdout_path, model_id, started_ms, stop_event, process_samples),
            daemon=True,
        )
        monitor.start()
        return {
            "argv": argv,
            "process": process,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "capture_started_ms": started_ms,
            "process_monitor_started_ms": monitor_started_ms,
            "process_monitor_stop": stop_event,
            "process_monitor_thread": monitor,
            "process_samples": process_samples,
        }

    def _finish_runtime_log_capture(
        self, *, model_id: str, capture: Mapping[str, object] | None
    ) -> None:
        if not isinstance(capture, Mapping):
            return
        process = capture.get("process")
        stdout_path = capture.get("stdout_path")
        stderr_path = capture.get("stderr_path")
        started_ms = capture.get("capture_started_ms")
        monitor_started_ms = capture.get("process_monitor_started_ms")
        stop_event = capture.get("process_monitor_stop")
        monitor = capture.get("process_monitor_thread")
        process_samples = capture.get("process_samples")
        if (
            not isinstance(process, subprocess.Popen)
            or not isinstance(stdout_path, Path)
            or not isinstance(stderr_path, Path)
            or not isinstance(started_ms, int)
            or not isinstance(monitor_started_ms, int)
            or not isinstance(stop_event, threading.Event)
            or not isinstance(monitor, threading.Thread)
            or not isinstance(process_samples, list)
        ):
            return
        time.sleep(0.1)
        authoritative_snapshot = self._capture_authoritative_loaded_instance(model_id=model_id)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            first_timestamp = process_samples[0].get("timestamp_ms") if process_samples else None
            last_timestamp = process_samples[-1].get("timestamp_ms") if process_samples else None
            if (
                len(process_samples) >= 3
                and isinstance(first_timestamp, int)
                and isinstance(last_timestamp, int)
                and last_timestamp - first_timestamp >= 500
            ):
                break
            time.sleep(0.05)
        stop_event.set()
        monitor.join(timeout=2)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        ended_ms = time.time_ns() // 1_000_000
        stdout = stdout_path.read_bytes()
        stderr = stderr_path.read_bytes()
        events = self._decode_runtime_log_events(stdout)
        record = {
            "capture_started_ms": started_ms,
            "capture_ended_ms": ended_ms,
            "process_monitor_started_ms": monitor_started_ms,
            "argv": capture.get("argv"),
            "stream_returncode": process.returncode,
            "stdout_bytes_b64": _safe_b64(stdout),
            "stdout_sha256": _sha256(stdout),
            "stderr_bytes_b64": _safe_b64(stderr),
            "stderr_sha256": _sha256(stderr),
            "events": events,
            "process_samples": process_samples,
            "authoritative_instance": authoritative_snapshot.get("instance"),
            "authoritative_instance_capture": authoritative_snapshot,
            "negative_capability_evidence": {
                "cpu_fallback_false": _NEGATIVE_CAPABILITY_UNAVAILABLE,
                "resource_guardrail_downgrade_false": _NEGATIVE_CAPABILITY_UNAVAILABLE,
            },
        }
        canonical = _canonical_bytes(record)
        capture_sha256 = _sha256(canonical)
        capture_path = self.private_root / f"runtime-telemetry-{capture_sha256}.json"
        descriptor = os.open(capture_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, canonical)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)
        self._runtime_capture_by_model[model_id] = {
            **record,
            "capture_sha256": capture_sha256,
            "capture_path": capture_path.name,
        }

    @staticmethod
    def _decode_runtime_log_events(raw: bytes) -> list[Mapping[str, object]]:
        events: list[Mapping[str, object]] = []
        for line in raw.splitlines():
            if not line.startswith(b"{"):
                continue
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, Mapping):
                events.append(value)
        return events

    @staticmethod
    def _bound_runtime_pid(
        events: Sequence[Mapping[str, object]], *, model_id: str, started_ms: int
    ) -> int | None:
        pids: set[int] = set()
        for event in events:
            timestamp = event.get("timestamp")
            data = event.get("data")
            if (
                not isinstance(timestamp, int)
                or timestamp < started_ms
                or not isinstance(data, Mapping)
                or data.get("type") != "runtime.log"
                or data.get("modelIdentifier") != model_id
                or not isinstance(data.get("instanceReference"), str)
                or not data.get("instanceReference")
            ):
                continue
            pid = data.get("pid")
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                pids.add(pid)
        return next(iter(pids)) if len(pids) == 1 else None

    @classmethod
    def _monitor_runtime_process(
        cls,
        stdout_path: Path,
        model_id: str,
        started_ms: int,
        stop_event: threading.Event,
        samples: list[Mapping[str, object]],
    ) -> None:
        """Start before load, discover the exact runtime PID, and sample through attestation."""

        bound_pid: int | None = None
        while not stop_event.is_set():
            if bound_pid is None:
                try:
                    events = cls._decode_runtime_log_events(stdout_path.read_bytes())
                except OSError:
                    return
                bound_pid = cls._bound_runtime_pid(events, model_id=model_id, started_ms=started_ms)
            if bound_pid is not None:
                sample = cls._read_runtime_process_sample(bound_pid)
                if sample is None:
                    return
                samples.append(sample)
            stop_event.wait(0.1)

    @staticmethod
    def _read_runtime_process_sample(pid: int) -> Mapping[str, object] | None:
        try:
            stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
            status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        except OSError:
            return None
        swap_match = re.search(r"(?m)^VmSwap:\s+(\d+)\s+kB$", status)
        if len(stat_fields) < 22 or swap_match is None:
            return None
        return {
            "timestamp_ms": time.time_ns() // 1_000_000,
            "pid": pid,
            "process_start_ticks": int(stat_fields[21]),
            "major_faults": int(stat_fields[11]),
            "vm_swap_kib": int(swap_match.group(1)),
        }

    def _capture_authoritative_loaded_instance(self, *, model_id: str) -> dict[str, object]:
        module_path = _INSTALLED_SDK_MODULE
        if not module_path.is_file():
            return {
                "available": False,
                "reason": "installed_sdk_module_missing",
                "module_path_sha256": _sha256(os.fsencode(module_path)),
            }
        script = """
const { LMStudioClient } = await import(process.argv[1]);
const modelId = process.argv[2];
const client = new LMStudioClient();
const loaded = await client.llm.listLoaded();
const values = await Promise.all(loaded.map(async model => ({
  identifier: model.identifier,
  instanceReference: model.instanceReference,
  modelKey: model.modelKey,
  info: await model.getModelInfo(),
})));
console.log(JSON.stringify(values.filter(value =>
  value.identifier === modelId && value.modelKey === modelId)));
"""
        try:
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script, str(module_path), model_id],
                check=False,
                capture_output=True,
                timeout=min(10.0, self.default_timeout_s),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"available": False, "reason": type(error).__name__}
        result: dict[str, object] = {
            "available": False,
            "module_sha256": self._hash_file(module_path),
            "stdout_sha256": _sha256(completed.stdout),
            "stderr_sha256": _sha256(completed.stderr),
            "returncode": completed.returncode,
        }
        try:
            values = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            values = None
        if completed.returncode != 0 or not isinstance(values, list) or len(values) != 1:
            result["reason"] = "installed_sdk_exact_loaded_instance_unavailable"
            return result
        value = values[0]
        info = value.get("info") if isinstance(value, Mapping) else None
        if (
            not isinstance(value, Mapping)
            or value.get("identifier") != model_id
            or value.get("modelKey") != model_id
            or not isinstance(value.get("instanceReference"), str)
            or not value.get("instanceReference")
            or not isinstance(info, Mapping)
            or info.get("identifier") != model_id
            or info.get("instanceReference") != value.get("instanceReference")
        ):
            result["reason"] = "installed_sdk_loaded_instance_identity_inconsistent"
            return result
        result.update({"available": True, "instance": dict(value)})
        return result

    @staticmethod
    def _sample_runtime_process(pid: int) -> list[Mapping[str, object]]:
        samples: list[Mapping[str, object]] = []
        for _ in range(3):
            try:
                stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
                status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
            except OSError:
                return []
            swap_match = re.search(r"(?m)^VmSwap:\s+(\d+)\s+kB$", status)
            if len(stat_fields) < 22 or swap_match is None:
                return []
            samples.append(
                {
                    "timestamp_ms": time.time_ns() // 1_000_000,
                    "pid": pid,
                    "process_start_ticks": int(stat_fields[21]),
                    "major_faults": int(stat_fields[11]),
                    "vm_swap_kib": int(swap_match.group(1)),
                }
            )
            time.sleep(0.25)
        return samples

    def execute_matrix_row(
        self, *, row: Mapping[str, object], timeout_s: float
    ) -> Mapping[str, object]:
        self._validate_row_binding(row)
        kind = str(row["request_kind"])
        if kind == "parallel_pair":
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(self._execute_one, row, timeout_s, slot) for slot in (0, 1)
                ]
                exchanges = [future.result() for future in futures]
        else:
            exchanges = [self._execute_one(row, timeout_s, 0)]
        verdicts = self._verdicts(row, exchanges)
        return {
            "http_call_count": len(exchanges),
            "exchanges": exchanges,
            "verdicts": verdicts,
            "runtime": {
                "request_kind": kind,
                "parallel_fanout": len(exchanges),
            },
        }

    def cleanup_model(self, *, model_id: str) -> object:
        active_capture = self._active_runtime_capture_by_model.pop(model_id, None)
        if active_capture is not None:
            self._finish_runtime_log_capture(model_id=model_id, capture=active_capture)
        model = self.materialized_model_metadata(model_id=model_id)
        if model is None:
            return {
                "cleanup_verified": self.count_all_loaded_instances() == 0,
                "already_absent": True,
            }
        instances = model.get("loaded_instances", model.get("instances"))
        if not isinstance(instances, Sequence) or isinstance(instances, (str, bytes, bytearray)):
            return {"cleanup_verified": False}
        for instance in instances:
            if not isinstance(instance, Mapping):
                return {"cleanup_verified": False}
            instance_id = instance.get("id", instance.get("instance_id"))
            if not isinstance(instance_id, str) or not instance_id:
                return {"cleanup_verified": False}
            self._request_json(
                "POST",
                "/api/v1/models/unload",
                {"instance_id": instance_id},
                self.default_timeout_s,
            )
        remaining = self.materialized_model_metadata(model_id=model_id)
        remaining_instances = () if remaining is None else remaining.get("loaded_instances", ())
        return {
            "cleanup_verified": isinstance(remaining_instances, Sequence)
            and not isinstance(remaining_instances, (str, bytes, bytearray))
            and len(remaining_instances) == 0
        }

    def _execute_one(
        self, row: Mapping[str, object], timeout_s: float, worker_slot: int
    ) -> dict[str, object]:
        endpoint, payload = self._build_request(row, worker_slot=worker_slot)
        outbound = _canonical_bytes(payload)
        attempt_index = self._reserve_attempt(row, endpoint, worker_slot, outbound)
        started = time.monotonic()
        try:
            status, content_type, raw = self._request_exact(endpoint, outbound, timeout_s)
        except Exception as error:
            latency_ms = round((time.monotonic() - started) * 1000, 3)
            completion = {
                "manifest_sha256": self.manifest.manifest_sha256,
                "row_id": row["row_id"],
                "attempt_index": attempt_index,
                "worker_slot": worker_slot,
                "response_available": False,
                "transport_error_category": type(error).__name__,
                "latency_ms": latency_ms,
            }
            self._complete_attempt(row, worker_slot, completion)
            return {
                "endpoint": endpoint,
                "worker_slot": worker_slot,
                "attempt_index": attempt_index,
                "outbound_bytes_b64": _safe_b64(outbound),
                "outbound_sha256": _sha256(outbound),
                "response_available": False,
                "transport_error_category": type(error).__name__,
                "latency_ms": latency_ms,
            }
        exchange: dict[str, object] = {
            "endpoint": endpoint,
            "worker_slot": worker_slot,
            "attempt_index": attempt_index,
            "outbound_bytes_b64": _safe_b64(outbound),
            "outbound_sha256": _sha256(outbound),
            "response_available": True,
            "raw_response_bytes_b64": _safe_b64(raw),
            "raw_response_sha256": _sha256(raw),
            "http_status": status,
            "content_type": content_type,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        }
        decoded: object | None = None
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        exchange["decoded"] = decoded
        response_id = decoded.get("response_id") if isinstance(decoded, Mapping) else None
        if (
            endpoint == _NATIVE_ROUTE
            and isinstance(response_id, str)
            and response_id.startswith("resp_")
        ):
            context_length = row["context_length"]
            if not isinstance(context_length, int) or isinstance(context_length, bool):
                raise Qwen35MatrixError("Qwen row context length is invalid")
            key = (str(row["model_id"]), context_length)
            self._previous_response_ids[key] = response_id
        self._complete_attempt(
            row,
            worker_slot,
            {
                "manifest_sha256": self.manifest.manifest_sha256,
                "row_id": row["row_id"],
                "attempt_index": attempt_index,
                "worker_slot": worker_slot,
                "response_available": True,
                "http_status": status,
                "content_type": content_type,
                "raw_response_bytes_b64": _safe_b64(raw),
                "raw_response_sha256": _sha256(raw),
                "decoded": decoded,
                "latency_ms": exchange["latency_ms"],
            },
        )
        return exchange

    def _reserve_attempt(
        self,
        row: Mapping[str, object],
        endpoint: str,
        worker_slot: int,
        outbound: bytes,
    ) -> int:
        ordinal = row.get("ordinal")
        row_id = row.get("row_id")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or not isinstance(row_id, str):
            raise Qwen35MatrixError("Qwen attempt row binding is invalid")
        with self._attempt_lock:
            attempt_index = (
                len(list(self.private_root.glob("attempt-q35-*-slot-*-request.json"))) + 1
            )
            if not 1 <= attempt_index <= self.manifest.max_inference_calls:
                raise Qwen35MatrixError("Qwen durable attempt index exceeds the frozen ceiling")
            payload = {
                "manifest_sha256": self.manifest.manifest_sha256,
                "row_id": row_id,
                "row_sha256": next(
                    item.row_sha256 for item in self.manifest.rows if item.row_id == row_id
                ),
                "attempt_index": attempt_index,
                "worker_slot": worker_slot,
                "endpoint": endpoint,
                "outbound_bytes_b64": _safe_b64(outbound),
                "outbound_sha256": _sha256(outbound),
                "state": "reserved_before_send",
            }
            self._write_attempt_file(row_id, worker_slot, "request", payload)
        return attempt_index

    def _complete_attempt(
        self,
        row: Mapping[str, object],
        worker_slot: int,
        payload: Mapping[str, object],
    ) -> None:
        row_id = row.get("row_id")
        if not isinstance(row_id, str):
            raise Qwen35MatrixError("Qwen attempt completion row binding is invalid")
        with self._attempt_lock:
            self._write_attempt_file(row_id, worker_slot, "response", payload)

    def _write_attempt_file(
        self,
        row_id: str,
        worker_slot: int,
        phase: str,
        payload: Mapping[str, object],
    ) -> None:
        path = self.private_root / f"attempt-{row_id}-slot-{worker_slot}-{phase}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, _canonical_bytes(payload) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_lifecycle_record(
        self,
        operation: str,
        phase: str,
        payload: Mapping[str, object],
    ) -> Path:
        self.private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.private_root, 0o700)
        index = len(list(self.private_root.glob("lifecycle-*-request.json"))) + 1
        path = self.private_root / f"lifecycle-{index:04d}-{operation}-{phase}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, _canonical_bytes(payload) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return path

    def _build_request(
        self, row: Mapping[str, object], *, worker_slot: int
    ) -> tuple[str, dict[str, object]]:
        kind = str(row["request_kind"])
        model_id = str(row["model_id"])
        reasoning = str(row["reasoning"])
        if kind in {
            "strict_json_canary",
            "structured_text",
            "strict_simple",
            "strict_medium",
            "strict_ui_repeat",
        }:
            prompt, schema_name, schema, content = self._strict_material(row)
            payload: dict[str, object] = {
                "model": model_id,
                "messages": [{"role": "user", "content": content or prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
                "temperature": 0.0,
                "max_tokens": 4096 if row.get("lane") == "structured_text" else 1024,
                "stream": False,
            }
            if reasoning != "omitted":
                payload["reasoning"] = reasoning
                payload["enable_thinking"] = reasoning == "on"
            return _STRICT_ROUTE, payload
        prompt, image_data_url = self._native_material(row, worker_slot=worker_slot)
        native: dict[str, object] = {
            "model": model_id,
            "input": prompt,
            "temperature": 0.0,
            "max_output_tokens": 1024,
            "stream": False,
            "store": kind in {"warm_prefix", "prefix_reuse", "session_reuse"},
        }
        if image_data_url is not None:
            native["input"] = [
                {"type": "text", "content": prompt},
                {"type": "image", "data_url": image_data_url},
            ]
        if reasoning != "omitted":
            native["reasoning"] = reasoning
        if kind == "session_reuse":
            context_length = row["context_length"]
            if not isinstance(context_length, int) or isinstance(context_length, bool):
                raise Qwen35MatrixError("Qwen row context length is invalid")
            key = (model_id, context_length)
            prior = self._previous_response_ids.get(key)
            if prior is None:
                raise Qwen35MatrixError("Qwen session row has no bound previous response id")
            native["previous_response_id"] = prior
        return _NATIVE_ROUTE, native

    def _strict_material(
        self, row: Mapping[str, object]
    ) -> tuple[str, str, dict[str, object], object | None]:
        kind = str(row["request_kind"])
        if kind == "strict_json_canary":
            schema = build_simple_flat_schema()
            return "Return id 1 and text ok.", "simple", schema, None
        if row.get("lane") == "structured_text":
            binding = str(row["source_binding"])
            fixture = self._read_json(
                self.manifest.repo_root
                / f"experiments/lmstudio/private_benchmark_pack/v1/views/{binding}/fixture.json"
            )
            units = fixture.get("ordered_units")
            if not isinstance(units, list):
                raise Qwen35MatrixError("Qwen structured fixture units are invalid")
            source = "\n".join(
                str(item.get("text", "")) for item in units if isinstance(item, Mapping)
            )
            if row.get("schema_name") == "blocks":
                ids: list[int | str] = []
                for item in units:
                    if not isinstance(item, Mapping):
                        continue
                    unit_id = item.get("unit_index")
                    if isinstance(unit_id, (int, str)) and not isinstance(unit_id, bool):
                        ids.append(unit_id)
                schema = build_blocks_schema(ids, "hardened_const")
                prompt = (
                    "Return one exact JSON block per ordered source unit without adding facts.\n"
                    + source
                )
                return prompt, "blocks", schema, None
            schema = self._read_json(
                self.manifest.repo_root
                / "experiments/lmstudio/private_benchmark_pack/v1/schemas/normalization_output_v1.schema.json"
            )
            instruction = (
                self.manifest.repo_root
                / "experiments/lmstudio/private_benchmark_pack/v1/prompts/normalization-v1.txt"
            ).read_text(encoding="utf-8")
            prompt = (
                instruction
                + "\npublic fixture digest: "
                + str(fixture.get("public_structure_sha256"))
                + "\nsource:\n"
                + source
            )
            return prompt, "normalization_v1", schema, None
        vision = self._vision_assets()
        fixture_id = str(row["fixture_id"])
        fixture = vision["fixtures"][fixture_id]
        schema_name = str(row["schema_name"])
        schema = vision["schemas"][schema_name]
        prompt = vision["prompts"][schema_name]
        data_url = "data:image/png;base64," + _safe_b64(Path(fixture["path"]).read_bytes())
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        return prompt, schema_name, schema, content

    def _native_material(
        self, row: Mapping[str, object], *, worker_slot: int
    ) -> tuple[str, str | None]:
        if row.get("lane") == "strict_structured_vision":
            vision = self._vision_assets()
            fixture = vision["fixtures"][str(row["fixture_id"])]
            return (
                vision["prompts"]["native_plain"],
                "data:image/png;base64," + _safe_b64(Path(fixture["path"]).read_bytes()),
            )
        kind = str(row["request_kind"])
        prefix = (
            "Synthetic reusable context. Preserve marker ROOT-Q35 and answer only the final "
            "question. "
        )
        if kind in {"cold", "warm_prefix", "prefix_reuse", "session_reuse"}:
            return prefix * 64 + f"\nRequest kind: {kind}. Return ROOT-Q35.", None
        return f"Bounded concurrency probe slot {worker_slot}. Return slot {worker_slot}.", None

    def _verdicts(
        self, row: Mapping[str, object], exchanges: Sequence[Mapping[str, object]]
    ) -> dict[str, str]:
        transport = "pass" if all(item.get("http_status") == 200 for item in exchanges) else "fail"
        decoded = [item.get("decoded") for item in exchanges]
        surface = (
            "pass"
            if transport == "pass" and all(isinstance(v, Mapping) for v in decoded)
            else "fail"
        )
        raw_parse = "not_applicable"
        schema_status = "not_applicable"
        business = "not_applicable"
        semantic = "pending_manual"
        if str(row["request_kind"]).startswith("strict") or row.get("lane") == "structured_text":
            contents = [self._compat_content(value) for value in decoded]
            raw_parse = "pass" if all(value is not None for value in contents) else "fail"
            parsed_values: list[object] = []
            if raw_parse == "pass":
                try:
                    parsed_values = [json.loads(value) for value in contents if value is not None]
                except json.JSONDecodeError:
                    raw_parse = "fail"
            if raw_parse == "pass":
                _prompt, _name, schema, _content = self._strict_material(row)
                schema_status = (
                    "pass"
                    if all(
                        validate_json_schema(value, schema).status == "pass"
                        for value in parsed_values
                    )
                    else "fail"
                )
                business = schema_status
                semantic = "pending_manual" if schema_status == "pass" else "fail"
            else:
                schema_status = "skip"
                business = "skip"
                semantic = "skip"
        manual = "pending" if row.get("lane") == "strict_structured_vision" else "not_applicable"
        return {
            "transport": transport,
            "response_surface": surface,
            "raw_parse": raw_parse,
            "schema": schema_status,
            "business": business,
            "semantic": semantic,
            "manual_pixel": manual,
        }

    def _vision_assets(self) -> dict[str, Any]:
        cached = self._asset_cache.get("vision")
        if isinstance(cached, dict):
            return cached
        path = self.manifest.repo_root / "experiments/lmstudio/strict_vision/launch_manifest.json"
        payload = self._read_json(path)
        fixtures: dict[str, dict[str, object]] = {}
        for item in payload.get("fixtures", []):
            if not isinstance(item, Mapping):
                continue
            fixture_path = (path.parent / str(item["path"])).resolve()
            raw = fixture_path.read_bytes()
            if _sha256(raw) != item.get("sha256"):
                raise Qwen35MatrixError("Qwen vision fixture digest mismatch")
            fixtures[str(item["fixture_id"])] = {
                **item,
                "path": fixture_path,
                "ground_truth_sha256": _sha256(_canonical_bytes(item.get("ground_truth"))),
            }
        schemas = {
            str(item["name"]): dict(item["body"])
            for item in payload.get("schemas", [])
            if isinstance(item, Mapping) and isinstance(item.get("body"), Mapping)
        }
        prompts = {
            str(item["name"]): str(item["text"])
            for item in payload.get("prompts", [])
            if isinstance(item, Mapping)
        }
        result = {"fixtures": fixtures, "schemas": schemas, "prompts": prompts}
        self._asset_cache["vision"] = result
        return result

    def _validate_row_binding(self, row: Mapping[str, object]) -> None:
        row_id = row.get("row_id")
        matches = [item for item in self.manifest.rows if item.row_id == row_id]
        if len(matches) != 1 or matches[0].binding() != dict(row):
            raise Qwen35MatrixError("Qwen production host received an unbound manifest row")

    def _artifact_evidence(
        self, pin: Qwen35ModelPin, metadata: Mapping[str, object]
    ) -> dict[str, object]:
        del metadata
        execution_pin = self.artifact_pins.get(pin.model_id)
        canonical_pin = _canonical_artifact_execution_pin(execution_pin)
        if canonical_pin is None or canonical_pin.get("model_id") != pin.model_id:
            return {"status": "unavailable", "reason": "external_artifact_pin_missing"}
        files = canonical_pin.get("files")
        if not isinstance(files, list):
            return {"status": "unavailable", "reason": "external_artifact_pin_missing"}
        for file_pin in files:
            if not isinstance(file_pin, Mapping):
                return {"status": "unavailable", "reason": "external_artifact_pin_missing"}
            path = Path(str(file_pin.get("path"))).resolve()
            if (
                not path.is_file()
                or path.stat().st_size != file_pin.get("size_bytes")
                or _sha256(os.fsencode(path)) != file_pin.get("path_sha256")
                or self._hash_file(path) != file_pin.get("sha256")
            ):
                return {
                    "status": "unavailable",
                    "variant": canonical_pin.get("variant"),
                    "reason": "external_artifact_pin_mismatch",
                }
        return {
            "status": "verified",
            "variant": canonical_pin.get("variant"),
            "pin_sha256": canonical_pin.get("pin_sha256"),
            "file_count": len(files),
        }

    def _request_exact(
        self, path: str, outbound: bytes, timeout_s: float
    ) -> tuple[int, str, bytes]:
        request = urllib_request.Request(
            self.base_url.rstrip("/") + path,
            data=outbound,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout_s) as response:
                return (
                    int(getattr(response, "status", 200)),
                    str(response.headers.get("Content-Type", "application/json")),
                    response.read(),
                )
        except HTTPError as error:
            return (
                int(error.code),
                str(error.headers.get("Content-Type", "application/json")),
                error.read(),
            )
        except URLError as error:
            raise Qwen35MatrixError("Qwen local LM Studio endpoint is not reachable") from error

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None,
        timeout_s: float,
    ) -> Mapping[str, object]:
        value, _raw = self._request_json_with_raw(method, path, payload, timeout_s)
        return value

    def _request_json_with_raw(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None,
        timeout_s: float,
    ) -> tuple[Mapping[str, object], bytes]:
        data = None if payload is None else _canonical_bytes(payload)
        request = urllib_request.Request(
            self.base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout_s) as response:
                raw = response.read()
        except (HTTPError, URLError) as error:
            raise Qwen35MatrixError(f"Qwen lifecycle request failed at {path}") from error
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise Qwen35MatrixError("Qwen lifecycle response was not JSON") from error
        if not isinstance(value, Mapping):
            raise Qwen35MatrixError("Qwen lifecycle response must be an object")
        return value, raw

    @staticmethod
    def _count_loaded_document(document: Mapping[str, object]) -> int | None:
        models = document.get("models", document.get("data"))
        if not isinstance(models, Sequence) or isinstance(models, (str, bytes, bytearray)):
            return None
        total = 0
        for model in models:
            if not isinstance(model, Mapping):
                continue
            instances = model.get("loaded_instances", model.get("instances"))
            if isinstance(instances, Sequence) and not isinstance(
                instances, (str, bytes, bytearray)
            ):
                total += len(instances)
            elif model.get("loaded") is True or model.get("state") == "loaded":
                total += 1
        return total

    def _pin(self, model_id: str) -> Qwen35ModelPin:
        return next(pin for pin in self.manifest.models if pin.model_id == model_id)

    @staticmethod
    def _exact_model(document: Mapping[str, object], model_id: str) -> Mapping[str, object] | None:
        models = document.get("models", document.get("data"))
        if not isinstance(models, Sequence) or isinstance(models, (str, bytes, bytearray)):
            return None
        matches = [
            item for item in models if isinstance(item, Mapping) and item.get("key") == model_id
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _compat_content(value: object) -> str | None:
        if not isinstance(value, Mapping):
            return None
        choices = value.get("choices")
        if (
            not isinstance(choices, Sequence)
            or isinstance(choices, (str, bytes, bytearray))
            or not choices
        ):
            return None
        choice = choices[0]
        if not isinstance(choice, Mapping):
            return None
        message = choice.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        return content if isinstance(content, str) else None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise Qwen35MatrixError(f"Qwen bound JSON asset is not an object: {path.name}")
        return value

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _first_int(mapping: Mapping[str, object], *keys: str) -> int | None:
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    @staticmethod
    def _first_number(mapping: Mapping[str, object], *keys: str) -> float | None:
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
        return None


__all__ = ["LocalQwen35FullGPUHost"]
