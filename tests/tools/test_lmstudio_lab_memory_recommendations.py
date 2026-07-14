from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest
from tools.lmstudio_lab.matrix import aggregate_memory_recommendations
from tools.lmstudio_lab.report import write_memory_recommendation_artifacts

from lmstudio_managed.metrics import (
    GpuTelemetryEvidenceLevel,
    MemoryCellObservation,
    MemoryRecommendationCatalog,
    MemoryRecommendationStatus,
    memory_recommendation_catalog_schema,
)


def _observation(
    attempt: int,
    *,
    parallel: int,
    peak: float,
    model_artifact: str = "publisher/model/file.gguf",
) -> MemoryCellObservation:
    return MemoryCellObservation(
        attempt_id=f"p{parallel}-attempt-{attempt}",
        model_artifact=model_artifact,
        artifact_revision="revision-7",
        artifact_checksum="sha256:" + "b" * 64,
        quantization="Q4_K_M",
        context_tokens=8192,
        runtime_parallel=parallel,
        application_concurrency=parallel,
        workload_class="structured_text",
        placement_requirement="full_gpu_required",
        kv_placement="gpu",
        telemetry_evidence=GpuTelemetryEvidenceLevel.NVML_PROCESS_ATTRIBUTED,
        clean_baseline_vram_mb=500.0,
        loaded_idle_vram_mb=9_000.0,
        measured_peak_vram_mb=peak,
        identity_verified=True,
        runtime_shape_verified=True,
        telemetry_valid=True,
        operation_succeeded=True,
        response_integrity_passed=True,
        cleanup_global_zero_passed=True,
        placement_observed=True,
        capacity_fit=True,
        thrash_observed=False,
        overlap_proven=True,
        phase_evidence_valid=True,
        independent_cycle_proven=True,
        immutable_owner_evidence_bound=True,
    )


def test_aggregation_uses_each_measured_lane_without_p1_linear_extrapolation() -> None:
    observations = tuple(
        _observation(attempt, parallel=parallel, peak=peak)
        for parallel, peak in ((1, 10_000.0), (4, 13_250.0))
        for attempt in range(3)
    )

    catalog = aggregate_memory_recommendations(observations)
    by_parallel = {row.runtime_parallel: row for row in catalog.recommendations}

    assert by_parallel[1].measured_peak_vram_mb == 10_000.0
    assert by_parallel[4].measured_peak_vram_mb == 13_250.0
    assert by_parallel[4].measured_peak_vram_mb != by_parallel[1].measured_peak_vram_mb * 4
    assert all(row.status is MemoryRecommendationStatus.APPROVED for row in catalog.recommendations)


def test_recommendation_artifacts_are_cross_format_consistent_and_schema_valid(
    tmp_path: Path,
) -> None:
    catalog = aggregate_memory_recommendations(
        tuple(_observation(attempt, parallel=2, peak=12_000.0 + attempt) for attempt in range(3))
    )

    paths = write_memory_recommendation_artifacts(tmp_path, catalog)
    matrix_json = json.loads(paths["matrix_json"].read_text(encoding="utf-8"))
    catalog_json = json.loads(paths["catalog_json"].read_text(encoding="utf-8"))
    with paths["matrix_csv"].open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    markdown = paths["matrix_markdown"].read_text(encoding="utf-8")

    assert matrix_json == catalog_json
    MemoryRecommendationCatalog.validate_payload(catalog_json)
    assert len(csv_rows) == len(catalog_json["recommendations"]) == 1
    row = catalog_json["recommendations"][0]
    assert csv_rows[0]["artifact_checksum"] == row["artifact_checksum"]
    assert csv_rows[0]["runtime_parallel"] == str(row["runtime_parallel"])
    assert csv_rows[0]["status"] == row["status"]
    assert csv_rows[0]["status_reasons"] == json.dumps(
        row["status_reasons"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert row["artifact_revision"] in markdown
    assert row["artifact_checksum"] in markdown

    schema = json.loads(paths["catalog_schema"].read_text(encoding="utf-8"))
    assert schema["$id"] == catalog_json["schema_revision"]
    assert set(schema["properties"]["recommendations"]["items"]["required"]) <= set(row)
    canonical_schema_path = (
        Path(__file__).parents[2]
        / "experiments/lmstudio/schemas/model_memory_recommendation_catalog_v1.schema.json"
    )
    assert json.loads(canonical_schema_path.read_text(encoding="utf-8")) == (
        memory_recommendation_catalog_schema()
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("context_tokens", True),
        ("runtime_parallel", 0),
        ("measured_peak_vram_mb", float("nan")),
        ("repeat_count", 0),
        ("required_repeats", 2),
    ),
)
def test_catalog_payload_validation_fails_closed_on_invalid_scalar_types(
    field_name: str,
    invalid_value: object,
) -> None:
    catalog = aggregate_memory_recommendations(
        tuple(_observation(attempt, parallel=2, peak=12_000.0) for attempt in range(3))
    )
    payload = deepcopy(catalog.to_dict())
    payload["recommendations"][0][field_name] = invalid_value

    with pytest.raises(ValueError):
        MemoryRecommendationCatalog.validate_payload(payload)


def test_catalog_payload_validation_rejects_duplicate_cell_identity() -> None:
    catalog = aggregate_memory_recommendations(
        tuple(_observation(attempt, parallel=2, peak=12_000.0) for attempt in range(3))
    )
    payload = deepcopy(catalog.to_dict())
    payload["recommendations"].append(deepcopy(payload["recommendations"][0]))

    with pytest.raises(ValueError, match="duplicate cell identities"):
        MemoryRecommendationCatalog.validate_payload(payload)


def test_catalog_payload_validation_rejects_extra_top_level_fields_and_empty_reasons() -> None:
    catalog = aggregate_memory_recommendations(
        tuple(_observation(attempt, parallel=2, peak=12_000.0) for attempt in range(3))
    )
    extra = deepcopy(catalog.to_dict())
    extra["unexpected"] = True
    empty_reasons = deepcopy(catalog.to_dict())
    empty_reasons["recommendations"][0]["status_reasons"] = []

    with pytest.raises(ValueError, match="top-level fields"):
        MemoryRecommendationCatalog.validate_payload(extra)
    with pytest.raises(ValueError, match="non-empty string array"):
        MemoryRecommendationCatalog.validate_payload(empty_reasons)


def test_catalog_payload_validation_rejects_semantically_impossible_approved_row() -> None:
    catalog = aggregate_memory_recommendations(
        tuple(_observation(attempt, parallel=2, peak=12_000.0) for attempt in range(3))
    )
    payload = deepcopy(catalog.to_dict())
    row = payload["recommendations"][0]
    row.update(
        {
            "repeat_count": 1,
            "telemetry_evidence": "unavailable",
            "measured_peak_vram_mb": None,
            "fixed_model_cost_vram_mb": None,
            "context_concurrency_overhead_vram_mb": None,
            "safety_reserve_vram_mb": None,
            "recommended_vram_mb": None,
        }
    )

    with pytest.raises(ValueError, match="approved recommendation"):
        MemoryRecommendationCatalog.validate_payload(payload)


@pytest.mark.parametrize(
    "model_artifact",
    (
        "/srv/private-user/models/file.gguf",
        "/tmp/private-user/file.gguf",
        "/mnt/private-user/file.gguf",
        "/home/other-user/models/file.gguf",
        "/Users/other-user/models/file.gguf",
        "C:\\Users\\private-user\\models\\file.gguf",
        "\\\\private-host\\models\\file.gguf",
        "file:///private/models/file.gguf",
        "~/private/models/file.gguf",
        "~private-user/models/file.gguf",
    ),
)
def test_recommendation_writer_rejects_private_filesystem_references(
    tmp_path: Path,
    model_artifact: str,
) -> None:
    catalog = aggregate_memory_recommendations(
        tuple(
            _observation(
                attempt,
                parallel=2,
                peak=12_000.0,
                model_artifact=model_artifact,
            )
            for attempt in range(3)
        )
    )

    with pytest.raises(ValueError, match="publication-unsafe"):
        write_memory_recommendation_artifacts(tmp_path, catalog)


def test_recommendation_writer_allows_public_repository_artifact_identity(tmp_path: Path) -> None:
    catalog = aggregate_memory_recommendations(
        tuple(_observation(attempt, parallel=2, peak=12_000.0) for attempt in range(3))
    )

    paths = write_memory_recommendation_artifacts(tmp_path, catalog)

    assert paths["catalog_json"].is_file()
