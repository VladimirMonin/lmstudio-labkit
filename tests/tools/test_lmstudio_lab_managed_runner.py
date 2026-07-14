from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

import pytest
import tools.lmstudio_lab.managed_runner as managed_runner_module
import yaml
from tools.lmstudio_lab import (
    ManagedLabRunner,
    SystemMetricsSnapshot,
    SystemMetricsSummary,
)
from tools.lmstudio_lab.datasets import load_chunked_dataset_view

from lmstudio_managed.cache_contracts.contracts import (
    CacheExperimentPlan,
    CompactMemoryRequest,
    StatefulBranchRequest,
    StatefulRootRequest,
    StatelessPrefixRequest,
)
from lmstudio_managed.client import (
    EndpointKind,
    EndpointSpec,
    HttpMethod,
    TransportRequest,
    TransportResponse,
    TransportResult,
)
from lmstudio_managed.download import DownloadRequest
from lmstudio_managed.generation import (
    PlainTextGenerationRequest,
    ResponseFormatKind,
    StructuredGenerationRequest,
)
from lmstudio_managed.lifecycle import LoadModelRequest, UnloadModelRequest

PREP_DATASET_ID = "blocks_json_medium_chunked"
PREP_MODEL_KEYS = ("gemma4_e2b_q4km", "gemma4_e4b_q4km")
PRIVATE_CONTENT_SENTINEL = "private-content-sentinel"
PRIVATE_PROVIDER_URL = "https://private.example.test/v1/providers/local"
PRIVATE_PROVIDER_PATH = r"C:\Users\Private\LM Studio\provider"

FORBIDDEN_SUMMARY_KEYS = {
    "body",
    "cmdline",
    "content",
    "cwd",
    "env",
    "instance_id",
    "job_id",
    "messages",
    "path",
    "payload",
    "prompt",
    "response_text",
    "url",
    "username",
}


def _safe_hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class _TransportEnvelope:
    transport_result: TransportResult
    payload: object | None = None


class _QueueTransport:
    def __init__(self, responses: dict[EndpointKind, list[_TransportEnvelope]]) -> None:
        self._responses = {kind: list(items) for kind, items in responses.items()}
        self.requests: list[TransportRequest] = []

    def __call__(self, request: TransportRequest) -> _TransportEnvelope:
        self.requests.append(request)
        queue = self._responses.get(request.endpoint.kind)
        if not queue:
            raise AssertionError(f"unexpected request for {request.endpoint.kind.value}")
        return queue.pop(0)


class _FakeSystemSampler:
    def __init__(
        self,
        *,
        samples: list[SystemMetricsSnapshot],
        summary: SystemMetricsSummary,
    ) -> None:
        self.samples = list(samples)
        self.summary = summary
        self.started_providers: dict[str, str] | None = None
        self.stopped_providers: dict[str, str] | None = None
        self.start_calls = 0
        self.stop_calls = 0

    def start(self, *, providers=None) -> None:
        self.start_calls += 1
        self.started_providers = dict(providers or {})
        for sample in self.samples:
            sample.providers = dict(providers or {})

    def stop(self, *, providers=None) -> SystemMetricsSummary:
        self.stop_calls += 1
        self.stopped_providers = dict(providers or {})
        for sample in self.samples:
            sample.providers = dict(providers or {})
        self.summary.providers = dict(providers or {})
        self.summary.sample_count = len(self.samples)
        return self.summary


class _ManualClock:
    def __init__(self) -> None:
        self._seconds = 0.0

    def now(self) -> float:
        return self._seconds

    def advance_ms(self, milliseconds: float) -> None:
        self._seconds += milliseconds / 1000.0


def _ok_response(
    kind: EndpointKind,
    method: HttpMethod,
    privacy_label: str,
    payload: object,
    *,
    body_seed: str,
) -> _TransportEnvelope:
    return _TransportEnvelope(
        transport_result=TransportResult(
            response=TransportResponse(
                endpoint=EndpointSpec(
                    kind=kind,
                    method=method,
                    privacy_label=privacy_label,
                ),
                status_code=200,
                body_hash=_safe_hash(body_seed),
                body_chars=32,
                schema_name=f"{privacy_label}_response",
            )
        ),
        payload=payload,
    )


def _structured_request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        model_key="model-structured",
        response_format=ResponseFormatKind.JSON_SCHEMA,
        prompt_hash=_safe_hash("prompt-structured"),
        prompt_chars=144,
        max_tokens=256,
        profile_id="structured-default",
    )


def _plain_request() -> PlainTextGenerationRequest:
    return PlainTextGenerationRequest(
        model_key="model-plain",
        prompt_hash=_safe_hash("prompt-plain"),
        prompt_chars=96,
        max_tokens=128,
        profile_id="plain-default",
    )


def _assert_safe_summary(summary: dict[str, object], *sentinels: str) -> None:
    assert FORBIDDEN_SUMMARY_KEYS.isdisjoint(summary.keys())
    serialized = json.dumps(summary, sort_keys=True)
    for sentinel in sentinels:
        assert sentinel not in serialized


def _fake_system_samples() -> list[SystemMetricsSnapshot]:
    return [
        SystemMetricsSnapshot(
            timestamp_utc="2026-01-01T00:00:00Z",
            monotonic_seconds=1.0,
            ram_used_mb=1024.0,
            process_name="lmstudio",
            process_rss_mb=256.0,
            vram_used_mb=2048.0,
            gpu_util_percent=10.0,
            gpu_power_watts=80.0,
        ),
        SystemMetricsSnapshot(
            timestamp_utc="2026-01-01T00:00:01Z",
            monotonic_seconds=2.0,
            ram_used_mb=1536.0,
            process_name="lmstudio",
            process_rss_mb=384.0,
            vram_used_mb=3072.0,
            gpu_util_percent=75.0,
            gpu_power_watts=120.0,
        ),
    ]


def _fake_system_summary() -> SystemMetricsSummary:
    return SystemMetricsSummary(
        ram_before_mb=1024.0,
        ram_peak_mb=1536.0,
        ram_after_mb=1536.0,
        process_rss_before_mb=256.0,
        process_rss_peak_mb=384.0,
        process_rss_after_mb=384.0,
        vram_before_mb=2048.0,
        vram_peak_mb=3072.0,
        vram_after_mb=3072.0,
        gpu_util_peak_percent=75.0,
        gpu_power_peak_watts=120.0,
    )


def _assert_safe_system_artifacts(*texts: str) -> None:
    for text in texts:
        assert '"cmdline"' not in text
        assert '"cwd"' not in text
        assert '"url"' not in text
        assert '"username"' not in text
        assert '"env"' not in text
        assert '"prompt"' not in text
        assert '"response"' not in text
        assert '"messages"' not in text
        assert '"instance_id"' not in text
        assert '"job_id"' not in text


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _cache_stateful_plan(
    *,
    model_key: str = "gemma4_e2b_q4km",
    context_window: int = 8192,
) -> CacheExperimentPlan:
    root_request = StatefulRootRequest(
        request_id="root_context",
        model_key=model_key,
        dataset_id="cache_stateful_synthetic",
        root_context_hash=_safe_hash(f"{PRIVATE_CONTENT_SENTINEL}-root-context"),
        estimated_input_tokens=4096,
        context_window=context_window,
    )
    return CacheExperimentPlan(
        experiment_id="cache_stateful_no_live_lab",
        model_key=model_key,
        context_window=context_window,
        root_request=root_request,
        stateful_branch_requests=(
            StatefulBranchRequest(
                request_id="stateful_summary",
                root_request_id=root_request.request_id,
                branch_id="summary",
                root_context_hash=root_request.root_context_hash,
                estimated_branch_tokens=512,
            ),
            StatefulBranchRequest(
                request_id="stateful_timeline",
                root_request_id=root_request.request_id,
                branch_id="timeline",
                root_context_hash=root_request.root_context_hash,
                estimated_branch_tokens=640,
            ),
        ),
        stateless_prefix_requests=(
            StatelessPrefixRequest(
                request_id="stateless_summary",
                branch_id="summary",
                prefix_context_hash=_safe_hash(f"{PRIVATE_CONTENT_SENTINEL}-stateless-summary"),
                estimated_input_tokens=4608,
            ),
            StatelessPrefixRequest(
                request_id="stateless_timeline",
                branch_id="timeline",
                prefix_context_hash=_safe_hash(f"{PRIVATE_CONTENT_SENTINEL}-stateless-timeline"),
                estimated_input_tokens=4736,
            ),
        ),
        compact_memory_requests=(
            CompactMemoryRequest(
                request_id="compact_summary",
                branch_id="summary",
                memory_hash=_safe_hash(f"{PRIVATE_CONTENT_SENTINEL}-compact-summary"),
                estimated_memory_tokens=256,
                estimated_branch_tokens=512,
            ),
            CompactMemoryRequest(
                request_id="compact_timeline",
                branch_id="timeline",
                memory_hash=_safe_hash(f"{PRIVATE_CONTENT_SENTINEL}-compact-timeline"),
                estimated_memory_tokens=288,
                estimated_branch_tokens=640,
            ),
        ),
    )


def _prep_chunk_payload(
    *,
    model_key: str,
    chunk_id: int,
    content_seed: str = PRIVATE_CONTENT_SENTINEL,
    reasoning_content: str | None = None,
    finish_reason: str = "stop",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "content": f"{content_seed}-{model_key}-chunk-{chunk_id}",
        "finish_reason": finish_reason,
        "usage": {
            "prompt_tokens": 100 + chunk_id,
            "completion_tokens": 40 + chunk_id,
        },
        "prompt": f"raw-prompt-{model_key}-{chunk_id}",
    }
    if reasoning_content is not None:
        payload["reasoning_content"] = reasoning_content
    return payload


def _prep_transport(
    *,
    failure_overrides: dict[tuple[str, int], dict[str, object]] | None = None,
) -> _QueueTransport:
    responses: list[_TransportEnvelope] = []
    overrides = failure_overrides or {}
    for model_key in PREP_MODEL_KEYS:
        for chunk_id in range(4):
            payload = overrides.get(
                (model_key, chunk_id),
                _prep_chunk_payload(model_key=model_key, chunk_id=chunk_id),
            )
            responses.append(
                _ok_response(
                    EndpointKind.COMPAT_CHAT,
                    HttpMethod.POST,
                    "compat_chat",
                    payload,
                    body_seed=f"{model_key}-{chunk_id}-body",
                )
            )
    return _QueueTransport({EndpointKind.COMPAT_CHAT: responses})


def _write_live_config(
    tmp_path: Path,
    *,
    experiment_id: str = "m1_2_structured_medium_chunked_gemma4_e2b",
    model_key: str = "gemma4_e2b_q4km",
    model_id: str = "google/gemma-4-e2b",
    dataset_id: str = "blocks_json_medium_chunked",
    modes: tuple[str, ...] = ("json_schema_single",),
    parallel: int = 1,
    context_length: int = 8192,
    repeats: int = 1,
    warmup_runs: int = 0,
    store_prompt_text: bool = False,
    store_response_text: bool = False,
    store_prompt_hash: bool = True,
    structured_prompt_variant: str | None = None,
    structured_schema_variant: str | None = None,
    business_failure_retry_limit: int | None = None,
    extra_load: dict[str, object] | None = None,
    prerequisites: dict[str, object] | None = None,
) -> Path:
    config_path = tmp_path / "managed-live.yaml"
    load_payload: dict[str, object] = {
        "context_length": [context_length],
        "parallel": [parallel],
    }
    if extra_load:
        load_payload.update(extra_load)
    payload: dict[str, object] = {
        "experiment_id": experiment_id,
        "hardware_profile": "local_manual",
        "lmstudio_base_url": "http://127.0.0.1:1234",
        "allow_remote": False,
        "models": [
            {
                "key": model_key,
                "model_id": model_id,
                "load": load_payload,
            }
        ],
        "modes": list(modes),
        "datasets": [dataset_id],
        "repeats": repeats,
        "warmup_runs": warmup_runs,
        "privacy": {
            "store_prompt_text": store_prompt_text,
            "store_response_text": store_response_text,
            "store_prompt_hash": store_prompt_hash,
        },
    }
    if prerequisites is not None:
        payload["prerequisites"] = prerequisites
    if structured_prompt_variant is not None:
        payload["structured_prompt_variant"] = structured_prompt_variant
    if structured_schema_variant is not None:
        payload["structured_schema_variant"] = structured_schema_variant
    if business_failure_retry_limit is not None:
        payload["business_failure_retry_limit"] = business_failure_retry_limit
    config_path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return config_path


def _build_12b_managed_live_prerequisites(evidence_dir: str) -> dict[str, object]:
    return {
        "load_only_evidence_dir": evidence_dir,
        "required_decision": "load_only_passed",
        "required_tiers": [8192, 16_384],
        "require_final_loaded_instances": 0,
    }


def _write_12b_load_only_evidence(
    tmp_path: Path,
    *,
    relative_dir: str = "l3-9c-load-only-evidence",
    context_tiers: Sequence[int] = (8192, 16_384),
    privacy_status: str = "pass",
    privacy_violation_count: int = 0,
    attempt_overrides: dict[int, dict[str, object]] | None = None,
) -> str:
    evidence_dir = tmp_path / relative_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    overrides = attempt_overrides or {}
    load_attempts_text = "".join(
        json.dumps(
            {
                "requested_context_length": context_tiers[index],
                "decision": "load_only_passed",
                "cleanup_verified": True,
                "final_loaded_instances": 0,
                "generation_called": False,
                "chat_called": False,
                "responses_called": False,
                "chat_completions_called": False,
                "inference_endpoint_called": False,
                **overrides.get(index, {}),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for index in range(len(context_tiers))
    )
    (evidence_dir / "load_attempts.jsonl").write_text(load_attempts_text, encoding="utf-8")
    (evidence_dir / "privacy_scan.json").write_text(
        json.dumps(
            {
                "status": privacy_status,
                "violation_count": privacy_violation_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return relative_dir


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cache_25k_no_live_prep_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_5_cache_25k_no_live_prep.yaml"
    )


def _load_cache_25k_no_live_prep_config_payload() -> dict[str, object]:
    return yaml.safe_load(_cache_25k_no_live_prep_config_path().read_text(encoding="utf-8"))


def _write_cache_25k_no_live_prep_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "l3_5_cache_25k_no_live_prep.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_6_25k_no_live_preflight_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6_25k_no_live_preflight_gemma4_e2b.yaml"
    )


def _load_l3_6_25k_no_live_preflight_config_payload() -> dict[str, object]:
    return yaml.safe_load(_l3_6_25k_no_live_preflight_config_path().read_text(encoding="utf-8"))


def _write_l3_6_25k_no_live_preflight_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "l3_6_25k_no_live_preflight_gemma4_e2b.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_6a_25k_tokenization_prompt_fit_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6a_25k_tokenization_prompt_fit_gemma4_e2b.yaml"
    )


def _load_l3_6a_25k_tokenization_prompt_fit_config_payload() -> dict[str, object]:
    return yaml.safe_load(
        _l3_6a_25k_tokenization_prompt_fit_config_path().read_text(encoding="utf-8")
    )


def _write_l3_6a_25k_tokenization_prompt_fit_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_6a_25k_tokenization_prompt_fit_gemma4_e2b.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_6b_25k_prompt_minimization_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6b_25k_prompt_minimization_gemma4_e2b.yaml"
    )


def _load_l3_6b_25k_prompt_minimization_config_payload() -> dict[str, object]:
    return yaml.safe_load(_l3_6b_25k_prompt_minimization_config_path().read_text(encoding="utf-8"))


def _write_l3_6b_25k_prompt_minimization_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_6b_25k_prompt_minimization_gemma4_e2b.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_6c_25k_compact_memory_live_smoke_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6c_25k_compact_memory_live_smoke_gemma4_e2b.yaml"
    )


def _load_l3_6c_25k_compact_memory_live_smoke_config_payload() -> dict[str, object]:
    return yaml.safe_load(
        _l3_6c_25k_compact_memory_live_smoke_config_path().read_text(encoding="utf-8")
    )


def _write_l3_6c_25k_compact_memory_live_smoke_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_6c_25k_compact_memory_live_smoke_gemma4_e2b.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_6d_25k_mode_comparison_live_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_6d_25k_mode_comparison_gemma4_e2b.yaml"
    )


def _load_l3_6d_25k_mode_comparison_live_config_payload() -> dict[str, object]:
    return yaml.safe_load(_l3_6d_25k_mode_comparison_live_config_path().read_text(encoding="utf-8"))


def _write_l3_6d_25k_mode_comparison_live_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_6d_25k_mode_comparison_gemma4_e2b.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_7d_structured_json_live_smoke_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_7d_structured_json_live_smoke_gemma4_e2b.yaml"
    )


def _load_l3_7d_structured_json_live_smoke_config_payload() -> dict[str, object]:
    return yaml.safe_load(
        _l3_7d_structured_json_live_smoke_config_path().read_text(encoding="utf-8")
    )


def _write_l3_7d_structured_json_live_smoke_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_7d_structured_json_live_smoke_gemma4_e2b.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _write_cache_32k_load_only_config(tmp_path: Path) -> Path:
    path = tmp_path / "l3_5b_32k_load_only_smoke.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "l3_5b_32k_load_only_smoke_gemma4_e2b",
                "mode": "load_only",
                "model": {
                    "key": "gemma4_e2b_q4km",
                    "lmstudio_model_id": "google/gemma-4-e2b",
                },
                "load": {
                    "context_length": 32768,
                    "echo_load_config": True,
                    "flash_attention": True,
                    "offload_kv_cache_to_gpu": True,
                    "parallel": 1,
                },
                "safety": {
                    "generation_allowed": False,
                    "live_25k_authorized": False,
                    "unload_required": True,
                    "final_loaded_instances_required": 0,
                },
                "privacy": {
                    "store_raw_prompt_response": False,
                    "store_local_urls": False,
                    "store_state_ids_raw": False,
                },
                "artifacts": [
                    "environment.json",
                    "run_config.json",
                    "load_request.json",
                    "load_response_sanitized.json",
                    "models_before.json",
                    "models_after_load.json",
                    "unload_response_sanitized.json",
                    "models_after_unload.json",
                    "system_summary.json",
                    "privacy_scan.json",
                    "report.md",
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _l3_8b_gemma4_e4b_load_only_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8b_gemma4_e4b_load_only_16k_32k.yaml"
    )


def _load_l3_8b_gemma4_e4b_load_only_config_payload() -> dict[str, object]:
    return yaml.safe_load(_l3_8b_gemma4_e4b_load_only_config_path().read_text(encoding="utf-8"))


def _write_l3_8b_gemma4_e4b_load_only_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_8b_gemma4_e4b_load_only_16k_32k.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_9c_gemma4_12b_qat_load_only_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_9c_gemma4_12b_qat_load_only_8k_16k.yaml"
    )


def _load_l3_9c_gemma4_12b_qat_load_only_config_payload() -> dict[str, object]:
    return yaml.safe_load(_l3_9c_gemma4_12b_qat_load_only_config_path().read_text(encoding="utf-8"))


def _write_l3_9c_gemma4_12b_qat_load_only_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_9c_gemma4_12b_qat_load_only_8k_16k.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_9d_gemma4_26b_a4b_qat_load_only_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_9d_gemma4_26b_a4b_qat_load_only_8k.yaml"
    )


def _load_l3_9d_gemma4_26b_a4b_qat_load_only_config_payload() -> dict[str, object]:
    return yaml.safe_load(
        _l3_9d_gemma4_26b_a4b_qat_load_only_config_path().read_text(encoding="utf-8")
    )


def _write_l3_9d_gemma4_26b_a4b_qat_load_only_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_9d_gemma4_26b_a4b_qat_load_only_8k.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_8c_gemma4_e4b_tiny_live_smoke_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8c_gemma4_e4b_tiny_live_smoke.yaml"
    )


def _load_l3_8c_gemma4_e4b_tiny_live_smoke_config_payload() -> dict[str, object]:
    return yaml.safe_load(
        _l3_8c_gemma4_e4b_tiny_live_smoke_config_path().read_text(encoding="utf-8")
    )


def _write_l3_8c_gemma4_e4b_tiny_live_smoke_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_8c_gemma4_e4b_tiny_live_smoke.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _l3_8d_gemma4_e4b_strict_json_smoke_config_path() -> Path:
    return (
        _project_root()
        / "experiments"
        / "lmstudio"
        / "configs"
        / "l3_8d_gemma4_e4b_strict_json_smoke.yaml"
    )


def _load_l3_8d_gemma4_e4b_strict_json_smoke_config_payload() -> dict[str, object]:
    return yaml.safe_load(
        _l3_8d_gemma4_e4b_strict_json_smoke_config_path().read_text(encoding="utf-8")
    )


def _write_l3_8d_gemma4_e4b_strict_json_smoke_config(
    tmp_path: Path,
    payload: dict[str, object],
) -> Path:
    path = tmp_path / "l3_8d_gemma4_e4b_strict_json_smoke.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _valid_blocks_json(expected_ids: tuple[int, ...]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "factual_blocks.v1",
                            "status": "success",
                            "blocks": [
                                {
                                    "block_id": block_id,
                                    "normalized_text": f"Normalized block {block_id}.",
                                    "status": "success",
                                    "warnings": [],
                                }
                                for block_id in expected_ids
                            ],
                            "warnings": [],
                        }
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 300, "completion_tokens": 120},
    }


def _id_diagnostics_failure_blocks_json(
    expected_ids: tuple[int, ...],
    *,
    text_sentinel: str | None = None,
) -> dict[str, object]:
    returned_ids = list(expected_ids)
    returned_ids[1] = expected_ids[2]
    returned_ids[-1] = 999
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "factual_blocks.v1",
                            "status": "success",
                            "blocks": [
                                {
                                    "block_id": block_id,
                                    "normalized_text": (
                                        text_sentinel
                                        if text_sentinel is not None
                                        else f"Normalized block {block_id}."
                                    ),
                                    "status": "success",
                                    "warnings": [],
                                }
                                for block_id in returned_ids
                            ],
                            "warnings": [],
                        }
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 300, "completion_tokens": 120},
    }


def _payload_chunk_ids(payload: dict[str, object]) -> tuple[int, ...]:
    messages = payload.get("messages")
    assert isinstance(messages, list)
    combined = "\n".join(
        message["content"]
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("content"), str)
    )
    return tuple(int(match) for match in re.findall(r"block_id=(\d+):", combined))


def _native_transport_for_managed_live(
    raw_instance_id: str,
    *,
    model_id: str = "google/gemma-4-e2b",
    context_length: int = 8192,
    parallel: int = 1,
):
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": model_id,
                "context_length": context_length,
                "parallel": parallel,
                "echo_load_config": True,
            }
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": raw_instance_id,
                    "load_config": {"context_length": context_length, "parallel": parallel},
                }
            ).encode("utf-8")
        if len(calls) == 2:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": model_id,
                            "loaded_instances": [{"instance_id": raw_instance_id}],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(calls) == 3:
            payload = json.loads(request.data.decode("utf-8"))
            assert payload == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 4:
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        raise AssertionError(f"unexpected native request #{len(calls)}")

    return calls, fake_transport


def _managed_live_transport() -> tuple[list[tuple[str, float]], object]:
    return _managed_live_transport_for_model()


def _managed_live_transport_for_model(
    *,
    model_id: str = "google/gemma-4-e2b",
    dataset_id: str = "blocks_json_medium_chunked",
) -> tuple[list[tuple[str, float]], object]:
    calls: list[tuple[str, float]] = []
    chunked_view = load_chunked_dataset_view(dataset_id)
    expected_chunks = list(chunked_view.chunks)

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        chunk = expected_chunks[len(calls)]
        calls.append((url, timeout_s))
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["temperature"] == 0
        return _valid_blocks_json(tuple(chunk.expected_ids))

    return calls, fake_transport


def _managed_true_parallel_transport(
    *,
    model_id: str = "google/gemma-4-e2b",
) -> tuple[list[tuple[str, float, tuple[int, ...]]], object]:
    calls: list[tuple[str, float, tuple[int, ...]]] = []

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        chunk_ids = _payload_chunk_ids(payload)
        calls.append((url, timeout_s, chunk_ids))
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["temperature"] == 0
        return _valid_blocks_json(chunk_ids)

    return calls, fake_transport


def _managed_stateful_live_smoke_transport(
    *,
    model_id: str = "google/gemma-4-e2b",
    fail_on_call: int | None = None,
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []
    raw_root_state_id = "raw-root-state-id-sentinel"
    raw_root_output = "raw-root-output-sentinel"
    raw_summary_state_id = "raw-summary-state-id-sentinel"
    raw_summary_output = "raw-summary-output-sentinel"
    raw_glossary_state_id = "raw-glossary-state-id-sentinel"
    raw_glossary_output = "raw-glossary-output-sentinel"

    responses = (
        {
            "response_id": raw_root_state_id,
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": raw_root_output}]}
            ],
        },
        {
            "response_id": raw_summary_state_id,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": raw_summary_output}],
                }
            ],
        },
        {
            "response_id": raw_glossary_state_id,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": raw_glossary_output}],
                }
            ],
        },
    )

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        assert url == "http://127.0.0.1:1234/api/v1/chat"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["store"] is True

        if len(calls) == 1:
            assert "previous_response_id" not in payload
            assert isinstance(payload["input"], str)
            if fail_on_call == 1:
                raise RuntimeError("simulated stateful branch failure")
            return responses[0]
        if len(calls) == 2:
            assert payload["previous_response_id"] == raw_root_state_id
            assert payload["input"] == (
                "Provide a short summary of the synthetic lecture in 3 bullet points with no extra preface."
            )
            if fail_on_call == 2:
                raise RuntimeError("simulated stateful branch failure")
            return responses[1]
        if len(calls) == 3:
            assert payload["previous_response_id"] == raw_root_state_id
            assert payload["input"] == (
                "List a short glossary with 5 terms from the synthetic lecture and brief definitions."
            )
            if fail_on_call == 3:
                raise RuntimeError("simulated stateful branch failure")
            return responses[2]
        raise AssertionError(f"unexpected stateful request #{len(calls)}")

    return calls, fake_transport


def _native_transport_for_load_only_smoke(
    raw_instance_id: str,
    *,
    model_id: str = "google/gemma-4-e2b",
    context_length: int = 32768,
    parallel: int = 1,
) -> tuple[list[tuple[str, str, bytes | None]], object]:
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": model_id,
                "context_length": context_length,
                "echo_load_config": True,
                "flash_attention": True,
                "offload_kv_cache_to_gpu": True,
                "parallel": parallel,
            }
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": raw_instance_id,
                    "load_config": {
                        "context_length": context_length,
                        "parallel": parallel,
                        "echo_load_config": True,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                }
            ).encode("utf-8")
        if len(calls) == 3:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps(
                {
                    "models": [
                        {
                            "key": model_id,
                            "loaded_instances": [
                                {
                                    "instance_id": raw_instance_id,
                                    "context_length": context_length,
                                    "parallel": parallel,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 5:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        raise AssertionError(f"unexpected native request #{len(calls)}")

    return calls, fake_transport


def _native_transport_for_l3_8b_gemma4_e4b_load_only(
    raw_instance_ids: tuple[str, str] = (
        "raw-instance-l3-8b-16k",
        "raw-instance-l3-8b-32k",
    ),
    *,
    model_id: str = "google/gemma-4-e4b",
    context_tiers: tuple[int, int] = (16_384, 32_768),
    parallel: int = 1,
    include_model_list_runtime_metadata: bool = True,
) -> tuple[list[tuple[str, str, bytes | None]], object]:
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        call_number = len(calls)
        if call_number in {1, 6}:
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        if call_number in {2, 7}:
            current_tier = 0 if call_number == 2 else 1
            context_length = context_tiers[current_tier]
            raw_instance_id = raw_instance_ids[current_tier]
            assert json.loads(request.data.decode("utf-8")) == {
                "model": model_id,
                "context_length": context_length,
                "echo_load_config": True,
                "flash_attention": True,
                "offload_kv_cache_to_gpu": True,
                "parallel": parallel,
            }
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": raw_instance_id,
                    "load_config": {
                        "context_length": context_length,
                        "parallel": parallel,
                        "echo_load_config": True,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                }
            ).encode("utf-8")
        if call_number in {3, 8}:
            current_tier = 0 if call_number == 3 else 1
            context_length = context_tiers[current_tier]
            raw_instance_id = raw_instance_ids[current_tier]
            loaded_instance: dict[str, object] = {"instance_id": raw_instance_id}
            if include_model_list_runtime_metadata:
                loaded_instance["context_length"] = context_length
                loaded_instance["parallel"] = parallel
            return json.dumps(
                {
                    "models": [
                        {
                            "key": model_id,
                            "loaded_instances": [loaded_instance],
                        }
                    ]
                }
            ).encode("utf-8")
        if call_number in {4, 9}:
            current_tier = 0 if call_number == 4 else 1
            assert json.loads(request.data.decode("utf-8")) == {
                "instance_id": raw_instance_ids[current_tier]
            }
            return b'{"status":"ok"}'
        if call_number in {5, 10}:
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        raise AssertionError(f"unexpected native request #{call_number}")

    return calls, fake_transport


def _native_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke(
    raw_instance_id: str,
    *,
    model_id: str = "google/gemma-4-e4b",
    context_length: int = 16_384,
    parallel: int = 1,
) -> tuple[list[tuple[str, str, bytes | None]], object]:
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": model_id,
                "context_length": context_length,
                "echo_load_config": True,
                "flash_attention": True,
                "offload_kv_cache_to_gpu": True,
                "parallel": parallel,
            }
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": raw_instance_id,
                    "load_config": {
                        "context_length": context_length,
                        "parallel": parallel,
                        "echo_load_config": True,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                }
            ).encode("utf-8")
        if len(calls) == 3:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps(
                {
                    "models": [
                        {
                            "key": model_id,
                            "loaded_instances": [
                                {
                                    "instance_id": raw_instance_id,
                                    "context_length": context_length,
                                    "parallel": parallel,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 5:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        raise AssertionError(f"unexpected native request #{len(calls)}")

    return calls, fake_transport


def _native_transport_for_l3_6c_compact_memory_live_smoke(
    raw_instance_id: str,
    *,
    model_id: str = "google/gemma-4-e2b",
    context_length: int = 32768,
    parallel: int = 1,
) -> tuple[list[tuple[str, str, bytes | None]], object]:
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": model_id,
                "context_length": context_length,
                "echo_load_config": True,
                "flash_attention": True,
                "offload_kv_cache_to_gpu": True,
                "parallel": parallel,
            }
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": raw_instance_id,
                    "load_config": {
                        "context_length": context_length,
                        "parallel": parallel,
                        "echo_load_config": True,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                }
            ).encode("utf-8")
        if len(calls) == 3:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps(
                {
                    "models": [
                        {
                            "key": model_id,
                            "loaded_instances": [
                                {
                                    "instance_id": raw_instance_id,
                                    "context_length": context_length,
                                    "parallel": parallel,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 5:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        raise AssertionError(f"unexpected native request #{len(calls)}")

    return calls, fake_transport


def _chat_transport_for_l3_6c_compact_memory_live_smoke(
    *,
    model_id: str = "google/gemma-4-e2b",
    max_output_tokens: int = 64,
    raw_response_id: str = "raw-l3-6c-response-id-sentinel",
    raw_output_text: str = "raw-l3-6c-output-sentinel",
    stats: dict[str, object] | None = None,
    on_input: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []
    response_stats = stats or {
        "time_to_first_token": 0.123,
        "tokens_per_second": 48.5,
        "prompt_processing_time": 4.321,
    }

    def fake_transport(url: str, payload: dict[str, object], timeout_s: float) -> dict[str, object]:
        calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        assert url == "http://127.0.0.1:1234/api/v1/chat"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["temperature"] == 0
        assert payload["max_output_tokens"] == max_output_tokens
        assert payload["store"] is False
        assert "previous_response_id" not in payload
        input_text = payload["input"]
        assert isinstance(input_text, str)
        assert len(input_text) == 68100
        assert managed_runner_module.estimate_input_tokens_from_chars(len(input_text)) == 22700
        if on_input is not None:
            on_input(input_text)
        return {
            "response_id": raw_response_id,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": raw_output_text}],
                }
            ],
            "usage": {"prompt_tokens": 22688, "completion_tokens": 12},
            "stats": dict(response_stats),
        }

    return calls, fake_transport


def _chat_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke(
    *,
    model_id: str = "google/gemma-4-e4b",
    max_output_tokens: int = 64,
    raw_response_id: str = "raw-l3-8c-response-id-sentinel",
    raw_output_text: str = "raw-l3-8c-output-sentinel",
    stats: dict[str, object] | None = None,
    on_input: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []
    response_stats = stats or {
        "time_to_first_token": 0.111,
        "tokens_per_second": 52.0,
        "prompt_processing_time": 1.234,
    }

    def fake_transport(url: str, payload: dict[str, object], timeout_s: float) -> dict[str, object]:
        calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        assert url == "http://127.0.0.1:1234/api/v1/chat"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["temperature"] == 0
        assert payload["max_output_tokens"] == max_output_tokens
        assert payload["store"] is False
        assert "previous_response_id" not in payload
        input_text = payload["input"]
        assert isinstance(input_text, str)
        assert input_text.startswith("L3.8c Gemma4 E4B tiny live smoke synthetic prompt.")
        if on_input is not None:
            on_input(input_text)
        return {
            "response_id": raw_response_id,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": raw_output_text}],
                }
            ],
            "usage": {"prompt_tokens": 28, "completion_tokens": 9},
            "stats": dict(response_stats),
        }

    return calls, fake_transport


def _chat_transport_for_l3_6d_mode_comparison_live(
    *,
    model_id: str = "google/gemma-4-e2b",
    max_output_tokens: int = 64,
    on_input: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []
    raw_root_state_id = "raw-l3-6d-root-state-id-sentinel"
    responses = (
        {
            "response_id": raw_root_state_id,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "raw-l3-6d-root-output-sentinel"}],
                }
            ],
            "usage": {"prompt_tokens": 25000, "completion_tokens": 8},
            "stats": {
                "time_to_first_token": 0.11,
                "tokens_per_second": 30.0,
                "prompt_processing_time": 5.0,
            },
        },
        {
            "response_id": "raw-l3-6d-compact-response-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-l3-6d-compact-output-sentinel"}
                    ],
                }
            ],
            "usage": {"prompt_tokens": 22688, "completion_tokens": 12},
            "stats": {
                "time_to_first_token": 0.123,
                "tokens_per_second": 48.5,
                "prompt_processing_time": 4.321,
            },
        },
        {
            "response_id": "raw-l3-6d-stateful-response-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-l3-6d-stateful-output-sentinel"}
                    ],
                }
            ],
            "usage": {"prompt_tokens": 28, "completion_tokens": 11},
            "stats": {
                "time_to_first_token": 0.091,
                "tokens_per_second": 61.0,
                "prompt_processing_time": 0.912,
            },
        },
        {
            "response_id": "raw-l3-6d-stateless-response-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-l3-6d-stateless-output-sentinel"}
                    ],
                }
            ],
            "usage": {"prompt_tokens": 25000, "completion_tokens": 10},
            "stats": {
                "time_to_first_token": 0.144,
                "tokens_per_second": 34.0,
                "prompt_processing_time": 5.432,
            },
        },
    )

    def fake_transport(url: str, payload: dict[str, object], timeout_s: float) -> dict[str, object]:
        calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        assert url == "http://127.0.0.1:1234/api/v1/chat"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["temperature"] == 0
        assert payload["max_output_tokens"] == max_output_tokens
        input_text = payload["input"]
        assert isinstance(input_text, str)
        if on_input is not None:
            on_input(input_text)

        call_index = len(calls)
        if call_index == 1:
            assert payload["store"] is True
            assert "previous_response_id" not in payload
            assert len(input_text) == 75000
            assert managed_runner_module.estimate_input_tokens_from_chars(len(input_text)) == 25000
        elif call_index == 2:
            assert payload["store"] is False
            assert "previous_response_id" not in payload
            assert len(input_text) == 68100
            assert managed_runner_module.estimate_input_tokens_from_chars(len(input_text)) == 22700
        elif call_index == 3:
            assert payload["store"] is True
            assert payload["previous_response_id"] == raw_root_state_id
            assert input_text == (
                "Provide a short summary of the synthetic lecture in 3 bullet points with no extra preface."
            )
        elif call_index == 4:
            assert payload["store"] is False
            assert "previous_response_id" not in payload
            assert len(input_text) == 75000
            assert managed_runner_module.estimate_input_tokens_from_chars(len(input_text)) == 25000
        else:
            raise AssertionError(f"unexpected L3.6d comparison request #{call_index}")
        return responses[call_index - 1]

    return calls, fake_transport


def _native_transport_for_l3_7d_structured_json_live_smoke(
    raw_instance_id: str,
    *,
    model_id: str = "google/gemma-4-e2b",
    context_length: int = 8192,
    parallel: int = 1,
) -> tuple[list[tuple[str, str, bytes | None]], object]:
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": model_id,
                "context_length": context_length,
                "echo_load_config": True,
                "parallel": parallel,
            }
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": raw_instance_id,
                    "load_config": {
                        "context_length": context_length,
                        "parallel": parallel,
                        "echo_load_config": True,
                    },
                }
            ).encode("utf-8")
        if len(calls) == 3:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps(
                {
                    "models": [
                        {
                            "key": model_id,
                            "loaded_instances": [
                                {
                                    "instance_id": raw_instance_id,
                                    "context_length": context_length,
                                    "parallel": parallel,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 5:
            assert request.get_method() == "GET"
            assert request.data is None
            return json.dumps({"models": [{"key": model_id, "loaded_instances": []}]}).encode(
                "utf-8"
            )
        raise AssertionError(f"unexpected native request #{len(calls)}")

    return calls, fake_transport


def _chat_transport_for_l3_7d_structured_json_live_smoke(
    *,
    model_id: str = "google/gemma-4-e2b",
    max_tokens: int = 512,
    raw_response_id: str = "raw-l3-7d-response-id-sentinel",
    public_content: str | None = None,
    reasoning_content: str | None = None,
    finish_reason: str = "stop",
    on_prompt: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []
    resolved_public_content = public_content
    if resolved_public_content is None:
        resolved_public_content = _valid_blocks_json((101, 102))["choices"][0]["message"]["content"]

    def fake_transport(url: str, payload: dict[str, object], timeout_s: float) -> dict[str, object]:
        calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["temperature"] == 0
        assert payload["max_tokens"] == max_tokens
        assert isinstance(payload["messages"], list)
        assert payload["response_format"]["json_schema"]["strict"] is True
        prompt_text = "\n".join(
            message["content"]
            for message in payload["messages"]
            if isinstance(message, dict) and isinstance(message.get("content"), str)
        )
        assert prompt_text
        if on_prompt is not None:
            on_prompt(prompt_text)

        message_payload: dict[str, object] = {"content": resolved_public_content}
        if reasoning_content is not None:
            message_payload["reasoning_content"] = reasoning_content
        return {
            "id": raw_response_id,
            "choices": [{"message": message_payload, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 88, "completion_tokens": 24},
            "stats": {
                "time_to_first_token": 0.111,
                "generation_time": 0.49,
                "tokens_per_second": 48.0,
            },
        }

    return calls, fake_transport


def _managed_cache_comparison_live_transport(
    clock: _ManualClock,
    *,
    model_id: str = "google/gemma-4-e2b",
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []
    root_input = managed_runner_module._build_cache_stateful_live_smoke_root_input()
    branch_inputs = managed_runner_module._build_cache_stateful_live_smoke_branch_inputs()
    full_prefix_inputs = managed_runner_module._build_cache_stateful_full_prefix_branch_inputs(
        root_input=root_input,
        branch_inputs=branch_inputs,
    )
    compact_memory_contexts = managed_runner_module._build_cache_stateful_compact_memory_contexts()
    compact_memory_inputs = (
        managed_runner_module._build_cache_stateful_compact_memory_branch_inputs(
            compact_memory_contexts=compact_memory_contexts,
            branch_inputs=branch_inputs,
        )
    )
    raw_root_state_id = "raw-root-state-id-sentinel"
    responses = (
        {
            "response_id": raw_root_state_id,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "raw-root-output-sentinel"}],
                }
            ],
        },
        {
            "response_id": "raw-stateful-summary-state-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-stateful-summary-output-sentinel"}
                    ],
                }
            ],
        },
        {
            "response_id": "raw-stateful-glossary-state-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-stateful-glossary-output-sentinel"}
                    ],
                }
            ],
        },
        {
            "response_id": "raw-stateless-summary-state-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-stateless-summary-output-sentinel"}
                    ],
                }
            ],
        },
        {
            "response_id": "raw-stateless-glossary-state-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-stateless-glossary-output-sentinel"}
                    ],
                }
            ],
        },
        {
            "response_id": "raw-compact-summary-state-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-compact-summary-output-sentinel"}
                    ],
                }
            ],
        },
        {
            "response_id": "raw-compact-glossary-state-id-sentinel",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "raw-compact-glossary-output-sentinel"}
                    ],
                }
            ],
        },
    )
    expected_latencies_ms = (100.0, 40.0, 60.0, 120.0, 130.0, 55.0, 65.0)

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        assert url == "http://127.0.0.1:1234/api/v1/chat"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["store"] is True

        call_index = len(calls)
        if call_index == 1:
            assert payload["input"] == root_input
            assert "previous_response_id" not in payload
        elif call_index == 2:
            assert payload["input"] == branch_inputs["summary_short"]
            assert payload["previous_response_id"] == raw_root_state_id
        elif call_index == 3:
            assert payload["input"] == branch_inputs["glossary_short"]
            assert payload["previous_response_id"] == raw_root_state_id
        elif call_index == 4:
            assert payload["input"] == full_prefix_inputs["summary_short"]
            assert "previous_response_id" not in payload
        elif call_index == 5:
            assert payload["input"] == full_prefix_inputs["glossary_short"]
            assert "previous_response_id" not in payload
        elif call_index == 6:
            assert payload["input"] == compact_memory_inputs["summary_short"]
            assert "previous_response_id" not in payload
        elif call_index == 7:
            assert payload["input"] == compact_memory_inputs["glossary_short"]
            assert "previous_response_id" not in payload
        else:
            raise AssertionError(f"unexpected comparison request #{call_index}")

        clock.advance_ms(expected_latencies_ms[call_index - 1])
        return responses[call_index - 1]

    return calls, fake_transport


def _managed_cache_instrumentation_live_transport(
    clock: _ManualClock,
    *,
    model_id: str = "google/gemma-4-e2b",
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []
    root_input = managed_runner_module._build_cache_stateful_live_smoke_root_input()
    branch_inputs = managed_runner_module._build_cache_stateful_live_smoke_branch_inputs()
    full_prefix_inputs = managed_runner_module._build_cache_stateful_full_prefix_branch_inputs(
        root_input=root_input,
        branch_inputs=branch_inputs,
    )
    compact_memory_contexts = managed_runner_module._build_cache_stateful_compact_memory_contexts()
    compact_memory_inputs = (
        managed_runner_module._build_cache_stateful_compact_memory_branch_inputs(
            compact_memory_contexts=compact_memory_contexts,
            branch_inputs=branch_inputs,
        )
    )
    raw_root_state_id = "raw-root-state-id-sentinel"
    timelines = (
        {
            "response_id": raw_root_state_id,
            "output_text": "raw-root-output-sentinel",
            "events": (
                (5.0, "prompt_processing.start", {"phase": "prompt"}),
                (30.0, "prompt_processing.end", {"phase": "prompt"}),
                (10.0, "message.delta", {"delta": {"text": "raw-root-delta-sentinel"}}),
                (
                    55.0,
                    "chat.end",
                    {
                        "response_id": raw_root_state_id,
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "raw-root-output-sentinel",
                                    }
                                ],
                            }
                        ],
                        "stats": {"time_to_first_token_seconds": 0.05},
                    },
                ),
            ),
        },
        {
            "response_id": "raw-stateful-summary-state-id-sentinel",
            "output_text": "raw-stateful-summary-output-sentinel",
            "events": (
                (5.0, "prompt_processing.start", {"phase": "prompt"}),
                (15.0, "prompt_processing.end", {"phase": "prompt"}),
                (5.0, "message.delta", {"delta": {"text": "raw-stateful-summary-delta"}}),
                (
                    15.0,
                    "chat.end",
                    {
                        "response_id": "raw-stateful-summary-state-id-sentinel",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "raw-stateful-summary-output-sentinel",
                                    }
                                ],
                            }
                        ],
                        "stats": {"time_to_first_token_seconds": 0.03},
                    },
                ),
            ),
        },
        {
            "response_id": "raw-stateful-glossary-state-id-sentinel",
            "output_text": "raw-stateful-glossary-output-sentinel",
            "events": (
                (5.0, "prompt_processing.start", {"phase": "prompt"}),
                (15.0, "prompt_processing.end", {"phase": "prompt"}),
                (10.0, "message.delta", {"delta": {"text": "raw-stateful-glossary-delta"}}),
                (
                    30.0,
                    "chat.end",
                    {
                        "response_id": "raw-stateful-glossary-state-id-sentinel",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "raw-stateful-glossary-output-sentinel",
                                    }
                                ],
                            }
                        ],
                        "stats": {"time_to_first_token_seconds": 0.035},
                    },
                ),
            ),
        },
        {
            "response_id": "raw-stateless-summary-state-id-sentinel",
            "output_text": "raw-stateless-summary-output-sentinel",
            "events": (
                (10.0, "prompt_processing.start", {"phase": "prompt"}),
                (60.0, "prompt_processing.end", {"phase": "prompt"}),
                (10.0, "message.delta", {"delta": {"text": "raw-stateless-summary-delta"}}),
                (
                    40.0,
                    "chat.end",
                    {
                        "response_id": "raw-stateless-summary-state-id-sentinel",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "raw-stateless-summary-output-sentinel",
                                    }
                                ],
                            }
                        ],
                        "stats": {"time_to_first_token_seconds": 0.085},
                    },
                ),
            ),
        },
        {
            "response_id": "raw-stateless-glossary-state-id-sentinel",
            "output_text": "raw-stateless-glossary-output-sentinel",
            "events": (
                (10.0, "prompt_processing.start", {"phase": "prompt"}),
                (60.0, "prompt_processing.end", {"phase": "prompt"}),
                (20.0, "message.delta", {"delta": {"text": "raw-stateless-glossary-delta"}}),
                (
                    40.0,
                    "chat.end",
                    {
                        "response_id": "raw-stateless-glossary-state-id-sentinel",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "raw-stateless-glossary-output-sentinel",
                                    }
                                ],
                            }
                        ],
                        "stats": {"time_to_first_token_seconds": 0.095},
                    },
                ),
            ),
        },
        {
            "response_id": "raw-compact-summary-state-id-sentinel",
            "output_text": "raw-compact-summary-output-sentinel",
            "events": (
                (8.0, "prompt_processing.start", {"phase": "prompt"}),
                (30.0, "prompt_processing.end", {"phase": "prompt"}),
                (4.0, "message.delta", {"delta": {"text": "raw-compact-summary-delta"}}),
                (
                    13.0,
                    "chat.end",
                    {
                        "response_id": "raw-compact-summary-state-id-sentinel",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "raw-compact-summary-output-sentinel",
                                    }
                                ],
                            }
                        ],
                        "stats": {"time_to_first_token_seconds": 0.047},
                    },
                ),
            ),
        },
        {
            "response_id": "raw-compact-glossary-state-id-sentinel",
            "output_text": "raw-compact-glossary-output-sentinel",
            "events": (
                (7.0, "prompt_processing.start", {"phase": "prompt"}),
                (30.0, "prompt_processing.end", {"phase": "prompt"}),
                (8.0, "message.delta", {"delta": {"text": "raw-compact-glossary-delta"}}),
                (
                    20.0,
                    "chat.end",
                    {
                        "response_id": "raw-compact-glossary-state-id-sentinel",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "raw-compact-glossary-output-sentinel",
                                    }
                                ],
                            }
                        ],
                        "stats": {"time_to_first_token_seconds": 0.05},
                    },
                ),
            ),
        },
    )

    def fake_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        assert url == "http://127.0.0.1:1234/api/v1/chat"
        assert timeout_s == 120.0
        assert payload["model"] == model_id
        assert payload["store"] is True
        assert payload["stream"] is True

        call_index = len(calls)
        if call_index == 1:
            assert payload["input"] == root_input
            assert "previous_response_id" not in payload
        elif call_index == 2:
            assert payload["input"] == branch_inputs["summary_short"]
            assert payload["previous_response_id"] == raw_root_state_id
        elif call_index == 3:
            assert payload["input"] == branch_inputs["glossary_short"]
            assert payload["previous_response_id"] == raw_root_state_id
        elif call_index == 4:
            assert payload["input"] == full_prefix_inputs["summary_short"]
            assert "previous_response_id" not in payload
        elif call_index == 5:
            assert payload["input"] == full_prefix_inputs["glossary_short"]
            assert "previous_response_id" not in payload
        elif call_index == 6:
            assert payload["input"] == compact_memory_inputs["summary_short"]
            assert "previous_response_id" not in payload
        elif call_index == 7:
            assert payload["input"] == compact_memory_inputs["glossary_short"]
            assert "previous_response_id" not in payload
        else:
            raise AssertionError(f"unexpected instrumentation request #{call_index}")

        probe_state = managed_runner_module._new_streaming_probe_state(clock.now())
        timeline = timelines[call_index - 1]["events"]
        for delay_ms, event_type, event_payload in timeline:
            clock.advance_ms(delay_ms)
            managed_runner_module._apply_streaming_probe_event(
                probe_state,
                event_type=event_type,
                data_payload=event_payload,
                now=clock.now(),
            )
        return managed_runner_module._finalize_streaming_probe_state(probe_state)

    return calls, fake_transport


def test_list_models_counts_compat_native_and_loaded_instances() -> None:
    transport = _QueueTransport(
        {
            EndpointKind.COMPAT_MODELS: [
                _ok_response(
                    EndpointKind.COMPAT_MODELS,
                    HttpMethod.GET,
                    "compat_models",
                    {
                        "data": [
                            {"id": "qwen-text", "owned_by": "lm-studio"},
                            {"id": "other-model", "owned_by": "external"},
                        ]
                    },
                    body_seed="compat-models",
                )
            ],
            EndpointKind.NATIVE_MODELS: [
                _ok_response(
                    EndpointKind.NATIVE_MODELS,
                    HttpMethod.GET,
                    "native_models",
                    {
                        "data": [
                            {
                                "modelKey": "qwen-native",
                                "loadedInstances": [
                                    {"id": "raw-instance-a"},
                                    {"id": "raw-instance-b"},
                                ],
                            },
                            {"modelKey": "idle-native", "loadedInstances": []},
                        ]
                    },
                    body_seed="native-models",
                )
            ],
        }
    )
    runner = ManagedLabRunner(transport, default_timeout_s=9.0)

    summary = runner.list_models(timeout_s=1.25)

    assert summary == {
        "compat_error": None,
        "native_error": None,
        "compat_count": 2,
        "native_count": 2,
        "loaded_instance_count": 2,
        "raw_prompt_response_stored": False,
    }
    assert [request.endpoint.kind for request in transport.requests] == [
        EndpointKind.COMPAT_MODELS,
        EndpointKind.NATIVE_MODELS,
    ]
    assert [request.timeout_s for request in transport.requests] == [1.25, 1.25]
    _assert_safe_summary(summary, "raw-instance-a", "raw-instance-b")


def test_ensure_downloaded_maps_already_downloaded_to_terminal_success() -> None:
    transport = _QueueTransport(
        {
            EndpointKind.NATIVE_DOWNLOAD: [
                _ok_response(
                    EndpointKind.NATIVE_DOWNLOAD,
                    HttpMethod.POST,
                    "native_download",
                    {"status": "already_downloaded", "job_id": "raw-job-1"},
                    body_seed="download-already",
                )
            ]
        }
    )
    runner = ManagedLabRunner(transport)

    summary = runner.ensure_downloaded(
        DownloadRequest(model_key="qwen-native", source_id="catalog")
    )

    assert summary == {
        "status": "already_downloaded",
        "ready_on_disk": True,
        "terminal_success": True,
        "error_kind": None,
    }
    _assert_safe_summary(summary, "raw-job-1")


def test_ensure_loaded_keeps_only_safe_presence_and_echo_fields() -> None:
    raw_instance_id = "raw-instance-load-1"
    transport = _QueueTransport(
        {
            EndpointKind.NATIVE_LOAD: [
                _ok_response(
                    EndpointKind.NATIVE_LOAD,
                    HttpMethod.POST,
                    "native_load",
                    {
                        "status": "success",
                        "instance": {"id": raw_instance_id, "modelKey": "qwen-native"},
                        "echoLoadConfig": {
                            "contextLength": 8192,
                            "numParallelSequences": 2,
                        },
                    },
                    body_seed="load-success",
                )
            ]
        }
    )
    runner = ManagedLabRunner(transport)

    summary = runner.ensure_loaded(
        LoadModelRequest(model_key="qwen-native", context_length=4096, parallel=4)
    )

    assert summary == {
        "status": "load_reconcile_ok",
        "instance_ref_present": True,
        "echo_context_length": 8192,
        "echo_parallel": 2,
        "error_kind": None,
    }
    _assert_safe_summary(summary, raw_instance_id)


def test_ensure_unloaded_handles_s5_unload_success_and_error_quirks() -> None:
    raw_identifier = "raw-instance-unload"
    request = UnloadModelRequest(
        instance_ref=_safe_hash(raw_identifier),
        model_key="qwen-native",
    )
    transport = _QueueTransport(
        {
            EndpointKind.NATIVE_UNLOAD: [
                _ok_response(
                    EndpointKind.NATIVE_UNLOAD,
                    HttpMethod.POST,
                    "native_unload",
                    {},
                    body_seed="unload-empty",
                ),
                _ok_response(
                    EndpointKind.NATIVE_UNLOAD,
                    HttpMethod.POST,
                    "native_unload",
                    {"instance_id": raw_identifier},
                    body_seed="unload-identifier-only",
                ),
                _ok_response(
                    EndpointKind.NATIVE_UNLOAD,
                    HttpMethod.POST,
                    "native_unload",
                    {"instance_id": raw_identifier, "error": "boom"},
                    body_seed="unload-identifier-error",
                ),
            ]
        }
    )
    runner = ManagedLabRunner(transport)

    empty_summary = runner.ensure_unloaded(request)
    identifier_summary = runner.ensure_unloaded(request)
    failed_summary = runner.ensure_unloaded(request)

    assert empty_summary == {
        "status": "unload_exact",
        "unloaded": True,
        "error_kind": None,
    }
    assert identifier_summary == {
        "status": "unload_exact",
        "unloaded": True,
        "error_kind": None,
    }
    assert failed_summary == {
        "status": "do_not_touch",
        "unloaded": False,
        "error_kind": "provider_error",
    }
    _assert_safe_summary(empty_summary, raw_identifier)
    _assert_safe_summary(identifier_summary, raw_identifier)
    _assert_safe_summary(failed_summary, raw_identifier)


def test_complete_structured_returns_safe_hash_chars_and_token_fields() -> None:
    raw_content = '{"answer": 42}'
    transport = _QueueTransport(
        {
            EndpointKind.COMPAT_CHAT: [
                _ok_response(
                    EndpointKind.COMPAT_CHAT,
                    HttpMethod.POST,
                    "compat_chat",
                    {
                        "content": raw_content,
                        "reasoning_content": "reasoning-secret",
                        "finish_reason": "stop",
                        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
                        "prompt": "raw-prompt-structured",
                        "messages": [{"role": "user", "content": "raw-message"}],
                    },
                    body_seed="structured-generation",
                )
            ]
        }
    )
    runner = ManagedLabRunner(transport)

    summary = runner.complete_structured(_structured_request())

    assert summary == {
        "content_empty": False,
        "response_chars": len(raw_content),
        "response_hash": _safe_hash(raw_content),
        "reasoning_content_present": True,
        "finish_reason": "stop",
        "input_tokens": 11,
        "output_tokens": 22,
        "error_kind": None,
    }
    _assert_safe_summary(
        summary,
        raw_content,
        "reasoning-secret",
        "raw-prompt-structured",
        "raw-message",
    )


def test_complete_plain_maps_nested_finish_reason_length_to_finish_length() -> None:
    transport = _QueueTransport(
        {
            EndpointKind.COMPAT_CHAT: [
                _ok_response(
                    EndpointKind.COMPAT_CHAT,
                    HttpMethod.POST,
                    "compat_chat",
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "reasoning_content": "hidden-chain",
                                },
                                "finish_reason": "length",
                            }
                        ],
                        "usage": {"input_tokens": 3, "output_tokens": 7},
                        "prompt": "raw-prompt-length",
                    },
                    body_seed="plain-nested-length",
                )
            ]
        }
    )
    runner = ManagedLabRunner(transport)

    summary = runner.complete_plain(_plain_request())

    assert summary == {
        "content_empty": True,
        "response_chars": 0,
        "response_hash": None,
        "reasoning_content_present": True,
        "finish_reason": "length",
        "input_tokens": 3,
        "output_tokens": 7,
        "error_kind": "finish_length",
    }
    _assert_safe_summary(summary, "hidden-chain", "raw-prompt-length")


def test_complete_plain_handles_successful_plain_response() -> None:
    raw_content = "plain answer"
    transport = _QueueTransport(
        {
            EndpointKind.COMPAT_CHAT: [
                _ok_response(
                    EndpointKind.COMPAT_CHAT,
                    HttpMethod.POST,
                    "compat_chat",
                    {
                        "choices": [
                            {
                                "message": {"content": raw_content},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"input_tokens": 5, "output_tokens": 8},
                        "messages": ["raw-message-plain"],
                    },
                    body_seed="plain-success",
                )
            ]
        }
    )
    runner = ManagedLabRunner(transport)

    summary = runner.complete_plain(_plain_request(), timeout_s=1.5)

    assert summary == {
        "content_empty": False,
        "response_chars": len(raw_content),
        "response_hash": _safe_hash(raw_content),
        "reasoning_content_present": False,
        "finish_reason": "stop",
        "input_tokens": 5,
        "output_tokens": 8,
        "error_kind": None,
    }
    assert transport.requests[0].timeout_s == 1.5
    _assert_safe_summary(summary, raw_content, "raw-message-plain")


def test_run_with_system_metrics_writes_artifacts_and_returns_safe_system_summary(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_with_system_metrics(
        lambda: {"status": "ok", "custom_flag": True, "prompt": "raw-prompt"},
        tmp_path,
    )

    assert fake_sampler.started_providers == {"lmstudio_local": "managed_runner"}
    assert fake_sampler.stopped_providers == {"lmstudio_local": "managed_runner"}
    assert summary == {
        "status": "ok",
        "custom_flag": True,
        "system_sample_count": 2,
        "ram_before_mb": 1024.0,
        "ram_peak_mb": 1536.0,
        "ram_after_mb": 1536.0,
        "process_rss_before_mb": 256.0,
        "process_rss_peak_mb": 384.0,
        "process_rss_after_mb": 384.0,
        "vram_before_mb": 2048.0,
        "vram_peak_mb": 3072.0,
        "vram_after_mb": 3072.0,
        "gpu_util_peak_percent": 75.0,
        "gpu_power_peak_watts": 120.0,
        "configured_sample_interval_s": None,
        "actual_sample_interval_s": None,
        "sampler_failure_count": 0,
        "telemetry_valid": True,
        "phase_order_valid": True,
        "phase_summaries": (),
    }
    assert (tmp_path / "system_samples.jsonl").exists()
    assert (tmp_path / "system_summary.json").exists()

    samples_text = (tmp_path / "system_samples.jsonl").read_text(encoding="utf-8")
    summary_text = (tmp_path / "system_summary.json").read_text(encoding="utf-8")
    _assert_safe_system_artifacts(samples_text, summary_text)
    assert "raw-prompt" not in samples_text
    assert "raw-prompt" not in summary_text
    assert '"process_name": "lmstudio"' in samples_text


def test_run_with_system_metrics_passes_explicit_providers_to_start_and_stop(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_with_system_metrics(
        lambda: {"status": "ok", "run_kind": "fake"},
        tmp_path,
        providers={"lmstudio_local": "managed_runner_custom"},
    )

    assert fake_sampler.started_providers == {"lmstudio_local": "managed_runner_custom"}
    assert fake_sampler.stopped_providers == {"lmstudio_local": "managed_runner_custom"}
    assert summary["status"] == "ok"
    assert summary["run_kind"] == "fake"
    written_summary = json.loads((tmp_path / "system_summary.json").read_text(encoding="utf-8"))
    assert written_summary["providers"] == {"lmstudio_local": "managed_runner_custom"}


def test_run_with_system_metrics_drops_unsafe_operation_keys_and_redacts_string_values(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)
    raw_url = "https://private.example.test/v1/jobs/abc?token=secret"
    raw_path = r"C:\Users\Private\LM Studio\secret.txt"

    summary = runner.run_with_system_metrics(
        lambda: {
            "status": "ok",
            "url": raw_url,
            "job_id": "raw-job-123",
            "instance_id": "raw-instance-123",
            "cmdline": ["python", raw_path],
            "cwd": raw_path,
            "env": {"HOME": raw_path},
            "username": "private-user",
            "payload": {"url": raw_url},
            "safe_note": f"url={raw_url} path={raw_path}",
            "details": {
                "url": raw_url,
                "path": raw_path,
                "keep": "ok",
            },
        },
        tmp_path,
    )

    assert summary["status"] == "ok"
    assert summary["safe_note"] == "url=[REDACTED] path=[REDACTED]"
    assert summary["details"] == {
        "url": "[REDACTED]",
        "path": "[REDACTED]",
        "keep": "ok",
    }
    _assert_safe_summary(
        summary,
        raw_url,
        raw_path,
        "raw-job-123",
        "raw-instance-123",
        "private-user",
    )


def test_run_with_system_metrics_sanitizes_explicit_provider_metadata_in_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)
    raw_url = "https://private.example.test/v1/providers/local"
    raw_path = r"C:\Users\Private\LM Studio\provider"

    summary = runner.run_with_system_metrics(
        lambda: {"status": "ok"},
        tmp_path,
        providers={
            "lmstudio_local": "managed_runner_custom",
            "support_ref": raw_url,
            "disk_label": raw_path,
            "url": raw_url,
            "instance_id": "raw-instance-provider",
        },
    )

    assert summary["status"] == "ok"
    expected_providers = {
        "lmstudio_local": "managed_runner_custom",
        "support_ref": "[REDACTED]",
        "disk_label": "[REDACTED]",
    }
    assert fake_sampler.started_providers == expected_providers
    assert fake_sampler.stopped_providers == expected_providers

    samples_text = (tmp_path / "system_samples.jsonl").read_text(encoding="utf-8")
    summary_text = (tmp_path / "system_summary.json").read_text(encoding="utf-8")
    written_summary = json.loads(summary_text)

    assert written_summary["providers"] == expected_providers
    _assert_safe_system_artifacts(samples_text, summary_text)
    assert raw_url not in samples_text
    assert raw_url not in summary_text
    assert raw_path not in samples_text
    assert raw_path not in summary_text
    assert "raw-instance-provider" not in samples_text
    assert "raw-instance-provider" not in summary_text
    assert '"support_ref": "[REDACTED]"' in summary_text
    assert '"disk_label": "[REDACTED]"' in summary_text


def test_run_with_system_metrics_reraises_operation_error_after_stopping_and_writing_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(RuntimeError, match="operation boom"):
        runner.run_with_system_metrics(
            lambda: (_ for _ in ()).throw(RuntimeError("operation boom")),
            tmp_path,
        )

    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert (tmp_path / "system_samples.jsonl").exists()
    assert (tmp_path / "system_summary.json").exists()
    _assert_safe_system_artifacts(
        (tmp_path / "system_samples.jsonl").read_text(encoding="utf-8"),
        (tmp_path / "system_summary.json").read_text(encoding="utf-8"),
    )


def test_run_with_system_metrics_prefers_operation_error_over_cleanup_failure(
    tmp_path: Path,
) -> None:
    class _StopFailingSystemSampler(_FakeSystemSampler):
        def stop(self, *, providers=None) -> SystemMetricsSummary:
            super().stop(providers=providers)
            raise RuntimeError("cleanup boom")

    fake_sampler = _StopFailingSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(RuntimeError, match="operation boom"):
        runner.run_with_system_metrics(
            lambda: (_ for _ in ()).throw(RuntimeError("operation boom")),
            tmp_path,
        )

    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1


def test_run_with_system_metrics_isolates_sampler_cleanup_failure_after_successful_operation(
    tmp_path: Path,
) -> None:
    class _StopFailingSystemSampler(_FakeSystemSampler):
        def stop(self, *, providers=None) -> SystemMetricsSummary:
            super().stop(providers=providers)
            raise RuntimeError("cleanup boom")

    fake_sampler = _StopFailingSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_with_system_metrics(
        lambda: {"status": "ok", "custom_flag": True},
        tmp_path,
    )

    assert fake_sampler.start_calls == 1
    assert summary["status"] == "ok"
    assert summary["custom_flag"] is True
    assert summary["telemetry_valid"] is False
    assert summary["sampler_failure_count"] == 1
    assert fake_sampler.stop_calls == 1


@pytest.mark.parametrize(
    ("config_kwargs", "call_kwargs", "message"),
    [
        (
            {"model_key": "qwen2_5_7b", "model_id": "qwen/qwen2.5-7b"},
            {},
            "supports only gemma4_e2b_q4km, gemma4_e4b_q4km, or gemma4_12b_qat",
        ),
        (
            {"dataset_id": "blocks_json_small"},
            {},
            "requires dataset_id in",
        ),
        (
            {
                "model_key": "gemma4_26b_a4b_qat",
                "model_id": "google/gemma-4-26b-a4b-qat",
            },
            {},
            "supports only gemma4_e2b_q4km, gemma4_e4b_q4km, or gemma4_12b_qat",
        ),
        ({"parallel": 2}, {}, "configured/requested parallel=1"),
        (
            {"extra_load": {"true_parallel": [2]}},
            {},
            "rejects unsupported load keys: true_parallel",
        ),
        (
            {"extra_load": {"n_parallel": [1]}},
            {},
            "rejects ambiguous load keys",
        ),
        ({}, {"app_concurrency": 2}, "app_concurrency must be exactly 1"),
    ],
)
def test_run_medium_chunked_sequential_live_rejects_out_of_scope_inputs(
    tmp_path: Path,
    config_kwargs: dict[str, object],
    call_kwargs: dict[str, object],
    message: str,
) -> None:
    config_path = _write_live_config(tmp_path, **config_kwargs)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_medium_chunked_sequential_live(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="managed-live-invalid",
            **call_kwargs,
        )


def test_run_medium_chunked_sequential_live_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(tmp_path)
    native_calls, native_transport = _native_transport_for_managed_live("raw-instance-managed-live")
    live_calls, live_transport = _managed_live_transport()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="managed-live-seq",
        providers={
            "lmstudio_local": "managed_live_runner_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        live_transport=live_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["managed_live"] is True
    assert summary["run_id"] == "managed-live-seq"
    assert summary["model_key"] == "gemma4_e2b_q4km"
    assert summary["model_id"] == "google/gemma-4-e2b"
    assert summary["requested_context_length"] == 8192
    assert summary["requested_parallel"] == 1
    assert summary["load_verified"] is True
    assert summary["applied_context_length"] == 8192
    assert summary["applied_parallel"] == 1
    assert summary["parallel_verified"] is True
    assert summary["app_concurrency"] == 1
    assert summary["queue_pressure_mode"] is False
    assert summary["parallel_semantics"] == "sequential"
    assert summary["measured_request_count"] == 4
    assert summary["json_parse_pass_count"] == 4
    assert summary["schema_pass_count"] == 4
    assert summary["business_pass_count"] == 4
    assert summary["business_failure_retry_limit"] == 0
    assert summary["retry_attempt_count"] == 0
    assert summary["retry_recovered_count"] == 0
    assert summary["retry_failed_count"] == 0
    assert summary["ids_exact_pass_count"] == 4
    assert summary["all_ids_covered"] is True
    assert summary["finish_length_count"] == 0
    assert summary["reasoning_leak_count"] == 0
    assert summary["structured_error_count"] == 0
    assert summary["cleanup_status"] == "cleanup_verified"
    assert summary["cleanup_verified_count"] == 1
    assert summary["final_loaded_instances"] == 0
    assert summary["raw_prompt_response_stored"] is False
    assert summary["system_sample_count"] == 2

    assert [(method, url) for method, url, _data in native_calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(live_calls) == 4
    assert all(url == "http://127.0.0.1:1234/v1/chat/completions" for url, _timeout in live_calls)

    expected_files = {
        "environment.json",
        "experiment.yaml",
        "run_config.json",
        "metrics.jsonl",
        "structured_errors.jsonl",
        "batch_summary.json",
        "structured_validation_summary.json",
        "structured_validation_summary.csv",
        "privacy_scan.json",
        "report.md",
        "system_samples.jsonl",
        "system_summary.json",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert len(metrics_rows) == 4
    assert {row["endpoint_kind"] for row in metrics_rows} == {"compat_chat"}
    assert {row["app_concurrency"] for row in metrics_rows} == {1}
    assert {row["configured_parallel"] for row in metrics_rows} == {1}
    assert {row["applied_parallel"] for row in metrics_rows} == {1}
    assert {row["parallel_semantics"] for row in metrics_rows} == {"sequential"}
    assert {row["validation"]["json_parse_pass"] for row in metrics_rows} == {True}
    assert {row["validation"]["ids_exact_pass"] for row in metrics_rows} == {True}
    assert {row["raw_prompt_response_stored"] for row in metrics_rows} == {False}

    structured_summary = json.loads(
        (run_dir / "structured_validation_summary.json").read_text(encoding="utf-8")
    )
    assert structured_summary["json_parse_pass_count"] == 4
    assert structured_summary["schema_pass_count"] == 4
    assert structured_summary["business_pass_count"] == 4
    assert structured_summary["retry_attempt_count"] == 0
    assert structured_summary["retry_recovered_count"] == 0
    assert structured_summary["retry_failed_count"] == 0
    assert structured_summary["ids_exact_pass_count"] == 4
    assert structured_summary["structured_error_count"] == 0

    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert environment_payload == {
        "schema_version": "1.0",
        "run_id": "managed-live-seq",
        "experiment_id": "m1_2_structured_medium_chunked_gemma4_e2b",
        "mode": "managed_runner_medium_chunked_sequential_live",
        "managed_live": True,
        "dry_run": False,
        "structured_prompt_variant": "baseline",
        "structured_schema_variant": "baseline",
        "business_failure_retry_limit": 0,
    }

    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    assert experiment_payload["experiment_id"] == "m1_2_structured_medium_chunked_gemma4_e2b"
    assert experiment_payload["lmstudio_base_url"] == "redacted_local_lmstudio_url"
    assert experiment_payload["models"][0]["load"] == {
        "context_length": [8192],
        "parallel": [1],
    }
    assert experiment_payload["structured_prompt_variant"] == "baseline"
    assert experiment_payload["structured_schema_variant"] == "baseline"

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["structured_prompt_variant"] == "baseline"
    assert run_config["structured_schema_variant"] == "baseline"
    assert run_config["business_failure_retry_limit"] == 0

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "managed_live_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "environment.json",
            "experiment.yaml",
            "run_config.json",
            "metrics.jsonl",
            "structured_errors.jsonl",
            "batch_summary.json",
            "structured_validation_summary.json",
            "structured_validation_summary.csv",
            "report.md",
            "system_summary.json",
            "system_samples.jsonl",
        ],
        "raw_prompt_response_stored": False,
    }

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "L3.9 Blocks JSON sequential managed-live proof through ManagedLabRunner" in report_text
    assert "structured_prompt_variant: `baseline`" in report_text
    assert "structured_schema_variant: `baseline`" in report_text
    assert "true live/GPU/LM Studio used" in report_text
    assert "not true_parallel proof" in report_text
    assert "not production default" in report_text
    assert "not host application runtime integration" in report_text
    assert "exact unload cleanup required/verified" in report_text


def test_run_medium_chunked_sequential_live_accepts_l3_9c_gemma4_12b_qat_candidate(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    evidence_dir = _write_12b_load_only_evidence(tmp_path)
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_9c_gemma_family_blocks_json_gemma4_12b_qat",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
        prerequisites=_build_12b_managed_live_prerequisites(evidence_dir),
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-12b",
        model_id="google/gemma-4-12b-qat",
    )
    live_calls, live_transport = _managed_live_transport_for_model(
        model_id="google/gemma-4-12b-qat"
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / "run-12b",
        run_id="managed-live-seq-12b",
        native_transport=native_transport,
        live_transport=live_transport,
    )

    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["model_key"] == "gemma4_12b_qat"
    assert summary["model_id"] == "google/gemma-4-12b-qat"
    assert summary["requested_context_length"] == 8192
    assert summary["requested_parallel"] == 1
    assert summary["parallel_semantics"] == "sequential"
    assert summary["cleanup_status"] == "cleanup_verified"
    assert len(live_calls) == 4

    run_dir = tmp_path / "run-12b"

    load_request = json.loads(native_calls[0][2].decode("utf-8"))
    assert load_request["model"] == "google/gemma-4-12b-qat"

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["experiment_id"] == "l3_9c_gemma_family_blocks_json_gemma4_12b_qat"
    assert run_config["model_key"] == "gemma4_12b_qat"
    assert run_config["model_id"] == "google/gemma-4-12b-qat"
    assert run_config["structured_prompt_variant"] == "baseline"
    assert run_config["structured_schema_variant"] == "baseline"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "L3.9 Blocks JSON sequential managed-live proof through ManagedLabRunner" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    assert "http://127.0.0.1:1234" not in all_artifact_text
    assert "raw-instance-managed-live" not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert '"instance_id": "*"' not in all_artifact_text


def test_run_medium_chunked_sequential_live_records_prompt_variant_labels(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_12b_load_only_evidence(tmp_path, relative_dir="l3-10c-load-only-evidence")
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_10c_gemma4_12b_qat_prompt_strict_id_contract",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
        prerequisites=_build_12b_managed_live_prerequisites(evidence_dir),
        structured_prompt_variant="strict_id_contract",
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-12b-l3-10c",
        model_id="google/gemma-4-12b-qat",
    )
    live_calls, live_transport = _managed_live_transport_for_model(
        model_id="google/gemma-4-12b-qat"
    )
    runner = ManagedLabRunner(lambda request: None)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-10c",
        run_id="managed-live-seq-12b-l3-10c",
        native_transport=native_transport,
        live_transport=live_transport,
    )

    assert len(native_calls) == 4
    assert len(live_calls) == 4
    assert summary["structured_prompt_variant"] == "strict_id_contract"

    run_dir = tmp_path / "run-l3-10c"
    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    batch_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    assert environment_payload["structured_prompt_variant"] == "strict_id_contract"
    assert environment_payload["structured_schema_variant"] == "baseline"
    assert experiment_payload["structured_prompt_variant"] == "strict_id_contract"
    assert experiment_payload["structured_schema_variant"] == "baseline"
    assert run_config["structured_prompt_variant"] == "strict_id_contract"
    assert run_config["structured_schema_variant"] == "baseline"
    assert batch_summary["structured_prompt_variant"] == "strict_id_contract"
    assert batch_summary["structured_schema_variant"] == "baseline"
    assert "structured_prompt_variant: `strict_id_contract`" in report_text
    assert "structured_schema_variant: `baseline`" in report_text


def test_run_medium_chunked_sequential_live_records_structured_schema_variant_labels_without_raw_schema_dump(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_12b_load_only_evidence(tmp_path, relative_dir="l3-10d-load-only-evidence")
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_10d_gemma4_12b_qat_schema_per_position_id_const",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
        prerequisites=_build_12b_managed_live_prerequisites(evidence_dir),
        structured_schema_variant="per_position_id_const",
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-12b-l3-10d",
        model_id="google/gemma-4-12b-qat",
    )
    live_calls, live_transport = _managed_live_transport_for_model(
        model_id="google/gemma-4-12b-qat"
    )
    runner = ManagedLabRunner(lambda request: None)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-10d",
        run_id="managed-live-seq-12b-l3-10d",
        native_transport=native_transport,
        live_transport=live_transport,
    )

    assert len(native_calls) == 4
    assert len(live_calls) == 4
    assert summary["structured_schema_variant"] == "per_position_id_const"

    run_dir = tmp_path / "run-l3-10d"
    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    batch_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    assert environment_payload["structured_schema_variant"] == "per_position_id_const"
    assert experiment_payload["structured_schema_variant"] == "per_position_id_const"
    assert run_config["structured_schema_variant"] == "per_position_id_const"
    assert batch_summary["structured_schema_variant"] == "per_position_id_const"
    assert {row["structured_schema_variant"] for row in metrics_rows} == {"per_position_id_const"}
    assert {row["response_format"]["schema_name"] for row in metrics_rows} == {
        "factual_blocks_v1_per_position_id_const"
    }
    assert "structured_schema_variant: `per_position_id_const`" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    assert '"prefixItems"' not in all_artifact_text
    assert '"normalized_text": {' not in all_artifact_text


def test_run_medium_chunked_sequential_live_l3_10f_business_retry_writes_safe_retry_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    evidence_dir = _write_12b_load_only_evidence(tmp_path, relative_dir="l3-10f-load-only-evidence")
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_10f_gemma4_12b_qat_business_retry",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
        prerequisites=_build_12b_managed_live_prerequisites(evidence_dir),
        business_failure_retry_limit=1,
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-12b-l3-10f",
        model_id="google/gemma-4-12b-qat",
    )
    request_payloads: list[dict[str, object]] = []
    attempts_by_chunk_ids: dict[tuple[int, ...], int] = {}
    response_sentinel = "SENTINEL_RETRY_RESPONSE_TEXT"

    def fake_live_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        request_payloads.append(json.loads(json.dumps(payload)))
        chunk_ids = _payload_chunk_ids(payload)
        attempts_by_chunk_ids[chunk_ids] = attempts_by_chunk_ids.get(chunk_ids, 0) + 1
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 120.0
        assert payload["model"] == "google/gemma-4-12b-qat"
        if chunk_ids[0] == 0 and attempts_by_chunk_ids[chunk_ids] == 1:
            return _id_diagnostics_failure_blocks_json(
                chunk_ids,
                text_sentinel=response_sentinel,
            )
        return _valid_blocks_json(chunk_ids)

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-10f",
        run_id="managed-live-seq-12b-l3-10f",
        native_transport=native_transport,
        live_transport=fake_live_transport,
    )

    run_dir = tmp_path / "run-l3-10f"
    assert len(native_calls) == 4
    assert len(request_payloads) == 5
    assert attempts_by_chunk_ids[tuple(range(25))] == 2
    assert summary["business_failure_retry_limit"] == 1
    assert summary["retry_attempt_count"] == 1
    assert summary["retry_recovered_count"] == 1
    assert summary["retry_failed_count"] == 0
    assert summary["structured_error_count"] == 0

    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    batch_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    structured_summary = json.loads(
        (run_dir / "structured_validation_summary.json").read_text(encoding="utf-8")
    )
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    assert environment_payload["business_failure_retry_limit"] == 1
    assert experiment_payload["business_failure_retry_limit"] == 1
    assert run_config["business_failure_retry_limit"] == 1
    assert batch_summary["business_failure_retry_limit"] == 1
    assert batch_summary["retry_attempt_count"] == 1
    assert batch_summary["retry_recovered_count"] == 1
    assert batch_summary["retry_failed_count"] == 0
    assert structured_summary["retry_attempt_count"] == 1
    assert structured_summary["retry_recovered_count"] == 1
    assert structured_summary["retry_failed_count"] == 0
    assert report_text.count("business_failure_retry_limit: `1`") == 1
    assert "retry_attempt_count: `1`" in report_text
    assert "retry_recovered_count: `1`" in report_text
    assert "retry_failed_count: `0`" in report_text

    retried_metric_row = next(
        row for row in metrics_rows if row["request_id"] == "batch_0001_chunk_0000"
    )
    assert retried_metric_row["validation"]["retry_count"] == 1
    assert retried_metric_row["validation"]["business_pass"] is True
    assert (run_dir / "structured_errors.jsonl").read_text(encoding="utf-8") == ""

    retry_messages = request_payloads[1]["messages"]
    assert isinstance(retry_messages, list)
    retry_messages_text = "\n".join(
        message["content"]
        for message in retry_messages
        if isinstance(message, dict) and isinstance(message.get("content"), str)
    )
    assert response_sentinel not in retry_messages_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    assert response_sentinel not in all_artifact_text
    assert '"messages"' not in all_artifact_text
    assert '"prompt"' not in all_artifact_text
    assert '"response_text"' not in all_artifact_text
    assert '"raw_response"' not in all_artifact_text


@pytest.mark.parametrize(
    ("config_name", "dataset_id", "chunk_size_blocks", "chunks_count"),
    [
        (
            "l3_10e_gemma4_12b_qat_chunk_size_25.yaml",
            "blocks_json_medium_chunked",
            25,
            4,
        ),
        (
            "l3_10e_gemma4_12b_qat_chunk_size_10.yaml",
            "blocks_json_medium_chunked_10",
            10,
            10,
        ),
        (
            "l3_10e_gemma4_12b_qat_chunk_size_5.yaml",
            "blocks_json_medium_chunked_5",
            5,
            20,
        ),
    ],
)
def test_run_medium_chunked_sequential_live_accepts_l3_10e_configs_and_writes_dataset_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_name: str,
    dataset_id: str,
    chunk_size_blocks: int,
    chunks_count: int,
) -> None:
    config_path = (
        Path(__file__).resolve().parents[2] / "experiments" / "lmstudio" / "configs" / config_name
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        f"raw-instance-{dataset_id}",
        model_id="google/gemma-4-12b-qat",
    )
    live_calls, live_transport = _managed_live_transport_for_model(
        model_id="google/gemma-4-12b-qat",
        dataset_id=dataset_id,
    )
    monkeypatch.setattr(
        managed_runner_module,
        "_validate_gemma4_12b_qat_managed_live_prerequisite",
        lambda **_kwargs: None,
    )
    runner = ManagedLabRunner(lambda request: None)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / f"run-{dataset_id}",
        run_id=f"managed-live-{dataset_id}",
        native_transport=native_transport,
        live_transport=live_transport,
    )

    run_dir = tmp_path / f"run-{dataset_id}"
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    batch_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")

    assert len(native_calls) == 4
    assert len(live_calls) == chunks_count
    assert summary["dataset_id"] == dataset_id
    assert summary["chunk_size_blocks"] == chunk_size_blocks
    assert summary["chunks_count"] == chunks_count
    assert summary["structured_prompt_variant"] == "baseline"
    assert summary["structured_schema_variant"] == "baseline"
    assert run_config["dataset_id"] == dataset_id
    assert run_config["chunk_size_blocks"] == chunk_size_blocks
    assert run_config["chunks_count"] == chunks_count
    assert batch_summary["dataset_id"] == dataset_id
    assert batch_summary["chunk_size_blocks"] == chunk_size_blocks
    assert batch_summary["chunks_count"] == chunks_count
    assert experiment_payload["datasets"] == [dataset_id]
    assert len(metrics_rows) == chunks_count
    assert {row["dataset_id"] for row in metrics_rows} == {dataset_id}


def test_run_medium_chunked_sequential_live_l3_10a_id_diagnostics_write_sanitized_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    evidence_dir = _write_12b_load_only_evidence(tmp_path, relative_dir="l3-10a-load-only-evidence")
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_10a_gemma4_12b_qat_id_forensics",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
        prerequisites=_build_12b_managed_live_prerequisites(evidence_dir),
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-12b-l3-10a",
        model_id="google/gemma-4-12b-qat",
    )
    live_calls: list[tuple[str, float]] = []
    chunked_view = load_chunked_dataset_view("blocks_json_medium_chunked")
    expected_chunks = list(chunked_view.chunks)

    def fake_live_transport(
        url: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict[str, object]:
        chunk = expected_chunks[len(live_calls)]
        live_calls.append((url, timeout_s))
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_s == 120.0
        assert payload["model"] == "google/gemma-4-12b-qat"
        if len(live_calls) == 1:
            return _id_diagnostics_failure_blocks_json(tuple(chunk.expected_ids))
        return _valid_blocks_json(tuple(chunk.expected_ids))

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-10a",
        run_id="l3-10a-id-forensics",
        providers={"lmstudio_local": "managed_live_l3_10a_id_forensics_test"},
        native_transport=native_transport,
        live_transport=fake_live_transport,
    )

    run_dir = tmp_path / "run-l3-10a"
    assert len(native_calls) == 4
    assert len(live_calls) == 4
    assert summary["experiment_id"] == "l3_10a_gemma4_12b_qat_id_forensics"
    assert summary["business_pass_count"] == 3
    assert summary["structured_error_count"] == 1

    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert metric_rows[0]["validation"]["expected_count"] == 25
    assert metric_rows[0]["validation"]["returned_count"] == 25
    assert metric_rows[0]["validation"]["duplicate_ids"] == [2]
    assert metric_rows[0]["validation"]["missing_ids"] == [1, 24]
    assert metric_rows[0]["validation"]["extra_ids"] == [999]
    assert metric_rows[0]["validation"]["reordered_positions"][0] == {
        "position": 1,
        "expected_id": 1,
        "returned_id": 2,
    }

    structured_errors = _read_jsonl(run_dir / "structured_errors.jsonl")
    assert len(structured_errors) == 1
    assert structured_errors[0]["request_id"] == "batch_0001_chunk_0000"
    assert structured_errors[0]["expected_ids"] == list(range(25))
    assert structured_errors[0]["returned_ids"][0:4] == [0, 2, 2, 3]
    assert structured_errors[0]["duplicate_ids"] == [2]
    assert structured_errors[0]["missing_ids"] == [1, 24]
    assert structured_errors[0]["extra_ids"] == [999]
    assert structured_errors[0]["reordered_positions"][-1] == {
        "position": 24,
        "expected_id": 24,
        "returned_id": 999,
    }
    assert structured_errors[0]["reordered_count"] == 2
    assert structured_errors[0]["reordered_positions_truncated"] is False

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    assert "Normalized block 999." not in all_artifact_text


def test_run_medium_chunked_sequential_live_accepts_gemma4_e4b_without_prerequisites(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="m1_2_structured_medium_chunked_gemma4_e4b",
        model_key="gemma4_e4b_q4km",
        model_id="google/gemma-4-e4b",
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-e4b",
        model_id="google/gemma-4-e4b",
    )
    live_calls, live_transport = _managed_live_transport_for_model(model_id="google/gemma-4-e4b")
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_sequential_live(
        config_path=config_path,
        run_dir=tmp_path / "run-e4b",
        run_id="managed-live-seq-e4b",
        native_transport=native_transport,
        live_transport=live_transport,
    )

    assert summary["model_key"] == "gemma4_e4b_q4km"
    assert summary["model_id"] == "google/gemma-4-e4b"
    assert summary["cleanup_status"] == "cleanup_verified"
    assert len(native_calls) == 4
    assert len(live_calls) == 4


def test_run_medium_chunked_sequential_live_rejects_unsupported_prompt_variant(
    tmp_path: Path,
) -> None:
    config_path = _write_live_config(
        tmp_path,
        structured_prompt_variant="anti_reasoning",
    )
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(
        ValueError,
        match="supports only structured_prompt_variant values",
    ):
        runner.run_medium_chunked_sequential_live(
            config_path=config_path,
            run_dir=tmp_path / "run-invalid-prompt-variant",
            run_id="managed-live-invalid-prompt-variant",
        )


def test_run_medium_chunked_sequential_live_rejects_12b_without_load_only_prerequisites(
    tmp_path: Path,
) -> None:
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_9c_gemma_family_blocks_json_gemma4_12b_qat",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
    )
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match="missing/failed 12B load-only prerequisite"):
        runner.run_medium_chunked_sequential_live(
            config_path=config_path,
            run_dir=tmp_path / "run-12b-missing-prereq",
            run_id="managed-live-seq-12b-missing-prereq",
        )


@pytest.mark.parametrize(
    ("context_tiers", "privacy_status", "privacy_violation_count", "message"),
    [
        ((8192,), "pass", 0, "required tier 16384 missing"),
        ((8192, 16_384), "fail", 1, "privacy scan failed"),
    ],
)
def test_run_medium_chunked_sequential_live_rejects_failed_12b_prerequisite_evidence(
    tmp_path: Path,
    context_tiers: Sequence[int],
    privacy_status: str,
    privacy_violation_count: int,
    message: str,
) -> None:
    evidence_dir = _write_12b_load_only_evidence(
        tmp_path,
        context_tiers=context_tiers,
        privacy_status=privacy_status,
        privacy_violation_count=privacy_violation_count,
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_9c_gemma_family_blocks_json_gemma4_12b_qat",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
        prerequisites=_build_12b_managed_live_prerequisites(evidence_dir),
    )
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_medium_chunked_sequential_live(
            config_path=config_path,
            run_dir=tmp_path / "run-12b-bad-prereq",
            run_id="managed-live-seq-12b-bad-prereq",
        )


@pytest.mark.parametrize(
    ("attempt_overrides", "message"),
    [
        ({0: {"chat_called": True}}, "required tier 8192 failed acceptance"),
        ({1: {"inference_endpoint_called": True}}, "required tier 16384 failed acceptance"),
    ],
)
def test_run_medium_chunked_sequential_live_rejects_12b_prerequisite_evidence_with_inference_flags(
    tmp_path: Path,
    attempt_overrides: dict[int, dict[str, object]],
    message: str,
) -> None:
    evidence_dir = _write_12b_load_only_evidence(
        tmp_path,
        attempt_overrides=attempt_overrides,
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_9c_gemma_family_blocks_json_gemma4_12b_qat",
        model_key="gemma4_12b_qat",
        model_id="google/gemma-4-12b-qat",
        prerequisites=_build_12b_managed_live_prerequisites(evidence_dir),
    )
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_medium_chunked_sequential_live(
            config_path=config_path,
            run_dir=tmp_path / "run-12b-bad-flags",
            run_id="managed-live-seq-12b-bad-flags",
        )


@pytest.mark.parametrize(
    ("config_kwargs", "call_kwargs", "message"),
    [
        (
            {"model_key": "qwen2_5_7b", "model_id": "qwen/qwen2.5-7b"},
            {},
            "supports only gemma4_e2b_q4km or gemma4_e4b_q4km",
        ),
        (
            {
                "model_key": "gemma4_12b_qat",
                "model_id": "google/gemma-4-12b-qat",
            },
            {},
            "supports only gemma4_e2b_q4km or gemma4_e4b_q4km",
        ),
        (
            {"dataset_id": "blocks_json_small"},
            {},
            "requires dataset_id in",
        ),
        ({"parallel": 1}, {}, "configured/requested parallel=2"),
        (
            {"extra_load": {"true_parallel": [2]}},
            {},
            "rejects unsupported load keys: true_parallel",
        ),
        (
            {"extra_load": {"n_parallel": [2]}},
            {},
            "rejects ambiguous load keys",
        ),
        ({}, {"app_concurrency": 1}, "app_concurrency must be exactly 2"),
        ({}, {"app_concurrency": 3}, "app_concurrency must be exactly 2"),
    ],
)
def test_run_medium_chunked_true_parallel_live_rejects_out_of_scope_inputs(
    tmp_path: Path,
    config_kwargs: dict[str, object],
    call_kwargs: dict[str, object],
    message: str,
) -> None:
    effective_config_kwargs = {
        "experiment_id": "m1_3_structured_medium_chunked_gemma4_e2b_appconc2",
        "parallel": 2,
        **config_kwargs,
    }
    config_path = _write_live_config(tmp_path, **effective_config_kwargs)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_medium_chunked_true_parallel_live(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="managed-live-tp-invalid",
            app_concurrency=call_kwargs.get("app_concurrency", 2),
        )


def test_run_medium_chunked_true_parallel_live_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="m1_3_structured_medium_chunked_gemma4_e2b_appconc2",
        parallel=2,
        context_length=16384,
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-tp",
        context_length=16384,
        parallel=2,
    )
    live_calls, live_transport = _managed_true_parallel_transport()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_true_parallel_live(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="managed-live-true-parallel",
        providers={
            "lmstudio_local": "managed_live_true_parallel_runner_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        live_transport=live_transport,
        sequential_baseline_wall_time_ms=80.0,
        baseline_end_to_end_wall_time_ms=100.0,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["managed_live"] is True
    assert summary["run_id"] == "managed-live-true-parallel"
    assert summary["model_key"] == "gemma4_e2b_q4km"
    assert summary["model_id"] == "google/gemma-4-e2b"
    assert summary["requested_context_length"] == 16384
    assert summary["requested_parallel"] == 2
    assert summary["configured_parallel"] == 2
    assert summary["load_verified"] is True
    assert summary["applied_context_length"] == 16384
    assert summary["applied_parallel"] == 2
    assert summary["parallel_verified"] is True
    assert summary["app_concurrency"] == 2
    assert summary["queue_pressure_mode"] is False
    assert summary["parallel_semantics"] == "true_parallel"
    assert summary["measured_batches"] == 1
    assert summary["measured_request_count"] == 4
    assert summary["json_parse_pass_count"] == 4
    assert summary["schema_pass_count"] == 4
    assert summary["business_pass_count"] == 4
    assert summary["ids_exact_pass_count"] == 4
    assert summary["all_ids_covered"] is True
    assert summary["finish_length_count"] == 0
    assert summary["reasoning_leak_count"] == 0
    assert summary["structured_error_count"] == 0
    assert summary["cleanup_status"] == "cleanup_verified"
    assert summary["cleanup_verified_count"] == 1
    assert summary["final_loaded_instances"] == 0
    assert summary["sequential_baseline_wall_time_ms"] == 80.0
    assert summary["baseline_end_to_end_wall_time_ms"] == 100.0
    assert summary["raw_prompt_response_stored"] is False
    assert summary["system_sample_count"] == 2

    assert [(method, url) for method, url, _data in native_calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    load_request = json.loads(native_calls[0][2].decode("utf-8"))
    assert load_request["context_length"] == 16384
    assert load_request["parallel"] == 2
    assert len(live_calls) == 4
    assert all(
        url == "http://127.0.0.1:1234/v1/chat/completions" for url, _timeout, _ids in live_calls
    )
    assert {chunk_ids for _url, _timeout, chunk_ids in live_calls} == {
        tuple(chunk.expected_ids)
        for chunk in load_chunked_dataset_view("blocks_json_medium_chunked").chunks
    }

    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert len(metrics_rows) == 4
    assert {row["endpoint_kind"] for row in metrics_rows} == {"compat_chat"}
    assert {row["app_concurrency"] for row in metrics_rows} == {2}
    assert {row["configured_parallel"] for row in metrics_rows} == {2}
    assert {row["applied_parallel"] for row in metrics_rows} == {2}
    assert {row["queue_pressure_mode"] for row in metrics_rows} == {False}
    assert {row["parallel_semantics"] for row in metrics_rows} == {"true_parallel"}
    assert {row["validation"]["json_parse_pass"] for row in metrics_rows} == {True}
    assert {row["validation"]["ids_exact_pass"] for row in metrics_rows} == {True}
    assert {row["raw_prompt_response_stored"] for row in metrics_rows} == {False}

    structured_summary = json.loads(
        (run_dir / "structured_validation_summary.json").read_text(encoding="utf-8")
    )
    assert structured_summary["json_parse_pass_count"] == 4
    assert structured_summary["schema_pass_count"] == 4
    assert structured_summary["business_pass_count"] == 4
    assert structured_summary["retry_attempt_count"] == 0
    assert structured_summary["retry_recovered_count"] == 0
    assert structured_summary["retry_failed_count"] == 0
    assert structured_summary["ids_exact_pass_count"] == 4
    assert structured_summary["structured_error_count"] == 0

    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert environment_payload == {
        "schema_version": "1.0",
        "run_id": "managed-live-true-parallel",
        "experiment_id": "m1_3_structured_medium_chunked_gemma4_e2b_appconc2",
        "mode": "managed_runner_medium_chunked_true_parallel_live",
        "managed_live": True,
        "dry_run": False,
        "structured_prompt_variant": "baseline",
        "structured_schema_variant": "baseline",
        "business_failure_retry_limit": 0,
    }

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["mode"] == "managed_runner_medium_chunked_true_parallel_live"
    assert run_config["requested_context_length"] == 16384
    assert run_config["requested_parallel"] == 2
    assert run_config["app_concurrency"] == 2
    assert run_config["parallel_semantics"] == "true_parallel"
    assert run_config["sequential_baseline_wall_time_ms"] == 80.0
    assert run_config["baseline_end_to_end_wall_time_ms"] == 100.0
    assert run_config["structured_prompt_variant"] == "baseline"
    assert run_config["structured_schema_variant"] == "baseline"
    assert run_config["business_failure_retry_limit"] == 0

    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    assert (
        experiment_payload["experiment_id"] == "m1_3_structured_medium_chunked_gemma4_e2b_appconc2"
    )
    assert experiment_payload["lmstudio_base_url"] == "redacted_local_lmstudio_url"
    assert experiment_payload["models"][0]["load"] == {
        "context_length": [16384],
        "parallel": [2],
    }
    assert experiment_payload["structured_prompt_variant"] == "baseline"
    assert experiment_payload["structured_schema_variant"] == "baseline"

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0
    assert "environment.json" in privacy_scan["scanned_artifacts"]
    assert "experiment.yaml" in privacy_scan["scanned_artifacts"]

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "medium true_parallel=2 proof through ManagedLabRunner" in report_text
    assert "structured_prompt_variant: `baseline`" in report_text
    assert "structured_schema_variant: `baseline`" in report_text
    assert "true live/GPU/LM Studio used" in report_text
    assert "not sequential proof" in report_text
    assert "not production default" in report_text
    assert "not host application runtime integration" in report_text
    assert "exact unload cleanup required/verified" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    assert "http://127.0.0.1:1234" not in all_artifact_text
    assert "raw-instance-managed-live-tp" not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert '"instance_id": "*"' not in all_artifact_text


def test_run_medium_chunked_true_parallel_live_allows_repeat3_with_warmup_one(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="r1_structured_medium_chunked_gemma4_e2b_appconc2_repeat3",
        parallel=2,
        repeats=3,
        warmup_runs=1,
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-managed-live-tp-repeat3",
        parallel=2,
    )
    live_calls, live_transport = _managed_true_parallel_transport()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_true_parallel_live(
        config_path=config_path,
        run_dir=tmp_path / "run-repeat3",
        run_id="managed-live-true-parallel-repeat3",
        native_transport=native_transport,
        live_transport=live_transport,
    )

    assert [(method, url) for method, url, _data in native_calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(live_calls) == 13
    assert summary["measured_batches"] == 3
    assert summary["measured_request_count"] == 12
    assert summary["warmup_runs"] == 1
    assert summary["warmup_policy"] == "sequential_chunk_0"
    assert summary["app_concurrency"] == 2
    assert summary["parallel_semantics"] == "true_parallel"
    assert summary["cleanup_status"] == "cleanup_verified"
    assert summary["final_loaded_instances"] == 0


def test_run_medium_chunked_sequential_live_prefers_operation_error_when_cleanup_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(tmp_path)
    native_calls: list[tuple[str, str, bytes | None]] = []

    def failing_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": "raw-instance-managed-live",
                    "load_config": {"context_length": 8192, "parallel": 1},
                }
            ).encode("utf-8")
        if len(native_calls) == 2:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e2b",
                            "loaded_instances": [{"instance_id": "raw-instance-managed-live"}],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(native_calls) == 3:
            return b'{"status":"ok"}'
        if len(native_calls) == 4:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e2b",
                            "loaded_instances": [{"instance_id": "raw-instance-managed-live"}],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError(f"unexpected native request #{len(native_calls)}")

    def failing_live_smoke(*args, **kwargs):
        raise RuntimeError("live smoke boom")

    monkeypatch.setattr(
        "tools.lmstudio_lab.managed_runner.run_live_chunked_structured_smoke",
        failing_live_smoke,
    )

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(RuntimeError, match="live smoke boom"):
        runner.run_medium_chunked_sequential_live(
            config_path=config_path,
            run_dir=tmp_path / "run-fail",
            run_id="managed-live-fail",
            native_transport=failing_native_transport,
        )

    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert (tmp_path / "run-fail" / "system_samples.jsonl").exists()
    assert (tmp_path / "run-fail" / "system_summary.json").exists()
    unload_payload = json.loads(native_calls[2][2].decode("utf-8"))
    assert unload_payload == {"instance_id": "raw-instance-managed-live"}


def test_run_medium_chunked_sequential_prep_writes_expected_no_live_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    transport = _prep_transport()
    runner = ManagedLabRunner(transport, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_sequential_prep(
        run_dir=tmp_path,
        run_id="mv22-pre-gemma-medium",
        timeout_s=2.5,
        providers={
            "lmstudio_local": "managed_runner_custom",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
    )

    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["run_id"] == "mv22-pre-gemma-medium"
    assert summary["dataset_id"] == PREP_DATASET_ID
    assert summary["model_keys"] == list(PREP_MODEL_KEYS)
    assert summary["measured_request_count"] == 8
    assert summary["validation_source"] == "safe_generation_envelope_no_raw_content"
    assert summary["validation_status"] == "not_evaluated_no_live"
    assert summary["json_parse_pass_count"] is None
    assert summary["schema_pass_count"] is None
    assert summary["business_pass_count"] is None
    assert summary["ids_exact_pass_count"] is None
    assert summary["reasoning_leak_count"] == 0
    assert summary["finish_length_count"] == 0
    assert summary["empty_text_count"] == 0
    assert summary["duplicate_id_count"] is None
    assert summary["invalid_json_count"] is None
    assert summary["schema_error_count"] is None
    assert summary["envelope_success_count"] == 8
    assert summary["envelope_success_rate"] == 1.0
    assert summary["envelope_readiness_pass"] is True
    assert summary["all_chunks_pass"] is None
    assert summary["batch_business_pass"] is None
    assert summary["cleanup_status"] == "not_required_no_live"
    assert summary["final_loaded_instances"] == 0
    assert summary["raw_prompt_response_stored"] is False
    assert summary["app_concurrency"] == 1
    assert summary["configured_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["parallel_verified"] is None
    assert summary["queue_pressure_mode"] is False
    assert summary["parallel_semantics"] == "sequential"
    assert summary["system_sample_count"] == 2

    expected_files = {
        "run_config.json",
        "metrics.jsonl",
        "batch_summary.json",
        "structured_validation_summary.json",
        "structured_validation_summary.csv",
        "privacy_scan.json",
        "report.md",
        "system_samples.jsonl",
        "system_summary.json",
    }
    assert expected_files == {path.name for path in tmp_path.iterdir()}

    run_config = json.loads((tmp_path / "run_config.json").read_text(encoding="utf-8"))
    assert run_config == {
        "schema_version": "1.0",
        "run_id": "mv22-pre-gemma-medium",
        "mode": "managed_runner_medium_chunked_sequential_prep",
        "dataset_id": PREP_DATASET_ID,
        "dataset_hash": "sha256:blocks-json-medium-chunked-v1",
        "model_keys": list(PREP_MODEL_KEYS),
        "model_count": 2,
        "chunks_count": 4,
        "chunk_size_blocks": 25,
        "app_concurrency": 1,
        "configured_parallel": 1,
        "applied_parallel": 1,
        "parallel_verified": None,
        "queue_pressure_mode": False,
        "parallel_semantics": "sequential",
        "fake_first": True,
        "no_live": True,
        "uses_fake_transport_only": True,
        "lmstudio_api_called": False,
        "raw_prompt_response_stored": False,
    }

    metrics_rows = _read_jsonl(tmp_path / "metrics.jsonl")
    assert len(metrics_rows) == 8
    assert {row["endpoint_kind"] for row in metrics_rows} == {"compat_chat"}
    assert {row["model_key"] for row in metrics_rows} == set(PREP_MODEL_KEYS)
    assert {row["parallel_semantics"] for row in metrics_rows} == {"sequential"}
    assert {row["app_concurrency"] for row in metrics_rows} == {1}
    assert {row["configured_parallel"] for row in metrics_rows} == {1}
    assert {row["applied_parallel"] for row in metrics_rows} == {1}
    assert {row["parallel_verified"] for row in metrics_rows} == {None}
    assert {row["queue_pressure_mode"] for row in metrics_rows} == {False}
    assert {row["response_format"]["kind"] for row in metrics_rows} == {"json_schema"}
    assert {row["response_format"]["schema_name"] for row in metrics_rows} == {"factual_blocks.v1"}
    assert {row["validation_source"] for row in metrics_rows} == {
        "safe_generation_envelope_no_raw_content"
    }
    assert {row["validation_status"] for row in metrics_rows} == {"not_evaluated_no_live"}
    assert {row["validation"]["json_parse_pass"] for row in metrics_rows} == {None}
    assert {row["validation"]["schema_pass"] for row in metrics_rows} == {None}
    assert {row["validation"]["business_pass"] for row in metrics_rows} == {None}
    assert {row["validation"]["ids_exact_pass"] for row in metrics_rows} == {None}
    assert {row["validation"]["non_empty_text_pass"] for row in metrics_rows} == {True}
    assert {row["error_status"] for row in metrics_rows} == {"ok"}
    assert {row["raw_prompt_response_stored"] for row in metrics_rows} == {False}
    assert [row["request_id"] for row in metrics_rows[:4]] == [
        "gemma4_e2b_q4km_chunk_0000",
        "gemma4_e2b_q4km_chunk_0001",
        "gemma4_e2b_q4km_chunk_0002",
        "gemma4_e2b_q4km_chunk_0003",
    ]

    structured_summary = json.loads(
        (tmp_path / "structured_validation_summary.json").read_text(encoding="utf-8")
    )
    assert structured_summary == {
        "schema_version": "1.0",
        "validation_source": "safe_generation_envelope_no_raw_content",
        "validation_status": "not_evaluated_no_live",
        "total_count": 8,
        "json_parse_pass_count": None,
        "json_parse_pass_rate": None,
        "schema_pass_count": None,
        "schema_pass_rate": None,
        "business_pass_count": None,
        "business_pass_rate": None,
        "ids_exact_pass_count": None,
        "ids_exact_pass_rate": None,
        "reasoning_leak_count": 0,
        "finish_length_count": 0,
        "duplicate_id_count": None,
        "empty_text_count": 0,
        "invalid_json_count": None,
        "schema_error_count": None,
        "envelope_success_count": 8,
        "envelope_success_rate": 1.0,
    }

    privacy_scan = json.loads((tmp_path / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "run_config.json",
            "metrics.jsonl",
            "batch_summary.json",
            "structured_validation_summary.json",
            "structured_validation_summary.csv",
            "report.md",
            "system_summary.json",
            "system_samples.jsonl",
        ],
        "raw_prompt_response_stored": False,
    }

    batch_summary = json.loads((tmp_path / "batch_summary.json").read_text(encoding="utf-8"))
    assert batch_summary["parallel_verified"] is None

    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "no-live/fake-first managed-runner prep" in report_text
    assert "LM Studio API/live/GPU: `not used`" in report_text
    assert (
        "ManagedLabRunner -> GenerationClient/contracts -> injected fake compat transport only; no live/network transport created"
        in report_text
    )
    assert "structured JSON/schema/business validation: `not evaluated in MV2.2-pre`" in report_text
    assert (
        "raw model content is not stored or exposed in this no-live safe envelope path"
        in report_text
    )
    assert (
        "envelope-readiness/config/privacy prep only and is not a real model quality proof"
        in report_text
    )
    assert "`run_config.json`" in report_text
    assert "`system_summary.json`" in report_text

    system_samples_text = (tmp_path / "system_samples.jsonl").read_text(encoding="utf-8")
    system_summary_text = (tmp_path / "system_summary.json").read_text(encoding="utf-8")
    _assert_safe_system_artifacts(system_samples_text, system_summary_text)

    all_artifact_text = "\n".join(
        (tmp_path / file_name).read_text(encoding="utf-8") for file_name in expected_files
    )
    assert PRIVATE_CONTENT_SENTINEL not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert "raw-prompt-" not in all_artifact_text

    assert len(transport.requests) == 8
    assert {request.endpoint.kind for request in transport.requests} == {EndpointKind.COMPAT_CHAT}
    assert {request.endpoint.method for request in transport.requests} == {HttpMethod.POST}
    assert {request.payload_kind for request in transport.requests} == {"structured_generation"}
    assert {request.timeout_s for request in transport.requests} == {2.5}
    assert all(request.payload_hash is not None for request in transport.requests)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"dataset_id": "blocks_json_medium"}, "dataset_id must be exactly"),
        ({"model_keys": ("qwen2_5_7b",)}, "model_keys must be a non-empty subset"),
        ({"model_keys": ()}, "model_keys must be a non-empty sequence"),
    ],
)
def test_run_medium_chunked_sequential_prep_rejects_wrong_scope_inputs(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    runner = ManagedLabRunner(_prep_transport())

    with pytest.raises(ValueError, match=message):
        runner.run_medium_chunked_sequential_prep(
            run_dir=tmp_path,
            run_id="invalid-scope",
            **kwargs,
        )


def test_run_medium_chunked_sequential_prep_marks_reasoning_leak_failure_without_content_leak(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    transport = _prep_transport(
        failure_overrides={
            ("gemma4_e2b_q4km", 1): _prep_chunk_payload(
                model_key="gemma4_e2b_q4km",
                chunk_id=1,
                reasoning_content="reasoning-private-sentinel",
            )
        }
    )
    runner = ManagedLabRunner(transport, system_sampler=fake_sampler)

    summary = runner.run_medium_chunked_sequential_prep(
        run_dir=tmp_path,
        run_id="mv22-pre-reasoning-failure",
    )

    assert summary["measured_request_count"] == 8
    assert summary["validation_status"] == "not_evaluated_no_live"
    assert summary["json_parse_pass_count"] is None
    assert summary["schema_pass_count"] is None
    assert summary["business_pass_count"] is None
    assert summary["reasoning_leak_count"] == 1
    assert summary["finish_length_count"] == 0
    assert summary["empty_text_count"] == 0
    assert summary["envelope_success_count"] == 7
    assert summary["envelope_success_rate"] == pytest.approx(7 / 8)
    assert summary["envelope_readiness_pass"] is False
    assert summary["all_chunks_pass"] is None
    assert summary["batch_business_pass"] is None

    structured_summary = json.loads(
        (tmp_path / "structured_validation_summary.json").read_text(encoding="utf-8")
    )
    assert structured_summary["reasoning_leak_count"] == 1
    assert structured_summary["business_pass_count"] is None
    assert structured_summary["envelope_success_count"] == 7

    metrics_rows = _read_jsonl(tmp_path / "metrics.jsonl")
    failed_rows = [row for row in metrics_rows if row["error_status"] == "failed"]
    assert len(failed_rows) == 1
    assert failed_rows[0]["error_category"] == "reasoning"
    assert failed_rows[0]["validation"]["reasoning_leak"] is True
    assert failed_rows[0]["validation"]["json_parse_pass"] is None
    assert failed_rows[0]["validation"]["schema_pass"] is None
    assert failed_rows[0]["validation"]["business_pass"] is None
    assert failed_rows[0]["validation"]["ids_exact_pass"] is None
    assert failed_rows[0]["reasoning_content_present"] is True
    assert failed_rows[0]["parallel_verified"] is None

    privacy_scan = json.loads((tmp_path / "privacy_scan.json").read_text(encoding="utf-8"))
    assert "structured_validation_summary.csv" in privacy_scan["scanned_artifacts"]
    assert "report.md" in privacy_scan["scanned_artifacts"]

    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "structured JSON/schema/business validation: `not evaluated in MV2.2-pre`" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in tmp_path.iterdir() if path.is_file()
    )
    assert PRIVATE_CONTENT_SENTINEL not in all_artifact_text
    assert "reasoning-private-sentinel" not in all_artifact_text
    assert "raw-prompt-gemma4_e2b_q4km-1" not in all_artifact_text
    assert {request.endpoint.kind for request in transport.requests} == {EndpointKind.COMPAT_CHAT}


def test_run_cache_stateful_no_live_writes_expected_fake_only_artifacts(tmp_path: Path) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    transport = _QueueTransport({})
    runner = ManagedLabRunner(transport, system_sampler=fake_sampler)
    plan = _cache_stateful_plan()

    summary = runner.run_cache_stateful_no_live(
        run_dir=tmp_path,
        run_id="cache-no-live-e2b",
        plan=plan,
        providers={
            "lmstudio_local": "managed_runner_custom",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
    )

    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["run_id"] == "cache-no-live-e2b"
    assert summary["experiment_id"] == plan.experiment_id
    assert summary["mode"] == "managed_runner_cache_stateful_no_live"
    assert summary["measurement_status"] == "not_measured_no_live"
    assert summary["reuse_verdict"] == "kv_reuse_unproven"
    assert summary["has_live_measurements"] is False
    assert summary["ttft_ms"] is None
    assert summary["prompt_processing_ms"] is None
    assert summary["total_latency_ms"] is None
    assert summary["cached_tokens"] is None
    assert summary["cache_proxy"] is None
    assert summary["ram_peak_mb"] is None
    assert summary["vram_peak_mb"] is None
    assert summary["stateful_functional_ok"] is None
    assert summary["kv_reuse_proven"] is False
    assert summary["successful_branch_count"] == 0
    assert summary["system_sample_count"] == 2
    assert summary["lmstudio_api_called"] is False
    assert summary["network"] is False
    assert summary["raw_prompt_response_stored"] is False

    expected_files = {
        "run_config.json",
        "cache_plan.json",
        "requests.jsonl",
        "metrics.jsonl",
        "cache_summary.json",
        "privacy_scan.json",
        "report.md",
        "system_samples.jsonl",
        "system_summary.json",
    }
    assert expected_files == {path.name for path in tmp_path.iterdir()}

    cache_summary = json.loads((tmp_path / "cache_summary.json").read_text(encoding="utf-8"))
    assert cache_summary["mode"] == "managed_runner_cache_stateful_no_live"
    assert cache_summary["planned_request_count"] == plan.planned_request_count
    assert cache_summary["placeholder_metric_count"] == plan.planned_request_count
    assert cache_summary["stateful_branch_request_count"] == 2
    assert cache_summary["stateless_prefix_request_count"] == 2
    assert cache_summary["compact_memory_request_count"] == 2
    assert cache_summary["ttft_ms"] is None
    assert cache_summary["prompt_processing_ms"] is None
    assert cache_summary["total_latency_ms"] is None
    assert cache_summary["cached_tokens"] is None
    assert cache_summary["cache_proxy"] is None
    assert cache_summary["ram_peak_mb"] is None
    assert cache_summary["vram_peak_mb"] is None
    assert cache_summary["stateful_functional_ok"] is None

    privacy_scan = json.loads((tmp_path / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "cache_stateful_no_live_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "run_config.json",
            "cache_plan.json",
            "requests.jsonl",
            "metrics.jsonl",
            "cache_summary.json",
            "report.md",
            "system_summary.json",
            "system_samples.jsonl",
        ],
        "raw_prompt_response_stored": False,
    }

    request_rows = _read_jsonl(tmp_path / "requests.jsonl")
    assert len(request_rows) == plan.planned_request_count
    assert request_rows[0]["request_kind"] == "stateful_root"
    assert {row["measurement_status"] for row in request_rows} == {"not_measured_no_live"}
    assert {row["reuse_verdict"] for row in request_rows} == {"kv_reuse_unproven"}
    assert {row["kv_reuse_proven"] for row in request_rows} == {False}
    assert {row["raw_material_stored"] for row in request_rows} == {False}

    metrics_rows = _read_jsonl(tmp_path / "metrics.jsonl")
    assert len(metrics_rows) == plan.planned_request_count
    assert {row["measurement_status"] for row in metrics_rows} == {"not_measured_no_live"}
    assert {row["reuse_verdict"] for row in metrics_rows} == {"kv_reuse_unproven"}
    assert {row["has_live_measurements"] for row in metrics_rows} == {False}
    assert {row["stateful_functional_ok"] for row in metrics_rows} == {None}
    assert {row["kv_reuse_proven"] for row in metrics_rows} == {False}
    assert {row["ttft_ms"] for row in metrics_rows} == {None}
    assert {row["prompt_processing_ms"] for row in metrics_rows} == {None}
    assert {row["total_latency_ms"] for row in metrics_rows} == {None}
    assert {row["cached_tokens"] for row in metrics_rows} == {None}
    assert {row["cache_proxy"] for row in metrics_rows} == {None}
    assert {row["ram_peak_mb"] for row in metrics_rows} == {None}
    assert {row["vram_peak_mb"] for row in metrics_rows} == {None}
    assert {row["raw_prompt_response_stored"] for row in metrics_rows} == {False}

    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "no-live/fake-first cache/stateful path" in report_text
    assert "LM Studio API/live/GPU/network: `not used`" in report_text
    assert "stateful API contract is not proof of physical KV reuse" in report_text
    assert "L3.3 live/cache proof requires explicit approval" in report_text

    all_artifact_text = "\n".join(
        (tmp_path / file_name).read_text(encoding="utf-8") for file_name in expected_files
    )
    assert PRIVATE_CONTENT_SENTINEL not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert '"cache_hit": true' not in all_artifact_text
    assert '"branch_ttft_improved": true' not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text

    assert transport.requests == []


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        (
            _cache_stateful_plan(model_key="gemma4_e4b_q4km"),
            "plan.model_key must be exactly 'gemma4_e2b_q4km'",
        ),
        (
            replace(_cache_stateful_plan(), production_default=True),
            "plan.production_default must be False",
        ),
        (
            replace(_cache_stateful_plan(), context_window=4096),
            "plan.context_window must be one of",
        ),
        (
            replace(_cache_stateful_plan(), raw_material_stored=True),
            "plan.raw_material_stored must be False",
        ),
        (
            replace(
                _cache_stateful_plan(),
                root_request=replace(
                    _cache_stateful_plan().root_request, model_key="gemma4_e4b_q4km"
                ),
            ),
            "plan.root_request.model_key must match plan.model_key",
        ),
        (
            replace(
                _cache_stateful_plan(),
                root_request=replace(_cache_stateful_plan().root_request, raw_material_stored=True),
            ),
            "plan.root_request.raw_material_stored must be False",
        ),
        (
            replace(_cache_stateful_plan(), stateful_branch_requests=()),
            "plan.stateful_branch_requests must contain at least one request",
        ),
        (
            replace(_cache_stateful_plan(), stateless_prefix_requests=()),
            "plan.stateless_prefix_requests must contain at least one request",
        ),
        (
            replace(_cache_stateful_plan(), compact_memory_requests=()),
            "plan.compact_memory_requests must contain at least one request",
        ),
        (
            replace(
                _cache_stateful_plan(),
                root_request=replace(_cache_stateful_plan().root_request, context_window=16384),
            ),
            "plan.root_request.context_window must match plan.context_window",
        ),
        (
            replace(
                _cache_stateful_plan(),
                root_request=replace(_cache_stateful_plan().root_request, estimated_input_tokens=0),
            ),
            "plan.root_request.estimated_input_tokens must be a positive integer",
        ),
        (
            replace(
                _cache_stateful_plan(),
                stateful_branch_requests=(
                    replace(
                        _cache_stateful_plan().stateful_branch_requests[0],
                        root_request_id="other_root",
                    ),
                    *_cache_stateful_plan().stateful_branch_requests[1:],
                ),
            ),
            r"plan.stateful_branch_requests\[0\]\.root_request_id must match plan.root_request.request_id",
        ),
        (
            replace(
                _cache_stateful_plan(),
                stateful_branch_requests=(
                    replace(
                        _cache_stateful_plan().stateful_branch_requests[0],
                        root_context_hash=_safe_hash("mismatched-root-context"),
                    ),
                    *_cache_stateful_plan().stateful_branch_requests[1:],
                ),
            ),
            r"plan.stateful_branch_requests\[0\]\.root_context_hash must match plan.root_request.root_context_hash",
        ),
        (
            replace(
                _cache_stateful_plan(),
                stateful_branch_requests=(
                    replace(
                        _cache_stateful_plan().stateful_branch_requests[0],
                        estimated_branch_tokens=0,
                    ),
                    *_cache_stateful_plan().stateful_branch_requests[1:],
                ),
            ),
            r"plan.stateful_branch_requests\[0\]\.estimated_branch_tokens must be a positive integer",
        ),
        (
            replace(
                _cache_stateful_plan(),
                stateful_branch_requests=(
                    replace(
                        _cache_stateful_plan().stateful_branch_requests[0],
                        raw_material_stored=True,
                    ),
                    *_cache_stateful_plan().stateful_branch_requests[1:],
                ),
            ),
            r"plan.stateful_branch_requests\[0\]\.raw_material_stored must be False",
        ),
        (
            replace(
                _cache_stateful_plan(),
                stateless_prefix_requests=(
                    replace(
                        _cache_stateful_plan().stateless_prefix_requests[0],
                        raw_material_stored=True,
                    ),
                    *_cache_stateful_plan().stateless_prefix_requests[1:],
                ),
            ),
            r"plan.stateless_prefix_requests\[0\]\.raw_material_stored must be False",
        ),
        (
            replace(
                _cache_stateful_plan(),
                stateless_prefix_requests=(
                    replace(
                        _cache_stateful_plan().stateless_prefix_requests[0],
                        estimated_input_tokens=0,
                    ),
                    *_cache_stateful_plan().stateless_prefix_requests[1:],
                ),
            ),
            r"plan.stateless_prefix_requests\[0\]\.estimated_input_tokens must be a positive integer",
        ),
        (
            replace(
                _cache_stateful_plan(),
                compact_memory_requests=(
                    replace(
                        _cache_stateful_plan().compact_memory_requests[0],
                        raw_material_stored=True,
                    ),
                    *_cache_stateful_plan().compact_memory_requests[1:],
                ),
            ),
            r"plan.compact_memory_requests\[0\]\.raw_material_stored must be False",
        ),
        (
            replace(
                _cache_stateful_plan(),
                compact_memory_requests=(
                    replace(
                        _cache_stateful_plan().compact_memory_requests[0],
                        estimated_memory_tokens=0,
                    ),
                    *_cache_stateful_plan().compact_memory_requests[1:],
                ),
            ),
            r"plan.compact_memory_requests\[0\]\.estimated_memory_tokens must be a positive integer",
        ),
        (
            replace(
                _cache_stateful_plan(),
                compact_memory_requests=(
                    replace(
                        _cache_stateful_plan().compact_memory_requests[0],
                        estimated_branch_tokens=0,
                    ),
                    *_cache_stateful_plan().compact_memory_requests[1:],
                ),
            ),
            r"plan.compact_memory_requests\[0\]\.estimated_branch_tokens must be a positive integer",
        ),
    ],
)
def test_run_cache_stateful_no_live_rejects_out_of_scope_inputs(
    tmp_path: Path,
    plan: CacheExperimentPlan,
    message: str,
) -> None:
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(ValueError, match=message):
        runner.run_cache_stateful_no_live(
            run_dir=tmp_path,
            run_id="cache-no-live-invalid",
            plan=plan,
        )


def test_run_cache_25k_no_live_prep_writes_expected_planning_artifacts(tmp_path: Path) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    transport = _QueueTransport({})
    runner = ManagedLabRunner(transport, system_sampler=fake_sampler)

    original_live_loader = managed_runner_module.load_live_smoke_config
    original_model_operation = managed_runner_module.run_exact_model_operation
    original_live_transport = managed_runner_module._default_live_transport
    original_live_streaming_transport = managed_runner_module._default_live_streaming_transport
    managed_runner_module.load_live_smoke_config = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live config loader must not be used")
    )
    managed_runner_module.run_exact_model_operation = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("native lifecycle helpers must not be used")
    )
    managed_runner_module._default_live_transport = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live transport must not be used")
    )
    managed_runner_module._default_live_streaming_transport = lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("live streaming transport must not be used"))
    try:
        summary = runner.run_cache_25k_no_live_prep(
            config_path=_cache_25k_no_live_prep_config_path(),
            run_dir=tmp_path,
            run_id="l3-5-cache-25k-no-live",
        )
    finally:
        managed_runner_module.load_live_smoke_config = original_live_loader
        managed_runner_module.run_exact_model_operation = original_model_operation
        managed_runner_module._default_live_transport = original_live_transport
        managed_runner_module._default_live_streaming_transport = original_live_streaming_transport

    assert fake_sampler.start_calls == 0
    assert fake_sampler.stop_calls == 0
    assert transport.requests == []

    assert summary == {
        "schema_version": managed_runner_module.SCHEMA_VERSION,
        "run_id": "l3-5-cache-25k-no-live",
        "experiment_id": "l3_5_cache_25k_no_live_prep",
        "mode": "managed_runner_cache_25k_no_live_prep",
        "model_key": "gemma4_e2b_q4km",
        "model_id": "google/gemma-4-e2b",
        "dataset_id": "lecture_25k_tokens",
        "request_shape_count": 25,
        "app_concurrency": 1,
        "practical_candidate_mode": "compact_memory_primary",
        "next_gate": "l3_5b_32k_load_only_smoke_after_approval",
        "privacy_scan_status": "pass",
        "measurement_status": "not_measured_no_live",
        "kv_reuse_proven": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "managed_live": False,
        "network": False,
        "lmstudio_api_called": False,
        "load_called": False,
        "unload_called": False,
        "generation_allowed": False,
        "generation_called": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }

    expected_files = {
        "dataset_manifest.json",
        "token_manifest.json",
        "context_fit_report.json",
        "cache_plan.json",
        "branch_plan.json",
        "request_shapes.jsonl",
        "mode_comparison_plan.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in tmp_path.iterdir()}

    dataset_manifest = json.loads((tmp_path / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert dataset_manifest["dataset_id"] == "lecture_25k_tokens"
    assert dataset_manifest["kind"] == "synthetic_long_lecture_transcript"
    assert dataset_manifest["privacy"] == "synthetic"
    assert dataset_manifest["items_count"] == 1
    assert dataset_manifest["chars"] == 75000
    assert dataset_manifest["estimated_input_tokens"] == 25000
    assert dataset_manifest["actual_input_tokens"] is None
    assert dataset_manifest["estimate_error_ratio"] is None
    assert dataset_manifest["content_hash"] == "sha256:lecture-25k-tokens-v1"
    assert dataset_manifest["source_hash"] == "sha256:lecture-25k-source-v1"
    assert dataset_manifest["privacy_safe"] is True

    token_manifest = json.loads((tmp_path / "token_manifest.json").read_text(encoding="utf-8"))
    assert token_manifest["root_material_hash"].startswith("sha256:")
    assert token_manifest["root_prompt_hash"].startswith("sha256:")
    assert token_manifest["output_reserve_tokens"] == 2048
    assert token_manifest["tokenizer_method"] == "heuristic_chars_div_3"
    assert token_manifest["tokenizer_family"] == "generic"
    assert token_manifest["tokenizer_version"] == "1.0"
    assert len(token_manifest["branches"]) == 8
    assert all(
        branch["material_hash"].startswith("sha256:") for branch in token_manifest["branches"]
    )
    assert all(branch["prompt_hash"].startswith("sha256:") for branch in token_manifest["branches"])

    context_fit_report = json.loads(
        (tmp_path / "context_fit_report.json").read_text(encoding="utf-8")
    )
    rows_by_window = {row["context_window"]: row for row in context_fit_report["context_windows"]}
    assert rows_by_window[8192]["fit_status"] == "full_root_does_not_fit"
    assert rows_by_window[8192]["full_root_fits"] is False
    assert rows_by_window[16384]["fit_status"] == "likely_partial_only"
    assert rows_by_window[16384]["full_root_fits"] is False
    assert rows_by_window[32768]["fit_status"] == "candidate_full_root_not_live_authorized"
    assert rows_by_window[32768]["full_root_fits"] is True
    assert rows_by_window[32768]["allowed_next_gate"] == "l3_5b_32k_load_only_smoke_after_approval"
    assert rows_by_window[65536]["fit_status"] == "later_stress_not_current_live_target"
    assert rows_by_window[65536]["live_25k_authorized"] is False

    cache_plan = json.loads((tmp_path / "cache_plan.json").read_text(encoding="utf-8"))
    assert cache_plan["mode"] == "managed_runner_cache_25k_no_live_prep"
    assert cache_plan["modes"] == [
        "compact_memory_primary",
        "stateful_root_branches_experimental",
        "stateless_full_prefix_baseline",
    ]
    assert cache_plan["context_windows"] == [8192, 16384, 32768, 65536]
    assert cache_plan["app_concurrency"] == 1
    assert cache_plan["measurement_status"] == "not_measured_no_live"
    assert cache_plan["kv_reuse_proven"] is False
    assert cache_plan["live_25k_authorized"] is False
    assert cache_plan["network"] is False
    assert cache_plan["lmstudio_api_called"] is False
    assert cache_plan["load_called"] is False
    assert cache_plan["unload_called"] is False
    assert cache_plan["generation_called"] is False

    branch_plan = json.loads((tmp_path / "branch_plan.json").read_text(encoding="utf-8"))
    assert set(branch_plan) == {
        "summary_short",
        "summary_detailed",
        "timeline_topics",
        "glossary_terms",
        "postprocess_chunk_1",
        "postprocess_chunk_2",
        "postprocess_chunk_3",
        "postprocess_chunk_4",
    }

    request_shapes = _read_jsonl(tmp_path / "request_shapes.jsonl")
    assert len(request_shapes) == 25
    assert request_shapes[0]["shape_kind"] == "root"
    assert request_shapes[0]["mode"] == "stateful_root_branches_experimental"
    assert {row["measurement_status"] for row in request_shapes} == {"not_measured_no_live"}
    assert {row["kv_reuse_proven"] for row in request_shapes} == {False}
    assert {row["managed_live"] for row in request_shapes} == {False}
    assert {row["network"] for row in request_shapes} == {False}
    assert {row["lmstudio_api_called"] for row in request_shapes} == {False}
    assert {row["load_called"] for row in request_shapes} == {False}
    assert {row["unload_called"] for row in request_shapes} == {False}
    assert {row["generation_called"] for row in request_shapes} == {False}
    assert {row["live_25k_authorized"] for row in request_shapes} == {False}
    assert {row["context_window_candidate"] for row in request_shapes} == {32768}
    assert all("cache_hit" not in row for row in request_shapes)
    assert all("branch_ttft_improved" not in row for row in request_shapes)

    mode_comparison = json.loads(
        (tmp_path / "mode_comparison_plan.json").read_text(encoding="utf-8")
    )
    assert mode_comparison == {
        "compact_memory_primary": {
            "summary": "practical candidate / primary posture",
            "candidate_status": "primary",
            "measurement_status": "not_measured_no_live",
            "kv_reuse_proven": False,
            "live_25k_authorized": False,
            "production_default": False,
            "wvm_runtime_integration": False,
            "managed_live": False,
            "network": False,
            "lmstudio_api_called": False,
            "load_called": False,
            "unload_called": False,
            "generation_allowed": False,
            "generation_called": False,
            "raw_prompt_response_stored": False,
            "raw_material_stored": False,
        },
        "stateful_root_branches_experimental": {
            "summary": "experimental candidate, functional/instrumentable but KV unproven",
            "candidate_status": "experimental",
            "measurement_status": "not_measured_no_live",
            "kv_reuse_proven": False,
            "live_25k_authorized": False,
            "production_default": False,
            "wvm_runtime_integration": False,
            "managed_live": False,
            "network": False,
            "lmstudio_api_called": False,
            "load_called": False,
            "unload_called": False,
            "generation_allowed": False,
            "generation_called": False,
            "raw_prompt_response_stored": False,
            "raw_material_stored": False,
        },
        "stateless_full_prefix_baseline": {
            "summary": "expensive baseline",
            "candidate_status": "baseline",
            "measurement_status": "not_measured_no_live",
            "kv_reuse_proven": False,
            "live_25k_authorized": False,
            "production_default": False,
            "wvm_runtime_integration": False,
            "managed_live": False,
            "network": False,
            "lmstudio_api_called": False,
            "load_called": False,
            "unload_called": False,
            "generation_allowed": False,
            "generation_called": False,
            "raw_prompt_response_stored": False,
            "raw_material_stored": False,
        },
    }

    privacy_scan = json.loads((tmp_path / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": [
            "dataset_manifest.json",
            "token_manifest.json",
            "context_fit_report.json",
            "cache_plan.json",
            "branch_plan.json",
            "request_shapes.jsonl",
            "mode_comparison_plan.json",
            "privacy_scan.json",
            "report.md",
        ],
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }

    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "L3.5 is a no-live prep run only." in report_text
    assert "No 25k live request was run." in report_text
    assert "No HTTP/load/unload/generation occurred." in report_text
    assert "KV reuse remains unproven." in report_text
    assert "compact_memory_primary remains the practical candidate." in report_text
    assert (
        "Next gate is L3.5b 32k load-only smoke (not implemented/run here) only after approval."
        in report_text
    )

    all_artifact_text = "\n".join(
        (tmp_path / file_name).read_text(encoding="utf-8") for file_name in expected_files
    )
    assert PRIVATE_CONTENT_SENTINEL not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert "http://127.0.0.1:1234" not in all_artifact_text
    assert "[REDACTED]" not in all_artifact_text
    assert '"cache_hit": true' not in all_artifact_text
    assert '"branch_ttft_improved": true' not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text
    assert "raw lecture" not in all_artifact_text.lower()


def test_run_l3_6_25k_no_live_preflight_writes_expected_artifacts(tmp_path: Path) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    transport = _QueueTransport({})
    runner = ManagedLabRunner(transport, system_sampler=fake_sampler)

    original_live_loader = managed_runner_module.load_live_smoke_config
    original_model_operation = managed_runner_module.run_exact_model_operation
    original_live_transport = managed_runner_module._default_live_transport
    original_live_streaming_transport = managed_runner_module._default_live_streaming_transport
    managed_runner_module.load_live_smoke_config = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live config loader must not be used")
    )
    managed_runner_module.run_exact_model_operation = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("native lifecycle helpers must not be used")
    )
    managed_runner_module._default_live_transport = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live transport must not be used")
    )
    managed_runner_module._default_live_streaming_transport = lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("live streaming transport must not be used"))
    try:
        summary = runner.run_l3_6_25k_no_live_preflight(
            config_path=_l3_6_25k_no_live_preflight_config_path(),
            run_dir=tmp_path,
            run_id="l3-6-25k-no-live-preflight",
        )
    finally:
        managed_runner_module.load_live_smoke_config = original_live_loader
        managed_runner_module.run_exact_model_operation = original_model_operation
        managed_runner_module._default_live_transport = original_live_transport
        managed_runner_module._default_live_streaming_transport = original_live_streaming_transport

    assert fake_sampler.start_calls == 0
    assert fake_sampler.stop_calls == 0
    assert transport.requests == []

    assert summary == {
        "schema_version": managed_runner_module.SCHEMA_VERSION,
        "run_id": "l3-6-25k-no-live-preflight",
        "experiment_id": "l3_6_25k_no_live_preflight_gemma4_e2b",
        "mode": "no_live_preflight",
        "model_key": "gemma4_e2b_q4km",
        "model_id": "google/gemma-4-e2b",
        "dataset_id": "lecture_25k_tokens",
        "target_context_length": 32768,
        "artifact_count": 7,
        "exact_tokenization_status": "pending_no_live",
        "responses_long_context_status": "blocked_long_context_internal_error",
        "safety_margin_tokens": 804,
        "privacy_scan_status": "pass",
        "next_gate": "no_live_tokenization_review_only",
        "measurement_status": "not_measured_no_live",
        "kv_reuse_proven": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "managed_live": False,
        "network": False,
        "lmstudio_api_called": False,
        "load_called": False,
        "unload_called": False,
        "generation_allowed": False,
        "generation_called": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }

    expected_files = {
        "tokenized_prompt_report.json",
        "output_reserve_report.json",
        "prompt_shape_report.md",
        "mode_plan.json",
        "abort_conditions.md",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in tmp_path.iterdir()}

    tokenized_prompt_report = json.loads(
        (tmp_path / "tokenized_prompt_report.json").read_text(encoding="utf-8")
    )
    assert tokenized_prompt_report["experiment_id"] == "l3_6_25k_no_live_preflight_gemma4_e2b"
    assert tokenized_prompt_report["mode"] == "no_live_preflight"
    assert tokenized_prompt_report["target_context_length"] == 32768
    assert tokenized_prompt_report["model"] == {
        "key": "gemma4_e2b_q4km",
        "lmstudio_model_id": "google/gemma-4-e2b",
    }
    assert tokenized_prompt_report["dataset"] == {
        "id": "lecture_25k_tokens",
        "chars": 75000,
        "content_hash": "sha256:lecture-25k-tokens-v1",
        "source_hash": "sha256:lecture-25k-source-v1",
        "estimated_input_tokens": 25000,
        "tokenizer": {"method": "heuristic_chars_div_3", "family": "generic", "version": "1.0"},
    }
    assert tokenized_prompt_report["tokenization_source"] == "dataset_manifest_static_estimate"
    assert tokenized_prompt_report["exact_tokenization_status"] == "pending_no_live"
    assert tokenized_prompt_report["chat_template_tokenization_status"] == "pending_no_live"
    assert tokenized_prompt_report["required_tokens"] == 27048
    assert tokenized_prompt_report["budget_tokens"] == 27852
    assert tokenized_prompt_report["safety_margin_tokens"] == 804
    assert tokenized_prompt_report["fit_status"] == "estimate_fit_with_pending_exact_tokenization"
    assert tokenized_prompt_report["generation_allowed"] is False
    assert tokenized_prompt_report["generation_called"] is False
    assert tokenized_prompt_report["live_25k_authorized"] is False
    assert tokenized_prompt_report["production_default"] is False
    assert tokenized_prompt_report["wvm_runtime_integration"] is False
    assert tokenized_prompt_report["kv_reuse_proven"] is False

    output_reserve_report = json.loads(
        (tmp_path / "output_reserve_report.json").read_text(encoding="utf-8")
    )
    assert output_reserve_report["reserve_tokens"] == 2048
    assert output_reserve_report["required_tokens"] == 27048
    assert output_reserve_report["budget_tokens"] == 27852
    assert output_reserve_report["safety_margin_tokens"] == 804
    assert output_reserve_report["exact_tokenization_status"] == "pending_no_live"
    assert output_reserve_report["generation_allowed"] is False
    assert output_reserve_report["live_25k_authorized"] is False
    assert output_reserve_report["production_default"] is False
    assert output_reserve_report["wvm_runtime_integration"] is False
    assert output_reserve_report["kv_reuse_proven"] is False

    mode_plan = json.loads((tmp_path / "mode_plan.json").read_text(encoding="utf-8"))
    assert mode_plan["compact_memory"]["route_status"] == "primary_candidate"
    assert mode_plan["native_chat_stateful"]["endpoint_path"] == "/api/v1/chat"
    assert mode_plan["native_chat_stateful"]["route_status"] == "research_latency_candidate"
    assert mode_plan["stateless_full_prefix"]["route_status"] == "baseline"
    assert mode_plan["responses"]["endpoint_path"] == "/v1/responses"
    assert mode_plan["responses"]["route_status"] == "blocked_long_context_internal_error"
    assert mode_plan["responses"]["cached_tokens_available"] is False
    assert mode_plan["responses"]["cached_tokens_observed"] is False
    assert mode_plan["responses"]["previous_response_id_supported"] is False
    assert mode_plan["responses"]["root_branch_16k_status"] == "blocked_internal_error"
    assert mode_plan["responses"]["repeated_prefix_16k_status"] == "blocked_internal_error"
    assert mode_plan["responses"]["mutated_prefix_16k_status"] == "blocked_internal_error"
    assert mode_plan["responses"]["live_25k_authorized"] is False
    assert mode_plan["responses"]["kv_reuse_proven"] is False
    assert mode_plan["qwen_structured"]["route_status"] == "blocked_recovery_only"
    assert mode_plan["generation_allowed"] is False
    assert mode_plan["generation_called"] is False
    assert mode_plan["live_25k_authorized"] is False
    assert mode_plan["production_default"] is False
    assert mode_plan["wvm_runtime_integration"] is False
    assert mode_plan["kv_reuse_proven"] is False

    privacy_scan = json.loads((tmp_path / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": [
            "tokenized_prompt_report.json",
            "output_reserve_report.json",
            "prompt_shape_report.md",
            "mode_plan.json",
            "abort_conditions.md",
            "privacy_scan.json",
            "report.md",
        ],
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }

    prompt_shape_report = (tmp_path / "prompt_shape_report.md").read_text(encoding="utf-8")
    assert "compact_memory primary candidate" in prompt_shape_report
    assert (
        "/api/v1/chat remains an instrumentation and latency candidate only" in prompt_shape_report
    )
    assert "/v1/responses is blocked for 16k" in prompt_shape_report
    assert (
        "No live calls, generation, load, unload, or queue/runtime integration occurred"
        in prompt_shape_report
    )

    abort_conditions = (tmp_path / "abort_conditions.md").read_text(encoding="utf-8")
    assert "Exact tokenizer measurement is still pending" in abort_conditions
    assert "below the approved `2048`-token minimum at `804` tokens" in abort_conditions
    assert (
        "Any output reserve below the approved `2048`-token minimum blocks live immediately."
        in abort_conditions
    )
    assert "/v1/responses long-context route is blocked by 16k `internal_error`" in abort_conditions
    assert (
        "generation_allowed, live_25k_authorized, production_default, wvm_runtime_integration, and kv_reuse_proven must all remain false"
        in abort_conditions
    )

    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (
        "No live LM Studio HTTP, native endpoints, OpenAI-compatible endpoints, load, unload, or generation calls were made."
        in report_text
    )
    assert "25k live remains blocked." in report_text
    assert "Responses long-context status: `blocked_long_context_internal_error`." in report_text
    assert (
        "Recommended next step: no-live tokenization and mode review only; not a production or live authorization."
        in report_text
    )

    all_artifact_text = "\n".join(
        (tmp_path / file_name).read_text(encoding="utf-8") for file_name in expected_files
    )
    assert PRIVATE_CONTENT_SENTINEL not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert "http://127.0.0.1:1234" not in all_artifact_text
    assert "state_id" not in all_artifact_text.lower()
    assert "[REDACTED]" not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text


@pytest.mark.parametrize(
    "field_name",
    [
        "generation_allowed",
        "live_25k_authorized",
        "production_default",
        "wvm_runtime_integration",
        "kv_reuse_proven",
    ],
)
def test_run_l3_6_25k_no_live_preflight_rejects_true_safety_flags(
    tmp_path: Path,
    field_name: str,
) -> None:
    payload = _load_l3_6_25k_no_live_preflight_config_payload()
    payload["safety"][field_name] = True
    config_path = _write_l3_6_25k_no_live_preflight_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(
        ValueError,
        match=rf"safety\.{field_name} must be exactly false",
    ):
        runner.run_l3_6_25k_no_live_preflight(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="l3-6-25k-invalid",
        )


def test_run_l3_6a_25k_tokenization_prompt_fit_writes_expected_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    transport = _QueueTransport({})
    runner = ManagedLabRunner(transport, system_sampler=fake_sampler)

    original_live_loader = managed_runner_module.load_live_smoke_config
    original_model_operation = managed_runner_module.run_exact_model_operation
    original_live_transport = managed_runner_module._default_live_transport
    original_live_streaming_transport = managed_runner_module._default_live_streaming_transport
    managed_runner_module.load_live_smoke_config = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live config loader must not be used")
    )
    managed_runner_module.run_exact_model_operation = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("native lifecycle helpers must not be used")
    )
    managed_runner_module._default_live_transport = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live transport must not be used")
    )
    managed_runner_module._default_live_streaming_transport = lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("live streaming transport must not be used"))
    try:
        summary = runner.run_l3_6a_25k_tokenization_prompt_fit(
            config_path=_l3_6a_25k_tokenization_prompt_fit_config_path(),
            run_dir=tmp_path,
            run_id="l3-6a-25k-tokenization-prompt-fit",
        )
    finally:
        managed_runner_module.load_live_smoke_config = original_live_loader
        managed_runner_module.run_exact_model_operation = original_model_operation
        managed_runner_module._default_live_transport = original_live_transport
        managed_runner_module._default_live_streaming_transport = original_live_streaming_transport

    assert fake_sampler.start_calls == 0
    assert fake_sampler.stop_calls == 0
    assert transport.requests == []

    assert summary == {
        "schema_version": managed_runner_module.SCHEMA_VERSION,
        "run_id": "l3-6a-25k-tokenization-prompt-fit",
        "experiment_id": "l3_6a_25k_tokenization_prompt_fit_gemma4_e2b",
        "mode": "tokenization_prompt_fit_no_live",
        "model_key": "gemma4_e2b_q4km",
        "model_id": "google/gemma-4-e2b",
        "dataset_id": "lecture_25k_tokens",
        "target_context_length": 32768,
        "artifact_count": 7,
        "exact_tokenization_status": "pending_no_live",
        "chat_template_tokenization_status": "pending_no_live",
        "safety_margin_tokens": 804,
        "minimum_approved_safety_margin_tokens": 2048,
        "current_output_reserve_tokens": 2048,
        "minimum_output_reserve_tokens": 2048,
        "margin_status": "blocked_high_risk_below_minimum_threshold",
        "prompt_minimization_required": True,
        "live_authorization_status": "blocked_pending_exact_tokenization_and_margin_threshold",
        "privacy_scan_status": "pass",
        "measurement_status": "not_measured_no_live",
        "kv_reuse_proven": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "managed_live": False,
        "network": False,
        "lmstudio_api_called": False,
        "load_called": False,
        "unload_called": False,
        "generation_allowed": False,
        "generation_called": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }

    expected_files = {
        "tokenization_strategy_report.md",
        "token_budget_breakdown.json",
        "chat_template_overhead_report.json",
        "prompt_minimization_candidates.md",
        "output_reserve_policy.json",
        "l3_6a_report.md",
        "privacy_scan.json",
    }
    assert expected_files == {path.name for path in tmp_path.iterdir()}

    token_budget_breakdown = json.loads(
        (tmp_path / "token_budget_breakdown.json").read_text(encoding="utf-8")
    )
    assert token_budget_breakdown["experiment_id"] == "l3_6a_25k_tokenization_prompt_fit_gemma4_e2b"
    assert token_budget_breakdown["mode"] == "tokenization_prompt_fit_no_live"
    assert token_budget_breakdown["current_heuristic_estimate"] == {
        "source": "dataset_manifest_static_estimate",
        "required_tokens": 27048,
        "budget_tokens": 27852,
        "assumed_chat_template_overhead_tokens": 0,
        "output_reserve_tokens": 2048,
        "remaining_safety_margin_tokens": 804,
    }
    assert token_budget_breakdown["estimated_overhead_scenario"] == {
        "chat_template_overhead_tokens": 512,
        "required_tokens": 27560,
        "remaining_safety_margin_tokens": 292,
        "threshold_met": False,
        "status": "blocked_high_risk_below_minimum_threshold",
        "measurement_kind": "no_live_estimate",
    }
    assert token_budget_breakdown["conservative_overhead_scenario"] == {
        "chat_template_overhead_tokens": 1024,
        "required_tokens": 28072,
        "remaining_safety_margin_tokens": -220,
        "threshold_met": False,
        "status": "blocked_over_budget",
        "measurement_kind": "no_live_conservative_estimate",
    }
    assert token_budget_breakdown["exact_tokenizer"] == {
        "status": "pending_no_live",
        "tokenizer_available": False,
        "blocks_live": True,
        "reason": "Exact tokenizer measurement is not available in this no-live slice.",
    }
    assert token_budget_breakdown["chat_template_tokenization"] == {
        "status": "pending_no_live",
        "exact_measurement_available": False,
        "assumed_overhead_tokens": 0,
        "assumption_status": "placeholder_only_not_approved",
        "blocks_live": True,
    }
    assert token_budget_breakdown["remaining_safety_margin"] == {
        "tokens": 804,
        "minimum_approved_safety_margin_tokens": 2048,
        "threshold_met": False,
        "status": "blocked_high_risk_below_minimum_threshold",
    }
    assert token_budget_breakdown["live_authorization"] == {
        "status": "blocked_pending_exact_tokenization_and_margin_threshold",
        "heuristic_fit_can_authorize_live": False,
        "exact_tokenization_required": True,
        "chat_template_tokenization_required": True,
        "minimization_required": True,
        "live_25k_authorized": False,
    }
    assert (
        token_budget_breakdown["mode_plan"]["compact_memory"]["route_status"] == "primary_candidate"
    )
    assert (
        token_budget_breakdown["mode_plan"]["native_chat_stateful"]["route_status"]
        == "research_latency_candidate"
    )
    assert (
        token_budget_breakdown["mode_plan"]["native_chat_stateful"]["endpoint_path"]
        == "/api/v1/chat"
    )
    assert (
        token_budget_breakdown["mode_plan"]["stateless_full_prefix"]["route_status"] == "baseline"
    )
    assert (
        token_budget_breakdown["mode_plan"]["responses"]["route_status"]
        == "blocked_long_context_internal_error"
    )
    assert token_budget_breakdown["mode_plan"]["responses"]["endpoint_path"] == "/v1/responses"
    assert token_budget_breakdown["generation_allowed"] is False
    assert token_budget_breakdown["generation_called"] is False
    assert token_budget_breakdown["live_25k_authorized"] is False
    assert token_budget_breakdown["production_default"] is False
    assert token_budget_breakdown["wvm_runtime_integration"] is False
    assert token_budget_breakdown["kv_reuse_proven"] is False

    chat_template_overhead_report = json.loads(
        (tmp_path / "chat_template_overhead_report.json").read_text(encoding="utf-8")
    )
    assert (
        chat_template_overhead_report["exact_chat_template_tokenization_status"]
        == "pending_no_live"
    )
    assert chat_template_overhead_report["exact_tokenizer_status"] == "pending_no_live"
    assert chat_template_overhead_report["estimated_chat_template_overhead_tokens"] == 512
    assert chat_template_overhead_report["conservative_chat_template_overhead_tokens"] == 1024
    assert (
        chat_template_overhead_report["estimate_kind"]
        == "no_live_estimate_only_not_exact_measurement"
    )
    assert chat_template_overhead_report["current_heuristic_margin_tokens"] == 804
    assert chat_template_overhead_report["estimated_margin_tokens"] == 292
    assert chat_template_overhead_report["conservative_margin_tokens"] == -220
    assert (
        chat_template_overhead_report["estimated_margin_status"]
        == "blocked_high_risk_below_minimum_threshold"
    )
    assert chat_template_overhead_report["conservative_margin_status"] == "blocked_over_budget"
    assert (
        chat_template_overhead_report["margin_status"]
        == "blocked_high_risk_below_minimum_threshold"
    )
    assert chat_template_overhead_report["live_authorization_status"] == (
        "blocked_pending_exact_tokenization_and_margin_threshold"
    )
    assert chat_template_overhead_report["minimization_required"] is True
    assert chat_template_overhead_report["generation_allowed"] is False
    assert chat_template_overhead_report["generation_called"] is False
    assert chat_template_overhead_report["live_25k_authorized"] is False
    assert chat_template_overhead_report["production_default"] is False
    assert chat_template_overhead_report["wvm_runtime_integration"] is False
    assert chat_template_overhead_report["kv_reuse_proven"] is False

    output_reserve_policy = json.loads(
        (tmp_path / "output_reserve_policy.json").read_text(encoding="utf-8")
    )
    assert output_reserve_policy["current_output_reserve_tokens"] == 2048
    assert output_reserve_policy["minimum_approved_output_reserve_tokens"] == 2048
    assert output_reserve_policy["reserve_status"] == "meets_minimum_threshold_exactly"
    assert output_reserve_policy["shrink_below_minimum_blocked"] is True
    assert output_reserve_policy["remaining_safety_margin_tokens"] == 804
    assert output_reserve_policy["minimum_approved_safety_margin_tokens"] == 2048
    assert output_reserve_policy["margin_status"] == "blocked_high_risk_below_minimum_threshold"
    assert output_reserve_policy["generation_allowed"] is False
    assert output_reserve_policy["generation_called"] is False
    assert output_reserve_policy["live_25k_authorized"] is False
    assert output_reserve_policy["production_default"] is False
    assert output_reserve_policy["wvm_runtime_integration"] is False
    assert output_reserve_policy["kv_reuse_proven"] is False

    privacy_scan = json.loads((tmp_path / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": [
            "tokenization_strategy_report.md",
            "token_budget_breakdown.json",
            "chat_template_overhead_report.json",
            "prompt_minimization_candidates.md",
            "output_reserve_policy.json",
            "l3_6a_report.md",
            "privacy_scan.json",
        ],
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }

    tokenization_strategy_report = (tmp_path / "tokenization_strategy_report.md").read_text(
        encoding="utf-8"
    )
    assert (
        "Exact tokenizer measurement: `pending_no_live`; heuristic fit cannot authorize live."
        in tokenization_strategy_report
    )
    assert (
        "Estimated no-live chat-template overhead scenario: `512` tokens -> required `27560`, remaining margin `292`."
        in tokenization_strategy_report
    )
    assert (
        "Conservative no-live chat-template overhead scenario: `1024` tokens -> required `28072`, remaining margin `-220`."
        in tokenization_strategy_report
    )
    assert (
        "The current 804-token margin becomes much smaller under the estimated overhead scenario and can go negative under the conservative scenario."
        in tokenization_strategy_report
    )
    assert (
        "Prompt minimization is required before any future live consideration."
        in tokenization_strategy_report
    )
    assert (
        "Live authorization status: blocked pending exact tokenization, pending chat-template tokenization, and below-threshold margin."
        in tokenization_strategy_report
    )

    prompt_minimization_candidates = (tmp_path / "prompt_minimization_candidates.md").read_text(
        encoding="utf-8"
    )
    assert (
        "Outcome: prompt minimization required before any live long-context attempt."
        in prompt_minimization_candidates
    )
    assert (
        "With the estimated no-live overhead scenario the remaining margin drops to `292` tokens."
        in prompt_minimization_candidates
    )
    assert (
        "With the conservative no-live overhead scenario the remaining margin drops to `-220` tokens, which is over budget."
        in prompt_minimization_candidates
    )
    assert "compact-memory routing as the primary candidate" in prompt_minimization_candidates

    report_text = (tmp_path / "l3_6a_report.md").read_text(encoding="utf-8")
    assert "Estimated overhead scenario: `512` tokens -> remaining margin `292`." in report_text
    assert (
        "Conservative overhead scenario: `1024` tokens -> remaining margin `-220`." in report_text
    )
    assert (
        "The current 804-token margin becomes much smaller under the estimated overhead scenario and can go negative under the conservative scenario."
        in report_text
    )
    assert (
        "Live authorization remains blocked; heuristic fit never authorizes live while exact tokenization is pending."
        in report_text
    )
    assert "Likely honest outcome: prompt minimization required and live blocked." in report_text
    assert "responses route: `blocked_long_context_internal_error`." in report_text

    all_artifact_text = "\n".join(
        (tmp_path / file_name).read_text(encoding="utf-8") for file_name in expected_files
    )
    assert PRIVATE_CONTENT_SENTINEL not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert "http://127.0.0.1:1234" not in all_artifact_text
    assert "state_id" not in all_artifact_text.lower()
    assert "C:\\" not in all_artifact_text


@pytest.mark.parametrize(
    "field_name",
    [
        "generation_allowed",
        "generation_called",
        "live_25k_authorized",
        "production_default",
        "wvm_runtime_integration",
        "kv_reuse_proven",
    ],
)
def test_run_l3_6a_25k_tokenization_prompt_fit_rejects_true_safety_flags(
    tmp_path: Path,
    field_name: str,
) -> None:
    payload = _load_l3_6a_25k_tokenization_prompt_fit_config_payload()
    payload["safety"][field_name] = True
    config_path = _write_l3_6a_25k_tokenization_prompt_fit_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(
        ValueError,
        match=rf"safety\.{field_name} must be exactly false",
    ):
        runner.run_l3_6a_25k_tokenization_prompt_fit(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="l3-6a-invalid",
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload.__setitem__(
                "model",
                {"key": "gemma4_e4b_q4km", "lmstudio_model_id": "google/gemma-4-12b-qat"},
            ),
            "model.key 'gemma4_12b_qat'",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_tiers", [8192]),
            r"load.context_tiers=\[8192, 16384\]",
        ),
        (
            lambda payload: payload.__setitem__("allow_remote", True),
            "allow_remote=false",
        ),
    ],
)
def test_run_l3_9c_gemma4_12b_qat_load_only_8k_16k_rejects_invalid_contracts(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_9c_gemma4_12b_qat_load_only_config_payload()
    mutator(payload)
    config_path = _write_l3_9c_gemma4_12b_qat_load_only_config(tmp_path, payload)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_l3_9c_gemma4_12b_qat_load_only_8k_16k(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-9c-invalid",
            run_id="l3-9c-invalid",
        )


def test_run_l3_9c_gemma4_12b_qat_load_only_8k_16k_runs_two_tiers_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_9c_gemma4_12b_qat_load_only_config_path()
    native_calls, native_transport = _native_transport_for_l3_8b_gemma4_e4b_load_only(
        raw_instance_ids=("raw-instance-l3-9c-8k", "raw-instance-l3-9c-16k"),
        model_id="google/gemma-4-12b-qat",
        context_tiers=(8192, 16_384),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_9c_gemma4_12b_qat_load_only_8k_16k(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-9c",
        run_id="l3-9c-gemma4-12b-qat-load-only",
        providers={
            "lmstudio_local": "managed_l3_9c_gemma4_12b_qat_load_only_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
    )

    run_dir = tmp_path / "run-l3-9c"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "candidate_load_only_8k_16k"
    assert summary["decision"] == "load_only_passed"
    assert summary["load_context_tiers"] == [8192, 16_384]
    assert summary["load_tiers_passed_count"] == 2
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["generation_called"] is False
    assert summary["chat_called"] is False
    assert summary["responses_called"] is False
    assert summary["chat_completions_called"] is False
    assert summary["privacy_scan_status"] == "pass"

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert all("/api/v1/chat" not in url for _method, url, _data in native_calls)
    assert all("/v1/chat/completions" not in url for _method, url, _data in native_calls)
    assert all("/v1/responses" not in url for _method, url, _data in native_calls)

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["model_key"] == "gemma4_12b_qat"
    assert run_config["model_id"] == "google/gemma-4-12b-qat"
    assert run_config["load_context_tiers"] == [8192, 16_384]
    assert run_config["allow_remote"] is False
    assert "generation" not in run_config

    load_attempts = _read_jsonl(run_dir / "load_attempts.jsonl")
    assert len(load_attempts) == 2
    assert [row["requested_context_length"] for row in load_attempts] == [8192, 16_384]
    assert {row["decision"] for row in load_attempts} == {"load_only_passed"}
    assert {row["cleanup_verified"] for row in load_attempts} == {True}
    assert {row["final_loaded_instances"] for row in load_attempts} == {0}
    assert {row["generation_called"] for row in load_attempts} == {False}
    assert {row["chat_called"] for row in load_attempts} == {False}
    assert {row["responses_called"] for row in load_attempts} == {False}
    assert {row["chat_completions_called"] for row in load_attempts} == {False}

    load_responses = _read_jsonl(run_dir / "load_response_sanitized.jsonl")
    assert len(load_responses) == 2
    assert [row["status"] for row in load_responses] == ["loaded", "loaded"]
    assert [row["load_config"]["context_length"] for row in load_responses] == [8192, 16_384]

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert (
        privacy_scan["scan_scope"] == "candidate_load_only_8k_16k_raw_url_path_private_value_scan"
    )

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# LM Studio Lab L3.9c Gemma4 12B QAT Load-Only 8k/16k Report" in report_text
    assert "| final_loaded_instances | `0` |" in report_text
    assert (
        "not production default, not host application runtime integration, no live generation"
        in report_text
    )

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-l3-9c-8k",
        "raw-instance-l3-9c-16k",
        "/api/v1/chat",
        "/v1/chat/completions",
        "/v1/responses",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload.__setitem__(
                "model",
                {
                    "key": "gemma4_12b_qat",
                    "lmstudio_model_id": "google/gemma-4-26b-a4b-qat",
                },
            ),
            "model.key 'gemma4_26b_a4b_qat'",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_tiers", [8192, 16_384]),
            r"load.context_tiers=\[8192\]",
        ),
        (
            lambda payload: payload["safety"].__setitem__("production_default", True),
            "production_default=false",
        ),
    ],
)
def test_run_l3_9d_gemma4_26b_a4b_qat_load_only_8k_rejects_invalid_contracts(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_9d_gemma4_26b_a4b_qat_load_only_config_payload()
    mutator(payload)
    config_path = _write_l3_9d_gemma4_26b_a4b_qat_load_only_config(tmp_path, payload)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_l3_9d_gemma4_26b_a4b_qat_load_only_8k(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-9d-invalid",
            run_id="l3-9d-invalid",
        )


def test_run_l3_9d_gemma4_26b_a4b_qat_load_only_8k_runs_one_tier_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_9d_gemma4_26b_a4b_qat_load_only_config_path()
    native_calls, native_transport = _native_transport_for_load_only_smoke(
        "raw-instance-l3-9d-8k",
        model_id="google/gemma-4-26b-a4b-qat",
        context_length=8192,
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_9d_gemma4_26b_a4b_qat_load_only_8k(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-9d",
        run_id="l3-9d-gemma4-26b-a4b-qat-load-only",
        providers={
            "lmstudio_local": "managed_l3_9d_gemma4_26b_a4b_load_only_test",
            "support_ref": PRIVATE_PROVIDER_URL,
        },
        native_transport=native_transport,
    )

    run_dir = tmp_path / "run-l3-9d"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "candidate_load_only_8k"
    assert summary["decision"] == "load_only_passed"
    assert summary["load_context_tiers"] == [8192]
    assert summary["load_tiers_passed_count"] == 1
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["generation_called"] is False
    assert summary["chat_called"] is False
    assert summary["responses_called"] is False
    assert summary["chat_completions_called"] is False
    assert summary["privacy_scan_status"] == "pass"

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert all("/api/v1/chat" not in url for _method, url, _data in native_calls)
    assert all("/v1/chat/completions" not in url for _method, url, _data in native_calls)
    assert all("/v1/responses" not in url for _method, url, _data in native_calls)

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["model_key"] == "gemma4_26b_a4b_qat"
    assert run_config["model_id"] == "google/gemma-4-26b-a4b-qat"
    assert run_config["load_context_tiers"] == [8192]
    assert run_config["allow_remote"] is False
    assert "generation" not in run_config

    load_attempts = _read_jsonl(run_dir / "load_attempts.jsonl")
    assert len(load_attempts) == 1
    assert load_attempts[0]["requested_context_length"] == 8192
    assert load_attempts[0]["decision"] == "load_only_passed"
    assert load_attempts[0]["cleanup_verified"] is True
    assert load_attempts[0]["final_loaded_instances"] == 0
    assert load_attempts[0]["generation_called"] is False
    assert load_attempts[0]["chat_called"] is False
    assert load_attempts[0]["responses_called"] is False
    assert load_attempts[0]["chat_completions_called"] is False

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["scan_scope"] == "candidate_load_only_8k_raw_url_path_private_value_scan"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# LM Studio Lab L3.9d Gemma4 26B A4B QAT Load-Only 8k Report" in report_text
    assert "| final_loaded_instances | `0` |" in report_text
    assert "load-only: no inference, no native chat, no responses" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-l3-9d-8k",
        "/api/v1/chat",
        "/v1/chat/completions",
        "/v1/responses",
        PRIVATE_PROVIDER_URL,
    ):
        assert forbidden not in all_artifact_text


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["approval_thresholds"].__setitem__(
                "minimum_approved_safety_margin_tokens", 1024
            ),
            r"approval_thresholds\.minimum_approved_safety_margin_tokens must be exactly 2048",
        ),
        (
            lambda payload: payload["approval_thresholds"].__setitem__(
                "minimum_output_reserve_tokens", 1024
            ),
            r"approval_thresholds\.minimum_output_reserve_tokens must be exactly 2048",
        ),
        (
            lambda payload: payload["heuristic_fit"].__setitem__("output_reserve_tokens", 1024),
            r"heuristic_fit\.output_reserve_tokens must be exactly 2048",
        ),
        (
            lambda payload: payload["heuristic_fit"].__setitem__(
                "expected_remaining_safety_margin_tokens", 2048
            ),
            r"heuristic_fit\.expected_remaining_safety_margin_tokens must match the computed heuristic",
        ),
        (
            lambda payload: payload["overhead_assumptions"].__setitem__(
                "estimated_chat_template_overhead_tokens", 256
            ),
            r"overhead_assumptions\.estimated_chat_template_overhead_tokens must be exactly 512",
        ),
        (
            lambda payload: payload["overhead_assumptions"].__setitem__(
                "conservative_chat_template_overhead_tokens", 768
            ),
            r"overhead_assumptions\.conservative_chat_template_overhead_tokens must be exactly 1024",
        ),
    ],
)
def test_run_l3_6a_25k_tokenization_prompt_fit_rejects_invalid_thresholds_or_reserve(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_6a_25k_tokenization_prompt_fit_config_payload()
    mutator(payload)
    config_path = _write_l3_6a_25k_tokenization_prompt_fit_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(ValueError, match=message):
        runner.run_l3_6a_25k_tokenization_prompt_fit(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="l3-6a-invalid-threshold",
        )


def test_run_l3_6b_25k_prompt_minimization_writes_expected_artifacts(tmp_path: Path) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    transport = _QueueTransport({})
    runner = ManagedLabRunner(transport, system_sampler=fake_sampler)

    original_live_loader = managed_runner_module.load_live_smoke_config
    original_model_operation = managed_runner_module.run_exact_model_operation
    original_live_transport = managed_runner_module._default_live_transport
    original_live_streaming_transport = managed_runner_module._default_live_streaming_transport
    managed_runner_module.load_live_smoke_config = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live config loader must not be used")
    )
    managed_runner_module.run_exact_model_operation = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("native lifecycle helpers must not be used")
    )
    managed_runner_module._default_live_transport = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("live transport must not be used")
    )
    managed_runner_module._default_live_streaming_transport = lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("live streaming transport must not be used"))
    try:
        summary = runner.run_l3_6b_25k_prompt_minimization(
            config_path=_l3_6b_25k_prompt_minimization_config_path(),
            run_dir=tmp_path,
            run_id="l3-6b-25k-prompt-minimization",
        )
    finally:
        managed_runner_module.load_live_smoke_config = original_live_loader
        managed_runner_module.run_exact_model_operation = original_model_operation
        managed_runner_module._default_live_transport = original_live_transport
        managed_runner_module._default_live_streaming_transport = original_live_streaming_transport

    assert fake_sampler.start_calls == 0
    assert fake_sampler.stop_calls == 0
    assert transport.requests == []

    assert summary == {
        "schema_version": managed_runner_module.SCHEMA_VERSION,
        "run_id": "l3-6b-25k-prompt-minimization",
        "experiment_id": "l3_6b_25k_prompt_minimization_gemma4_e2b",
        "mode": "prompt_minimization_no_live",
        "model_key": "gemma4_e2b_q4km",
        "model_id": "google/gemma-4-e2b",
        "dataset_id": "lecture_25k_tokens",
        "target_context_length": 32768,
        "artifact_count": 6,
        "exact_tokenization_status": "pending_no_live",
        "chat_template_tokenization_status": "pending_no_live",
        "baseline_margin_tokens": 804,
        "minimized_input_estimate_tokens": 22700,
        "estimated_reduction_tokens": 2300,
        "output_reserve_tokens": 2048,
        "no_overhead_margin_tokens": 3104,
        "estimated_overhead_margin_tokens": 2592,
        "conservative_overhead_margin_tokens": 2080,
        "estimated_overhead_threshold_met": True,
        "conservative_overhead_threshold_met": True,
        "live_authorization_status": "blocked_pending_exact_tokenization_and_chat_template_measurement",
        "privacy_scan_status": "pass",
        "measurement_status": "not_measured_no_live",
        "kv_reuse_proven": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "managed_live": False,
        "network": False,
        "lmstudio_api_called": False,
        "load_called": False,
        "unload_called": False,
        "generation_allowed": False,
        "generation_called": False,
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
    }

    expected_files = {
        "minimized_prompt_shape_report.md",
        "minimized_token_budget_breakdown.json",
        "prompt_diff_summary.md",
        "updated_abort_conditions.md",
        "l3_6b_report.md",
        "privacy_scan.json",
    }
    assert expected_files == {path.name for path in tmp_path.iterdir()}

    minimized_token_budget_breakdown = json.loads(
        (tmp_path / "minimized_token_budget_breakdown.json").read_text(encoding="utf-8")
    )
    assert (
        minimized_token_budget_breakdown["experiment_id"]
        == "l3_6b_25k_prompt_minimization_gemma4_e2b"
    )
    assert minimized_token_budget_breakdown["mode"] == "prompt_minimization_no_live"
    assert minimized_token_budget_breakdown["baseline_snapshot"] == {
        "source": "l3_6a_accepted_snapshot",
        "estimated_input_tokens": 25000,
        "required_tokens": 27048,
        "budget_tokens": 27852,
        "remaining_safety_margin_tokens": 804,
        "estimated_overhead_margin_tokens": 292,
        "conservative_overhead_margin_tokens": -220,
        "risk_status": "b_c_risk_live_blocked",
    }
    assert minimized_token_budget_breakdown["minimized_estimate"] == {
        "estimated_input_tokens": 22700,
        "estimated_reduction_tokens": 2300,
        "required_tokens": 24748,
        "budget_tokens": 27852,
        "output_reserve_tokens": 2048,
        "remaining_safety_margin_tokens": 3104,
        "threshold_met": True,
        "status": "approved_margin_threshold_met",
        "measurement_kind": "no_live_minimized_estimate",
    }
    assert minimized_token_budget_breakdown["estimated_overhead_scenario"] == {
        "chat_template_overhead_tokens": 512,
        "required_tokens": 25260,
        "remaining_safety_margin_tokens": 2592,
        "threshold_met": True,
        "status": "approved_margin_threshold_met",
        "measurement_kind": "no_live_estimate",
    }
    assert minimized_token_budget_breakdown["conservative_overhead_scenario"] == {
        "chat_template_overhead_tokens": 1024,
        "required_tokens": 25772,
        "remaining_safety_margin_tokens": 2080,
        "threshold_met": True,
        "status": "approved_margin_threshold_met",
        "measurement_kind": "no_live_conservative_estimate",
    }
    assert minimized_token_budget_breakdown["output_reserve"] == {
        "current_output_reserve_tokens": 2048,
        "minimum_approved_output_reserve_tokens": 2048,
        "threshold_met": True,
        "shrink_below_minimum_blocked": True,
    }
    assert minimized_token_budget_breakdown["live_authorization"] == {
        "status": "blocked_pending_exact_tokenization_and_chat_template_measurement",
        "heuristic_minimization_target_reached": True,
        "exact_tokenization_required": True,
        "chat_template_tokenization_required": True,
        "privacy_scan_required": True,
        "live_25k_authorized": False,
    }
    assert minimized_token_budget_breakdown["minimized_estimate"]["output_reserve_tokens"] >= 2048
    assert (
        minimized_token_budget_breakdown["estimated_overhead_scenario"][
            "remaining_safety_margin_tokens"
        ]
        >= 2048
    )
    assert (
        minimized_token_budget_breakdown["conservative_overhead_scenario"][
            "remaining_safety_margin_tokens"
        ]
        >= 2048
    )
    assert (
        minimized_token_budget_breakdown["mode_plan"]["compact_memory"]["route_status"]
        == "primary_candidate"
    )
    assert (
        minimized_token_budget_breakdown["mode_plan"]["native_chat_stateful"]["route_status"]
        == "research_latency_candidate"
    )
    assert (
        minimized_token_budget_breakdown["mode_plan"]["native_chat_stateful"]["endpoint_path"]
        == "/api/v1/chat"
    )
    assert (
        minimized_token_budget_breakdown["mode_plan"]["stateless_full_prefix"]["route_status"]
        == "baseline"
    )
    assert (
        minimized_token_budget_breakdown["mode_plan"]["responses"]["route_status"]
        == "blocked_long_context_internal_error"
    )
    assert (
        minimized_token_budget_breakdown["mode_plan"]["responses"]["endpoint_path"]
        == "/v1/responses"
    )
    assert (
        minimized_token_budget_breakdown["mode_plan"]["qwen_structured"]["route_status"]
        == "blocked_recovery_only"
    )
    assert minimized_token_budget_breakdown["generation_allowed"] is False
    assert minimized_token_budget_breakdown["generation_called"] is False
    assert minimized_token_budget_breakdown["live_25k_authorized"] is False
    assert minimized_token_budget_breakdown["production_default"] is False
    assert minimized_token_budget_breakdown["wvm_runtime_integration"] is False
    assert minimized_token_budget_breakdown["kv_reuse_proven"] is False

    privacy_scan = json.loads((tmp_path / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scanned_artifacts": [
            "minimized_prompt_shape_report.md",
            "minimized_token_budget_breakdown.json",
            "prompt_diff_summary.md",
            "updated_abort_conditions.md",
            "l3_6b_report.md",
            "privacy_scan.json",
        ],
        "raw_prompt_response_stored": False,
        "raw_material_stored": False,
        "generation_allowed": False,
        "generation_called": False,
        "live_25k_authorized": False,
        "production_default": False,
        "wvm_runtime_integration": False,
        "kv_reuse_proven": False,
    }

    minimized_prompt_shape_report = (tmp_path / "minimized_prompt_shape_report.md").read_text(
        encoding="utf-8"
    )
    assert (
        "Minimized input estimate: `22700` tokens (reduction `2300`)."
        in minimized_prompt_shape_report
    )
    assert "compact_memory remains `primary_candidate`." in minimized_prompt_shape_report
    assert (
        "Responses remains `blocked_long_context_internal_error`." in minimized_prompt_shape_report
    )
    assert (
        "No live calls, generation, load, unload, or queue/runtime integration occurred"
        in minimized_prompt_shape_report
    )

    prompt_diff_summary = (tmp_path / "prompt_diff_summary.md").read_text(encoding="utf-8")
    assert "Minimized categories only; no raw prompt text is stored." in prompt_diff_summary
    assert "duplicate schema/instruction text" in prompt_diff_summary
    assert "system prompt prose" in prompt_diff_summary
    assert "root metadata labels" in prompt_diff_summary
    assert "branch instructions" in prompt_diff_summary
    assert "diagnostic prose" in prompt_diff_summary
    assert "verbose wrappers" in prompt_diff_summary

    updated_abort_conditions = (tmp_path / "updated_abort_conditions.md").read_text(
        encoding="utf-8"
    )
    assert (
        "Exact tokenizer measurement is still pending (`pending_no_live`)."
        in updated_abort_conditions
    )
    assert (
        "Chat-template tokenization is still pending (`pending_no_live`)."
        in updated_abort_conditions
    )
    assert "Privacy scan must pass for all L3.6b artifacts." in updated_abort_conditions
    assert "`/v1/responses` remains blocked for long-context routing" in updated_abort_conditions
    assert "heuristic scenarios alone do not authorize live" in updated_abort_conditions
    assert (
        "improves to `2592` and conservative overhead margin improves to `2080`"
        in updated_abort_conditions
    )

    report_text = (tmp_path / "l3_6b_report.md").read_text(encoding="utf-8")
    assert (
        "Honest outcome: no-live prompt minimization target reached for heuristic scenarios."
        in report_text
    )
    assert "Estimated overhead scenario margin: `2592` (>= `2048`)." in report_text
    assert (
        "Conservative overhead scenario margin: `2080` (no longer over budget and still >= `2048`)."
        in report_text
    )
    assert (
        "Live remains blocked due exact tokenizer and chat-template tokenization pending"
        in report_text
    )
    assert "responses route: `blocked_long_context_internal_error`." in report_text

    all_artifact_text = "\n".join(
        (tmp_path / file_name).read_text(encoding="utf-8") for file_name in expected_files
    )
    assert PRIVATE_CONTENT_SENTINEL not in all_artifact_text
    assert PRIVATE_PROVIDER_URL not in all_artifact_text
    assert PRIVATE_PROVIDER_PATH not in all_artifact_text
    assert "http://127.0.0.1:1234" not in all_artifact_text
    assert "state_id" not in all_artifact_text.lower()
    assert "C:\\" not in all_artifact_text


@pytest.mark.parametrize(
    "field_name",
    [
        "generation_allowed",
        "generation_called",
        "live_25k_authorized",
        "production_default",
        "wvm_runtime_integration",
        "kv_reuse_proven",
    ],
)
def test_run_l3_6b_25k_prompt_minimization_rejects_true_safety_flags(
    tmp_path: Path,
    field_name: str,
) -> None:
    payload = _load_l3_6b_25k_prompt_minimization_config_payload()
    payload["safety"][field_name] = True
    config_path = _write_l3_6b_25k_prompt_minimization_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(
        ValueError,
        match=rf"safety\.{field_name} must be exactly false",
    ):
        runner.run_l3_6b_25k_prompt_minimization(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="l3-6b-invalid",
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["approval_thresholds"].__setitem__(
                "minimum_approved_safety_margin_tokens", 1024
            ),
            r"approval_thresholds\.minimum_approved_safety_margin_tokens must be exactly 2048",
        ),
        (
            lambda payload: payload["approval_thresholds"].__setitem__(
                "minimum_output_reserve_tokens", 1024
            ),
            r"approval_thresholds\.minimum_output_reserve_tokens must be exactly 2048",
        ),
        (
            lambda payload: payload["minimized_prompt"].__setitem__(
                "estimated_input_tokens", 23000
            ),
            r"minimized_prompt\.estimated_input_tokens must be exactly 22700",
        ),
        (
            lambda payload: payload["minimized_prompt"].__setitem__("output_reserve_tokens", 1024),
            r"minimized_prompt\.output_reserve_tokens must be exactly 2048",
        ),
        (
            lambda payload: payload["minimized_prompt"].__setitem__(
                "expected_remaining_safety_margin_tokens", 3000
            ),
            r"minimized_prompt\.expected_remaining_safety_margin_tokens must match the computed minimized heuristic",
        ),
        (
            lambda payload: payload["overhead_assumptions"].__setitem__(
                "estimated_required_tokens", 25000
            ),
            r"overhead_assumptions\.estimated_required_tokens must match the computed minimized heuristic",
        ),
        (
            lambda payload: payload["overhead_assumptions"].__setitem__(
                "conservative_remaining_safety_margin_tokens", 1024
            ),
            r"overhead_assumptions\.conservative_remaining_safety_margin_tokens must match the computed minimized heuristic",
        ),
    ],
)
def test_run_l3_6b_25k_prompt_minimization_rejects_invalid_contract_values(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_6b_25k_prompt_minimization_config_payload()
    mutator(payload)
    config_path = _write_l3_6b_25k_prompt_minimization_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(ValueError, match=message):
        runner.run_l3_6b_25k_prompt_minimization(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="l3-6b-invalid-contract",
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload.__setitem__("experiment_id", "wrong_experiment"),
            "experiment_id must be exactly 'l3_5_cache_25k_no_live_prep'",
        ),
        (
            lambda payload: payload["models"][0].__setitem__("key", "gemma4_e4b_q4km"),
            r"models\[0\]\.key must be exactly 'gemma4_e2b_q4km'",
        ),
        (
            lambda payload: payload.__setitem__("datasets", ["wrong_dataset"]),
            r"datasets must be exactly \['lecture_25k_tokens'\]",
        ),
        (
            lambda payload: payload.__setitem__("modes", ["compact_memory_primary"]),
            "modes must be exactly",
        ),
        (
            lambda payload: payload["models"][0]["load"].__setitem__(
                "context_length", [8192, 16384, 32768]
            ),
            r"models\[0\]\.load\.context_length must be exactly \[8192, 16384, 32768, 65536\]",
        ),
        (
            lambda payload: payload["privacy"].__setitem__("store_root_text", True),
            r"privacy\.store_root_text must be exactly false",
        ),
        (
            lambda payload: payload.__setitem__("app_concurrency", 2),
            "app_concurrency must be exactly 1",
        ),
    ],
)
def test_run_cache_25k_no_live_prep_rejects_invalid_config(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_cache_25k_no_live_prep_config_payload()
    mutator(payload)
    config_path = _write_cache_25k_no_live_prep_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(ValueError, match=message):
        runner.run_cache_25k_no_live_prep(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="l3-5-cache-25k-invalid",
        )


def test_run_cache_stateful_live_smoke_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_3_cache_stateful_gemma4_e2b_live_smoke",
        dataset_id="cache_stateful_smoke",
        modes=("stateful_root_branches",),
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-cache-stateful-live"
    )
    stateful_calls, stateful_transport = _managed_stateful_live_smoke_transport()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_cache_stateful_live_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="cache-stateful-live-smoke",
        providers={
            "lmstudio_local": "managed_cache_live_smoke_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        stateful_transport=stateful_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "managed_runner_cache_stateful_live_smoke"
    assert summary["managed_live"] is True
    assert summary["run_id"] == "cache-stateful-live-smoke"
    assert summary["model_key"] == "gemma4_e2b_q4km"
    assert summary["model_id"] == "google/gemma-4-e2b"
    assert summary["requested_context_length"] == 8192
    assert summary["requested_parallel"] == 1
    assert summary["measurement_status"] == "functional_stateful_ok"
    assert summary["reuse_verdict"] == "kv_reuse_unproven"
    assert summary["kv_reuse_proven"] is False
    assert summary["stateful_functional_ok"] is True
    assert summary["successful_branch_count"] == 2
    assert summary["branch_count"] == 2
    assert summary["app_concurrency"] == 1
    assert summary["load_verified"] is True
    assert summary["parallel_verified"] is True
    assert summary["cleanup_status"] == "cleanup_verified"
    assert summary["cleanup_verified_count"] == 1
    assert summary["final_loaded_instances"] == 0
    assert summary["raw_prompt_response_stored"] is False

    assert [(method, url) for method, url, _data in native_calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(stateful_calls) == 3
    assert [call["url"] for call in stateful_calls] == [
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
    ]
    assert stateful_calls[1]["payload"]["previous_response_id"] == "raw-root-state-id-sentinel"
    assert stateful_calls[2]["payload"]["previous_response_id"] == "raw-root-state-id-sentinel"

    expected_files = {
        "environment.json",
        "experiment.yaml",
        "run_config.json",
        "requests.jsonl",
        "metrics.jsonl",
        "cache_summary.json",
        "privacy_scan.json",
        "report.md",
        "system_samples.jsonl",
        "system_summary.json",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    requests_rows = _read_jsonl(run_dir / "requests.jsonl")
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert len(requests_rows) == 3
    assert len(metrics_rows) == 3
    assert {row["status"] for row in requests_rows} == {"success"}
    assert {row["status"] for row in metrics_rows} == {"success"}
    assert {row["measurement_status"] for row in requests_rows} == {"functional_stateful_ok"}
    assert {row["measurement_status"] for row in metrics_rows} == {"functional_stateful_ok"}
    assert {row["reuse_verdict"] for row in requests_rows} == {"kv_reuse_unproven"}
    assert {row["reuse_verdict"] for row in metrics_rows} == {"kv_reuse_unproven"}
    assert {row["raw_prompt_response_stored"] for row in requests_rows} == {False}
    assert {row["raw_prompt_response_stored"] for row in metrics_rows} == {False}
    assert requests_rows[0]["request_kind"] == "stateful_root"
    assert requests_rows[0]["previous_state_hash"] is None
    assert requests_rows[0]["state_id_hash"].startswith("sha256:")
    assert requests_rows[0]["prompt_chars"] == 29112
    assert requests_rows[0]["estimated_input_tokens"] == 7278
    assert run_config["root_request"]["prompt_chars"] == requests_rows[0]["prompt_chars"]
    assert (
        run_config["root_request"]["estimated_input_tokens"]
        == requests_rows[0]["estimated_input_tokens"]
    )
    assert requests_rows[1]["request_kind"] == "stateful_branch"
    assert requests_rows[1]["branch_id"] == "summary_short"
    assert requests_rows[1]["used_previous_root_state"] is True
    assert requests_rows[1]["previous_state_hash"] == requests_rows[0]["state_id_hash"]
    assert requests_rows[2]["branch_id"] == "glossary_short"
    assert requests_rows[2]["used_previous_root_state"] is True
    assert {row["output_hash"].startswith("sha256:") for row in requests_rows} == {True}
    assert {row["output_hash"].startswith("sha256:") for row in metrics_rows} == {True}
    assert {row["output_chars"] > 0 for row in requests_rows} == {True}
    assert {row["output_chars"] > 0 for row in metrics_rows} == {True}

    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    assert experiment_payload["experiment_id"] == "l3_3_cache_stateful_gemma4_e2b_live_smoke"
    assert experiment_payload["lmstudio_base_url"] == "redacted_local_lmstudio_url"
    assert experiment_payload["modes"] == ["stateful_root_branches"]
    assert experiment_payload["datasets"] == ["cache_stateful_smoke"]

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "cache_stateful_live_smoke_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "environment.json",
            "experiment.yaml",
            "run_config.json",
            "requests.jsonl",
            "metrics.jsonl",
            "cache_summary.json",
            "report.md",
            "system_summary.json",
            "system_samples.jsonl",
        ],
        "raw_prompt_response_stored": False,
    }

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-cache-stateful-live",
        "raw-root-state-id-sentinel",
        "raw-summary-state-id-sentinel",
        "raw-glossary-state-id-sentinel",
        "raw-root-output-sentinel",
        "raw-summary-output-sentinel",
        "raw-glossary-output-sentinel",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text
    assert '"cache_hit": true' not in all_artifact_text
    assert '"branch_ttft_improved": true' not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text


def test_run_cache_stateful_live_smoke_keeps_partial_rows_inconclusive_on_late_branch_failure(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_3_cache_stateful_gemma4_e2b_live_smoke",
        dataset_id="cache_stateful_smoke",
        modes=("stateful_root_branches",),
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-cache-stateful-live-failure"
    )
    stateful_calls, stateful_transport = _managed_stateful_live_smoke_transport(fail_on_call=3)
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(RuntimeError, match="simulated stateful branch failure"):
        runner.run_cache_stateful_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="cache-stateful-live-smoke-failure",
            providers={
                "lmstudio_local": "managed_cache_live_smoke_test",
                "support_ref": PRIVATE_PROVIDER_URL,
                "disk_label": PRIVATE_PROVIDER_PATH,
            },
            native_transport=native_transport,
            stateful_transport=stateful_transport,
        )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert [(method, url) for method, url, _data in native_calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(stateful_calls) == 3

    requests_path = run_dir / "requests.jsonl"
    metrics_path = run_dir / "metrics.jsonl"
    requests_rows = _read_jsonl(requests_path)
    metrics_rows = _read_jsonl(metrics_path)
    assert len(requests_rows) == 2
    assert len(metrics_rows) == 2
    assert {row["status"] for row in requests_rows} == {"success"}
    assert {row["status"] for row in metrics_rows} == {"success"}
    assert {row["measurement_status"] for row in requests_rows} == {"inconclusive"}
    assert {row["measurement_status"] for row in metrics_rows} == {"inconclusive"}
    assert {row["stateful_functional_ok"] for row in requests_rows} == {False}
    assert {row["stateful_functional_ok"] for row in metrics_rows} == {False}
    assert {row["kv_reuse_proven"] for row in requests_rows} == {False}
    assert {row["kv_reuse_proven"] for row in metrics_rows} == {False}

    partial_artifact_text = "\n".join(
        (
            requests_path.read_text(encoding="utf-8"),
            metrics_path.read_text(encoding="utf-8"),
        )
    )
    for forbidden in (
        "functional_stateful_ok",
        "http://127.0.0.1:1234",
        "raw-root-state-id-sentinel",
        "raw-summary-state-id-sentinel",
        "raw-glossary-state-id-sentinel",
        "raw-root-output-sentinel",
        "raw-summary-output-sentinel",
        "raw-glossary-output-sentinel",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in partial_artifact_text
    assert '"stateful_functional_ok": true' not in partial_artifact_text
    assert '"kv_reuse_proven": true' not in partial_artifact_text
    assert '"cache_hit": true' not in partial_artifact_text
    assert '"branch_ttft_improved": true' not in partial_artifact_text


@pytest.mark.parametrize(
    ("config_kwargs", "call_kwargs", "message"),
    [
        (
            {
                "experiment_id": "l3_3_cache_stateful_gemma4_e2b_live_smoke",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches",),
                "model_key": "gemma4_e4b_q4km",
            },
            {},
            "cache/stateful live smoke requires model key 'gemma4_e2b_q4km'",
        ),
        (
            {
                "experiment_id": "l3_3_cache_stateful_gemma4_e2b_live_smoke",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches",),
                "context_length": 4096,
            },
            {},
            "cache/stateful live smoke requires context_length=8192",
        ),
        (
            {
                "experiment_id": "l3_3_cache_stateful_gemma4_e2b_live_smoke",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches",),
                "parallel": 2,
            },
            {},
            "cache/stateful live smoke requires parallel=1",
        ),
        (
            {
                "experiment_id": "l3_3_cache_stateful_gemma4_e2b_live_smoke",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("json_schema_single",),
            },
            {},
            "cache/stateful live smoke supports only stateful_root_branches",
        ),
        (
            {
                "experiment_id": "l3_3_cache_stateful_gemma4_e2b_live_smoke",
                "dataset_id": "blocks_json_medium_chunked",
                "modes": ("stateful_root_branches",),
            },
            {},
            "cache/stateful live smoke requires dataset_id 'cache_stateful_smoke'",
        ),
        (
            {
                "experiment_id": "l3_3_cache_stateful_gemma4_e2b_live_smoke",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches",),
            },
            {"app_concurrency": 2},
            "app_concurrency must be exactly 1 for L3.3 live smoke",
        ),
        (
            {
                "experiment_id": "l3_3_cache_stateful_gemma4_e2b_live_smoke",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches",),
                "store_prompt_text": True,
            },
            {},
            "privacy.store_prompt_text must remain false for live smoke",
        ),
    ],
)
def test_run_cache_stateful_live_smoke_rejects_out_of_scope_inputs(
    tmp_path: Path,
    config_kwargs: dict[str, object],
    call_kwargs: dict[str, object],
    message: str,
) -> None:
    config_path = _write_live_config(tmp_path, **config_kwargs)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_cache_stateful_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="cache-stateful-live-invalid",
            **call_kwargs,
        )


def test_run_cache_stateful_comparison_live_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
        dataset_id="cache_stateful_smoke",
        modes=("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-cache-stateful-compare-live"
    )
    clock = _ManualClock()
    monkeypatch.setattr(managed_runner_module, "_live_request_perf_counter", clock.now)
    comparison_calls, comparison_transport = _managed_cache_comparison_live_transport(clock)
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_cache_stateful_comparison_live(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="cache-stateful-compare-live",
        providers={
            "lmstudio_local": "managed_cache_compare_live_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        stateful_transport=comparison_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "managed_runner_cache_stateful_comparison_live"
    assert summary["managed_live"] is True
    assert summary["run_id"] == "cache-stateful-compare-live"
    assert summary["model_key"] == "gemma4_e2b_q4km"
    assert summary["model_id"] == "google/gemma-4-e2b"
    assert summary["requested_context_length"] == 8192
    assert summary["requested_parallel"] == 1
    assert summary["measurement_status"] == "inconclusive"
    assert summary["reuse_verdict"] == "kv_reuse_unproven"
    assert summary["kv_reuse_proven"] is False
    assert summary["stateful_functional_ok"] is True
    assert summary["root_success_count_by_mode"] == {
        "stateful_root_branches": 1,
        "stateless_full_prefix": 0,
        "compact_memory": 0,
    }
    assert summary["branch_count_by_mode"] == {
        "stateful_root_branches": 2,
        "stateless_full_prefix": 2,
        "compact_memory": 2,
    }
    assert summary["branch_success_count_by_mode"] == {
        "stateful_root_branches": 2,
        "stateless_full_prefix": 2,
        "compact_memory": 2,
    }
    assert summary["stateful_branch_avg_total_latency_ms"] == 50.0
    assert summary["stateless_full_prefix_branch_avg_total_latency_ms"] == 125.0
    assert summary["compact_memory_branch_avg_total_latency_ms"] == 60.0
    assert summary["stateless_full_prefix_vs_stateful_total_latency_ratio"] == 2.5
    assert summary["stateful_total_latency_faster_than_stateless"] is True
    assert summary["load_verified"] is True
    assert summary["parallel_verified"] is True
    assert summary["cleanup_status"] == "cleanup_verified"
    assert summary["cleanup_verified_count"] == 1
    assert summary["final_loaded_instances"] == 0
    assert summary["raw_prompt_response_stored"] is False
    assert summary["production_default"] is False

    assert [(method, url) for method, url, _data in native_calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(comparison_calls) == 7
    assert [call["url"] for call in comparison_calls] == [
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
        "http://127.0.0.1:1234/api/v1/chat",
    ]
    assert comparison_calls[1]["payload"]["previous_response_id"] == "raw-root-state-id-sentinel"
    assert comparison_calls[2]["payload"]["previous_response_id"] == "raw-root-state-id-sentinel"
    assert "previous_response_id" not in comparison_calls[3]["payload"]
    assert "previous_response_id" not in comparison_calls[5]["payload"]

    expected_files = {
        "environment.json",
        "experiment.yaml",
        "run_config.json",
        "requests.jsonl",
        "metrics.jsonl",
        "cache_comparison_summary.json",
        "privacy_scan.json",
        "report.md",
        "system_samples.jsonl",
        "system_summary.json",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    requests_rows = _read_jsonl(run_dir / "requests.jsonl")
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert len(requests_rows) == 7
    assert len(metrics_rows) == 7
    assert {row["status"] for row in requests_rows} == {"success"}
    assert {row["status"] for row in metrics_rows} == {"success"}
    assert {row["measurement_status"] for row in requests_rows} == {"inconclusive"}
    assert {row["measurement_status"] for row in metrics_rows} == {"inconclusive"}
    assert {row["reuse_verdict"] for row in requests_rows} == {"kv_reuse_unproven"}
    assert {row["reuse_verdict"] for row in metrics_rows} == {"kv_reuse_unproven"}
    assert {row["raw_prompt_response_stored"] for row in requests_rows} == {False}
    assert {row["raw_prompt_response_stored"] for row in metrics_rows} == {False}
    assert {row["kv_reuse_proven"] for row in requests_rows} == {False}
    assert {row["kv_reuse_proven"] for row in metrics_rows} == {False}
    assert {row["stateful_functional_ok"] for row in requests_rows} == {True}
    assert {row["stateful_functional_ok"] for row in metrics_rows} == {True}
    assert [row["mode"] for row in requests_rows] == [
        "stateful_root_branches",
        "stateful_root_branches",
        "stateful_root_branches",
        "stateless_full_prefix",
        "stateless_full_prefix",
        "compact_memory",
        "compact_memory",
    ]
    assert [row["total_latency_ms"] for row in requests_rows] == [
        100.0,
        40.0,
        60.0,
        120.0,
        130.0,
        55.0,
        65.0,
    ]
    assert [row["total_latency_ms"] for row in metrics_rows] == [
        100.0,
        40.0,
        60.0,
        120.0,
        130.0,
        55.0,
        65.0,
    ]
    assert requests_rows[0]["request_kind"] == "stateful_root"
    assert requests_rows[0]["previous_state_hash"] is None
    assert requests_rows[1]["request_kind"] == "stateful_branch"
    assert requests_rows[1]["branch_id"] == "summary_short"
    assert requests_rows[1]["used_previous_root_state"] is True
    assert requests_rows[1]["previous_state_hash"] == requests_rows[0]["state_id_hash"]
    assert requests_rows[3]["request_kind"] == "stateless_full_prefix_branch"
    assert requests_rows[3]["used_previous_root_state"] is False
    assert requests_rows[5]["request_kind"] == "compact_memory_branch"
    assert requests_rows[5]["compact_memory_hash"].startswith("sha256:")
    assert requests_rows[5]["estimated_memory_tokens"] is not None
    assert {row["ttft_ms"] for row in requests_rows} == {None}
    assert {row["prompt_processing_ms"] for row in requests_rows} == {None}
    assert {row["cached_tokens"] for row in requests_rows} == {None}
    assert {row["cache_proxy"] for row in requests_rows} == {None}
    assert {row["output_hash"].startswith("sha256:") for row in requests_rows} == {True}
    assert {row["output_hash"].startswith("sha256:") for row in metrics_rows} == {True}
    assert {row["output_chars"] > 0 for row in requests_rows} == {True}
    assert {row["output_chars"] > 0 for row in metrics_rows} == {True}
    assert run_config["comparison_modes"] == [
        "stateful_root_branches",
        "stateless_full_prefix",
        "compact_memory",
    ]
    assert run_config["root_request"]["prompt_hash"].startswith("sha256:")
    assert run_config["compact_memory_branch_requests"][0]["compact_memory_hash"].startswith(
        "sha256:"
    )

    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    assert experiment_payload["experiment_id"] == "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live"
    assert experiment_payload["lmstudio_base_url"] == "redacted_local_lmstudio_url"
    assert experiment_payload["modes"] == [
        "stateful_root_branches",
        "stateless_full_prefix",
        "compact_memory",
    ]
    assert experiment_payload["datasets"] == ["cache_stateful_smoke"]

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "cache_stateful_comparison_live_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "environment.json",
            "experiment.yaml",
            "run_config.json",
            "requests.jsonl",
            "metrics.jsonl",
            "cache_comparison_summary.json",
            "report.md",
            "system_summary.json",
            "system_samples.jsonl",
        ],
        "raw_prompt_response_stored": False,
    }

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-cache-stateful-compare-live",
        "raw-root-state-id-sentinel",
        "raw-stateful-summary-state-id-sentinel",
        "raw-stateful-glossary-state-id-sentinel",
        "raw-stateless-summary-state-id-sentinel",
        "raw-stateless-glossary-state-id-sentinel",
        "raw-compact-summary-state-id-sentinel",
        "raw-compact-glossary-state-id-sentinel",
        "raw-root-output-sentinel",
        "raw-stateful-summary-output-sentinel",
        "raw-stateful-glossary-output-sentinel",
        "raw-stateless-summary-output-sentinel",
        "raw-stateless-glossary-output-sentinel",
        "raw-compact-summary-output-sentinel",
        "raw-compact-glossary-output-sentinel",
        "Synthetic lecture transcript for cache/stateful lab smoke.",
        "Provide a short summary of the synthetic lecture in 3 bullet points with no extra preface.",
        "List a short glossary with 5 terms from the synthetic lecture and brief definitions.",
        "Compact memory: synthetic lecture covers queue warmup checkpoints",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text
    assert '"cache_hit": true' not in all_artifact_text
    assert '"branch_ttft_improved": true' not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text


def test_run_l3_6c_25k_compact_memory_live_smoke_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6c_25k_compact_memory_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6c-compact-memory"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_6c_compact_memory_live_smoke()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_6c_25k_compact_memory_live_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="l3-6c-compact-memory-live-smoke",
        providers={
            "lmstudio_local": "managed_l3_6c_compact_memory_live_smoke_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["decision"] == "compact_memory_live_smoke_pass"
    assert summary["mode"] == "compact_memory_controlled_live_smoke"
    assert summary["requested_context_length"] == 32768
    assert summary["applied_context_length"] == 32768
    assert summary["requested_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["app_concurrency"] == 1
    assert summary["load_verified"] is True
    assert summary["generation_called"] is True
    assert summary["request_succeeded"] is True
    assert summary["non_empty_text_pass"] is True
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["privacy_scan_status"] == "pass"
    assert summary["memory_safety_pass"] is True
    assert summary["max_ram_peak_mb"] == 131072
    assert summary["max_vram_peak_mb"] == 32768
    assert summary["production_default"] is False
    assert summary["wvm_runtime_integration"] is False
    assert summary["kv_reuse_proven"] is False
    assert summary["generation_allowed"] is True
    assert summary["live_25k_authorized"] is True
    assert summary["max_output_tokens"] == 64
    assert summary["temperature"] == 0
    assert summary["estimated_input_tokens"] == 22700
    assert summary["input_tokens"] == 22688
    assert summary["output_tokens"] == 12
    assert summary["load_time_ms"] is not None
    assert summary["total_latency_ms"] is not None

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(chat_calls) == 1

    expected_files = {
        "environment.json",
        "run_config.json",
        "load_response_sanitized.json",
        "requests.jsonl",
        "metrics.jsonl",
        "system_samples.jsonl",
        "system_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["generation"] == {
        "route": "compact_memory",
        "endpoint_path": "/api/v1/chat",
        "temperature": 0,
        "max_output_tokens": 64,
        "store": False,
    }
    assert run_config["app_concurrency"] == 1
    assert run_config["requested_context_length"] == 32768
    assert run_config["requested_parallel"] == 1
    assert run_config["input_shape"]["estimated_input_tokens"] == 22700
    assert run_config["memory_safety"] == {
        "max_ram_peak_mb": 131072,
        "max_vram_peak_mb": 32768,
    }

    load_response = json.loads(
        (run_dir / "load_response_sanitized.json").read_text(encoding="utf-8")
    )
    assert load_response["instance_id_hash"].startswith("sha256:")
    assert load_response["applied_load_config"] == {
        "context_length": 32768,
        "parallel": 1,
        "echo_load_config": True,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": True,
    }

    request_rows = [
        json.loads(line)
        for line in (run_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    metric_rows = [
        json.loads(line)
        for line in (run_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(request_rows) == 1
    assert len(metric_rows) == 1
    request_row = request_rows[0]
    metric_row = metric_rows[0]
    assert request_row["request_role"] == "compact_memory"
    assert request_row["endpoint_path"] == "/api/v1/chat"
    assert request_row["requested_context_length"] == 32768
    assert request_row["requested_parallel"] == 1
    assert request_row["app_concurrency"] == 1
    assert request_row["max_output_tokens"] == 64
    assert request_row["temperature"] == 0
    assert request_row["estimated_input_tokens"] == 22700
    assert request_row["previous_response_id_used"] is False
    assert request_row["response_id_hash"].startswith("sha256:")
    assert request_row["response_hash"].startswith("sha256:")
    assert request_row["content_nonempty"] is True
    assert metric_row["input_tokens"] == 22688
    assert metric_row["output_tokens"] == 12
    assert metric_row["prompt_processing_ms"] == 4321.0
    assert metric_row["time_to_first_token_ms"] == 123.0
    assert metric_row["tokens_per_second"] == 48.5
    assert metric_row["max_ram_peak_mb"] == 131072
    assert metric_row["max_vram_peak_mb"] == 32768
    assert metric_row["memory_safety_pass"] is True

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["raw_prompt_response_stored"] is False

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "lab-only compact_memory-only live smoke gate" in report_text
    assert (
        "production_default=false, wvm_runtime_integration=false, kv_reuse_proven=false."
        in report_text
    )
    assert "KV reuse is not proven by this run." in report_text
    assert "| max_ram_peak_mb | `131072` |" in report_text
    assert "| memory_safety_pass | `true` |" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "raw-instance-l3-6c-compact-memory",
        "raw-l3-6c-response-id-sentinel",
        "raw-l3-6c-output-sentinel",
        "http://127.0.0.1:1234",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text


def test_run_l3_6c_25k_compact_memory_live_smoke_allows_public_model_id_instance_marker(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6c_25k_compact_memory_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "google/gemma-4-e2b"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_6c_compact_memory_live_smoke(
        raw_response_id="raw-l3-6c-public-model-id-response-id",
        raw_output_text="raw-l3-6c-public-model-id-output",
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_6c_25k_compact_memory_live_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run-public-model-id-instance",
        run_id="l3-6c-public-model-id-instance",
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    assert summary["decision"] == "compact_memory_live_smoke_pass"
    assert summary["privacy_scan_status"] == "pass"
    assert len(native_calls) == 5
    assert len(chat_calls) == 1
    privacy_scan = json.loads(
        (tmp_path / "run-public-model-id-instance" / "privacy_scan.json").read_text(
            encoding="utf-8"
        )
    )
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "run-public-model-id-instance").iterdir()
        if path.is_file()
    )
    for forbidden in (
        "raw-l3-6c-public-model-id-response-id",
        "raw-l3-6c-public-model-id-output",
        "http://127.0.0.1:1234",
    ):
        assert forbidden not in all_artifact_text


def test_run_l3_6c_25k_compact_memory_live_smoke_ignores_short_output_marker_in_privacy_scan(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6c_25k_compact_memory_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6c-short-output"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_6c_compact_memory_live_smoke(
        raw_response_id="raw-l3-6c-short-output-response-id",
        raw_output_text="false",
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_6c_25k_compact_memory_live_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run-short-output",
        run_id="l3-6c-short-output",
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    assert summary["decision"] == "compact_memory_live_smoke_pass"
    assert summary["privacy_scan_status"] == "pass"
    assert len(native_calls) == 5
    assert len(chat_calls) == 1
    privacy_scan = json.loads(
        (tmp_path / "run-short-output" / "privacy_scan.json").read_text(encoding="utf-8")
    )
    assert privacy_scan["status"] == "pass"


def test_run_l3_6c_25k_compact_memory_live_smoke_raises_after_writing_artifacts_when_privacy_scan_fails(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6c_25k_compact_memory_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6c-privacy-fail"
    )

    def _leak_prompt_prefix(input_text: str) -> None:
        fake_sampler.samples[0].process_name = input_text.splitlines()[0][:96]

    _chat_calls, chat_transport = _chat_transport_for_l3_6c_compact_memory_live_smoke(
        raw_response_id="raw-l3-6c-privacy-fail-response-id",
        on_input=_leak_prompt_prefix,
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.6c compact-memory live smoke acceptance gate failed: privacy_scan_failed",
    ):
        runner.run_l3_6c_25k_compact_memory_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-privacy-fail",
            run_id="l3-6c-privacy-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-privacy-fail"
    assert len(native_calls) == 5
    assert (run_dir / "privacy_scan.json").exists()
    assert (run_dir / "report.md").exists()
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "fail"
    assert privacy_scan["violation_count"] >= 1


def test_run_l3_6c_25k_compact_memory_live_smoke_aborts_before_post_load_when_target_is_preloaded(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6c_25k_compact_memory_live_smoke_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []

    def preloaded_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e2b",
                            "loaded_instances": [
                                {
                                    "instance_id": "preloaded-raw-instance-sentinel",
                                    "context_length": 32768,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError("POST /load must not be called when target model is already preloaded")

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        ValueError,
        match="target model already has loaded instances before host application-owned load",
    ):
        runner.run_l3_6c_25k_compact_memory_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-preloaded",
            run_id="l3-6c-preloaded",
            native_transport=preloaded_native_transport,
        )

    assert native_calls == [("GET", "http://127.0.0.1:1234/api/v1/models", None)]


def test_run_l3_6c_25k_compact_memory_live_smoke_raises_after_writing_artifacts_when_memory_threshold_exceeded(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=replace(_fake_system_summary(), ram_peak_mb=140000.0),
    )
    config_path = _l3_6c_25k_compact_memory_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6c-memory-fail"
    )
    _chat_calls, chat_transport = _chat_transport_for_l3_6c_compact_memory_live_smoke(
        raw_response_id="raw-l3-6c-memory-fail-response-id",
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.6c compact-memory live smoke acceptance gate failed: memory_safety_failed",
    ):
        runner.run_l3_6c_25k_compact_memory_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-memory-fail",
            run_id="l3-6c-memory-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-memory-fail"
    assert len(native_calls) == 5
    assert (run_dir / "privacy_scan.json").exists()
    assert (run_dir / "report.md").exists()
    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert metric_rows[0]["memory_safety_pass"] is False
    assert metric_rows[0]["max_ram_peak_mb"] == 131072
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "| memory_safety_pass | `false` |" in report_text


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["safety"].__setitem__("production_default", True),
            "safety.production_default must remain false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("wvm_runtime_integration", True),
            "safety.wvm_runtime_integration must remain false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("kv_reuse_proven", True),
            "safety.kv_reuse_proven must remain false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("generation_allowed", False),
            "L3.6c compact-memory live smoke requires safety.generation_allowed=true",
        ),
        (
            lambda payload: payload["safety"].__setitem__("live_25k_authorized", False),
            "L3.6c compact-memory live smoke requires safety.live_25k_authorized=true",
        ),
        (
            lambda payload: payload["generation"].__setitem__("max_output_tokens", 512),
            "L3.6c compact-memory live smoke requires generation.max_output_tokens; allowed values are 64 or 128",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_length", 16384),
            "L3.6c compact-memory live smoke requires load.context_length=32768",
        ),
        (
            lambda payload: payload["memory_safety"].__setitem__("max_ram_peak_mb", 0),
            "memory_safety.max_ram_peak_mb must be >= 1",
        ),
        (
            lambda payload: payload["memory_safety"].__setitem__("max_vram_peak_mb", 0),
            "memory_safety.max_vram_peak_mb must be >= 1",
        ),
    ],
)
def test_run_l3_6c_25k_compact_memory_live_smoke_rejects_invalid_contract_values(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_6c_25k_compact_memory_live_smoke_config_payload()
    mutator(payload)
    config_path = _write_l3_6c_25k_compact_memory_live_smoke_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(ValueError, match=message):
        runner.run_l3_6c_25k_compact_memory_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-invalid",
            run_id="l3-6c-invalid",
        )


def test_run_l3_6c_25k_compact_memory_live_smoke_accepts_128_max_output_tokens(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    payload = _load_l3_6c_25k_compact_memory_live_smoke_config_payload()
    payload["generation"]["max_output_tokens"] = 128
    config_path = _write_l3_6c_25k_compact_memory_live_smoke_config(tmp_path, payload)
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6c-compact-memory-128"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_6c_compact_memory_live_smoke(
        max_output_tokens=128
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_6c_25k_compact_memory_live_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run-valid-128",
        run_id="l3-6c-valid-128",
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    assert summary["decision"] == "compact_memory_live_smoke_pass"
    assert summary["max_output_tokens"] == 128
    run_config = json.loads(
        (tmp_path / "run-valid-128" / "run_config.json").read_text(encoding="utf-8")
    )
    assert run_config["generation"]["max_output_tokens"] == 128
    assert len(native_calls) == 5
    assert len(chat_calls) == 1


def test_run_l3_6d_25k_mode_comparison_live_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6d_25k_mode_comparison_live_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6d-mode-comparison"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_6d_mode_comparison_live()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_6d_25k_mode_comparison_live(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="l3-6d-mode-comparison-live",
        providers={
            "lmstudio_local": "managed_l3_6d_mode_comparison_live_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["decision"] == "mode_comparison_live_pass"
    assert summary["mode"] == "mode_comparison_controlled_live"
    assert summary["requested_context_length"] == 32768
    assert summary["applied_context_length"] == 32768
    assert summary["requested_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["app_concurrency"] == 1
    assert summary["load_verified"] is True
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["privacy_scan_status"] == "pass"
    assert summary["memory_safety_pass"] is True
    assert summary["max_ram_peak_mb"] == 131072
    assert summary["max_vram_peak_mb"] == 32768
    assert summary["production_default"] is False
    assert summary["wvm_runtime_integration"] is False
    assert summary["kv_reuse_proven"] is False
    assert summary["generation_allowed"] is True
    assert summary["live_25k_authorized"] is True
    assert summary["max_output_tokens"] == 64
    assert summary["temperature"] == 0

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(chat_calls) == 4

    expected_files = {
        "environment.json",
        "run_config.json",
        "load_response_sanitized.json",
        "requests.jsonl",
        "metrics.jsonl",
        "system_samples.jsonl",
        "system_summary.json",
        "comparison_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["mode_comparison"]["setup_request"] == {
        "mode": "native_chat_stateful_setup",
        "classification": "setup_metadata",
        "route": "native_chat_stateful",
        "endpoint_path": "/api/v1/chat",
        "previous_response_id_used": False,
        "store": True,
    }
    assert [row["mode"] for row in run_config["mode_comparison"]["comparable_modes"]] == [
        "compact_memory",
        "native_chat_stateful",
        "stateless_full_prefix",
    ]

    request_rows = _read_jsonl(run_dir / "requests.jsonl")
    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert [row["request_role"] for row in request_rows] == [
        "native_chat_stateful_setup",
        "compact_memory",
        "native_chat_stateful",
        "stateless_full_prefix",
    ]
    assert [row["classification"] for row in request_rows] == [
        "setup_metadata",
        "primary_candidate",
        "research_latency_candidate",
        "baseline",
    ]
    assert request_rows[0]["comparable_mode"] is False
    assert all(row["endpoint_path"] == "/api/v1/chat" for row in request_rows)
    assert request_rows[1]["previous_response_id_used"] is False
    assert request_rows[2]["previous_response_id_used"] is True
    assert request_rows[2]["previous_response_id_hash"].startswith("sha256:")
    assert request_rows[2]["root_state_id_hash"].startswith("sha256:")
    assert request_rows[3]["previous_response_id_used"] is False
    assert all(row["request_succeeded"] is True for row in request_rows)
    assert all(row["content_nonempty"] is True for row in request_rows)
    assert all(row["kv_reuse_proven"] is False for row in request_rows)

    assert metric_rows[1]["prompt_processing_ms"] == 4321.0
    assert metric_rows[1]["time_to_first_token_ms"] == 123.0
    assert metric_rows[1]["tokens_per_second"] == 48.5
    assert metric_rows[1]["input_tokens"] == 22688
    assert metric_rows[1]["output_tokens"] == 12
    assert metric_rows[2]["prompt_processing_ms"] == 912.0
    assert metric_rows[2]["time_to_first_token_ms"] == 91.0
    assert metric_rows[2]["tokens_per_second"] == 61.0
    assert metric_rows[2]["input_tokens"] == 28
    assert metric_rows[2]["output_tokens"] == 11
    assert metric_rows[3]["prompt_processing_ms"] == 5432.0
    assert metric_rows[3]["time_to_first_token_ms"] == 144.0
    assert metric_rows[3]["tokens_per_second"] == 34.0
    assert metric_rows[3]["input_tokens"] == 25000
    assert metric_rows[3]["output_tokens"] == 10
    assert all(row["memory_safety_pass"] is True for row in metric_rows)

    comparison_summary = json.loads(
        (run_dir / "comparison_summary.json").read_text(encoding="utf-8")
    )
    assert comparison_summary["cleanup_verified"] is True
    assert comparison_summary["final_loaded_instances"] == 0
    assert comparison_summary["privacy_scan_status"] == "pass"
    assert [row["mode"] for row in comparison_summary["mode_results"]] == [
        "compact_memory",
        "native_chat_stateful",
        "stateless_full_prefix",
    ]
    assert [row["classification"] for row in comparison_summary["mode_results"]] == [
        "primary_candidate",
        "research_latency_candidate",
        "baseline",
    ]

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["raw_prompt_response_stored"] is False

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "lab-only LM Studio mode comparison gate" in report_text
    assert "native_chat_stateful is a research latency candidate only" in report_text
    assert "| cleanup_verified | `true` |" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "raw-instance-l3-6d-mode-comparison",
        "raw-l3-6d-root-state-id-sentinel",
        "raw-l3-6d-root-output-sentinel",
        "raw-l3-6d-compact-response-id-sentinel",
        "raw-l3-6d-compact-output-sentinel",
        "raw-l3-6d-stateful-response-id-sentinel",
        "raw-l3-6d-stateful-output-sentinel",
        "raw-l3-6d-stateless-response-id-sentinel",
        "raw-l3-6d-stateless-output-sentinel",
        "http://127.0.0.1:1234",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
        "Stateful root setup synthetic 25k lecture prompt for L3.6d mode comparison.",
        "Compact memory controlled synthetic minimized prompt for L3.6d mode comparison.",
    ):
        assert forbidden not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text


def test_run_l3_6d_25k_mode_comparison_live_allows_public_model_id_instance_marker(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6d_25k_mode_comparison_live_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "google/gemma-4-e2b"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_6d_mode_comparison_live()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_6d_25k_mode_comparison_live(
        config_path=config_path,
        run_dir=tmp_path / "run-public-model-id-instance",
        run_id="l3-6d-public-model-id-instance",
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    assert summary["decision"] == "mode_comparison_live_pass"
    assert summary["privacy_scan_status"] == "pass"
    assert len(native_calls) == 5
    assert len(chat_calls) == 4
    privacy_scan = json.loads(
        (tmp_path / "run-public-model-id-instance" / "privacy_scan.json").read_text(
            encoding="utf-8"
        )
    )
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0


def test_run_l3_6d_25k_mode_comparison_live_raises_after_writing_artifacts_when_privacy_scan_fails(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6d_25k_mode_comparison_live_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6d-privacy-fail"
    )

    def _leak_prompt_prefix(input_text: str) -> None:
        fake_sampler.samples[0].process_name = input_text.splitlines()[0][:96]

    _chat_calls, chat_transport = _chat_transport_for_l3_6d_mode_comparison_live(
        on_input=_leak_prompt_prefix
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.6d mode comparison live acceptance gate failed: privacy_scan_failed",
    ):
        runner.run_l3_6d_25k_mode_comparison_live(
            config_path=config_path,
            run_dir=tmp_path / "run-privacy-fail",
            run_id="l3-6d-privacy-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-privacy-fail"
    assert len(native_calls) == 5
    assert (run_dir / "privacy_scan.json").exists()
    assert (run_dir / "comparison_summary.json").exists()
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "fail"
    assert privacy_scan["violation_count"] >= 1


def test_run_l3_6d_25k_mode_comparison_live_aborts_before_post_load_when_target_is_preloaded(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_6d_25k_mode_comparison_live_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []

    def preloaded_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e2b",
                            "loaded_instances": [
                                {
                                    "instance_id": "preloaded-raw-instance-sentinel",
                                    "context_length": 32768,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError("POST /load must not be called when target model is already preloaded")

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        ValueError,
        match="target model already has loaded instances before host application-owned load",
    ):
        runner.run_l3_6d_25k_mode_comparison_live(
            config_path=config_path,
            run_dir=tmp_path / "run-preloaded",
            run_id="l3-6d-preloaded",
            native_transport=preloaded_native_transport,
        )

    assert native_calls == [("GET", "http://127.0.0.1:1234/api/v1/models", None)]


def test_run_l3_6d_25k_mode_comparison_live_raises_after_writing_artifacts_when_memory_threshold_exceeded(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=replace(_fake_system_summary(), ram_peak_mb=140000.0),
    )
    config_path = _l3_6d_25k_mode_comparison_live_config_path()
    native_calls, native_transport = _native_transport_for_l3_6c_compact_memory_live_smoke(
        "raw-instance-l3-6d-memory-fail"
    )
    _chat_calls, chat_transport = _chat_transport_for_l3_6d_mode_comparison_live()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.6d mode comparison live acceptance gate failed: memory_safety_failed",
    ):
        runner.run_l3_6d_25k_mode_comparison_live(
            config_path=config_path,
            run_dir=tmp_path / "run-memory-fail",
            run_id="l3-6d-memory-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-memory-fail"
    assert len(native_calls) == 5
    assert (run_dir / "privacy_scan.json").exists()
    assert (run_dir / "comparison_summary.json").exists()
    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert all(row["memory_safety_pass"] is False for row in metric_rows)
    assert metric_rows[0]["max_ram_peak_mb"] == 131072
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    comparison_summary = json.loads(
        (run_dir / "comparison_summary.json").read_text(encoding="utf-8")
    )
    assert comparison_summary["memory_safety_pass"] is False


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["safety"].__setitem__("production_default", True),
            "safety.production_default must remain false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("kv_reuse_proven", True),
            "safety.kv_reuse_proven must remain false",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_length", 16384),
            "L3.6d mode comparison live requires load.context_length=32768",
        ),
        (
            lambda payload: payload["mode_comparison"]["comparable_modes"][0].__setitem__(
                "mode", "native_chat_stateful"
            ),
            r"L3.6d mode comparison live requires comparable modes \['compact_memory', 'native_chat_stateful', 'stateless_full_prefix'\]",
        ),
        (
            lambda payload: payload["mode_comparison"]["comparable_modes"][1].__setitem__(
                "route", "responses_probe"
            ),
            r"L3.6d mode comparison live requires mode_comparison.comparable_modes\[1\].route 'native_chat_stateful'",
        ),
        (
            lambda payload: payload["generation"].__setitem__("max_output_tokens", 512),
            "L3.6d mode comparison live requires generation.max_output_tokens; allowed values are 64 or 128",
        ),
    ],
)
def test_run_l3_6d_25k_mode_comparison_live_rejects_invalid_contract_values(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_6d_25k_mode_comparison_live_config_payload()
    mutator(payload)
    config_path = _write_l3_6d_25k_mode_comparison_live_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(ValueError, match=message):
        runner.run_l3_6d_25k_mode_comparison_live(
            config_path=config_path,
            run_dir=tmp_path / "run-invalid",
            run_id="l3-6d-invalid",
        )


def test_run_l3_7d_structured_json_live_smoke_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_7d_structured_json_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-7d-structured-json"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_7d_structured_json_live_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="l3-7d-structured-json-live-smoke",
        providers={
            "lmstudio_local": "managed_l3_7d_structured_json_live_smoke_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["decision"] == "structured_json_live_smoke_pass"
    assert summary["mode"] == "structured_json_controlled_live_smoke"
    assert summary["route"] == "strict_json_chat_completions"
    assert summary["helper_mode"] == "json_schema_single"
    assert summary["requested_context_length"] == 8192
    assert summary["applied_context_length"] == 8192
    assert summary["requested_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["load_verified"] is True
    assert summary["generation_called"] is True
    assert summary["request_succeeded"] is True
    assert summary["public_output_pass"] is True
    assert summary["structured_validation_pass"] is True
    assert summary["structured_gate_status"] == "passed"
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["privacy_scan_status"] == "pass"
    assert summary["production_default"] is False
    assert summary["wvm_runtime_integration"] is False
    assert summary["kv_reuse_proven"] is False
    assert summary["generation_allowed"] is True
    assert summary["max_tokens"] == 512
    assert summary["temperature"] == 0
    assert summary["input_tokens"] == 88
    assert summary["output_tokens"] == 24
    assert summary["total_latency_ms"] is not None

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(chat_calls) == 1

    expected_files = {
        "environment.json",
        "run_config.json",
        "load_response_sanitized.json",
        "requests.jsonl",
        "metrics.jsonl",
        "structured_errors.jsonl",
        "system_samples.jsonl",
        "system_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["generation"] == {
        "route": "strict_json_chat_completions",
        "helper_mode": "json_schema_single",
        "endpoint_path": "/v1/chat/completions",
        "temperature": 0,
        "max_tokens": 512,
    }

    load_response = json.loads(
        (run_dir / "load_response_sanitized.json").read_text(encoding="utf-8")
    )
    assert load_response["instance_id_hash"].startswith("sha256:")
    assert load_response["applied_load_config"] == {
        "context_length": 8192,
        "parallel": 1,
        "echo_load_config": True,
    }

    request_rows = _read_jsonl(run_dir / "requests.jsonl")
    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert len(request_rows) == 1
    assert len(metric_rows) == 1
    assert request_rows[0]["route"] == "strict_json_chat_completions"
    assert request_rows[0]["helper_mode"] == "json_schema_single"
    assert request_rows[0]["content_nonempty"] is True
    assert request_rows[0]["structured_gate_status"] == "passed"
    assert request_rows[0]["response_id_hash"].startswith("sha256:")
    assert metric_rows[0]["validation"]["json_parse_pass"] is True
    assert metric_rows[0]["validation"]["schema_pass"] is True
    assert metric_rows[0]["validation"]["business_pass"] is True

    assert (run_dir / "structured_errors.jsonl").read_text(encoding="utf-8") == ""
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["raw_prompt_response_stored"] is False

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "strict JSON chat-completions smoke gate" in report_text
    assert "Public assistant content is required; reasoning-only JSON is a failure." in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "raw-instance-l3-7d-structured-json",
        "raw-l3-7d-response-id-sentinel",
        "http://127.0.0.1:1234",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["model"].__setitem__("key", "qwen35_4b"),
            "L3.7d structured JSON live smoke requires model.key 'gemma4_e2b_q4km'",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_length", 16384),
            "L3.7d structured JSON live smoke requires load.context_length=8192",
        ),
        (
            lambda payload: payload["generation"].__setitem__("route", "compact_memory"),
            "L3.7d structured JSON live smoke requires generation.route 'strict_json_chat_completions'",
        ),
        (
            lambda payload: payload["generation"].__setitem__("helper_mode", "plain_text_single"),
            "L3.7d structured JSON live smoke requires generation.helper_mode 'json_schema_single'",
        ),
        (
            lambda payload: payload["safety"].__setitem__("production_default", True),
            "safety.production_default must remain false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("kv_reuse_proven", True),
            "safety.kv_reuse_proven must remain false",
        ),
        (
            lambda payload: payload["privacy"].__setitem__("store_raw_prompt_response", True),
            "privacy.store_raw_prompt_response must remain false",
        ),
    ],
)
def test_run_l3_7d_structured_json_live_smoke_rejects_invalid_contract_values(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_7d_structured_json_live_smoke_config_payload()
    mutator(payload)
    config_path = _write_l3_7d_structured_json_live_smoke_config(tmp_path, payload)
    runner = ManagedLabRunner(_QueueTransport({}))

    with pytest.raises(ValueError, match=message):
        runner.run_l3_7d_structured_json_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-invalid",
            run_id="l3-7d-invalid",
        )


def test_run_l3_7d_structured_json_live_smoke_aborts_before_post_load_when_target_is_preloaded(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_7d_structured_json_live_smoke_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []

    def preloaded_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e2b",
                            "loaded_instances": [
                                {
                                    "instance_id": "preloaded-raw-instance-sentinel",
                                    "context_length": 8192,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError("POST /load must not be called when target model is already preloaded")

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        ValueError,
        match="target model already has loaded instances before host application-owned load",
    ):
        runner.run_l3_7d_structured_json_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-preloaded",
            run_id="l3-7d-preloaded",
            native_transport=preloaded_native_transport,
        )

    assert native_calls == [("GET", "http://127.0.0.1:1234/api/v1/models", None)]


def test_run_l3_7d_structured_json_live_smoke_rejects_reasoning_only_json_response(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_7d_structured_json_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-7d-reasoning-only"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke(
        raw_response_id="raw-l3-7d-reasoning-only-response-id",
        public_content="   ",
        reasoning_content=_valid_blocks_json((101, 102))["choices"][0]["message"]["content"],
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.7d structured JSON live smoke acceptance gate failed: failed_reasoning_only_json",
    ):
        runner.run_l3_7d_structured_json_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-reasoning-only",
            run_id="l3-7d-reasoning-only",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-reasoning-only"
    assert len(native_calls) == 5
    assert len(chat_calls) == 1
    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert metric_rows[0]["content_empty"] is True
    assert metric_rows[0]["reasoning_content_present"] is True
    request_rows = _read_jsonl(run_dir / "requests.jsonl")
    assert request_rows[0]["structured_gate_status"] == "failed_reasoning_only_json"
    structured_errors = _read_jsonl(run_dir / "structured_errors.jsonl")
    assert len(structured_errors) == 1
    assert structured_errors[0]["error_category"] == "empty"


def test_run_l3_7d_structured_json_live_smoke_raises_after_writing_artifacts_when_privacy_scan_fails(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_7d_structured_json_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-7d-privacy-fail"
    )

    def _leak_base_url(_prompt_text: str) -> None:
        fake_sampler.samples[0].process_name = "http://127.0.0.1:1234"

    _chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke(
        on_prompt=_leak_base_url,
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.7d structured JSON live smoke acceptance gate failed: privacy_scan_failed",
    ):
        runner.run_l3_7d_structured_json_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-privacy-fail",
            run_id="l3-7d-privacy-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-privacy-fail"
    assert len(native_calls) == 5
    assert (run_dir / "privacy_scan.json").exists()
    assert (run_dir / "report.md").exists()
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "fail"
    assert privacy_scan["violation_count"] >= 1


def test_run_cache_32k_load_only_smoke_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_cache_32k_load_only_config(tmp_path)
    native_calls, native_transport = _native_transport_for_load_only_smoke(
        "raw-instance-cache-32k-load-only"
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_cache_32k_load_only_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="cache-32k-load-only",
        providers={
            "lmstudio_local": "managed_cache_32k_load_only_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "load_only"
    assert summary["endpoint_family"] == "model_lifecycle"
    assert summary["requested_context_length"] == 32768
    assert summary["applied_context_length"] == 32768
    assert summary["requested_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["load_called"] is True
    assert summary["unload_called"] is True
    assert summary["generation_called"] is False
    assert summary["chat_called"] is False
    assert summary["responses_called"] is False
    assert summary["chat_completions_called"] is False
    assert summary["inference_endpoint_called"] is False
    assert summary["echo_load_config_received"] is True
    assert summary["cleanup_verified"] is True
    assert summary["final_owned_instances"] == 0
    assert summary["live_25k_authorized"] is False
    assert summary["production_default"] is False
    assert summary["kv_reuse_proven"] is False
    assert summary["privacy_scan_status"] == "pass"
    assert summary["decision"] == "load_only_pass"

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]

    expected_files = {
        "environment.json",
        "run_config.json",
        "load_request.json",
        "load_response_sanitized.json",
        "models_before.json",
        "models_after_load.json",
        "unload_response_sanitized.json",
        "models_after_unload.json",
        "system_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    load_request = json.loads((run_dir / "load_request.json").read_text(encoding="utf-8"))
    assert load_request == {
        "endpoint_kind": "native_load",
        "method": "POST",
        "body_field_names": [
            "model",
            "context_length",
            "echo_load_config",
            "flash_attention",
            "offload_kv_cache_to_gpu",
            "parallel",
        ],
        "body_fields": {
            "model": "google/gemma-4-e2b",
            "context_length": 32768,
            "echo_load_config": True,
            "flash_attention": True,
            "offload_kv_cache_to_gpu": True,
            "parallel": 1,
        },
    }

    load_response = json.loads(
        (run_dir / "load_response_sanitized.json").read_text(encoding="utf-8")
    )
    assert load_response["status"] == "loaded"
    assert load_response["instance_id_hash"].startswith("sha256:")
    assert load_response["load_config"] == {
        "context_length": 32768,
        "parallel": 1,
        "echo_load_config": True,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": True,
    }

    models_before = json.loads((run_dir / "models_before.json").read_text(encoding="utf-8"))
    models_after_load = json.loads((run_dir / "models_after_load.json").read_text(encoding="utf-8"))
    models_after_unload = json.loads(
        (run_dir / "models_after_unload.json").read_text(encoding="utf-8")
    )
    assert models_before["target_loaded_instance_count"] == 0
    assert models_after_load["target_loaded_instance_count"] == 1
    assert models_after_unload["target_loaded_instance_count"] == 0
    assert all(value.startswith("sha256:") for value in models_after_load["instance_id_hashes"])

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "cache_32k_load_only_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "environment.json",
            "run_config.json",
            "load_request.json",
            "load_response_sanitized.json",
            "models_before.json",
            "models_after_load.json",
            "unload_response_sanitized.json",
            "models_after_unload.json",
            "system_summary.json",
            "report.md",
        ],
        "raw_prompt_response_stored": False,
    }

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "| experiment_id | `l3_5b_32k_load_only_smoke_gemma4_e2b` |" in report_text
    assert "| endpoint_family | `model_lifecycle` |" in report_text
    assert "| inference_endpoint_called | `false` |" in report_text
    assert "| requested_context_length | `32768` |" in report_text
    assert "| final_owned_instances | `0` |" in report_text
    assert "| decision | `load_only_pass` |" in report_text
    assert (
        "This run does not prove generation stability, quality, structured output correctness, or KV reuse."
        in report_text
    )
    assert (
        "It only proves whether the model can be loaded with the requested 32k context profile and cleaned up safely."
        in report_text
    )

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-cache-32k-load-only",
        "/api/v1/chat",
        "/v1/chat/completions",
        "/v1/responses",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text


def test_run_cache_32k_load_only_smoke_attempts_exact_unload_when_post_load_verification_fails(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_cache_32k_load_only_config(tmp_path)
    raw_instance_id = "raw-instance-cleanup-required"
    native_calls: list[tuple[str, str, bytes | None]] = []

    def failing_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {"models": [{"key": "google/gemma-4-e2b", "loaded_instances": []}]}
            ).encode("utf-8")
        if len(native_calls) == 2:
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": raw_instance_id,
                    "load_config": {
                        "context_length": 32768,
                        "parallel": 1,
                        "echo_load_config": True,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                }
            ).encode("utf-8")
        if len(native_calls) == 3:
            return b'{"invalid": true}'
        if len(native_calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        raise AssertionError(f"unexpected native request #{len(native_calls)}")

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(ValueError, match="native model list response must parse successfully"):
        runner.run_cache_32k_load_only_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-fail-after-load",
            run_id="cache-32k-load-only-fail-after-load",
            providers={"lmstudio_local": "managed_cache_32k_load_only_failure_test"},
            native_transport=failing_native_transport,
        )

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
    ]
    assert all("/api/v1/chat" not in url for _method, url, _data in native_calls)
    assert all("/v1/chat/completions" not in url for _method, url, _data in native_calls)
    assert all("/v1/responses" not in url for _method, url, _data in native_calls)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload.__setitem__(
                "model", {"key": "gemma4_e2b_q4km", "lmstudio_model_id": "google/gemma-4-e4b"}
            ),
            "model.key 'gemma4_e4b_q4km'",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_tiers", [16_384]),
            r"load.context_tiers=\[16384, 32768\]",
        ),
        (
            lambda payload: payload["load"].__setitem__("parallel", 2),
            "load.parallel=1",
        ),
        (
            lambda payload: payload["safety"].__setitem__("generation_allowed", True),
            "generation_allowed=false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("production_default", True),
            "production_default=false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("kv_reuse_proven", True),
            "kv_reuse_proven=false",
        ),
        (
            lambda payload: payload["privacy"].__setitem__("store_state_ids_raw", True),
            "store_state_ids_raw must remain false",
        ),
    ],
)
def test_run_l3_8b_gemma4_e4b_load_only_16k_32k_rejects_invalid_contracts(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_8b_gemma4_e4b_load_only_config_payload()
    mutator(payload)
    config_path = _write_l3_8b_gemma4_e4b_load_only_config(tmp_path, payload)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_l3_8b_gemma4_e4b_load_only_16k_32k(
            config_path=config_path,
            run_dir=tmp_path / "run-invalid",
            run_id="l3-8b-invalid",
        )


def test_run_l3_8b_gemma4_e4b_load_only_16k_32k_runs_two_tiers_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8b_gemma4_e4b_load_only_config_path()
    native_calls, native_transport = _native_transport_for_l3_8b_gemma4_e4b_load_only()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_8b_gemma4_e4b_load_only_16k_32k(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-8b",
        run_id="l3-8b-gemma4-e4b-load-only",
        providers={
            "lmstudio_local": "managed_l3_8b_gemma4_e4b_load_only_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
    )

    run_dir = tmp_path / "run-l3-8b"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "candidate_load_only_16k_32k"
    assert summary["decision"] == "load_only_passed"
    assert summary["load_context_tiers"] == [16_384, 32_768]
    assert summary["requested_parallel"] == 1
    assert summary["app_concurrency"] == 1
    assert summary["load_called"] is True
    assert summary["unload_called"] is True
    assert summary["generation_called"] is False
    assert summary["chat_called"] is False
    assert summary["responses_called"] is False
    assert summary["chat_completions_called"] is False
    assert summary["inference_endpoint_called"] is False
    assert summary["load_tiers_passed_count"] == 2
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["production_default"] is False
    assert summary["wvm_runtime_integration"] is False
    assert summary["kv_reuse_proven"] is False
    assert summary["final_user_facing_recommendation"] is False
    assert summary["privacy_scan_status"] == "pass"

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert all("/api/v1/chat" not in url for _method, url, _data in native_calls)
    assert all("/v1/chat/completions" not in url for _method, url, _data in native_calls)
    assert all("/v1/responses" not in url for _method, url, _data in native_calls)

    expected_files = {
        "environment.json",
        "run_config.json",
        "load_attempts.jsonl",
        "load_response_sanitized.jsonl",
        "models_summary.jsonl",
        "system_samples.jsonl",
        "system_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["model_key"] == "gemma4_e4b_q4km"
    assert run_config["model_id"] == "google/gemma-4-e4b"
    assert run_config["load_context_tiers"] == [16_384, 32_768]
    assert run_config["requested_parallel"] == 1
    assert run_config["app_concurrency"] == 1
    assert run_config["safety"]["production_default"] is False
    assert run_config["safety"]["wvm_runtime_integration"] is False
    assert run_config["safety"]["kv_reuse_proven"] is False

    load_attempts = _read_jsonl(run_dir / "load_attempts.jsonl")
    assert len(load_attempts) == 2
    assert [row["requested_context_length"] for row in load_attempts] == [16_384, 32_768]
    assert {row["decision"] for row in load_attempts} == {"load_only_passed"}
    assert {row["cleanup_verified"] for row in load_attempts} == {True}
    assert {row["final_loaded_instances"] for row in load_attempts} == {0}
    assert {row["generation_called"] for row in load_attempts} == {False}
    assert {row["model_list_context_metadata_present"] for row in load_attempts} == {True}
    assert {row["model_list_parallel_metadata_present"] for row in load_attempts} == {True}
    assert {row["model_list_applied_metadata_verified"] for row in load_attempts} == {True}

    load_responses = _read_jsonl(run_dir / "load_response_sanitized.jsonl")
    assert len(load_responses) == 2
    assert [row["load_config"]["context_length"] for row in load_responses] == [16_384, 32_768]
    assert {row["load_config"]["parallel"] for row in load_responses} == {1}
    assert all(str(row["instance_id_hash"]).startswith("sha256:") for row in load_responses)

    models_summary = _read_jsonl(run_dir / "models_summary.jsonl")
    assert len(models_summary) == 6
    assert [row["phase"] for row in models_summary] == [
        "before_load",
        "post_load",
        "post_unload",
        "before_load",
        "post_load",
        "post_unload",
    ]
    assert [
        row["requested_context_length"] for row in models_summary if row["phase"] == "post_load"
    ] == [
        16_384,
        32_768,
    ]
    assert {
        row["target_loaded_instance_count"]
        for row in models_summary
        if row["phase"] == "post_unload"
    } == {0}

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "candidate_load_only_16k_32k_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "environment.json",
            "run_config.json",
            "load_attempts.jsonl",
            "load_response_sanitized.jsonl",
            "models_summary.jsonl",
            "system_samples.jsonl",
            "system_summary.json",
            "report.md",
        ],
        "raw_prompt_response_stored": False,
    }

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# LM Studio Lab L3.8b Gemma4 E4B Load-Only 16k/32k Report" in report_text
    assert "| decision | `load_only_passed` |" in report_text
    assert (
        "no inference, no native chat, no responses, and no chat-completions endpoints"
        in report_text
    )
    assert "Model-list context_length/parallel arrays are optional telemetry only" in report_text
    assert "This report remains lab-only" in report_text
    assert "not production default" in report_text
    assert "not host application runtime integration" in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-l3-8b-16k",
        "raw-instance-l3-8b-32k",
        "/api/v1/chat",
        "/v1/chat/completions",
        "/v1/responses",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text


def test_run_l3_8b_gemma4_e4b_load_only_16k_32k_aborts_before_post_when_target_preloaded(
    tmp_path: Path,
) -> None:
    config_path = _l3_8b_gemma4_e4b_load_only_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []

    def preloaded_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e4b",
                            "loaded_instances": [
                                {
                                    "instance_id": "raw-preloaded",
                                    "context_length": 16_384,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError(f"unexpected native request #{len(native_calls)}")

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=_FakeSystemSampler(
            samples=_fake_system_samples(), summary=_fake_system_summary()
        ),
    )

    with pytest.raises(RuntimeError, match="aborts before POST load"):
        runner.run_l3_8b_gemma4_e4b_load_only_16k_32k(
            config_path=config_path,
            run_dir=tmp_path / "run-preloaded",
            run_id="l3-8b-preloaded",
            native_transport=preloaded_native_transport,
        )

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models")
    ]


def test_run_l3_8b_gemma4_e4b_load_only_16k_32k_accepts_missing_model_list_runtime_metadata(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8b_gemma4_e4b_load_only_config_path()
    native_calls, native_transport = _native_transport_for_l3_8b_gemma4_e4b_load_only(
        include_model_list_runtime_metadata=False
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_8b_gemma4_e4b_load_only_16k_32k(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-8b-metadata-optional",
        run_id="l3-8b-gemma4-e4b-metadata-optional",
        native_transport=native_transport,
    )

    assert summary["decision"] == "load_only_passed"
    assert summary["load_tiers_passed_count"] == 2
    assert summary["cleanup_verified"] is True
    assert all("/api/v1/chat" not in url for _method, url, _data in native_calls)
    assert all("/v1/chat/completions" not in url for _method, url, _data in native_calls)
    assert all("/v1/responses" not in url for _method, url, _data in native_calls)

    load_attempts = _read_jsonl(tmp_path / "run-l3-8b-metadata-optional" / "load_attempts.jsonl")
    assert len(load_attempts) == 2
    assert {row["decision"] for row in load_attempts} == {"load_only_passed"}
    assert {row["model_list_context_metadata_present"] for row in load_attempts} == {False}
    assert {row["model_list_parallel_metadata_present"] for row in load_attempts} == {False}
    assert {row["model_list_applied_metadata_verified"] for row in load_attempts} == {None}

    models_summary = _read_jsonl(tmp_path / "run-l3-8b-metadata-optional" / "models_summary.jsonl")
    post_load_rows = [row for row in models_summary if row["phase"] == "post_load"]
    assert len(post_load_rows) == 2
    assert {tuple(row["context_lengths"]) for row in post_load_rows} == {()}
    assert {tuple(row["parallels"]) for row in post_load_rows} == {()}


def test_run_l3_8b_gemma4_e4b_load_only_16k_32k_fails_on_applied_context_mismatch(
    tmp_path: Path,
) -> None:
    config_path = _l3_8b_gemma4_e4b_load_only_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []

    def mismatched_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {"models": [{"key": "google/gemma-4-e4b", "loaded_instances": []}]}
            ).encode("utf-8")
        if len(native_calls) == 2:
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": "raw-l3-8b-mismatch",
                    "load_config": {
                        "context_length": 8_192,
                        "parallel": 1,
                        "echo_load_config": True,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                }
            ).encode("utf-8")
        if len(native_calls) == 3:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e4b",
                            "loaded_instances": [
                                {
                                    "instance_id": "raw-l3-8b-mismatch",
                                    "context_length": 8_192,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(native_calls) == 4:
            return b'{"status":"ok"}'
        if len(native_calls) == 5:
            return json.dumps(
                {"models": [{"key": "google/gemma-4-e4b", "loaded_instances": []}]}
            ).encode("utf-8")
        raise AssertionError(f"unexpected native request #{len(native_calls)}")

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=_FakeSystemSampler(
            samples=_fake_system_samples(), summary=_fake_system_summary()
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="exact applied context_length and parallel from the native load response",
    ):
        runner.run_l3_8b_gemma4_e4b_load_only_16k_32k(
            config_path=config_path,
            run_dir=tmp_path / "run-mismatch",
            run_id="l3-8b-mismatch",
            native_transport=mismatched_native_transport,
        )

    load_attempts = _read_jsonl(tmp_path / "run-mismatch" / "load_attempts.jsonl")
    assert len(load_attempts) == 1
    assert load_attempts[0]["failure_reason"] == "applied_load_contract_mismatch"
    assert load_attempts[0]["model_list_context_metadata_present"] is True
    assert load_attempts[0]["model_list_parallel_metadata_present"] is True
    assert load_attempts[0]["model_list_applied_metadata_verified"] is False

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]


def test_run_l3_8b_gemma4_e4b_load_only_16k_32k_fails_when_cleanup_not_verified(
    tmp_path: Path,
) -> None:
    config_path = _l3_8b_gemma4_e4b_load_only_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []

    def cleanup_failure_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {"models": [{"key": "google/gemma-4-e4b", "loaded_instances": []}]}
            ).encode("utf-8")
        if len(native_calls) == 2:
            return json.dumps(
                {
                    "status": "loaded",
                    "instance_id": "raw-l3-8b-cleanup-fail",
                    "load_config": {
                        "context_length": 16_384,
                        "parallel": 1,
                        "echo_load_config": True,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                }
            ).encode("utf-8")
        if len(native_calls) == 3:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e4b",
                            "loaded_instances": [
                                {
                                    "instance_id": "raw-l3-8b-cleanup-fail",
                                    "context_length": 16_384,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        if len(native_calls) == 4:
            return b'{"status":"ok"}'
        if len(native_calls) == 5:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e4b",
                            "loaded_instances": [
                                {
                                    "instance_id": "raw-l3-8b-cleanup-fail",
                                    "context_length": 16_384,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError(f"unexpected native request #{len(native_calls)}")

    runner = ManagedLabRunner(
        lambda request: None,
        system_sampler=_FakeSystemSampler(
            samples=_fake_system_samples(), summary=_fake_system_summary()
        ),
    )

    with pytest.raises(RuntimeError, match="exact cleanup verification"):
        runner.run_l3_8b_gemma4_e4b_load_only_16k_32k(
            config_path=config_path,
            run_dir=tmp_path / "run-cleanup-fail",
            run_id="l3-8b-cleanup-fail",
            native_transport=cleanup_failure_native_transport,
        )

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload.__setitem__(
                "model", {"key": "gemma4_e2b_q4km", "lmstudio_model_id": "google/gemma-4-e4b"}
            ),
            "model.key 'gemma4_e4b_q4km'",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_length", 32_768),
            "load.context_length=16384",
        ),
        (
            lambda payload: payload["generation"].__setitem__("route", "native_chat_tiny"),
            "generation.route 'tiny_live_chat'",
        ),
        (
            lambda payload: payload["generation"].__setitem__(
                "endpoint_path", "/v1/chat/completions"
            ),
            "generation.endpoint_path '/api/v1/chat'",
        ),
        (
            lambda payload: payload["generation"].__setitem__("max_output_tokens", 128),
            "generation.max_output_tokens=64",
        ),
        (
            lambda payload: payload["safety"].__setitem__("generation_allowed", False),
            "generation_allowed=true",
        ),
        (
            lambda payload: payload["safety"].__setitem__("production_default", True),
            "production_default must remain false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("kv_reuse_proven", True),
            "kv_reuse_proven must remain false",
        ),
        (
            lambda payload: payload["privacy"].__setitem__("store_raw_prompt_response", True),
            "store_raw_prompt_response must remain false",
        ),
    ],
)
def test_run_l3_8c_gemma4_e4b_tiny_live_smoke_rejects_invalid_contracts(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_8c_gemma4_e4b_tiny_live_smoke_config_payload()
    mutator(payload)
    config_path = _write_l3_8c_gemma4_e4b_tiny_live_smoke_config(tmp_path, payload)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_l3_8c_gemma4_e4b_tiny_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8c-invalid",
            run_id="l3-8c-invalid",
        )


def test_run_l3_8c_gemma4_e4b_tiny_live_smoke_runs_exact_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8c_gemma4_e4b_tiny_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke(
        "raw-instance-l3-8c"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke()
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_8c_gemma4_e4b_tiny_live_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-8c",
        run_id="l3-8c-gemma4-e4b-tiny-live-smoke",
        providers={
            "lmstudio_local": "managed_l3_8c_gemma4_e4b_tiny_live_smoke_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    run_dir = tmp_path / "run-l3-8c"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "candidate_tiny_live_smoke"
    assert summary["decision"] == "candidate_tiny_live_smoke_pass"
    assert summary["requested_context_length"] == 16_384
    assert summary["applied_context_length"] == 16_384
    assert summary["requested_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["load_called"] is True
    assert summary["unload_called"] is True
    assert summary["generation_called"] is True
    assert summary["request_succeeded"] is True
    assert summary["non_empty_text_pass"] is True
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["production_default"] is False
    assert summary["wvm_runtime_integration"] is False
    assert summary["kv_reuse_proven"] is False
    assert summary["final_user_facing_recommendation"] is False
    assert summary["live_25k_authorized"] is False
    assert summary["privacy_scan_status"] == "pass"

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(chat_calls) == 1
    assert chat_calls[0]["url"] == "http://127.0.0.1:1234/api/v1/chat"
    assert all("/v1/responses" not in url for _method, url, _data in native_calls)
    assert all("/v1/chat/completions" not in url for _method, url, _data in native_calls)
    assert all("/v1/responses" not in call["url"] for call in chat_calls)
    assert all("/v1/chat/completions" not in call["url"] for call in chat_calls)

    expected_files = {
        "environment.json",
        "run_config.json",
        "load_response_sanitized.json",
        "requests.jsonl",
        "metrics.jsonl",
        "system_samples.jsonl",
        "system_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["model_key"] == "gemma4_e4b_q4km"
    assert run_config["model_id"] == "google/gemma-4-e4b"
    assert run_config["requested_context_length"] == 16_384
    assert run_config["requested_parallel"] == 1
    assert run_config["app_concurrency"] == 1
    assert run_config["generation"]["route"] == "tiny_live_chat"
    assert run_config["generation"]["endpoint_path"] == "/api/v1/chat"
    assert run_config["generation"]["max_output_tokens"] == 64
    assert run_config["input_shape"]["input_chars"] > 0
    assert str(run_config["input_shape"]["input_hash"]).startswith("sha256:")

    load_response = json.loads(
        (run_dir / "load_response_sanitized.json").read_text(encoding="utf-8")
    )
    assert load_response["applied_load_config"]["context_length"] == 16_384
    assert load_response["applied_load_config"]["parallel"] == 1
    assert str(load_response["instance_id_hash"]).startswith("sha256:")

    requests_rows = _read_jsonl(run_dir / "requests.jsonl")
    assert len(requests_rows) == 1
    assert requests_rows[0]["request_role"] == "tiny_live_chat"
    assert requests_rows[0]["endpoint_path"] == "/api/v1/chat"
    assert requests_rows[0]["status"] == "success"
    assert requests_rows[0]["content_nonempty"] is True
    assert requests_rows[0]["raw_prompt_response_stored"] is False
    assert str(requests_rows[0]["input_hash"]).startswith("sha256:")
    assert str(requests_rows[0]["response_hash"]).startswith("sha256:")

    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert len(metrics_rows) == 1
    assert metrics_rows[0]["status"] == "success"
    assert metrics_rows[0]["load_verified"] is True
    assert metrics_rows[0]["content_nonempty"] is True
    assert metrics_rows[0]["responses_called"] is False
    assert metrics_rows[0]["chat_completions_called"] is False

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "l3_8c_gemma4_e4b_tiny_live_smoke_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "environment.json",
            "run_config.json",
            "load_response_sanitized.json",
            "requests.jsonl",
            "metrics.jsonl",
            "system_samples.jsonl",
            "system_summary.json",
            "report.md",
        ],
        "raw_prompt_response_stored": False,
    }

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# LM Studio Lab L3.8c Gemma4 E4B Tiny Live Smoke Report" in report_text
    assert "exactly one `/api/v1/chat` request" in report_text
    assert "No `/v1/responses` or `/v1/chat/completions` calls are allowed" in report_text
    assert "final_user_facing_recommendation | `false`" in report_text

    system_samples_text = (run_dir / "system_samples.jsonl").read_text(encoding="utf-8")
    system_summary_text = (run_dir / "system_summary.json").read_text(encoding="utf-8")
    _assert_safe_system_artifacts(system_samples_text, system_summary_text)

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-l3-8c",
        "raw-l3-8c-response-id-sentinel",
        "raw-l3-8c-output-sentinel",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text


def test_run_l3_8c_gemma4_e4b_tiny_live_smoke_fails_after_artifacts_for_empty_output(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8c_gemma4_e4b_tiny_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke(
        "raw-instance-l3-8c-empty"
    )
    chat_calls, chat_transport = _chat_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke(
        raw_output_text=""
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(ValueError, match="non-empty public output"):
        runner.run_l3_8c_gemma4_e4b_tiny_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8c-empty",
            run_id="l3-8c-empty-output",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-l3-8c-empty"
    assert len(native_calls) == 5
    assert len(chat_calls) == 1
    assert {path.name for path in run_dir.iterdir()} == {
        "environment.json",
        "run_config.json",
        "load_response_sanitized.json",
        "requests.jsonl",
        "metrics.jsonl",
        "system_samples.jsonl",
        "system_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    request_rows = _read_jsonl(run_dir / "requests.jsonl")
    assert len(request_rows) == 1
    assert request_rows[0]["status"] == "empty_output"
    assert request_rows[0]["content_nonempty"] is False
    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert len(metric_rows) == 1
    assert metric_rows[0]["status"] == "empty_output"
    assert metric_rows[0]["content_nonempty"] is False
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"


def test_run_l3_8c_gemma4_e4b_tiny_live_smoke_aborts_before_post_load_when_target_is_preloaded(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8c_gemma4_e4b_tiny_live_smoke_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []
    chat_calls: list[dict[str, object]] = []

    def preloaded_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e4b",
                            "loaded_instances": [
                                {
                                    "instance_id": "raw-preloaded-l3-8c",
                                    "context_length": 16_384,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError("POST /load must not be called when target model is already preloaded")

    def forbidden_chat_transport(
        url: str, payload: dict[str, object], timeout_s: float
    ) -> dict[str, object]:
        chat_calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        raise AssertionError("/api/v1/chat must not be called when target model is preloaded")

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(RuntimeError, match="aborts before POST load"):
        runner.run_l3_8c_gemma4_e4b_tiny_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8c-preloaded",
            run_id="l3-8c-preloaded",
            native_transport=preloaded_native_transport,
            chat_transport=forbidden_chat_transport,
        )

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models")
    ]
    assert chat_calls == []


def test_run_l3_8c_gemma4_e4b_tiny_live_smoke_raises_after_writing_artifacts_when_privacy_scan_fails(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8c_gemma4_e4b_tiny_live_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke(
        "raw-instance-l3-8c-privacy"
    )

    def _leak_prompt_prefix(input_text: str) -> None:
        fake_sampler.samples[0].process_name = input_text.splitlines()[0][:96]

    _chat_calls, chat_transport = _chat_transport_for_l3_8c_gemma4_e4b_tiny_live_smoke(
        raw_response_id="raw-l3-8c-privacy-response-id",
        on_input=_leak_prompt_prefix,
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.8c Gemma E4B tiny live smoke acceptance gate failed: privacy_scan_failed",
    ):
        runner.run_l3_8c_gemma4_e4b_tiny_live_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8c-privacy-fail",
            run_id="l3-8c-privacy-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    run_dir = tmp_path / "run-l3-8c-privacy-fail"
    assert len(native_calls) == 5
    assert (run_dir / "privacy_scan.json").exists()
    assert (run_dir / "report.md").exists()
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "fail"
    assert privacy_scan["violation_count"] >= 1


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["model"].__setitem__("key", "gemma4_e2b_q4km"),
            "L3.8d Gemma E4B strict JSON smoke requires model.key 'gemma4_e4b_q4km'",
        ),
        (
            lambda payload: payload["load"].__setitem__("context_length", 16384),
            "L3.8d Gemma E4B strict JSON smoke requires load.context_length=8192",
        ),
        (
            lambda payload: payload["generation"].__setitem__("route", "tiny_live_chat"),
            "L3.8d Gemma E4B strict JSON smoke requires generation.route 'strict_json_chat_completions'",
        ),
        (
            lambda payload: payload["generation"].__setitem__("endpoint_path", "/api/v1/chat"),
            "L3.8d Gemma E4B strict JSON smoke requires generation.endpoint_path '/v1/chat/completions'",
        ),
        (
            lambda payload: payload["generation"].__setitem__("max_tokens", 256),
            "L3.8d Gemma E4B strict JSON smoke requires generation.max_tokens=512",
        ),
        (
            lambda payload: payload["safety"].__setitem__("generation_allowed", False),
            "L3.8d Gemma E4B strict JSON smoke requires safety.generation_allowed=true",
        ),
        (
            lambda payload: payload["safety"].__setitem__("production_default", True),
            "safety.production_default must remain false",
        ),
        (
            lambda payload: payload["safety"].__setitem__("kv_reuse_proven", True),
            "safety.kv_reuse_proven must remain false",
        ),
        (
            lambda payload: payload["privacy"].__setitem__("store_raw_prompt_response", True),
            "privacy.store_raw_prompt_response must remain false",
        ),
    ],
)
def test_run_l3_8d_gemma4_e4b_strict_json_smoke_rejects_invalid_contract_values(
    tmp_path: Path,
    mutator,
    message: str,
) -> None:
    payload = _load_l3_8d_gemma4_e4b_strict_json_smoke_config_payload()
    mutator(payload)
    config_path = _write_l3_8d_gemma4_e4b_strict_json_smoke_config(tmp_path, payload)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8d-invalid",
            run_id="l3-8d-invalid",
        )


def test_run_l3_8d_gemma4_e4b_strict_json_smoke_runs_exact_native_lifecycle_and_writes_safe_artifacts(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8d_gemma4_e4b_strict_json_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-8d-structured-json",
        model_id="google/gemma-4-e4b",
    )
    chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke(
        model_id="google/gemma-4-e4b"
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
        config_path=config_path,
        run_dir=tmp_path / "run-l3-8d",
        run_id="l3-8d-strict-json-smoke",
        providers={
            "lmstudio_local": "managed_l3_8d_gemma4_e4b_strict_json_smoke_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        chat_transport=chat_transport,
    )

    run_dir = tmp_path / "run-l3-8d"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["decision"] == "l3_8d_strict_json_smoke_pass"
    assert summary["mode"] == "strict_json_smoke"
    assert summary["route"] == "strict_json_chat_completions"
    assert summary["helper_mode"] == "json_schema_single"
    assert summary["requested_context_length"] == 8192
    assert summary["applied_context_length"] == 8192
    assert summary["requested_parallel"] == 1
    assert summary["applied_parallel"] == 1
    assert summary["load_verified"] is True
    assert summary["generation_called"] is True
    assert summary["request_succeeded"] is True
    assert summary["public_output_pass"] is True
    assert summary["reasoning_present"] is False
    assert summary["structured_validation_pass"] is True
    assert summary["structured_gate_status"] == "passed"
    assert summary["cleanup_verified"] is True
    assert summary["final_loaded_instances"] == 0
    assert summary["privacy_scan_status"] == "pass"
    assert summary["live_25k_authorized"] is False
    assert summary["production_default"] is False
    assert summary["wvm_runtime_integration"] is False
    assert summary["kv_reuse_proven"] is False
    assert summary["final_user_facing_recommendation"] is False
    assert summary["generation_allowed"] is True
    assert summary["max_tokens"] == 512
    assert summary["temperature"] == 0

    assert [(method, url) for method, url, _data in native_calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(chat_calls) == 1
    assert chat_calls[0]["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert all("/api/v1/chat" not in call["url"] for call in chat_calls)
    assert all("/v1/responses" not in call["url"] for call in chat_calls)

    expected_files = {
        "environment.json",
        "run_config.json",
        "load_response_sanitized.json",
        "requests.jsonl",
        "metrics.jsonl",
        "structured_errors.jsonl",
        "system_samples.jsonl",
        "system_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["generation"] == {
        "route": "strict_json_chat_completions",
        "helper_mode": "json_schema_single",
        "endpoint_path": "/v1/chat/completions",
        "temperature": 0,
        "max_tokens": 512,
    }
    assert run_config["safety"]["live_25k_authorized"] is False
    assert run_config["safety"]["final_user_facing_recommendation"] is False

    request_rows = _read_jsonl(run_dir / "requests.jsonl")
    metric_rows = _read_jsonl(run_dir / "metrics.jsonl")
    assert len(request_rows) == 1
    assert len(metric_rows) == 1
    assert request_rows[0]["route"] == "strict_json_chat_completions"
    assert request_rows[0]["reasoning_content_present"] is False
    assert request_rows[0]["structured_gate_status"] == "passed"
    assert metric_rows[0]["validation"]["json_parse_pass"] is True
    assert metric_rows[0]["validation"]["schema_pass"] is True
    assert metric_rows[0]["validation"]["business_pass"] is True

    assert (run_dir / "structured_errors.jsonl").read_text(encoding="utf-8") == ""
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["raw_prompt_response_stored"] is False

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "strict JSON chat-completions smoke gate" in report_text
    assert "No `/api/v1/chat` or `/v1/responses` calls are allowed in this gate." in report_text

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "raw-instance-l3-8d-structured-json",
        "raw-l3-7d-response-id-sentinel",
        "http://127.0.0.1:1234",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text


def test_run_l3_8d_gemma4_e4b_strict_json_smoke_fails_for_empty_public_content(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8d_gemma4_e4b_strict_json_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-8d-empty",
        model_id="google/gemma-4-e4b",
    )
    chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke(
        model_id="google/gemma-4-e4b",
        raw_response_id="raw-l3-8d-empty-response-id",
        public_content="   ",
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.8d Gemma E4B strict JSON smoke acceptance gate failed: failed_public_content_empty",
    ):
        runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8d-empty",
            run_id="l3-8d-empty",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    assert len(native_calls) == 5
    assert len(chat_calls) == 1
    request_rows = _read_jsonl(tmp_path / "run-l3-8d-empty" / "requests.jsonl")
    assert request_rows[0]["structured_gate_status"] == "failed_public_content_empty"


def test_run_l3_8d_gemma4_e4b_strict_json_smoke_rejects_reasoning_only_json_response(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8d_gemma4_e4b_strict_json_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-8d-reasoning-only",
        model_id="google/gemma-4-e4b",
    )
    chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke(
        model_id="google/gemma-4-e4b",
        raw_response_id="raw-l3-8d-reasoning-only-response-id",
        public_content="   ",
        reasoning_content=_valid_blocks_json((101, 102))["choices"][0]["message"]["content"],
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.8d Gemma E4B strict JSON smoke acceptance gate failed: failed_reasoning_only_json",
    ):
        runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8d-reasoning-only",
            run_id="l3-8d-reasoning-only",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    assert len(native_calls) == 5
    assert len(chat_calls) == 1
    metric_rows = _read_jsonl(tmp_path / "run-l3-8d-reasoning-only" / "metrics.jsonl")
    assert metric_rows[0]["content_empty"] is True
    assert metric_rows[0]["reasoning_content_present"] is True


def test_run_l3_8d_gemma4_e4b_strict_json_smoke_records_structured_error_on_business_failure(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8d_gemma4_e4b_strict_json_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-8d-business-fail",
        model_id="google/gemma-4-e4b",
    )
    chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke(
        model_id="google/gemma-4-e4b",
        public_content=json.dumps(
            {
                "schema_version": "factual_blocks.v1",
                "status": "success",
                "blocks": [
                    {
                        "block_id": 101,
                        "normalized_text": "Only one block.",
                        "status": "success",
                        "warnings": [],
                    }
                ],
                "warnings": [],
            }
        ),
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.8d Gemma E4B strict JSON smoke acceptance gate failed: structured_validation_failed",
    ):
        runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8d-business-fail",
            run_id="l3-8d-business-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    assert len(native_calls) == 5
    assert len(chat_calls) == 1
    structured_errors = _read_jsonl(
        tmp_path / "run-l3-8d-business-fail" / "structured_errors.jsonl"
    )
    assert len(structured_errors) == 1
    assert structured_errors[0]["error_category"] == "business"


def test_run_l3_8d_gemma4_e4b_strict_json_smoke_aborts_before_post_load_when_target_is_preloaded(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8d_gemma4_e4b_strict_json_smoke_config_path()
    native_calls: list[tuple[str, str, bytes | None]] = []
    chat_calls: list[dict[str, object]] = []

    def preloaded_native_transport(request, timeout_s: float) -> bytes:
        native_calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(native_calls) == 1:
            return json.dumps(
                {
                    "models": [
                        {
                            "key": "google/gemma-4-e4b",
                            "loaded_instances": [
                                {
                                    "instance_id": "preloaded-raw-instance-sentinel",
                                    "context_length": 8192,
                                    "parallel": 1,
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")
        raise AssertionError("POST /load must not be called when target model is already preloaded")

    def forbidden_chat_transport(
        url: str, payload: dict[str, object], timeout_s: float
    ) -> dict[str, object]:
        chat_calls.append({"url": url, "payload": dict(payload), "timeout_s": timeout_s})
        raise AssertionError(
            "/v1/chat/completions must not be called when target model is preloaded"
        )

    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        ValueError,
        match="target model already has loaded instances before host application-owned load",
    ):
        runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8d-preloaded",
            run_id="l3-8d-preloaded",
            native_transport=preloaded_native_transport,
            chat_transport=forbidden_chat_transport,
        )

    assert native_calls == [("GET", "http://127.0.0.1:1234/api/v1/models", None)]
    assert chat_calls == []


def test_run_l3_8d_gemma4_e4b_strict_json_smoke_raises_after_writing_artifacts_when_privacy_scan_fails(
    tmp_path: Path,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _l3_8d_gemma4_e4b_strict_json_smoke_config_path()
    native_calls, native_transport = _native_transport_for_l3_7d_structured_json_live_smoke(
        "raw-instance-l3-8d-privacy-fail",
        model_id="google/gemma-4-e4b",
    )

    def _leak_base_url(_prompt_text: str) -> None:
        fake_sampler.samples[0].process_name = "http://127.0.0.1:1234"

    _chat_calls, chat_transport = _chat_transport_for_l3_7d_structured_json_live_smoke(
        model_id="google/gemma-4-e4b",
        on_prompt=_leak_base_url,
    )
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    with pytest.raises(
        RuntimeError,
        match="L3.8d Gemma E4B strict JSON smoke acceptance gate failed: privacy_scan_failed",
    ):
        runner.run_l3_8d_gemma4_e4b_strict_json_smoke(
            config_path=config_path,
            run_dir=tmp_path / "run-l3-8d-privacy-fail",
            run_id="l3-8d-privacy-fail",
            native_transport=native_transport,
            chat_transport=chat_transport,
        )

    assert len(native_calls) == 5
    privacy_scan = json.loads(
        (tmp_path / "run-l3-8d-privacy-fail" / "privacy_scan.json").read_text(encoding="utf-8")
    )
    assert privacy_scan["status"] == "fail"
    assert privacy_scan["violation_count"] >= 1


@pytest.mark.parametrize(
    ("config_kwargs", "call_kwargs", "message"),
    [
        (
            {
                "experiment_id": "wrong_experiment_id",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
            },
            {},
            "cache/stateful comparison live requires experiment_id 'l3_4_cache_stateful_vs_prefix_gemma4_e2b_live'",
        ),
        (
            {
                "experiment_id": "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "model_key": "gemma4_e4b_q4km",
            },
            {},
            "cache/stateful comparison live requires model key 'gemma4_e2b_q4km'",
        ),
        (
            {
                "experiment_id": "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "context_length": 4096,
            },
            {},
            "cache/stateful comparison live requires context_length=8192",
        ),
        (
            {
                "experiment_id": "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "parallel": 2,
            },
            {},
            "cache/stateful comparison live requires parallel=1",
        ),
        (
            {
                "experiment_id": "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches",),
            },
            {},
            "cache/stateful comparison live requires exactly three modes",
        ),
        (
            {
                "experiment_id": "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "store_prompt_text": True,
            },
            {},
            "privacy.store_prompt_text must remain false for live smoke",
        ),
        (
            {
                "experiment_id": "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "store_response_text": True,
            },
            {},
            "privacy.store_response_text must remain false for live smoke",
        ),
        (
            {
                "experiment_id": "l3_4_cache_stateful_vs_prefix_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
            },
            {"app_concurrency": 2},
            "app_concurrency must be exactly 1 for L3.4 live comparison",
        ),
    ],
)
def test_run_cache_stateful_comparison_live_rejects_out_of_scope_inputs(
    tmp_path: Path,
    config_kwargs: dict[str, object],
    call_kwargs: dict[str, object],
    message: str,
) -> None:
    config_path = _write_live_config(tmp_path, **config_kwargs)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_cache_stateful_comparison_live(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="cache-stateful-compare-invalid",
            **call_kwargs,
        )


def test_run_cache_stateful_instrumentation_live_writes_conservative_streaming_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sampler = _FakeSystemSampler(
        samples=_fake_system_samples(),
        summary=_fake_system_summary(),
    )
    config_path = _write_live_config(
        tmp_path,
        experiment_id="l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
        dataset_id="cache_stateful_smoke",
        modes=("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
    )
    native_calls, native_transport = _native_transport_for_managed_live(
        "raw-instance-cache-stateful-instrument-live"
    )
    clock = _ManualClock()
    monkeypatch.setattr(managed_runner_module, "_live_request_perf_counter", clock.now)
    streaming_calls, streaming_transport = _managed_cache_instrumentation_live_transport(clock)
    runner = ManagedLabRunner(lambda request: None, system_sampler=fake_sampler)

    summary = runner.run_cache_stateful_instrumentation_live(
        config_path=config_path,
        run_dir=tmp_path / "run",
        run_id="cache-stateful-instrument-live",
        providers={
            "lmstudio_local": "managed_cache_instrument_live_test",
            "support_ref": PRIVATE_PROVIDER_URL,
            "disk_label": PRIVATE_PROVIDER_PATH,
        },
        native_transport=native_transport,
        streaming_transport=streaming_transport,
    )

    run_dir = tmp_path / "run"
    assert fake_sampler.start_calls == 1
    assert fake_sampler.stop_calls == 1
    assert summary["mode"] == "managed_runner_cache_stateful_instrumentation_live"
    assert summary["managed_live"] is True
    assert summary["run_id"] == "cache-stateful-instrument-live"
    assert summary["model_key"] == "gemma4_e2b_q4km"
    assert summary["model_id"] == "google/gemma-4-e2b"
    assert summary["requested_context_length"] == 8192
    assert summary["requested_parallel"] == 1
    assert summary["instrumentation_status"] == "ttft_prompt_processing_available"
    assert summary["ttft_available"] is True
    assert summary["prompt_processing_available"] is True
    assert summary["cached_tokens_available"] is False
    assert summary["measurement_status"] == "inconclusive"
    assert summary["reuse_verdict"] == "kv_reuse_unproven"
    assert summary["kv_reuse_proven"] is False
    assert summary["stateful_functional_ok"] is True
    assert summary["root_success_count_by_mode"] == {
        "stateful_root_branches": 1,
        "stateless_full_prefix": 0,
        "compact_memory": 0,
    }
    assert summary["branch_count_by_mode"] == {
        "stateful_root_branches": 2,
        "stateless_full_prefix": 2,
        "compact_memory": 2,
    }
    assert summary["branch_success_count_by_mode"] == {
        "stateful_root_branches": 2,
        "stateless_full_prefix": 2,
        "compact_memory": 2,
    }
    assert summary["average_total_latency_ms_by_mode"] == {
        "stateful_root_branches": 66.667,
        "stateless_full_prefix": 125.0,
        "compact_memory": 60.0,
    }
    assert summary["average_ttft_ms_by_mode"] == {
        "stateful_root_branches": 33.333,
        "stateless_full_prefix": 85.0,
        "compact_memory": 43.5,
    }
    assert summary["average_prompt_processing_ms_by_mode"] == {
        "stateful_root_branches": 20.0,
        "stateless_full_prefix": 60.0,
        "compact_memory": 30.0,
    }
    assert summary["stateful_branch_avg_prompt_processing_ms"] == 15.0
    assert summary["stateless_full_prefix_branch_avg_prompt_processing_ms"] == 60.0
    assert summary["compact_memory_branch_avg_prompt_processing_ms"] == 30.0
    assert summary["cache_proxy"] == 4.0
    assert summary["load_verified"] is True
    assert summary["parallel_verified"] is True
    assert summary["cleanup_status"] == "cleanup_verified"
    assert summary["cleanup_verified_count"] == 1
    assert summary["final_loaded_instances"] == 0
    assert summary["raw_prompt_response_stored"] is False
    assert summary["production_default"] is False

    assert [(method, url) for method, url, _data in native_calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert len(streaming_calls) == 7
    assert all(call["url"] == "http://127.0.0.1:1234/api/v1/chat" for call in streaming_calls)
    assert streaming_calls[1]["payload"]["previous_response_id"] == "raw-root-state-id-sentinel"
    assert streaming_calls[2]["payload"]["previous_response_id"] == "raw-root-state-id-sentinel"
    assert "previous_response_id" not in streaming_calls[3]["payload"]
    assert "previous_response_id" not in streaming_calls[5]["payload"]
    assert {call["payload"]["stream"] for call in streaming_calls} == {True}

    expected_files = {
        "environment.json",
        "experiment.yaml",
        "run_config.json",
        "requests.jsonl",
        "metrics.jsonl",
        "cache_instrumentation_summary.json",
        "privacy_scan.json",
        "report.md",
        "system_samples.jsonl",
        "system_summary.json",
    }
    assert expected_files == {path.name for path in run_dir.iterdir()}

    requests_rows = _read_jsonl(run_dir / "requests.jsonl")
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    summary_payload = json.loads(
        (run_dir / "cache_instrumentation_summary.json").read_text(encoding="utf-8")
    )
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert len(requests_rows) == 7
    assert len(metrics_rows) == 7
    assert {row["status"] for row in requests_rows} == {"success"}
    assert {row["status"] for row in metrics_rows} == {"success"}
    assert {row["measurement_status"] for row in requests_rows} == {"inconclusive"}
    assert {row["measurement_status"] for row in metrics_rows} == {"inconclusive"}
    assert {row["reuse_verdict"] for row in requests_rows} == {"kv_reuse_unproven"}
    assert {row["reuse_verdict"] for row in metrics_rows} == {"kv_reuse_unproven"}
    assert {row["raw_prompt_response_stored"] for row in requests_rows} == {False}
    assert {row["raw_prompt_response_stored"] for row in metrics_rows} == {False}
    assert {row["kv_reuse_proven"] for row in requests_rows} == {False}
    assert {row["kv_reuse_proven"] for row in metrics_rows} == {False}
    assert {row["stateful_functional_ok"] for row in requests_rows} == {True}
    assert {row["stateful_functional_ok"] for row in metrics_rows} == {True}
    assert [row["mode"] for row in requests_rows] == [
        "stateful_root_branches",
        "stateful_root_branches",
        "stateful_root_branches",
        "stateless_full_prefix",
        "stateless_full_prefix",
        "compact_memory",
        "compact_memory",
    ]
    assert [row["total_latency_ms"] for row in requests_rows] == [
        100.0,
        40.0,
        60.0,
        120.0,
        130.0,
        55.0,
        65.0,
    ]
    assert [row["ttft_ms"] for row in requests_rows] == [45.0, 25.0, 30.0, 80.0, 90.0, 42.0, 45.0]
    assert [row["stream_ttft_ms"] for row in requests_rows] == [
        45.0,
        25.0,
        30.0,
        80.0,
        90.0,
        42.0,
        45.0,
    ]
    assert [row["stats_ttft_ms"] for row in requests_rows] == [
        50.0,
        30.0,
        35.0,
        85.0,
        95.0,
        47.0,
        50.0,
    ]
    assert [row["prompt_processing_ms"] for row in requests_rows] == [
        30.0,
        15.0,
        15.0,
        60.0,
        60.0,
        30.0,
        30.0,
    ]
    assert {row["prompt_processing_events_seen"] for row in requests_rows} == {True}
    assert {row["prompt_processing_events_seen"] for row in metrics_rows} == {True}
    assert {row["cached_tokens"] for row in requests_rows} == {None}
    assert {row["cache_proxy"] for row in requests_rows} == {None}
    assert {"privacy_redaction_count" in row for row in requests_rows} == {False}
    assert {"privacy_redaction_count" in row for row in metrics_rows} == {False}
    assert requests_rows[0]["request_kind"] == "stateful_root"
    assert requests_rows[1]["request_kind"] == "stateful_branch"
    assert requests_rows[1]["used_previous_root_state"] is True
    assert requests_rows[1]["previous_state_hash"] == requests_rows[0]["state_id_hash"]
    assert requests_rows[3]["request_kind"] == "stateless_full_prefix_branch"
    assert requests_rows[3]["used_previous_root_state"] is False
    assert requests_rows[5]["request_kind"] == "compact_memory_branch"
    assert requests_rows[5]["compact_memory_hash"].startswith("sha256:")
    assert requests_rows[5]["estimated_memory_tokens"] is not None
    assert {row["output_hash"].startswith("sha256:") for row in requests_rows} == {True}
    assert {row["output_hash"].startswith("sha256:") for row in metrics_rows} == {True}
    assert {row["output_chars"] > 0 for row in requests_rows} == {True}
    assert {row["output_chars"] > 0 for row in metrics_rows} == {True}
    assert run_config["native_streaming"] is True
    assert run_config["comparison_modes"] == [
        "stateful_root_branches",
        "stateless_full_prefix",
        "compact_memory",
    ]
    assert run_config["root_request"]["prompt_hash"].startswith("sha256:")
    assert run_config["compact_memory_branch_requests"][0]["compact_memory_hash"].startswith(
        "sha256:"
    )
    assert summary_payload["prompt_processing_available"] is True
    assert summary_payload["average_prompt_processing_ms_by_mode"] == {
        "compact_memory": 30.0,
        "stateful_root_branches": 20.0,
        "stateless_full_prefix": 60.0,
    }
    assert summary_payload["stateful_branch_avg_prompt_processing_ms"] == 15.0
    assert summary_payload["stateless_full_prefix_branch_avg_prompt_processing_ms"] == 60.0
    assert summary_payload["cache_proxy"] == 4.0
    assert "privacy_redaction_count" not in summary_payload
    assert summary_payload["prompt_processing_available"] != "[REDACTED]"
    assert summary_payload["average_prompt_processing_ms_by_mode"] != "[REDACTED]"

    experiment_payload = yaml.safe_load((run_dir / "experiment.yaml").read_text(encoding="utf-8"))
    assert (
        experiment_payload["experiment_id"]
        == "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live"
    )
    assert experiment_payload["lmstudio_base_url"] == "redacted_local_lmstudio_url"
    assert experiment_payload["modes"] == [
        "stateful_root_branches",
        "stateless_full_prefix",
        "compact_memory",
    ]
    assert experiment_payload["datasets"] == ["cache_stateful_smoke"]

    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    assert privacy_scan == {
        "status": "pass",
        "violation_count": 0,
        "scan_scope": "cache_stateful_instrumentation_live_raw_url_path_private_value_scan",
        "scanned_artifacts": [
            "environment.json",
            "experiment.yaml",
            "run_config.json",
            "requests.jsonl",
            "metrics.jsonl",
            "cache_instrumentation_summary.json",
            "report.md",
            "system_summary.json",
            "system_samples.jsonl",
        ],
        "raw_prompt_response_stored": False,
    }

    all_artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    for forbidden in (
        "http://127.0.0.1:1234",
        "raw-instance-cache-stateful-instrument-live",
        "raw-root-state-id-sentinel",
        "raw-stateful-summary-state-id-sentinel",
        "raw-stateful-glossary-state-id-sentinel",
        "raw-stateless-summary-state-id-sentinel",
        "raw-stateless-glossary-state-id-sentinel",
        "raw-compact-summary-state-id-sentinel",
        "raw-compact-glossary-state-id-sentinel",
        "raw-root-output-sentinel",
        "raw-stateful-summary-output-sentinel",
        "raw-stateful-glossary-output-sentinel",
        "raw-stateless-summary-output-sentinel",
        "raw-stateless-glossary-output-sentinel",
        "raw-compact-summary-output-sentinel",
        "raw-compact-glossary-output-sentinel",
        "raw-root-delta-sentinel",
        "Synthetic lecture transcript for cache/stateful lab smoke.",
        "Provide a short summary of the synthetic lecture in 3 bullet points with no extra preface.",
        "List a short glossary with 5 terms from the synthetic lecture and brief definitions.",
        "Compact memory: synthetic lecture covers queue warmup checkpoints",
        PRIVATE_PROVIDER_URL,
        PRIVATE_PROVIDER_PATH,
    ):
        assert forbidden not in all_artifact_text
    assert '"cache_hit": true' not in all_artifact_text
    assert '"branch_ttft_improved": true' not in all_artifact_text
    assert '"kv_reuse_proven": true' not in all_artifact_text


@pytest.mark.parametrize(
    ("config_kwargs", "call_kwargs", "message"),
    [
        (
            {
                "experiment_id": "wrong_experiment_id",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
            },
            {},
            "cache/stateful instrumentation live requires experiment_id 'l3_4b_cache_stateful_instrumentation_gemma4_e2b_live'",
        ),
        (
            {
                "experiment_id": "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "model_key": "gemma4_e4b_q4km",
            },
            {},
            "cache/stateful instrumentation live requires model key 'gemma4_e2b_q4km'",
        ),
        (
            {
                "experiment_id": "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "context_length": 4096,
            },
            {},
            "cache/stateful instrumentation live requires context_length=8192",
        ),
        (
            {
                "experiment_id": "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "parallel": 2,
            },
            {},
            "cache/stateful instrumentation live requires parallel=1",
        ),
        (
            {
                "experiment_id": "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches",),
            },
            {},
            "cache/stateful instrumentation live requires exactly three modes",
        ),
        (
            {
                "experiment_id": "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "store_prompt_text": True,
            },
            {},
            "privacy.store_prompt_text must remain false for live smoke",
        ),
        (
            {
                "experiment_id": "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
                "store_response_text": True,
            },
            {},
            "privacy.store_response_text must remain false for live smoke",
        ),
        (
            {
                "experiment_id": "l3_4b_cache_stateful_instrumentation_gemma4_e2b_live",
                "dataset_id": "cache_stateful_smoke",
                "modes": ("stateful_root_branches", "stateless_full_prefix", "compact_memory"),
            },
            {"app_concurrency": 2},
            "app_concurrency must be exactly 1 for L3.4b live instrumentation",
        ),
    ],
)
def test_run_cache_stateful_instrumentation_live_rejects_out_of_scope_inputs(
    tmp_path: Path,
    config_kwargs: dict[str, object],
    call_kwargs: dict[str, object],
    message: str,
) -> None:
    config_path = _write_live_config(tmp_path, **config_kwargs)
    runner = ManagedLabRunner(lambda request: None)

    with pytest.raises(ValueError, match=message):
        runner.run_cache_stateful_instrumentation_live(
            config_path=config_path,
            run_dir=tmp_path / "run",
            run_id="cache-stateful-instrument-invalid",
            **call_kwargs,
        )
