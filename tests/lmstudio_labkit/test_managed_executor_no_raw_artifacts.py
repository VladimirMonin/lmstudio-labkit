from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lmstudio_labkit import (
    BenchmarkConfig,
    ChatMessage,
    ExecutionOptions,
    LocalFailureForensics,
    ManagedLMStudioExecutor,
    ManagedLMStudioTransport,
    RequestEnvelope,
    RequestPlan,
    ResponseContract,
    build_simple_flat_schema,
    run_matrix,
)


class MockManagedHostRunner:
    def __init__(self) -> None:
        self.loaded_instances = 0

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(self, **kwargs: object) -> object:
        return {
            "choices": [
                {
                    "message": {"content": json.dumps({"id": "ok", "text": "Synthetic response"})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.loaded_instances = 0
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        return self.loaded_instances


def minimal_payload() -> dict[str, Any]:
    return {
        "run_id": "managed_executor_no_raw",
        "models": [
            {"model_key": "mock", "model_id": "mock/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "t",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "prompt": "Synthetic prompt",
                "schema": build_simple_flat_schema(),
                "expected_output": {"id": "ok", "text": "Synthetic response"},
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
        },
        "safety": {"max_requests": 1},
    }


def structured_plan() -> RequestPlan:
    return RequestPlan(
        cell_id="managed-cell",
        envelope=RequestEnvelope(
            request_id="managed-cell",
            modality="text",
            chat_messages=(ChatMessage(role="user", content="Return structured JSON"),),
            response_contract=ResponseContract(
                mode="json",
                schema=build_simple_flat_schema(),
                expected_output={"id": "ok", "text": "Synthetic response"},
            ),
        ),
        options=ExecutionOptions(
            model_id="mock/text",
            endpoint_family="openai_compat",
            context_tier="8192",
            temperature=0.0,
            timeout_s=30.0,
            live=True,
        ),
    )


def test_managed_executor_transport_returns_safe_result_metadata_only() -> None:
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(host_runner=MockManagedHostRunner(), allow_model_loads=True)
    )

    raw_response, result = transport.execute(structured_plan())

    assert json.loads(raw_response) == {"id": "ok", "text": "Synthetic response"}
    safe_metadata = result.safe_metadata()
    assert safe_metadata["response_hash"] == result.raw_response_hash
    assert "Synthetic response" not in json.dumps(safe_metadata)
    assert safe_metadata["token_counts"] == {"prompt": 7, "completion": 5}


def test_run_matrix_with_managed_executor_writes_no_raw_response_artifacts(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(minimal_payload())
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(host_runner=MockManagedHostRunner(), allow_model_loads=True)
    )

    artifacts = run_matrix(config, tmp_path, transport=transport)

    cell_results = artifacts.cell_results.read_text(encoding="utf-8")
    summary = artifacts.planner_summary.read_text(encoding="utf-8")
    assert "Synthetic response" not in cell_results
    assert "Synthetic prompt" not in cell_results
    assert "Synthetic response" not in summary
    assert "response_hash" in cell_results
    assert json.loads(artifacts.privacy_scan.read_text(encoding="utf-8"))["status"] == "pass"


def test_public_artifacts_include_only_sanitized_private_pack_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    private_root = tmp_path / "private-pack"
    forensics = LocalFailureForensics(private_root, repo_root=repo, enabled=True)
    config = BenchmarkConfig.from_dict(minimal_payload())
    transport = ManagedLMStudioTransport(
        ManagedLMStudioExecutor(
            host_runner=MockManagedHostRunner(),
            allow_model_loads=True,
            failure_forensics=forensics,
        )
    )

    artifacts = run_matrix(config, tmp_path / "public", transport=transport)

    cell_results = artifacts.cell_results.read_text(encoding="utf-8")
    assert '"private_local_pack_exists": true' in cell_results
    assert "Synthetic response" not in cell_results
    assert "Synthetic prompt" not in cell_results
    assert str(private_root) not in cell_results
    assert "malformed_tail" not in cell_results
    assert json.loads(artifacts.privacy_scan.read_text(encoding="utf-8"))["status"] == "pass"
