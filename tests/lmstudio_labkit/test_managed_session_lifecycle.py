from __future__ import annotations

import json
from typing import Any

from lmstudio_labkit.live_bridge import LiveBridgeOptions
from lmstudio_labkit.schema_builders import build_simple_flat_schema

from lmstudio_labkit import (
    BenchmarkConfig,
    ManagedLMStudioExecutor,
    ManagedLMStudioTransport,
    plan_matrix,
    run_matrix,
)


class SessionLifecycleHostRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.loaded_instances = 0
        self.chat_count = 0
        self.invisible_after_load = False
        self.cleanup_leaves_loaded = False

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append("load_model")
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(self, **kwargs: object) -> object:
        self.calls.append("chat_completion")
        self.chat_count += 1
        payload = {"id": "ok", "text": f"Synthetic response {self.chat_count}"}
        return {
            "choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append("cleanup_model")
        if not self.cleanup_leaves_loaded:
            self.loaded_instances = 0
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        self.calls.append("count_loaded_instances")
        if self.invisible_after_load and "load_model" in self.calls:
            return 0
        return self.loaded_instances


def session_payload() -> dict[str, Any]:
    return {
        "run_id": "managed_session_lifecycle",
        "models": [
            {"model_key": "mock", "model_id": "mock/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "session_task",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "prompt": "Synthetic prompt",
                "schema": build_simple_flat_schema(),
                "expected_ids": ["ok"],
                "id_paths": ["id"],
                "expected_output": {"id": "ok", "text": "Synthetic response"},
                "min_length_ratio": 0.1,
                "max_length_ratio": 5.0,
            }
        ],
        "axes": {
            "modality": ["text"],
            "language": ["en_en"],
            "structure_complexity": ["simple"],
            "volume": ["single"],
            "context_tier": ["8192"],
            "schema_variant": ["baseline_loose"],
            "retry_policy": ["off"],
            "execution_mode": ["session_loaded"],
            "cache_mode": ["warmup_first"],
            "execution_target": ["remote_link"],
            "resource_telemetry_mode": ["timing_only"],
            "text_interaction_mode": ["same_text_repeat"],
        },
        "repeats": 3,
        "safety": {
            "live": True,
            "allow_model_loads": True,
            "allow_remote_base_url": True,
            "max_requests": 3,
            "max_repeats": 3,
        },
    }


def test_managed_executor_session_loads_once_for_multiple_requests() -> None:
    host = SessionLifecycleHostRunner()
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    config_payload = session_payload()
    config_payload["safety"] = {"max_requests": 3, "max_repeats": 3}
    config = BenchmarkConfig.from_dict(config_payload)
    plans = tuple(cell.to_request_plan() for cell in plan_matrix(config).cells)

    results = executor.execute_session(plans)

    assert len(results) == 3
    assert host.calls == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "chat_completion",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]
    assert all(result.cleanup_verified for result in results)
    assert all(result.final_loaded_instances == 0 for result in results)


def test_run_matrix_session_loaded_uses_one_lifecycle_for_repeated_cells(tmp_path) -> None:  # type: ignore[no-untyped-def]
    host = SessionLifecycleHostRunner()
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    )

    artifacts = run_matrix(
        BenchmarkConfig.from_dict(session_payload()),
        tmp_path,
        transport=transport,
        live_options=LiveBridgeOptions(
            live=True,
            allow_model_load=True,
            allow_remote=True,
            max_requests=3,
        ),
    )

    assert host.calls == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "chat_completion",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]
    rows = [
        json.loads(line)
        for line in artifacts.cell_results.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert [row["repeat_index"] for row in rows] == [0, 1, 2]
    assert [row["warmup_request_index"] for row in rows] == [1, 2, 3]
    assert [row["is_warmup_request"] for row in rows] == [True, False, False]
    assert all(row["axes"]["execution_mode"] == "session_loaded" for row in rows)
    assert all(row["status"] == "pass" for row in rows)
    assert len({row["session_id"] for row in rows}) == 1
    assert [row["request_index"] for row in rows] == [1, 2, 3]
    assert [row["count"] for row in rows] == [3, 3, 3]
    assert [row["load_scope"] for row in rows] == ["per_session", "per_session", "per_session"]
    assert [row["cleanup_scope"] for row in rows] == ["per_session", "per_session", "per_session"]
    assert [row["loaded_before_session"] for row in rows] == [0, 0, 0]
    assert [row["loaded_after_session_load"] for row in rows] == [1, 1, 1]
    assert [row["final_loaded_instances"] for row in rows] == [0, 0, 0]
    assert [row["session_cleanup_verified"] for row in rows] == [True, True, True]
    assert [row["cache_hit_reported"] for row in rows] == ["unknown", "unknown", "unknown"]
    assert [row["kv_reuse_proven"] for row in rows] == [False, False, False]


def cold_payload() -> dict[str, Any]:
    payload = session_payload()
    payload["run_id"] = "managed_cold_lifecycle"
    payload["axes"] = {
        **payload["axes"],
        "execution_mode": ["cold_per_request"],
        "cache_mode": ["none"],
    }
    return payload


def bad_warmup_payload() -> dict[str, Any]:
    payload = cold_payload()
    payload["axes"] = {**payload["axes"], "cache_mode": ["warmup_first"]}
    return payload


def test_run_matrix_cold_per_request_loads_and_cleans_each_cell(tmp_path) -> None:  # type: ignore[no-untyped-def]
    host = SessionLifecycleHostRunner()
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    )

    artifacts = run_matrix(
        BenchmarkConfig.from_dict(cold_payload()),
        tmp_path,
        transport=transport,
        live_options=LiveBridgeOptions(
            live=True,
            allow_model_load=True,
            allow_remote=True,
            max_requests=3,
        ),
    )

    assert host.calls == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "chat_completion",
        "cleanup_model",
        "count_loaded_instances",
    ]
    rows = [
        json.loads(line)
        for line in artifacts.cell_results.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert [row["load_scope"] for row in rows] == ["per_request", "per_request", "per_request"]
    assert [row["cleanup_scope"] for row in rows] == ["per_request", "per_request", "per_request"]
    assert len({row["session_id"] for row in rows}) == 3
    assert [row["request_index"] for row in rows] == [1, 1, 1]
    assert [row["count"] for row in rows] == [1, 1, 1]
    assert [row["final_loaded_instances"] for row in rows] == [0, 0, 0]


def test_warmup_first_fails_fast_without_session_loaded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    host = SessionLifecycleHostRunner()
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    )

    try:
        run_matrix(
            BenchmarkConfig.from_dict(bad_warmup_payload()),
            tmp_path,
            transport=transport,
            live_options=LiveBridgeOptions(
                live=True,
                allow_model_load=True,
                allow_remote=True,
                max_requests=3,
            ),
        )
    except Exception as error:
        assert "warmup_first requires execution_mode=session_loaded" in str(error)
    else:
        raise AssertionError("warmup_first without session_loaded should fail fast")
    assert host.calls == []


def test_session_loaded_rejects_dirty_preload_state() -> None:
    host = SessionLifecycleHostRunner()
    host.loaded_instances = 1
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    config_payload = session_payload()
    config_payload["safety"] = {"max_requests": 3, "max_repeats": 3}
    plans = tuple(
        cell.to_request_plan()
        for cell in plan_matrix(BenchmarkConfig.from_dict(config_payload)).cells
    )

    try:
        executor.execute_session(plans)
    except Exception as error:
        assert "refuses to reuse dirty loaded state" in str(error)
    else:
        raise AssertionError("dirty pre-load state should fail")
    assert host.calls == ["count_loaded_instances"]


def test_session_loaded_rejects_post_load_invisible_instance() -> None:
    host = SessionLifecycleHostRunner()
    host.invisible_after_load = True
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    config_payload = session_payload()
    config_payload["safety"] = {"max_requests": 3, "max_repeats": 3}
    plans = tuple(
        cell.to_request_plan()
        for cell in plan_matrix(BenchmarkConfig.from_dict(config_payload)).cells
    )

    try:
        executor.execute_session(plans)
    except Exception as error:
        assert "loaded instance was not visible" in str(error)
    else:
        raise AssertionError("post-load invisible instance should fail")
    assert host.calls == [
        "count_loaded_instances",
        "load_model",
        "count_loaded_instances",
        "cleanup_model",
        "count_loaded_instances",
    ]


def test_session_loaded_rejects_cleanup_non_zero_final_state() -> None:
    host = SessionLifecycleHostRunner()
    host.cleanup_leaves_loaded = True
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)
    config_payload = session_payload()
    config_payload["safety"] = {"max_requests": 3, "max_repeats": 3}
    plans = tuple(
        cell.to_request_plan()
        for cell in plan_matrix(BenchmarkConfig.from_dict(config_payload)).cells
    )

    try:
        executor.execute_session(plans)
    except Exception as error:
        assert "final loaded instances must be zero" in str(error)
    else:
        raise AssertionError("cleanup non-zero final state should fail")
    assert host.calls[-2:] == ["cleanup_model", "count_loaded_instances"]
