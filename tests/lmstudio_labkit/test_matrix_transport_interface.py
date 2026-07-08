from __future__ import annotations

import json

from lmstudio_labkit import BenchmarkConfig, FakeTransport, MatrixTransport, plan_matrix


def minimal_payload() -> dict[str, object]:
    return {
        "run_id": "transport_interface",
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


def test_fake_transport_satisfies_matrix_transport_protocol() -> None:
    config = BenchmarkConfig.from_dict(minimal_payload())
    request_plan = plan_matrix(config).cells[0].to_request_plan()
    transport: MatrixTransport = FakeTransport()

    raw_response, result = transport.execute(request_plan, attempt_index=1)

    assert json.loads(raw_response) == {"id": "ok", "text": "Synthetic response"}
    assert result.status == "ok"
    assert result.raw_response_char_count == len(raw_response)
