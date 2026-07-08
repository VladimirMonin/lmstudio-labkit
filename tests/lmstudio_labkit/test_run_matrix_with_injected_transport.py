from __future__ import annotations

import json
from pathlib import Path

from lmstudio_labkit import BenchmarkConfig, RequestPlan, RequestResult, run_matrix


class CountingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, bool]] = []

    def execute(self, plan: RequestPlan, *, attempt_index: int = 1) -> tuple[str, RequestResult]:
        self.calls.append((plan.cell_id, attempt_index, plan.options.live))
        raw_response = json.dumps({"id": "ok", "text": "Synthetic response"})
        return raw_response, RequestResult.from_raw_response(
            request_id=plan.envelope.request_id,
            model_id=plan.options.model_id,
            raw_response=raw_response,
            status="ok",
            latency_ms=1.25,
            token_counts={"prompt": 10, "completion": 20},
            finish_reason="stop",
        )


def minimal_payload() -> dict[str, object]:
    return {
        "run_id": "injected_transport",
        "models": [
            {"model_key": "fake", "model_id": "fake/text", "supported_modalities": ["text"]}
        ],
        "tasks": [
            {
                "task_id": "t",
                "family": "simple_flat",
                "modality": "text",
                "language": "en_en",
                "prompt": "Synthetic prompt",
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


def test_run_matrix_uses_injected_transport_and_writes_only_safe_artifacts(tmp_path: Path) -> None:
    config = BenchmarkConfig.from_dict(minimal_payload())
    transport = CountingTransport()

    artifacts = run_matrix(config, tmp_path, transport=transport)

    assert len(transport.calls) == 1
    assert transport.calls[0][1:] == (1, False)
    cell_results = artifacts.cell_results.read_text(encoding="utf-8")
    assert "Synthetic response" not in cell_results
    assert "response_hash" in cell_results
    assert json.loads(artifacts.privacy_scan.read_text(encoding="utf-8"))["status"] == "pass"
