from __future__ import annotations

import json

from lmstudio_labkit.benchmarks import BenchmarkConfig, ModelSpec, TaskSpec, plan_matrix, run_matrix

import lmstudio_labkit
from lmstudio_labkit import RequestEnvelope, ResponseContract


def test_public_facade_exports_request_core_symbols() -> None:
    envelope = RequestEnvelope.text(
        "req-1",
        "private prompt text",
        local_path="/home/private/input.md",
    )

    metadata = envelope.safe_metadata()

    assert lmstudio_labkit.RequestEnvelope is RequestEnvelope
    assert metadata["text_inputs"][0]["char_count"] == len("private prompt text")
    assert metadata["text_inputs"][0]["text_hash"]
    assert "private prompt text" not in json.dumps(metadata, ensure_ascii=False)
    assert "/home/private/input.md" not in json.dumps(metadata, ensure_ascii=False)
    assert metadata["metadata"]["local_path"]["value_hash"]


def test_request_core_supports_chat_image_and_contract_metadata_without_raw_content() -> None:
    image = lmstudio_labkit.ImageInput(
        content_hash="sha256:public-fixture",
        width=640,
        height=480,
    )
    envelope = RequestEnvelope.image(
        "img-1",
        image,
        prompt="describe the public fixture",
    )

    metadata = envelope.safe_metadata()

    assert metadata["modality"] == "image"
    assert metadata["image_inputs"] == [
        {
            "kind": "image",
            "label": "image",
            "content_hash": "sha256:public-fixture",
            "mime_type": "image/png",
            "width": 640,
            "height": 480,
        }
    ]
    assert "describe the public fixture" not in json.dumps(metadata, ensure_ascii=False)


def test_offline_matrix_runner_writes_privacy_safe_artifacts(tmp_path) -> None:
    schema = {
        "type": "object",
        "required": ["id", "text"],
        "properties": {
            "id": {"const": "expected-1"},
            "text": {"type": "string"},
        },
    }
    config = BenchmarkConfig(
        run_id="offline-smoke",
        models=(ModelSpec(model_key="fake", model_id="fake/model"),),
        tasks=(
            TaskSpec(
                task_id="task-1",
                family="simple_flat",
                prompt="private task prompt",
                schema=schema,
                expected_output={"id": "expected-1", "text": "ok"},
                expected_ids=("expected-1",),
            ),
        ),
        axes={"modality": ("text",), "language": ("en_en",)},
    )

    plan = plan_matrix(config)
    artifacts = run_matrix(config, tmp_path)

    assert plan.cells
    assert artifacts.planner_summary_path.exists()
    assert artifacts.cell_results_path.exists()
    assert artifacts.privacy_scan_path.exists()
    assert artifacts.report_path.exists()

    planner_summary = json.loads(artifacts.planner_summary_path.read_text(encoding="utf-8"))
    cell_results = artifacts.cell_results_path.read_text(encoding="utf-8")
    privacy_scan = json.loads(artifacts.privacy_scan_path.read_text(encoding="utf-8"))

    assert planner_summary["cell_count"] == 1
    assert privacy_scan["status"] == "pass"
    assert "private task prompt" not in cell_results
    assert "expected-1" in cell_results


def test_default_runner_rejects_live_execution(tmp_path) -> None:
    config = BenchmarkConfig(
        run_id="live-blocked",
        models=(ModelSpec(model_key="fake", model_id="fake/model"),),
        tasks=(TaskSpec(task_id="task-1", family="plain", prompt="hello"),),
        axes={"modality": ("text",)},
    )

    try:
        run_matrix(config, tmp_path, live=True)
    except ValueError as error:
        assert "Live LM Studio execution is not implemented" in str(error)
    else:  # pragma: no cover - defensive assertion for explicit live guard
        raise AssertionError("run_matrix should reject live=True")


def test_request_envelope_rejects_invalid_image_shape() -> None:
    try:
        RequestEnvelope(request_id="bad", modality="image")
    except ValueError as error:
        assert "image modality requires" in str(error)
    else:  # pragma: no cover - defensive assertion for invariant
        raise AssertionError("image requests must include image metadata")


def test_response_contract_metadata_hashes_expected_output() -> None:
    contract = ResponseContract(
        mode="json",
        schema={"type": "object"},
        expected_output={"secret": "do-not-store-raw"},
    )

    metadata = contract.safe_metadata()

    assert metadata["schema_hash"]
    assert metadata["expected_output_hash"]
    assert "do-not-store-raw" not in json.dumps(metadata, ensure_ascii=False)
