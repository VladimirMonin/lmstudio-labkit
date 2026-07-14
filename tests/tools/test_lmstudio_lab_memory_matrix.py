from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.lmstudio_lab.matrix import (
    MemoryMatrixAttemptResult,
    MemoryMatrixAttemptStore,
    MemoryMatrixCandidate,
    MemoryMatrixWorkload,
    RequestInterval,
    build_memory_concurrency_plan,
    execute_memory_matrix_attempt,
)


def _candidate() -> MemoryMatrixCandidate:
    return MemoryMatrixCandidate(
        model_artifact="publisher/model/file.gguf",
        artifact_revision="revision-7",
        artifact_checksum="sha256:" + "a" * 64,
        quantization="Q4_K_M",
        gpu_placement="full_gpu_requested",
        kv_placement="gpu",
        runtime_identity="lmstudio-runtime-1.5.0-build-9",
        runner_revision="gpu-memory-matrix.v1",
        schema_revision="gpu-telemetry.v2",
    )


def _text_workload() -> MemoryMatrixWorkload:
    return MemoryMatrixWorkload(workload_id="structured-short-v1", modality="text")


def _plan(*, contexts: tuple[int, ...] = (8192, 16384), required_attempts: int = 3):
    return build_memory_concurrency_plan(
        candidate=_candidate(),
        workloads=(_text_workload(),),
        context_tiers=contexts,
        required_attempts=required_attempts,
    )


def _result_for(cell, *, intervals: tuple[RequestInterval, ...] | None = None):
    if intervals is None:
        intervals = tuple(
            RequestInterval(
                request_id=f"request-{index}",
                started_monotonic_s=0.0,
                ended_monotonic_s=1.0,
            )
            for index in range(cell.application_concurrency)
        )
    return MemoryMatrixAttemptResult(
        operation_succeeded=True,
        observed_identity=cell.identity_payload(),
        request_intervals=intervals,
        phase_evidence_valid=True,
        independent_cycle_proven=True,
        immutable_owner_evidence_bound=True,
    )


def _execute_ready(plan, store: MemoryMatrixAttemptStore):
    cell = store.ready_cells()[0]
    execute_memory_matrix_attempt(
        store=store,
        cell=cell,
        executor=lambda reservation: _result_for(cell),
        live_enabled=True,
    )
    return cell


def test_memory_matrix_cell_identity_binds_all_required_axes_and_hashes() -> None:
    plan = _plan()

    assert [(cell.context_tokens, cell.lane) for cell in plan.cells] == [
        (8192, "load_only"),
        (8192, "p1"),
        (8192, "p2"),
        (8192, "p4"),
        (16384, "load_only"),
        (16384, "p1"),
        (16384, "p2"),
        (16384, "p4"),
    ]
    assert len({cell.cell_id for cell in plan.cells}) == len(plan.cells)
    identity = plan.cells[-1].identity_payload()
    assert identity == {
        "application_concurrency": 4,
        "artifact_checksum": "sha256:" + "a" * 64,
        "artifact_revision": "revision-7",
        "context_tokens": 16384,
        "gpu_placement": "full_gpu_requested",
        "kv_placement": "gpu",
        "model_artifact": "publisher/model/file.gguf",
        "quantization": "Q4_K_M",
        "runner_revision": "gpu-memory-matrix.v1",
        "runtime_identity": "lmstudio-runtime-1.5.0-build-9",
        "runtime_parallel": 4,
        "schema_revision": "gpu-telemetry.v2",
        "workload_id": "structured-short-v1",
        "workload_modality": "text",
    }


def test_memory_matrix_identity_rejects_non_string_values() -> None:
    with pytest.raises(ValueError, match="model_artifact must be a non-empty string"):
        MemoryMatrixCandidate(
            model_artifact=None,  # type: ignore[arg-type]
            artifact_revision="revision-7",
            artifact_checksum="sha256:" + "a" * 64,
            quantization="Q4_K_M",
            gpu_placement="full_gpu_requested",
            kv_placement="gpu",
            runtime_identity="lmstudio-runtime-1.5.0-build-9",
            runner_revision="gpu-memory-matrix.v1",
            schema_revision="gpu-telemetry.v2",
        )


def test_memory_matrix_rejects_duplicate_workload_identity() -> None:
    with pytest.raises(ValueError, match="workload_id values must be unique"):
        build_memory_concurrency_plan(
            candidate=_candidate(),
            workloads=(_text_workload(), _text_workload()),
            context_tiers=(8192,),
        )


def test_memory_matrix_requires_three_independent_attempts() -> None:
    with pytest.raises(ValueError, match="required_attempts must be an integer >= 3"):
        _plan(required_attempts=1)


def test_text_and_vision_plans_are_separate_and_vision_requires_text_admission() -> None:
    vision = MemoryMatrixWorkload(workload_id="vision-simple-v1", modality="vision")

    with pytest.raises(ValueError, match="must not mix text and vision"):
        build_memory_concurrency_plan(
            candidate=_candidate(),
            workloads=(_text_workload(), vision),
            context_tiers=(8192,),
        )
    with pytest.raises(ValueError, match="requires admitted text plan evidence"):
        build_memory_concurrency_plan(
            candidate=_candidate(),
            workloads=(vision,),
            context_tiers=(8192,),
        )

    plan = build_memory_concurrency_plan(
        candidate=_candidate(),
        workloads=(vision,),
        context_tiers=(8192,),
        text_plan_admitted=True,
    )
    assert {cell.workload_modality for cell in plan.cells} == {"vision"}


def test_promotion_is_load_only_then_p1_p2_p4_then_next_context(tmp_path: Path) -> None:
    plan = _plan()
    store = MemoryMatrixAttemptStore(tmp_path / "attempts.jsonl", plan)

    expected = [
        pair
        for pair in (
            (8192, "load_only"),
            (8192, "p1"),
            (8192, "p2"),
            (8192, "p4"),
            (16384, "load_only"),
        )
        for _ in range(3)
    ]
    observed = []
    for _ in expected:
        cell = _execute_ready(plan, store)
        observed.append((cell.context_tokens, cell.lane))

    assert observed == expected


def test_identity_mismatch_is_append_only_evidence_and_blocks_promotion(tmp_path: Path) -> None:
    plan = _plan(contexts=(8192,))
    store = MemoryMatrixAttemptStore(tmp_path / "attempts.jsonl", plan)
    cell = store.ready_cells()[0]
    observed_identity = cell.identity_payload()
    observed_identity["artifact_revision"] = "different-revision"

    outcome = execute_memory_matrix_attempt(
        store=store,
        cell=cell,
        executor=lambda reservation: MemoryMatrixAttemptResult(
            operation_succeeded=True,
            observed_identity=observed_identity,
        ),
        live_enabled=True,
    )

    assert outcome["status"] == "identity_mismatch"
    for _ in range(2):
        retry = store.ready_cells()[0]
        execute_memory_matrix_attempt(
            store=store,
            cell=retry,
            executor=lambda reservation, retry=retry: _result_for(retry),
            live_enabled=True,
        )
    assert store.ready_cells() == ()
    rows = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == [
        "plan_bound",
        "attempt_reserved",
        "attempt_outcome",
        "attempt_reserved",
        "attempt_outcome",
        "attempt_reserved",
        "attempt_outcome",
    ]


def test_attempt_outcome_rejects_a_reservation_from_another_cell(tmp_path: Path) -> None:
    plan = build_memory_concurrency_plan(
        candidate=_candidate(),
        workloads=(
            _text_workload(),
            MemoryMatrixWorkload(workload_id="plain-short-v1", modality="text"),
        ),
        context_tiers=(8192,),
        required_attempts=3,
    )
    store = MemoryMatrixAttemptStore(tmp_path / "attempts.jsonl", plan)
    first_cell, second_cell = store.ready_cells()
    reservation = store.reserve(first_cell)

    with pytest.raises(ValueError, match="reservation identity mismatch"):
        store.complete(reservation, second_cell, _result_for(second_cell))


def test_configured_parallel_is_not_overlap_proof(tmp_path: Path) -> None:
    plan = _plan(contexts=(8192,))
    store = MemoryMatrixAttemptStore(tmp_path / "attempts.jsonl", plan)
    for _ in range(3):
        _execute_ready(plan, store)  # load-only
    for _ in range(3):
        _execute_ready(plan, store)  # P1
    p2 = store.ready_cells()[0]
    assert p2.application_concurrency == 2

    outcome = execute_memory_matrix_attempt(
        store=store,
        cell=p2,
        executor=lambda reservation: _result_for(
            p2,
            intervals=(
                RequestInterval("request-1", 0.0, 1.0),
                RequestInterval("request-2", 1.0, 2.0),
            ),
        ),
        live_enabled=True,
    )

    assert outcome["configured_application_concurrency"] == 2
    assert outcome["maximum_observed_overlap"] == 1
    assert outcome["overlap_proven"] is False
    assert outcome["status"] == "overlap_unproven"
    assert outcome["request_intervals"] == [
        {
            "request_id": "request-1",
            "started_monotonic_s": 0.0,
            "ended_monotonic_s": 1.0,
        },
        {
            "request_id": "request-2",
            "started_monotonic_s": 1.0,
            "ended_monotonic_s": 2.0,
        },
    ]
    for _ in range(2):
        retry = store.ready_cells()[0]
        execute_memory_matrix_attempt(
            store=store,
            cell=retry,
            executor=lambda reservation, retry=retry: _result_for(retry),
            live_enabled=True,
        )
    assert store.ready_cells() == ()


def test_matrix_attempt_cannot_admit_without_phase_cycle_and_owner_proof(tmp_path: Path) -> None:
    plan = _plan(contexts=(8192,))
    store = MemoryMatrixAttemptStore(tmp_path / "attempts.jsonl", plan)
    cell = store.ready_cells()[0]

    outcome = execute_memory_matrix_attempt(
        store=store,
        cell=cell,
        executor=lambda reservation: MemoryMatrixAttemptResult(
            operation_succeeded=True,
            observed_identity=cell.identity_payload(),
        ),
        live_enabled=True,
    )

    assert outcome["overlap_proven"] is True
    assert outcome["phase_evidence_valid"] is False
    assert outcome["independent_cycle_proven"] is False
    assert outcome["immutable_owner_evidence_bound"] is False
    assert outcome["status"] == "phase_evidence_invalid"


def test_reservation_is_fsynced_before_executor_and_journal_never_rewrites(tmp_path: Path) -> None:
    plan = _plan(contexts=(8192,))
    store = MemoryMatrixAttemptStore(tmp_path / "attempts.jsonl", plan)
    cell = store.ready_cells()[0]
    before = store.path.read_bytes()

    def executor(reservation):
        rows = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
        assert rows[-1]["event"] == "attempt_reserved"
        assert rows[-1]["attempt_id"] == reservation.attempt_id
        return _result_for(cell)

    execute_memory_matrix_attempt(
        store=store,
        cell=cell,
        executor=executor,
        live_enabled=True,
    )

    after = store.path.read_bytes()
    assert after.startswith(before)
    assert len(after) > len(before)


def test_resume_is_idempotent_and_does_not_repeat_reserved_attempt(tmp_path: Path) -> None:
    plan = _plan(contexts=(8192,))
    path = tmp_path / "attempts.jsonl"
    first_store = MemoryMatrixAttemptStore(path, plan)
    load_cell = first_store.ready_cells()[0]
    reservation = first_store.reserve(load_cell)

    resumed_store = MemoryMatrixAttemptStore(path, plan)

    assert resumed_store.ready_cells() == (load_cell,)
    assert resumed_store.reservation_for(reservation.attempt_id) is not None
    assert [row["event"] for row in resumed_store.events()] == ["plan_bound", "attempt_reserved"]


def test_resume_rejects_a_different_plan_identity(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    MemoryMatrixAttemptStore(path, _plan(contexts=(8192,)))

    with pytest.raises(ValueError, match="plan identity mismatch"):
        MemoryMatrixAttemptStore(path, _plan(contexts=(8192, 16384)))


def test_live_execution_is_opt_in_and_downloads_are_always_forbidden(tmp_path: Path) -> None:
    plan = _plan(contexts=(8192,))
    store = MemoryMatrixAttemptStore(tmp_path / "attempts.jsonl", plan)
    cell = store.ready_cells()[0]
    calls = []

    with pytest.raises(ValueError, match="requires live_enabled=True"):
        execute_memory_matrix_attempt(
            store=store,
            cell=cell,
            executor=lambda reservation: calls.append(reservation),
            live_enabled=False,
        )
    with pytest.raises(ValueError, match="downloads are forbidden"):
        execute_memory_matrix_attempt(
            store=store,
            cell=cell,
            executor=lambda reservation: calls.append(reservation),
            live_enabled=True,
            downloads_allowed=True,
        )

    assert calls == []
    assert [row["event"] for row in store.events()] == ["plan_bound"]
