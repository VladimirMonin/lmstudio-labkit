from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from tools.lmstudio_lab.l3_39_family_matrix import (
    DEFAULT_CONTRACT,
    DEFAULT_REPLAY,
    _build_native_png_payload,
    _evaluate_live_row,
    _request_material,
    _rows_pass_stop_gate,
    _run_loaded_batch,
    _session_prerequisites_accepted,
    _unsupported_phase,
    _unsupported_reasoning_reason,
    _verify_exact_model_metadata,
    _vision_transport_canary_accepted,
    aggregate_summaries,
    expand_matrix,
    load_contract,
    load_yaml,
    main,
    replay_private_records,
    verified_resume_rows,
)


def _write_completed_review(path: Path, row: dict[str, object]) -> None:
    import csv

    review = {
        "row_id": row["row_id"],
        "evidence_id": "evidence-1",
        "rubric_version": "v1",
        "reviewer_id_hash": "reviewer-hash",
        "reviewed_private_output": "true",
        "dimension_scores_json": '{"correctness":2}',
        "factual_categories_json": '["correct"]',
        "evidence_category_ids_json": '["fixture-truth"]',
        "final_answer_present": "true",
        "raw_json_valid": "true",
        "normalized_json_valid": "true",
        "schema_valid": "true",
        "grounding_valid": "true",
        "verdict": "accepted",
    }
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(review))
        writer.writeheader()
        writer.writerow(review)


def test_l3_39_plan_has_exact_inventory_taxonomy_and_114_record_budget() -> None:
    contract = load_contract(DEFAULT_CONTRACT)
    rows = expand_matrix(contract)

    assert len(rows) == 114
    assert sum(row["call_planned"] for row in rows) == 108
    assert {row["model_id"] for row in rows if row["call_planned"]} == {
        "google/gemma-4-e2b",
        "google/gemma-4-e4b",
        "google/gemma-4-12b-qat",
        "google/gemma-4-26b-a4b-qat",
        "gemma-4-31b-it",
    }
    live = [row for row in rows if row["call_planned"]]
    assert sum(row["phase"] == "text_structure" for row in live) == 27
    assert sum(row["phase"] == "vision" for row in live) == 36
    assert sum(row["phase"] == "one_shot_context" for row in live) == 15
    assert sum(row["phase"] == "session" for row in live) == 30
    assert all(
        row["reasoning_class"] == "reasoning_omitted_unknown"
        for row in live
        if row["model_id"] == "gemma-4-31b-it"
    )
    assert all("google/gemma-4-31b-qat" not in row["exact_variant"] for row in live)
    assert len({row["row_id"] for row in rows}) == 114


def test_l3_39_live_command_requires_two_explicit_flags(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="requires both --live and --allow-model-loads"):
        main(
            [
                "run-model-phase",
                "--model",
                "google/gemma-4-e2b",
                "--phase",
                "text_structure",
                "--base-url",
                "http://127.0.0.1:1234",
                "--private-dir",
                str(tmp_path / "private"),
                "--output",
                str(tmp_path / "summary.json"),
            ]
        )


def _private_record(root: Path, index: int) -> None:
    marker = f"M-{index}"
    message = f'```json\n{{"marker":"{marker}","status":"ok","warnings":[]}}\n```'
    payload = {
        "request": {"request_id_hash": f"hash-{index}"},
        "attempt": {"index": index, "context_length": 16384, "output_cap": 1024},
        "raw": {"message": message, "reasoning": "private reasoning"},
        "numeric_stats": {
            "stats.total_output_tokens": 20,
            "stats.reasoning_output_tokens": 5,
        },
        "observed": {"finish_reason": "stop"},
    }
    path = root / f"attempt-{index:04d}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)


def test_replay_builds_path_free_raw_free_index_and_validates_after_normalization(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    for index in range(1, 7):
        _private_record(private, index)

    result = replay_private_records(
        source_dir=private,
        replay_contract=load_yaml(DEFAULT_REPLAY),
    )
    encoded = json.dumps(result)

    assert result["record_count"] == 6
    assert result["raw_strict_invalid"] == 6
    assert result["normalized_contract_valid"] == 6
    assert result["regeneration_calls"] == 0
    assert result["semantic_repairs"] == 0
    assert all(row["reasoning_tokens"] == 5 for row in result["records"])
    assert all(row["message_tokens"] == 15 for row in result["records"])
    assert all(row["transformation"] == "single_complete_json_fence" for row in result["records"])
    assert "private reasoning" not in encoded
    assert str(tmp_path) not in encoded
    assert '"marker":"M-' not in encoded


def test_resume_accepts_only_verified_clean_known_rows_with_private_evidence(
    tmp_path: Path,
) -> None:
    planned = expand_matrix(load_contract(DEFAULT_CONTRACT))
    completed = {
        **planned[0],
        "status": "review_required",
        "private_record_exists": True,
    }
    summary = tmp_path / "phase.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "lmstudio-labkit-l339-phase-summary-v1",
                "verified": True,
                "final_loaded_global_count": 0,
                "rows": [completed],
            }
        ),
        encoding="utf-8",
    )

    review = tmp_path / "review.csv"
    _write_completed_review(review, completed)
    resumed = verified_resume_rows(planned, [summary], [review])
    aggregate = aggregate_summaries(planned, [summary], [review])

    assert resumed[0]["status"] == "review_required"
    assert aggregate["row_count"] == 114
    assert aggregate["private_paths_exposed"] is False

    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["final_loaded_global_count"] = 1
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="not verified clean"):
        verified_resume_rows(planned, [summary], [review])


def test_resume_fails_closed_without_completed_private_review(tmp_path: Path) -> None:
    planned = expand_matrix(load_contract(DEFAULT_CONTRACT))
    row = {**planned[0], "status": "review_required", "private_record_exists": True}
    summary = tmp_path / "phase.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "lmstudio-labkit-l339-phase-summary-v1",
                "verified": True,
                "final_loaded_global_count": 0,
                "rows": [row],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="completed private-answer review"):
        verified_resume_rows(planned, [summary])


def test_exact_metadata_and_reasoning_preflight_are_fail_closed() -> None:
    model = load_contract(DEFAULT_CONTRACT)["models"][-1]
    exact = {
        "key": model["model_id"],
        "publisher": model["publisher"],
        "quantization": {
            "name": model["quantization"],
            "bits_per_weight": model["quantization_bits"],
        },
        "architecture": model["architecture"],
        "format": model["format"],
        "capabilities": model["capabilities"],
    }
    artifact = {
        "modelKey": model["model_id"],
        "publisher": model["publisher"],
        "architecture": model["architecture"],
        "format": model["format"],
        "sizeBytes": model["size_bytes"],
        "paramsString": model["params_string"],
        "path": model["exact_variant"],
        "indexedModelIdentifier": model["exact_variant"],
        "quantization": {"name": model["quantization"], "bits": model["quantization_bits"]},
    }
    _verify_exact_model_metadata(exact, model, artifact_metadata=artifact)
    with pytest.raises(RuntimeError, match="artifact metadata mismatch: path"):
        _verify_exact_model_metadata(
            exact,
            model,
            artifact_metadata={**artifact, "path": "google/gemma-4-31b-qat"},
        )
    with pytest.raises(RuntimeError, match="quantization.bits_per_weight"):
        _verify_exact_model_metadata(
            {**exact, "quantization": {"name": "IQ3_XXS", "bits_per_weight": 4}},
            model,
            artifact_metadata=artifact,
        )
    rows = [{"reasoning_class": "on"}]
    assert _unsupported_reasoning_reason(rows, exact) == "reasoning_capability_unknown_zero_call"
    exact["capabilities"] = {"reasoning": {"allowed_options": ["off"]}}
    assert (
        _unsupported_reasoning_reason(rows, exact) == "unsupported_reasoning_options_zero_call:on"
    )


def test_google_metadata_requires_exact_documented_shape_and_capabilities() -> None:
    model = load_contract(DEFAULT_CONTRACT)["models"][0]
    exact = {
        "key": model["model_id"],
        "selected_variant": model["exact_variant"],
        "publisher": "google",
        "architecture": "gemma4",
        "format": "gguf",
        "quantization": {"name": "Q4_K_M", "bits_per_weight": 4},
        "capabilities": model["capabilities"],
    }
    _verify_exact_model_metadata(exact, model)
    with pytest.raises(RuntimeError, match="selected_variant"):
        _verify_exact_model_metadata(
            {**exact, "selected_variant": "google/gemma-4-31b-qat@q4_0"}, model
        )
    with pytest.raises(RuntimeError, match="capabilities"):
        _verify_exact_model_metadata(
            {**exact, "capabilities": {"vision": True, "trained_for_tool_use": True}}, model
        )


def test_executable_verdicts_drive_lane_stop_and_image_grounding() -> None:
    contract = load_contract(DEFAULT_CONTRACT)
    dataset = load_yaml(
        Path(DEFAULT_CONTRACT).parents[1]
        / "structured_matrix/datasets/text/l3_39_family_matrix.yaml"
    )
    rows = expand_matrix(contract, include_replay=False)
    simple = next(
        row for row in rows if row["phase"] == "text_structure" and row["task"] == "simple"
    )
    passed = _evaluate_live_row(
        simple,
        '{"summary":"Проверка завершена","status":"ok","warnings":[]}',
        dataset,
        contract,
    )
    failed = _evaluate_live_row(simple, '{"status":"ok"}', dataset, contract)
    assert passed["raw_json_valid"] is True
    assert passed["normalized_json_valid"] is True
    assert passed["schema_valid"] is True
    assert passed["business_verdict"] == "pass"
    assert failed["schema_valid"] is False
    assert _rows_pass_stop_gate([{**passed, "status": "review_required"}]) is True
    assert _rows_pass_stop_gate([{**failed, "status": "blocked_by_prior_gate"}]) is False

    perception = next(
        row for row in rows if row["phase"] == "vision" and row["task"] == "perception"
    )
    grounded = _evaluate_live_row(
        perception,
        "Настройки модели google/gemma-4-e4b 8192 0.0 JSON-схема Сохранить Отмена",
        dataset,
        contract,
    )
    assert grounded["image_grounding_verdict"] == "pass"


def test_zero_call_rows_and_session_prerequisites_are_explicit() -> None:
    summary = _unsupported_phase(
        [{"row_id": "x", "call_planned": True}],
        "unsupported_reasoning",
        status="unsupported",
    )
    assert summary["rows"][0]["call_planned"] is False
    assert summary["rows"][0]["calls_executed"] == 0
    assert summary["rows"][0]["stop_reason"] == "unsupported_reasoning"
    prerequisites = [
        {
            "phase": "text_structure",
            "task": "simple",
            "schema_valid": True,
            "business_verdict": "pass",
        },
        {
            "phase": "one_shot_context",
            "context_length": 16384,
            "schema_valid": True,
            "business_verdict": "pass",
        },
    ]
    assert _session_prerequisites_accepted(prerequisites) is True
    prerequisites[-1]["business_verdict"] = "fail"
    assert _session_prerequisites_accepted(prerequisites) is False


class _Host:
    def __init__(self) -> None:
        self.loaded = 0
        self.loads = 0
        self.cleanups = 0
        self.requests: list[dict[str, object]] = []

    def count_all_loaded_instances(self) -> int:
        return self.loaded

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        del model_id
        self.loads += 1
        self.loaded = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def cleanup_model(self, *, model_id: str) -> object:
        del model_id
        self.cleanups += 1
        self.loaded = 0
        return {"cleanup_verified": True}

    def native_chat_diagnostic(self, **kwargs: object) -> object:
        self.requests.append(dict(kwargs))
        return SimpleNamespace(
            http_status=200,
            content_type="text/event-stream",
            finish_reason="stop",
            boundary="terminal",
            reasoning_text="",
            message_text='{"status":"ok"}',
            numeric_stats={"stats.total_output_tokens": 4},
            forensics_handle=SimpleNamespace(safe_manifest={"latency_ms": 1.0}),
        )


class _Forensics:
    def __init__(self) -> None:
        self.finalized = 0

    def finalize_attempt(self, handle: object, **kwargs: object) -> None:
        del handle, kwargs
        self.finalized += 1


def test_serial_loaded_batch_enforces_one_load_and_global_zero() -> None:
    host = _Host()
    forensics = _Forensics()
    rows = [
        {
            "row_id": f"row-{index}",
            "phase": "text_structure",
            "task": "simple",
            "reasoning_class": "off",
            "context_length": 8192,
            "max_output_tokens": 1024,
        }
        for index in range(3)
    ]
    dataset = load_yaml(
        Path(DEFAULT_CONTRACT).parents[1]
        / "structured_matrix/datasets/text/l3_39_family_matrix.yaml"
    )
    model = {"model_id": "google/gemma-4-e2b", "exact_variant": "x"}

    output = _run_loaded_batch(
        host,
        forensics,  # type: ignore[arg-type]
        model,
        rows,
        dataset,
        load_contract(DEFAULT_CONTRACT),
    )

    assert len(output) == 3
    assert host.loads == 1
    assert host.cleanups == 1
    assert host.loaded == 0
    assert forensics.finalized == 3
    assert all(row["final_loaded_global_count"] == 0 for row in output)


def test_native_png_payload_contains_exact_approved_bytes_and_safe_metadata() -> None:
    contract = load_contract(DEFAULT_CONTRACT)
    row = next(
        item for item in expand_matrix(contract, include_replay=False) if item["phase"] == "vision"
    )
    dataset = load_yaml(
        Path(DEFAULT_CONTRACT).parents[1]
        / "structured_matrix/datasets/text/l3_39_family_matrix.yaml"
    )

    _, _, data_url, metadata = _request_material(row, dataset, contract)
    assert data_url is not None
    assert data_url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(data_url.partition(",")[2], validate=True)
    fixture = Path(__file__).parents[2] / contract["axes"]["vision"]["fixture_path"]
    assert decoded == fixture.read_bytes()
    assert metadata == {
        "route": "/api/v1/chat",
        "input_types": ["text", "image"],
        "mime_type": "image/png",
        "decoded_byte_count": len(decoded),
        "width": 1024,
        "height": 682,
        "sha256": contract["axes"]["vision"]["image_sha256"],
        "data_url_present": True,
        "raw_data_url_exposed": False,
    }
    assert data_url not in json.dumps(metadata)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.replace("image/png", "image/webp", 1), "PNG data URL"),
        (lambda value: value.partition(",")[2], "PNG data URL"),
        (lambda value: value[:25] + "!" + value[26:], "base64 is invalid"),
        (lambda value: value[:22], "base64 must be non-empty"),
    ],
)
def test_native_png_payload_rejects_missing_malformed_and_wrong_mime(
    mutation: Callable[[str], str], message: str
) -> None:
    from tools.lmstudio_lab.l3_39_family_matrix import _validate_native_png_data_url

    contract = load_contract(DEFAULT_CONTRACT)
    fixture = Path(__file__).parents[2] / contract["axes"]["vision"]["fixture_path"]
    data_url, _ = _build_native_png_payload(
        fixture, expected_sha256=contract["axes"]["vision"]["image_sha256"]
    )
    with pytest.raises(RuntimeError, match=message):
        _validate_native_png_data_url(
            mutation(data_url),
            expected_sha256=contract["axes"]["vision"]["image_sha256"],
        )


def test_native_png_payload_rejects_wrong_hash() -> None:
    contract = load_contract(DEFAULT_CONTRACT)
    fixture = Path(__file__).parents[2] / contract["axes"]["vision"]["fixture_path"]
    with pytest.raises(RuntimeError, match="fixture hash mismatch"):
        _build_native_png_payload(fixture, expected_sha256="0" * 64)


def test_native_png_metadata_rejects_transport_body_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.lmstudio_lab.l3_39_family_matrix as family_matrix

    contract = load_contract(DEFAULT_CONTRACT)
    fixture = Path(__file__).parents[2] / contract["axes"]["vision"]["fixture_path"]
    data_url, _ = _build_native_png_payload(
        fixture, expected_sha256=contract["axes"]["vision"]["image_sha256"]
    )
    monkeypatch.setattr(
        family_matrix,
        "_native_image_input",
        lambda prompt, image: [
            {"type": "message", "content": prompt},
            {"type": "image", "data_url": image},
        ],
    )

    with pytest.raises(RuntimeError, match="text first"):
        family_matrix._validate_native_png_data_url(
            data_url,
            expected_sha256=contract["axes"]["vision"]["image_sha256"],
        )


def test_e2b_off_perception_canary_is_required_before_vision_expansion() -> None:
    accepted = {
        "model_id": "google/gemma-4-e2b",
        "phase": "vision",
        "task": "perception",
        "reasoning_class": "off",
        "status": "review_required",
        "business_verdict": "pass",
        "image_grounding_verdict": "pass",
        "private_record_exists": True,
    }
    assert _vision_transport_canary_accepted([accepted]) is True
    for field, value in (
        ("reasoning_class", "on"),
        ("status", "blocked_by_prior_gate"),
        ("business_verdict", "fail"),
        ("private_record_exists", False),
    ):
        assert _vision_transport_canary_accepted([{**accepted, field: value}]) is False


def test_unsloth_vision_canary_uses_reasoning_omitted_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tools.lmstudio_lab.l3_39_family_matrix as family_matrix

    contract = load_contract(DEFAULT_CONTRACT)
    dataset = load_yaml(
        Path(DEFAULT_CONTRACT).parents[1]
        / "structured_matrix/datasets/text/l3_39_family_matrix.yaml"
    )
    model = contract["models"][-1]
    metadata = {
        "key": model["model_id"],
        "publisher": model["publisher"],
        "quantization": {
            "name": model["quantization"],
            "bits_per_weight": model["quantization_bits"],
        },
        "architecture": model["architecture"],
        "format": model["format"],
        "capabilities": model["capabilities"],
    }
    artifact = {
        "modelKey": model["model_id"],
        "publisher": model["publisher"],
        "architecture": model["architecture"],
        "format": model["format"],
        "sizeBytes": model["size_bytes"],
        "paramsString": model["params_string"],
        "path": model["exact_variant"],
        "indexedModelIdentifier": model["exact_variant"],
        "quantization": {"name": model["quantization"], "bits": model["quantization_bits"]},
    }
    captured: list[dict[str, object]] = []

    class Host:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def count_all_loaded_instances(self) -> int:
            return 0

        def model_metadata(self, *, model_id: str) -> dict[str, object]:
            assert model_id == model["model_id"]
            return metadata

    def fake_batch(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del kwargs
        rows = args[3]
        assert isinstance(rows, list)
        captured.extend(rows)
        return [{**rows[0], "status": "blocked_by_prior_gate", "business_verdict": "fail"}]

    monkeypatch.setattr(family_matrix, "LocalLMStudioHostRunner", Host)
    monkeypatch.setattr(family_matrix, "_read_lms_model_artifact_metadata", lambda _: artifact)
    monkeypatch.setattr(family_matrix, "_run_loaded_batch", fake_batch)
    prerequisite = {
        "model_id": "google/gemma-4-e2b",
        "phase": "vision",
        "task": "perception",
        "reasoning_class": "off",
        "status": "accepted",
        "business_verdict": "pass",
        "image_grounding_verdict": "pass",
        "private_record_exists": True,
    }

    result = family_matrix.run_model_phase(
        contract=contract,
        dataset=dataset,
        model_id=model["model_id"],
        phase="vision",
        base_url="http://127.0.0.1:1234",
        private_dir=tmp_path / "private",
        prerequisite_rows=[prerequisite],
    )

    assert captured[0]["task"] == "perception"
    assert captured[0]["reasoning_class"] == "reasoning_omitted_unknown"
    assert len(result["rows"]) == 4


def test_vision_loaded_batch_sends_png_data_url_to_native_transport() -> None:
    host = _Host()
    forensics = _Forensics()
    contract = load_contract(DEFAULT_CONTRACT)
    row = next(
        item
        for item in expand_matrix(contract, include_replay=False)
        if item["model_id"] == "google/gemma-4-e2b"
        and item["phase"] == "vision"
        and item["task"] == "perception"
        and item["reasoning_class"] == "off"
    )
    dataset = load_yaml(
        Path(DEFAULT_CONTRACT).parents[1]
        / "structured_matrix/datasets/text/l3_39_family_matrix.yaml"
    )
    _run_loaded_batch(
        host,
        forensics,  # type: ignore[arg-type]
        {"model_id": "google/gemma-4-e2b", "exact_variant": "x"},
        [row],
        dataset,
        contract,
    )
    assert len(host.requests) == 1
    sent = host.requests[0]["image_data_url"]
    assert isinstance(sent, str) and sent.startswith("data:image/png;base64,")
    assert len(base64.b64decode(sent.partition(",")[2], validate=True)) > 0
