from __future__ import annotations

import argparse
import base64
import binascii
import csv
import json
import struct
import subprocess
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from lmstudio_labkit.managed_executor import _native_image_input, _validate_native_image_input
from lmstudio_labkit.validation import validate_json_schema

from lmstudio_labkit import LocalFailureForensics, LocalLMStudioHostRunner, parse_json_response

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO_ROOT / "experiments/lmstudio/configs/l3_39_gemma_family_matrix.yaml"
DEFAULT_REPLAY = REPO_ROOT / "experiments/lmstudio/configs/l3_39_12b_fenced_replay.yaml"
DEFAULT_DATASET = (
    REPO_ROOT / "experiments/lmstudio/structured_matrix/datasets/text/l3_39_family_matrix.yaml"
)
PHASES = ("text_structure", "vision", "one_shot_context", "session")
REVIEW_REQUIRED_STATUSES = {"review_required", "accepted"}
REVIEW_VERDICTS = {"accepted", "rejected", "research_only"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_VISION_SIDE = 1024


def load_yaml(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return payload


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = load_yaml(path)
    validate_contract(payload)
    return payload


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != "lmstudio-labkit-l339-family-matrix-v1":
        raise ValueError("unsupported L3.39 contract schema_version")
    execution = _mapping(contract.get("execution"), "execution")
    required = {
        "serial_only": True,
        "parallel": 1,
        "retries": "off",
        "temperature": 0,
        "route": "/api/v1/chat",
        "stream": True,
        "private_forensics_required": True,
        "private_forensics_must_be_external": True,
        "allow_model_downloads": False,
        "allow_raw_artifacts_in_git": False,
        "global_loaded_count_required_between_phases": 0,
        "immutable_phase_summaries": True,
        "resume_requires_verified_summary": True,
    }
    for key, value in required.items():
        if execution.get(key) != value:
            raise ValueError(f"execution.{key} must be {value!r}")
    models = contract.get("models")
    if not isinstance(models, list) or len(models) != 5:
        raise ValueError("L3.39 requires exactly five model records")
    expected = [
        ("google/gemma-4-e2b", "google/gemma-4-e2b@q4_k_m", ["off", "on"]),
        ("google/gemma-4-e4b", "google/gemma-4-e4b@q4_k_m", ["off", "on"]),
        ("google/gemma-4-12b-qat", "google/gemma-4-12b-qat@q4_0", ["off", "on"]),
        (
            "google/gemma-4-26b-a4b-qat",
            "google/gemma-4-26b-a4b-qat@q4_0",
            ["off", "on"],
        ),
        (
            "gemma-4-31b-it",
            "unsloth/gemma-4-31B-it-GGUF/gemma-4-31B-it-UD-IQ3_XXS.gguf",
            ["reasoning_omitted_unknown"],
        ),
    ]
    observed = [
        (item.get("model_id"), item.get("exact_variant"), item.get("reasoning_classes"))
        for item in models
        if isinstance(item, Mapping)
    ]
    if observed != expected:
        raise ValueError("exact five-model inventory or reasoning taxonomy changed")
    if "google/gemma-4-31b-qat" in json.dumps(contract):
        forbidden = models[-1].get("forbidden_substitute")
        if forbidden != "google/gemma-4-31b-qat":
            raise ValueError("Google 31B QAT must not substitute for exact Unsloth 31B")
    budget = _mapping(contract.get("row_budget"), "row_budget")
    rows = expand_matrix(contract, include_replay=True, validate=False)
    if len(rows) != 114 or sum(row["call_planned"] for row in rows) != 108:
        raise ValueError("L3.39 matrix must contain 114 records and 108 maximum calls")
    if budget.get("total_matrix_records") != 114 or budget.get("maximum_live_calls") != 108:
        raise ValueError("row_budget totals must remain 114/108")


def expand_matrix(
    contract: Mapping[str, Any], *, include_replay: bool = True, validate: bool = True
) -> list[dict[str, Any]]:
    if validate:
        validate_contract(contract)
    axes = _mapping(contract["axes"], "axes")
    rows: list[dict[str, Any]] = []
    for model in contract["models"]:
        model_id = str(model["model_id"])
        variant = str(model["exact_variant"])
        reasoning_classes = list(model["reasoning_classes"])
        for reasoning in reasoning_classes:
            for complexity in axes["text_structure"]["complexities"]:
                rows.append(
                    _row(
                        model_id,
                        variant,
                        "text_structure",
                        str(complexity),
                        str(reasoning),
                        8192,
                        int(axes["text_structure"]["caps"][reasoning][complexity]),
                    )
                )
            for stage in axes["vision"]["stages"]:
                rows.append(
                    _row(
                        model_id,
                        variant,
                        "vision",
                        str(stage),
                        str(reasoning),
                        8192,
                        int(axes["vision"]["caps"][reasoning][stage]),
                        modality="image",
                        fixture_id=str(axes["vision"]["fixture_id"]),
                        image_sha256=str(axes["vision"]["image_sha256"]),
                        ground_truth_path=str(axes["vision"]["expected_path"]),
                    )
                )
        baseline_reasoning = (
            "reasoning_omitted_unknown"
            if reasoning_classes == ["reasoning_omitted_unknown"]
            else "off"
        )
        for tier in axes["one_shot_context"]["tiers"]:
            rows.append(
                _row(
                    model_id,
                    variant,
                    "one_shot_context",
                    str(tier["name"]),
                    baseline_reasoning,
                    int(tier["context_length"]),
                    int(axes["one_shot_context"]["max_output_tokens"]),
                    nominal_input_tokens=int(tier["nominal_input_tokens"]),
                )
            )
        for mode in axes["session"]["modes"]:
            for chunk in axes["session"]["changing_message_2_chunks"]:
                rows.append(
                    _row(
                        model_id,
                        variant,
                        "session",
                        f"{mode}-{chunk}",
                        baseline_reasoning,
                        int(axes["session"]["context_length"]),
                        int(axes["session"]["max_output_tokens"]),
                        session_mode=str(mode),
                        chunk_id=str(chunk),
                    )
                )
    if include_replay:
        for index in range(1, 7):
            rows.append(
                {
                    "row_id": f"replay-l338-12b-{index:02d}",
                    "request_id": f"replay-l338-12b-{index:02d}",
                    "phase": "offline_replay",
                    "model_id": "google/gemma-4-12b-qat",
                    "exact_variant": "google/gemma-4-12b-qat@q4_0",
                    "route": "/api/v1/chat",
                    "modality": "text",
                    "task": "repeated_context_fenced_replay",
                    "dataset_id": "l3_38_reasoning_off_followup",
                    "dataset_sha256": None,
                    "prompt_id": "private_hash_only",
                    "prompt_sha256": None,
                    "schema_id": "l339-marker-status-warnings",
                    "schema_sha256": sha256(b"l339-marker-status-warnings").hexdigest(),
                    "image_id": None,
                    "ground_truth_id": None,
                    "ground_truth_sha256": None,
                    "reasoning_class": "off",
                    "context_length": 16384,
                    "max_output_tokens": 1024,
                    "lifecycle": "offline_replay",
                    "status": "replay_pending",
                    "call_planned": False,
                    "evidence_id": None,
                    "stop_reason": None,
                }
            )
    return rows


def _row(
    model_id: str,
    variant: str,
    phase: str,
    task: str,
    reasoning: str,
    context: int,
    cap: int,
    **extra: object,
) -> dict[str, Any]:
    row_id = "--".join(
        _slug(part) for part in (model_id, phase, task, reasoning, str(context), str(cap))
    )
    prompt_id = f"l339-{phase}-{task}"
    schema_id = "plain_text" if phase == "vision" and task == "perception" else prompt_id
    ground_truth_path = extra.pop("ground_truth_path", None)
    fixture_id = extra.get("fixture_id")
    return {
        "row_id": row_id,
        "request_id": row_id,
        "phase": phase,
        "model_id": model_id,
        "exact_variant": variant,
        "route": "/api/v1/chat",
        "modality": "text",
        "task": task,
        "dataset_id": "l3_39_family_matrix_public_safe",
        "dataset_sha256": _file_sha256(DEFAULT_DATASET),
        "prompt_id": prompt_id,
        "prompt_sha256": sha256(prompt_id.encode("utf-8")).hexdigest(),
        "schema_id": schema_id,
        "schema_sha256": sha256(schema_id.encode("utf-8")).hexdigest(),
        "image_id": fixture_id,
        "ground_truth_id": fixture_id,
        "ground_truth_sha256": (
            _file_sha256(REPO_ROOT / str(ground_truth_path)) if ground_truth_path else None
        ),
        "reasoning_class": reasoning,
        "context_length": context,
        "max_output_tokens": cap,
        "lifecycle": "serial",
        "status": "planned",
        "stop_reason": None,
        "evidence_id": None,
        "call_planned": True,
        **extra,
    }


def replay_private_records(
    *, source_dir: str | Path, replay_contract: Mapping[str, Any]
) -> dict[str, Any]:
    root = Path(source_dir).expanduser().resolve(strict=True)
    if root == REPO_ROOT or root.is_relative_to(REPO_ROOT):
        raise ValueError("replay source must remain outside the repository")
    files = sorted(root.glob("attempt-*.json"))
    expected = int(replay_contract["expected_records"])
    if len(files) != expected:
        raise ValueError(f"replay requires exactly {expected} private records, found {len(files)}")
    schema = _mapping(replay_contract["expected_contract"], "expected_contract")
    rows: list[dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = _mapping(payload.get("raw"), "raw")
        message = str(raw.get("message", ""))
        parsed = parse_json_response(message, policy="single_complete_json_fence")
        schema_result = (
            validate_json_schema(parsed.parsed, schema) if parsed.parse_succeeded else None
        )
        stats = (
            payload.get("numeric_stats") if isinstance(payload.get("numeric_stats"), dict) else {}
        )
        request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        evidence_id = f"l339-replay-{sha256(path.read_bytes()).hexdigest()[:20]}"
        rows.append(
            {
                "row_id": f"replay-l338-12b-{index:02d}",
                "request_id": f"replay-l338-12b-{index:02d}",
                "evidence_id": evidence_id,
                "request_id_hash": request.get("request_id_hash"),
                "model_id": replay_contract["model_id"],
                "exact_variant": replay_contract["exact_variant"],
                "route": replay_contract["route"],
                "dataset_id": replay_contract["source_experiment"],
                "dataset_sha256": None,
                "prompt_id": "private_hash_only",
                "prompt_sha256": request.get("request_id_hash"),
                "schema_id": "l339-marker-status-warnings",
                "schema_sha256": sha256(b"l339-marker-status-warnings").hexdigest(),
                "image_id": None,
                "image_sha256": None,
                "ground_truth_id": None,
                "ground_truth_sha256": None,
                "context_length": replay_contract["context_length"],
                "reasoning_class": replay_contract["reasoning"],
                "raw_message": parsed.safe_diagnostics()["raw"],
                "normalized_message": parsed.safe_diagnostics()["normalized"],
                "transformation": parsed.transformation,
                "fence_eligible": parsed.fence_eligible,
                "semantic_repair": False,
                "raw_json_valid": parsed.raw_parse.status == "pass",
                "normalized_json_valid": parsed.normalized_parse.status == "pass",
                "schema_valid": schema_result is not None and schema_result.status == "pass",
                "reasoning_tokens": _numeric_stat(stats, "reasoning_output_tokens"),
                "message_tokens": _message_tokens(stats),
                "finish_reason": _mapping(payload.get("observed"), "observed").get("finish_reason"),
                "private_record_exists": True,
                "private_path_exposed": False,
                "status": "replayed",
                "verdict": "normalized_contract_valid"
                if schema_result is not None and schema_result.status == "pass"
                else "invalid",
            }
        )
    return {
        "schema_version": "lmstudio-labkit-l339-replay-summary-v1",
        "source_experiment": replay_contract["source_experiment"],
        "records": rows,
        "record_count": len(rows),
        "raw_strict_invalid": sum(not row["raw_json_valid"] for row in rows),
        "normalized_contract_valid": sum(
            row["normalized_json_valid"] and row["schema_valid"] for row in rows
        ),
        "regeneration_calls": 0,
        "semantic_repairs": 0,
        "private_paths_exposed": False,
        "kv_reuse_claimed": False,
        "cache_benefit_claimed": False,
        "memory_attribution_claimed": False,
    }


def verified_resume_rows(
    planned_rows: Sequence[Mapping[str, Any]],
    summary_paths: Sequence[str | Path],
    review_paths: Sequence[str | Path] = (),
) -> list[dict[str, Any]]:
    by_id = {str(row["row_id"]): dict(row) for row in planned_rows}
    reviews = _load_completed_reviews(review_paths)
    for summary_path in summary_paths:
        payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != "lmstudio-labkit-l339-phase-summary-v1":
            raise ValueError("resume summary has an unsupported schema_version")
        if payload.get("verified") is not True or payload.get("final_loaded_global_count") != 0:
            raise ValueError("resume summary is not verified clean")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError("resume summary rows must be a list")
        for row in rows:
            if not isinstance(row, Mapping) or str(row.get("row_id")) not in by_id:
                raise ValueError("resume summary contains an unknown row_id")
            if row.get("private_record_exists") is not True and row.get("status") not in {
                "unsupported",
                "unknown_capability",
                "blocked_by_prior_gate",
            }:
                raise ValueError("resume row lacks private evidence")
            if row.get("status") in REVIEW_REQUIRED_STATUSES and str(row["row_id"]) not in reviews:
                raise ValueError("resume row lacks completed private-answer review")
            by_id[str(row["row_id"])].update(dict(row))
            if str(row["row_id"]) in reviews:
                by_id[str(row["row_id"])]["private_review"] = reviews[str(row["row_id"])]
    return list(by_id.values())


def aggregate_summaries(
    planned_rows: Sequence[Mapping[str, Any]],
    summary_paths: Sequence[str | Path],
    review_paths: Sequence[str | Path] = (),
) -> dict[str, Any]:
    rows = verified_resume_rows(planned_rows, summary_paths, review_paths)
    return {
        "schema_version": "lmstudio-labkit-l339-aggregate-v1",
        "rows": rows,
        "row_count": len(rows),
        "live_row_count": sum(row.get("call_planned") is True for row in rows),
        "status_counts": _counts(str(row.get("status")) for row in rows),
        "private_paths_exposed": False,
        "raw_text_exposed": False,
    }


def run_model_phase(
    *,
    contract: Mapping[str, Any],
    dataset: Mapping[str, Any],
    model_id: str,
    phase: str,
    base_url: str,
    private_dir: str | Path,
    token_counts: Mapping[str, int] | None = None,
    prerequisite_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError(f"unsupported phase: {phase}")
    model = next((item for item in contract["models"] if item["model_id"] == model_id), None)
    if model is None:
        raise ValueError("model_id is not in the exact L3.39 inventory")
    assert isinstance(model, Mapping)
    forensics = LocalFailureForensics(private_dir, repo_root=REPO_ROOT, enabled=True)
    host = LocalLMStudioHostRunner(
        base_url=base_url,
        default_timeout_s=900.0,
        allow_remote_base_url=True,
        allow_native_diagnostics=True,
        failure_forensics=forensics,
    )
    _assert_global_zero(host, "run-start")
    rows = [
        row
        for row in expand_matrix(contract, include_replay=False)
        if row["model_id"] == model_id and row["phase"] == phase
    ]
    metadata = host.model_metadata(model_id=model_id)
    artifact_metadata = _read_lms_model_artifact_metadata(model_id)
    try:
        _verify_exact_model_metadata(metadata, model, artifact_metadata=artifact_metadata)
    except RuntimeError as exc:
        return _unsupported_phase(
            rows,
            f"exact_model_preflight_failed:{exc}",
            model=model,
            phase=phase,
            status="unknown_capability",
        )
    assert isinstance(metadata, Mapping)
    if phase in {"one_shot_context", "session"}:
        if token_counts is None:
            raise ValueError("context/session phases require exact per-row token counts")
        _verify_token_fit(rows, token_counts, contract)
    reasoning_reason = _unsupported_reasoning_reason(rows, metadata)
    if reasoning_reason is not None:
        return _unsupported_phase(rows, reasoning_reason, model=model, phase=phase)
    if phase == "vision":
        capabilities = metadata.get("capabilities")
        if not isinstance(capabilities, Mapping) or capabilities.get("vision") is not True:
            return _unsupported_phase(
                rows, "exact_model_does_not_advertise_vision", model=model, phase=phase
            )
        if model_id != "google/gemma-4-e2b" and not _vision_transport_canary_accepted(
            prerequisite_rows
        ):
            return _unsupported_phase(
                rows,
                "vision_requires_accepted_e2b_off_transport_canary",
                model=model,
                phase=phase,
                status="blocked_by_prior_gate",
            )
    if phase == "session" and not _session_prerequisites_accepted(prerequisite_rows):
        return _unsupported_phase(
            rows,
            "session_requires_accepted_16k_and_simple_text_prerequisites",
            model=model,
            phase=phase,
            status="blocked_by_prior_gate",
        )
    results: list[dict[str, Any]] = []
    lane_open = True
    if phase == "session":
        cold = [row for row in rows if row["session_mode"] == "cold_full_prefix"]
        loaded = [row for row in rows if row["session_mode"] == "loaded_stable_message_1"]
        for row in cold:
            if not lane_open:
                results.append(_blocked_row(row, "failed_prior_session_row"))
                continue
            batch = _run_loaded_batch(host, forensics, model, [row], dataset, contract)
            results.extend(batch)
            lane_open = _rows_pass_stop_gate(batch)
        if lane_open:
            results.extend(_run_loaded_batch(host, forensics, model, loaded, dataset, contract))
        else:
            results.extend(_blocked_row(row, "failed_prior_session_row") for row in loaded)
    elif phase == "vision":
        baseline_reasoning = (
            "reasoning_omitted_unknown"
            if model.get("reasoning_classes") == ["reasoning_omitted_unknown"]
            else "off"
        )
        canary = next(
            row
            for row in rows
            if row["task"] == "perception" and row["reasoning_class"] == baseline_reasoning
        )
        canary_result = _run_loaded_batch(host, forensics, model, [canary], dataset, contract)
        results.extend(canary_result)
        if not _rows_pass_stop_gate(canary_result):
            results.extend(
                _blocked_row(row, "failed_vision_transport_canary")
                for row in rows
                if row["row_id"] != canary["row_id"]
            )
        else:
            remaining = [row for row in rows if row["row_id"] != canary["row_id"]]
            active_lane: str | None = None
            for row in remaining:
                lane = str(row["reasoning_class"])
                if lane != active_lane:
                    active_lane = lane
                    lane_open = True
                if not lane_open:
                    results.append(_blocked_row(row, "failed_prior_vision_gate"))
                    continue
                batch = _run_loaded_batch(host, forensics, model, [row], dataset, contract)
                results.extend(batch)
                lane_open = _rows_pass_stop_gate(batch)
    else:
        active_lane: str | None = None
        for row in rows:
            lane = str(row["reasoning_class"])
            if lane != active_lane:
                active_lane = lane
                lane_open = True
            if not lane_open:
                results.append(_blocked_row(row, f"failed_prior_{phase}_gate"))
                continue
            batch = _run_loaded_batch(host, forensics, model, [row], dataset, contract)
            results.extend(batch)
            lane_open = _rows_pass_stop_gate(batch)
    _assert_global_zero(host, "run-end")
    return {
        "schema_version": "lmstudio-labkit-l339-phase-summary-v1",
        "model_id": model_id,
        "exact_variant": model["exact_variant"],
        "phase": phase,
        "rows": results,
        "verified": True,
        "final_loaded_global_count": 0,
        "private_paths_exposed": False,
        "raw_text_exposed": False,
    }


def _run_loaded_batch(
    host: Any,
    forensics: LocalFailureForensics,
    model: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    dataset: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    context = int(rows[0]["context_length"])
    if any(int(row["context_length"]) != context for row in rows):
        raise ValueError("one loaded batch cannot mix context tiers")
    _assert_global_zero(host, "pre-load")
    load = host.load_model(model_id=model["model_id"], context_length=context, parallel=1)
    handles: list[Any] = []
    output: list[dict[str, Any]] = []
    cleanup: object = {"cleanup_verified": False}
    try:
        if not isinstance(load, Mapping) or load.get("load_verified") is not True:
            raise RuntimeError("model load was not verified")
        applied = load.get("applied_load_config", load.get("load_config"))
        if not isinstance(applied, Mapping) or int(applied.get("context_length", -1)) != context:
            raise RuntimeError("applied context mismatch")
        if int(applied.get("parallel", applied.get("n_parallel", -1))) != 1:
            raise RuntimeError("applied parallelism mismatch")
        if host.count_all_loaded_instances() != 1:
            raise RuntimeError("exactly one global loaded instance is required")
        for index, row in enumerate(rows, start=1):
            prompt, messages, image_data_url, image_transport = _request_material(
                row, dataset, contract
            )
            del prompt
            reasoning = (
                None
                if row["reasoning_class"] == "reasoning_omitted_unknown"
                else row["reasoning_class"]
            )
            result = host.native_chat_diagnostic(
                model_id=model["model_id"],
                messages=messages,
                reasoning=reasoning,
                max_output_tokens=int(row["max_output_tokens"]),
                timeout_s=900.0,
                stream=True,
                request_id=str(row["row_id"]),
                attempt_index=index,
                context_length=context,
                image_data_url=image_data_url,
            )
            if result.forensics_handle is None:
                raise RuntimeError("private forensic capture is required")
            handles.append(result.forensics_handle)
            verdict = _evaluate_live_row(row, result.message_text, dataset, contract)
            output.append(
                {
                    **dict(row),
                    **verdict,
                    "status": "review_required"
                    if result.http_status == 200 and verdict["business_verdict"] == "pass"
                    else "runtime_failed"
                    if result.http_status != 200
                    else "blocked_by_prior_gate",
                    "evidence_id": f"l339-{sha256(str(row['row_id']).encode()).hexdigest()[:20]}",
                    "http_status": result.http_status,
                    "finish_reason": result.finish_reason,
                    "boundary": result.boundary,
                    "reasoning_tokens": _numeric_stat(
                        result.numeric_stats, "reasoning_output_tokens"
                    ),
                    "message_tokens": _message_tokens(result.numeric_stats),
                    "private_record_exists": True,
                    "private_path_exposed": False,
                    "qualitative_review_required": True,
                    **({"image_transport": image_transport} if image_transport else {}),
                }
            )
    finally:
        cleanup = host.cleanup_model(model_id=model["model_id"])
        final = host.count_all_loaded_instances()
        for handle in handles:
            forensics.finalize_attempt(
                handle,
                cleanup_result=cleanup,
                final_loaded_instances=final,
            )
    if not isinstance(cleanup, Mapping) or cleanup.get("cleanup_verified") is not True:
        raise RuntimeError("cleanup was not verified")
    _assert_global_zero(host, "post-batch")
    for row in output:
        row["cleanup_verified"] = True
        row["final_loaded_global_count"] = 0
    return output


def _request_material(
    row: Mapping[str, Any], dataset: Mapping[str, Any], contract: Mapping[str, Any]
) -> tuple[str, tuple[dict[str, str], ...], str | None, dict[str, Any] | None]:
    phase = row["phase"]
    task = str(row["task"])
    image_data_url: str | None = None
    image_transport: dict[str, Any] | None = None
    if phase == "text_structure":
        section = _mapping(dataset["text_structure"], "text_structure")
        prompt = f"Source: {section['source']}\n{section[f'{task}_prompt']}"
    elif phase == "vision":
        section = _mapping(dataset["vision"], "vision")
        prompt = str(section[f"{task}_prompt"])
        fixture = REPO_ROOT / contract["axes"]["vision"]["fixture_path"]
        image_data_url, image_transport = _build_native_png_payload(
            fixture,
            expected_sha256=str(contract["axes"]["vision"]["image_sha256"]),
        )
    elif phase == "one_shot_context":
        target = int(row["nominal_input_tokens"])
        lines = [
            str(dataset["context"]["line_template"]).format(index=index)
            for index in range(max(1, target // 14))
        ]
        prompt = "\n".join(lines) + "\n" + str(dataset["context"]["marker_prompt"])
    else:
        stable = "\n".join(
            str(dataset["session"]["stable_line_template"]).format(index=index)
            for index in range(730)
        )
        chunk = next(
            item for item in dataset["session"]["changing_chunks"] if item["id"] == row["chunk_id"]
        )
        messages = (
            {"role": "user", "content": stable},
            {
                "role": "user",
                "content": f"{chunk['question']} Return JSON only with marker={chunk['marker']!r}, status='ok', warnings=[].",
            },
        )
        return messages[-1]["content"], messages, None, None
    return prompt, ({"role": "user", "content": prompt},), image_data_url, image_transport


def _build_native_png_payload(
    fixture: str | Path, *, expected_sha256: str
) -> tuple[str, dict[str, Any]]:
    image_bytes = Path(fixture).read_bytes()
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    metadata = _validate_native_png_data_url(data_url, expected_sha256=expected_sha256)
    return data_url, metadata


def _validate_native_png_data_url(data_url: str, *, expected_sha256: str) -> dict[str, Any]:
    prefix = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise RuntimeError("vision payload must be a PNG data URL")
    encoded = data_url[len(prefix) :]
    if not encoded or any(character.isspace() for character in encoded):
        raise RuntimeError("vision payload base64 must be non-empty and whitespace-free")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError("vision payload base64 is invalid") from exc
    if base64.b64encode(image_bytes).decode("ascii") != encoded:
        raise RuntimeError("vision payload base64 round-trip mismatch")
    if not image_bytes.startswith(PNG_SIGNATURE) or len(image_bytes) < 33:
        raise RuntimeError("vision payload PNG signature or header is invalid")
    if image_bytes[12:16] != b"IHDR" or struct.unpack(">I", image_bytes[8:12])[0] != 13:
        raise RuntimeError("vision payload PNG IHDR is invalid")
    width, height = struct.unpack(">II", image_bytes[16:24])
    bit_depth, color_type = image_bytes[24], image_bytes[25]
    if width < 1 or height < 1 or max(width, height) > MAX_VISION_SIDE:
        raise RuntimeError("vision payload dimensions are outside the approved bounds")
    if bit_depth != 8 or color_type != 2:
        raise RuntimeError("vision payload must be 8-bit RGB PNG")
    if b"acTL" in image_bytes:
        raise RuntimeError("animated or multi-frame PNG is not allowed")
    digest = sha256(image_bytes).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError("vision fixture hash mismatch")
    native_input = _native_image_input("redacted", data_url)
    return {
        "route": "/api/v1/chat",
        "input_types": list(_validate_native_image_input(native_input)),
        "mime_type": "image/png",
        "decoded_byte_count": len(image_bytes),
        "width": width,
        "height": height,
        "sha256": digest,
        "data_url_present": True,
        "raw_data_url_exposed": False,
    }


def _verify_token_fit(
    rows: Sequence[Mapping[str, Any]],
    token_counts: Mapping[str, int],
    contract: Mapping[str, Any],
) -> None:
    reserve = int(contract["axes"]["one_shot_context"]["framing_reserve_tokens"])
    for row in rows:
        count = token_counts.get(str(row["row_id"]))
        if not isinstance(count, int) or count <= 0:
            raise ValueError(f"missing exact token count for {row['row_id']}")
        if count + int(row["max_output_tokens"]) + reserve > int(row["context_length"]):
            raise ValueError(f"token-fit gate failed for {row['row_id']}")


def _unsupported_phase(
    rows: Sequence[Mapping[str, Any]],
    reason: str,
    *,
    model: Mapping[str, Any] | None = None,
    phase: str | None = None,
    status: str = "unsupported",
) -> dict[str, Any]:
    return {
        "schema_version": "lmstudio-labkit-l339-phase-summary-v1",
        "model_id": model.get("model_id") if model else None,
        "exact_variant": model.get("exact_variant") if model else None,
        "phase": phase,
        "rows": [
            {
                **dict(row),
                "status": status,
                "stop_reason": reason,
                "call_planned": False,
                "calls_executed": 0,
                "private_record_exists": False,
            }
            for row in rows
        ],
        "verified": True,
        "final_loaded_global_count": 0,
        "private_paths_exposed": False,
        "raw_text_exposed": False,
    }


def _verify_exact_model_metadata(
    metadata: Any, model: Mapping[str, Any], *, artifact_metadata: Any = None
) -> None:
    if not isinstance(metadata, Mapping):
        raise RuntimeError("exact model metadata preflight failed")
    for field in ("key", "publisher", "architecture", "format"):
        expected = model["model_id"] if field == "key" else model[field]
        if metadata.get(field) != expected:
            raise RuntimeError(f"exact model metadata mismatch: {field}")
    _require_quantization(metadata.get("quantization"), model)
    if model.get("artifact_identity_required") is True:
        _verify_artifact_identity(artifact_metadata, model)
    elif metadata.get("selected_variant") != model["exact_variant"]:
        raise RuntimeError("exact model metadata mismatch: selected_variant")
    if metadata.get("capabilities") != model.get("capabilities"):
        raise RuntimeError("exact model metadata mismatch: capabilities")
    _verify_prompt_template_compatibility(model)
    forbidden = model.get("forbidden_substitute")
    if isinstance(forbidden, str) and forbidden in json.dumps(metadata, sort_keys=True):
        raise RuntimeError("forbidden model substitute detected")


def _require_quantization(observed: Any, model: Mapping[str, Any]) -> None:
    if not isinstance(observed, Mapping):
        raise RuntimeError("exact model metadata mismatch: quantization")
    if observed.get("name") != model.get("quantization"):
        raise RuntimeError("exact model metadata mismatch: quantization.name")
    if observed.get("bits_per_weight") != model.get("quantization_bits"):
        raise RuntimeError("exact model metadata mismatch: quantization.bits_per_weight")


def _verify_artifact_identity(artifact: Any, model: Mapping[str, Any]) -> None:
    if not isinstance(artifact, Mapping):
        raise RuntimeError("exact artifact identity unavailable")
    expected = {
        "modelKey": model["model_id"],
        "publisher": model["publisher"],
        "architecture": model["architecture"],
        "format": model["format"],
        "sizeBytes": model["size_bytes"],
        "paramsString": model["params_string"],
    }
    for field, value in expected.items():
        if artifact.get(field) != value:
            raise RuntimeError(f"exact artifact metadata mismatch: {field}")
    device = artifact.get("deviceIdentifier")
    allowed_paths = {model["exact_variant"]}
    if isinstance(device, str) and device:
        allowed_paths.add(f"{device}:{model['exact_variant']}")
    for field in ("path", "indexedModelIdentifier"):
        if artifact.get(field) not in allowed_paths:
            raise RuntimeError(f"exact artifact metadata mismatch: {field}")
    quantization = artifact.get("quantization")
    if not isinstance(quantization, Mapping):
        raise RuntimeError("exact artifact metadata mismatch: quantization")
    if quantization.get("name") != model["quantization"]:
        raise RuntimeError("exact artifact metadata mismatch: quantization.name")
    if quantization.get("bits") != model["quantization_bits"]:
        raise RuntimeError("exact artifact metadata mismatch: quantization.bits")


def _verify_prompt_template_compatibility(model: Mapping[str, Any]) -> None:
    expected = {
        "family": "gemma-4",
        "architecture": "gemma4",
        "verification_basis": "official_family_architecture_contract",
    }
    if model.get("prompt_template_compatibility") != expected:
        raise RuntimeError("prompt template compatibility contract mismatch")
    if model.get("architecture") != expected["architecture"]:
        raise RuntimeError("prompt template architecture mismatch")


def _read_lms_model_artifact_metadata(model_id: str) -> Mapping[str, Any] | None:
    try:
        completed = subprocess.run(
            ["lms", "ls", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    matches = [
        item for item in payload if isinstance(item, Mapping) and item.get("modelKey") == model_id
    ]
    return matches[0] if len(matches) == 1 else None


def _unsupported_reasoning_reason(
    rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]
) -> str | None:
    requested = {str(row["reasoning_class"]) for row in rows}
    if requested == {"reasoning_omitted_unknown"}:
        return None
    capabilities = metadata.get("capabilities")
    reasoning = capabilities.get("reasoning") if isinstance(capabilities, Mapping) else None
    allowed = reasoning.get("allowed_options") if isinstance(reasoning, Mapping) else None
    if not isinstance(allowed, Sequence) or isinstance(allowed, str):
        return "reasoning_capability_unknown_zero_call"
    missing = sorted(requested - {str(item) for item in allowed})
    return f"unsupported_reasoning_options_zero_call:{','.join(missing)}" if missing else None


def _session_prerequisites_accepted(rows: Sequence[Mapping[str, Any]]) -> bool:
    simple_ok = any(
        row.get("phase") == "text_structure"
        and row.get("task") == "simple"
        and row.get("business_verdict") == "pass"
        and row.get("schema_valid") is True
        for row in rows
    )
    context_ok = any(
        row.get("phase") == "one_shot_context"
        and int(row.get("context_length", 0)) == 16384
        and row.get("business_verdict") == "pass"
        and row.get("schema_valid") is True
        for row in rows
    )
    return simple_ok and context_ok


def _vision_transport_canary_accepted(rows: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        row.get("model_id") == "google/gemma-4-e2b"
        and row.get("phase") == "vision"
        and row.get("task") == "perception"
        and row.get("reasoning_class") == "off"
        and row.get("status") in REVIEW_REQUIRED_STATUSES
        and row.get("business_verdict") == "pass"
        and row.get("image_grounding_verdict") == "pass"
        and row.get("private_record_exists") is True
        for row in rows
    )


def _blocked_row(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        **dict(row),
        "status": "blocked_by_prior_gate",
        "stop_reason": reason,
        "call_planned": False,
        "calls_executed": 0,
        "private_record_exists": False,
    }


def _rows_pass_stop_gate(rows: Sequence[Mapping[str, Any]]) -> bool:
    return bool(rows) and all(
        row.get("business_verdict") == "pass" and row.get("status") == "review_required"
        for row in rows
    )


def _evaluate_live_row(
    row: Mapping[str, Any], message: str, dataset: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    if row["phase"] == "vision" and row["task"] == "perception":
        truth = load_yaml(REPO_ROOT / contract["axes"]["vision"]["expected_path"])
        expected = [str(item).casefold() for item in truth["expected_visible_text"]]
        recall = sum(item in message.casefold() for item in expected) / len(expected)
        grounded = bool(message.strip()) and recall >= 0.6
        return {
            "raw_json_valid": None,
            "normalized_json_valid": None,
            "schema_valid": None,
            "business_verdict": "pass" if grounded else "fail",
            "image_grounding_verdict": "pass" if grounded else "fail",
            "grounding_visible_text_recall": recall,
            "transformation": None,
            "semantic_repair": False,
        }
    parsed = parse_json_response(message, policy="single_complete_json_fence")
    schema_result = (
        validate_json_schema(parsed.parsed, _row_schema(row)) if parsed.parse_succeeded else None
    )
    schema_valid = schema_result is not None and schema_result.status == "pass"
    business_valid = schema_valid and _business_contract_valid(row, parsed.parsed, dataset)
    grounding: str | None = None
    if row["phase"] == "vision":
        truth = load_yaml(REPO_ROOT / contract["axes"]["vision"]["expected_path"])
        grounding = "pass" if _vision_grounding_valid(parsed.parsed, truth) else "fail"
        business_valid = business_valid and grounding == "pass"
    safe = parsed.safe_diagnostics()
    return {
        "raw_json_valid": parsed.raw_parse.status == "pass",
        "normalized_json_valid": parsed.parse_succeeded,
        "schema_valid": schema_valid,
        "business_verdict": "pass" if business_valid else "fail",
        "image_grounding_verdict": grounding,
        "raw_message": safe["raw"],
        "normalized_message": safe["normalized"],
        "transformation": parsed.transformation,
        "semantic_repair": False,
    }


def _row_schema(row: Mapping[str, Any]) -> dict[str, Any]:
    task = str(row["task"])
    if row["phase"] in {"one_shot_context", "session"}:
        return _object_schema(
            {
                "marker": {"type": "string"},
                "status": {"const": "ok"},
                "warnings": {"type": "array", "maxItems": 0},
            }
        )
    if row["phase"] == "text_structure":
        if task == "simple":
            return _object_schema(
                {
                    "summary": {"type": "string"},
                    "status": {"const": "ok"},
                    "warnings": {"type": "array", "maxItems": 0},
                }
            )
        if task == "blocks":
            return _object_schema(
                {
                    "blocks": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": _object_schema({"id": {"type": "integer"}}),
                    }
                }
            )
        return _object_schema(
            {
                "report": {"type": "object"},
                "stages": {"type": "array", "minItems": 3},
                "summary": {"type": "string"},
            }
        )
    fields: dict[str, Any] = {
        "screen_type": {"type": "string"},
        "visible_text": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "warnings": {"type": "array"},
    }
    if task in {"medium", "complex"}:
        fields["controls"] = {"type": "array", "minItems": 2}
    if task == "complex":
        fields.update(
            {
                "layout_regions": {"type": "array", "minItems": 2},
                "model_settings": {"type": "object"},
                "uncertainty": {"type": "string"},
            }
        )
    return _object_schema(fields)


def _object_schema(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(properties),
        "properties": dict(properties),
        "additionalProperties": False,
    }


def _business_contract_valid(
    row: Mapping[str, Any], value: Any, dataset: Mapping[str, Any]
) -> bool:
    if not isinstance(value, Mapping):
        return False
    if row["phase"] == "text_structure" and row["task"] == "blocks":
        blocks = value.get("blocks")
        return isinstance(blocks, list) and [
            item.get("id") for item in blocks if isinstance(item, Mapping)
        ] == [0, 1, 2]
    if row["phase"] == "session":
        chunk = next(
            item for item in dataset["session"]["changing_chunks"] if item["id"] == row["chunk_id"]
        )
        return value.get("marker") == chunk["marker"]
    return True


def _vision_grounding_valid(value: Any, truth: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping) or not isinstance(value.get("visible_text"), list):
        return False
    observed = " ".join(str(item) for item in value["visible_text"]).casefold()
    expected = [str(item).casefold() for item in truth["expected_visible_text"]]
    return sum(item in observed for item in expected) / len(expected) >= 0.6


def _load_completed_reviews(paths: Sequence[str | Path]) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    required = {
        "row_id",
        "evidence_id",
        "rubric_version",
        "reviewer_id_hash",
        "reviewed_private_output",
        "dimension_scores_json",
        "factual_categories_json",
        "evidence_category_ids_json",
        "final_answer_present",
        "raw_json_valid",
        "normalized_json_valid",
        "schema_valid",
        "grounding_valid",
        "verdict",
    }
    for path in paths:
        with Path(path).open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if set(row) != required or not all(
                    row.get(field, "").strip() for field in required
                ):
                    raise ValueError("private-answer review is incomplete")
                if (
                    row["reviewed_private_output"].lower() != "true"
                    or row["verdict"] not in REVIEW_VERDICTS
                ):
                    raise ValueError("private-answer review did not prove completed inspection")
                for field in (
                    "dimension_scores_json",
                    "factual_categories_json",
                    "evidence_category_ids_json",
                ):
                    json.loads(row[field])
                if row["row_id"] in reviews:
                    raise ValueError("duplicate private-answer review row")
                reviews[row["row_id"]] = dict(row)
    return reviews


def write_immutable_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite immutable output: {destination}")
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def write_review_csv(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite immutable review: {destination}")
    fields = [
        "row_id",
        "evidence_id",
        "rubric_version",
        "reviewer_id_hash",
        "reviewed_private_output",
        "dimension_scores_json",
        "factual_categories_json",
        "evidence_category_ids_json",
        "final_answer_present",
        "raw_json_valid",
        "normalized_json_valid",
        "schema_valid",
        "grounding_valid",
        "verdict",
    ]
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="L3.39 five-model matrix and replay launcher")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("plan")
    replay = sub.add_parser("replay")
    replay.add_argument("--replay-contract", default=str(DEFAULT_REPLAY))
    replay.add_argument("--private-dir", required=True)
    replay.add_argument("--output", required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--summary", action="append", default=[])
    resume.add_argument("--review", action="append", default=[])
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--summary", action="append", default=[])
    aggregate.add_argument("--review", action="append", default=[])
    aggregate.add_argument("--output", required=True)
    run = sub.add_parser("run-model-phase")
    run.add_argument("--model", required=True)
    run.add_argument("--phase", required=True, choices=PHASES)
    run.add_argument("--base-url", required=True)
    run.add_argument("--private-dir", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--dataset", default=str(DEFAULT_DATASET))
    run.add_argument("--token-counts")
    run.add_argument("--prerequisite-summary", action="append", default=[])
    run.add_argument("--live", action="store_true")
    run.add_argument("--allow-model-loads", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    contract = load_contract(args.contract)
    planned = expand_matrix(contract)
    if args.command == "validate":
        print(json.dumps({"status": "pass", "records": 114, "max_calls": 108}))
        return 0
    if args.command == "plan":
        print(json.dumps({"rows": planned, "records": 114, "max_calls": 108}, indent=2))
        return 0
    if args.command == "replay":
        payload = replay_private_records(
            source_dir=args.private_dir,
            replay_contract=load_yaml(args.replay_contract),
        )
        write_immutable_json(args.output, payload)
        print(json.dumps({"status": "ok", "records": payload["record_count"]}))
        return 0
    if args.command == "resume":
        rows = verified_resume_rows(planned, args.summary, args.review)
        print(json.dumps({"rows": rows, "record_count": len(rows)}, indent=2))
        return 0
    if args.command == "aggregate":
        payload = aggregate_summaries(planned, args.summary, args.review)
        write_immutable_json(args.output, payload)
        print(json.dumps({"status": "ok", "records": payload["row_count"]}))
        return 0
    if not args.live or not args.allow_model_loads:
        raise SystemExit("run-model-phase requires both --live and --allow-model-loads")
    token_counts = load_yaml(args.token_counts) if args.token_counts else None
    prerequisite_rows: list[dict[str, Any]] = []
    for path in args.prerequisite_summary:
        prerequisite = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            prerequisite.get("verified") is not True
            or prerequisite.get("final_loaded_global_count") != 0
        ):
            raise ValueError("prerequisite summary is not verified clean")
        prerequisite_rows.extend(prerequisite.get("rows", []))
    payload = run_model_phase(
        contract=contract,
        dataset=load_yaml(args.dataset),
        model_id=args.model,
        phase=args.phase,
        base_url=args.base_url,
        private_dir=args.private_dir,
        token_counts=token_counts,
        prerequisite_rows=prerequisite_rows,
    )
    write_immutable_json(args.output, payload)
    print(json.dumps({"status": "ok", "rows": len(payload["rows"])}))
    return 0


def _assert_global_zero(host: Any, boundary: str) -> None:
    count = host.count_all_loaded_instances()
    if count != 0:
        raise RuntimeError(f"{boundary}: global loaded_count must be zero, observed {count}")


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip(
        "-"
    )


def _file_sha256(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def _numeric_stat(stats: Mapping[str, Any], suffix: str) -> int | float | None:
    for key, value in stats.items():
        if (
            str(key).endswith(suffix)
            and isinstance(value, int | float)
            and not isinstance(value, bool)
        ):
            return value
    return None


def _message_tokens(stats: Mapping[str, Any]) -> int | float | None:
    total = _numeric_stat(stats, "total_output_tokens")
    reasoning = _numeric_stat(stats, "reasoning_output_tokens") or 0
    return total - reasoning if isinstance(total, int | float) else None


def _counts(values: Sequence[str] | Any) -> dict[str, int]:
    output: dict[str, int] = {}
    for value in values:
        output[value] = output.get(value, 0) + 1
    return dict(sorted(output.items()))


if __name__ == "__main__":
    raise SystemExit(main())
