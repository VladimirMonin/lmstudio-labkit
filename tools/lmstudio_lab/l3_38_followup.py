from __future__ import annotations

import argparse
import base64
import json
import statistics
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from lmstudio_labkit.validation import validate_response

from lmstudio_labkit import LocalFailureForensics, LocalLMStudioHostRunner, ResponseContract

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO_ROOT / "experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml"
_ALLOWED_PHASES = ("moe_8k", "moe_16k", "e4b_vision", "repeated_context_12b")


def load_contract(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("L3.38 contract must be a YAML mapping")
    _validate_contract(payload)
    return payload


def _validate_contract(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != "lmstudio-labkit-l338-followup-v1":
        raise ValueError("unsupported L3.38 contract schema_version")
    execution = _mapping(payload.get("execution"), "execution")
    required_execution = {
        "serial_only": True,
        "parallel": 1,
        "retries": "off",
        "temperature": 0,
        "private_forensics_required": True,
        "private_forensics_must_be_external": True,
        "global_loaded_count_required_between_phases": 0,
        "allow_model_downloads": False,
        "allow_raw_artifacts_in_git": False,
        "remote_resource_telemetry": "timing_only",
    }
    for key, expected in required_execution.items():
        if execution.get(key) != expected:
            raise ValueError(f"execution.{key} must be {expected!r}")
    phases = _mapping(payload.get("phases"), "phases")
    if set(phases) != {*_ALLOWED_PHASES, "strict_json_investigation"}:
        raise ValueError("L3.38 contract must declare exactly the five bounded phases")
    expected = {
        "moe_8k": ("google/gemma-4-26b-a4b-qat", 8192, 2),
        "moe_16k": ("google/gemma-4-26b-a4b-qat", 16384, 2),
        "repeated_context_12b": ("google/gemma-4-12b-qat", 16384, 6),
    }
    for name, (model_id, context, rows) in expected.items():
        phase = _mapping(phases.get(name), f"phases.{name}")
        if phase.get("model_id") != model_id or phase.get("context_length") != context:
            raise ValueError(f"phases.{name} has an unexpected model/context contract")
        if phase.get("expected_rows") != rows:
            raise ValueError(f"phases.{name}.expected_rows must be {rows}")
        if phase.get("max_output_tokens") != 1024:
            raise ValueError(f"phases.{name}.max_output_tokens must be 1024")
        if phase.get("route") != "/api/v1/chat":
            raise ValueError(f"phases.{name}.route must be the native chat route")
    if phases["moe_8k"].get("reasoning_modes") != ["off", "on"]:
        raise ValueError("moe_8k requires the paired off/on order")
    if phases["moe_16k"].get("reasoning_modes") != ["off", "on"]:
        raise ValueError("moe_16k requires the paired off/on order")
    vision = _mapping(phases.get("e4b_vision"), "phases.e4b_vision")
    if (
        vision.get("model_id") != "google/gemma-4-e4b"
        or vision.get("context_length") != 8192
        or vision.get("route") != "/api/v1/chat"
        or vision.get("reasoning") != "off"
        or vision.get("max_output_tokens") != 1024
        or vision.get("lifecycle") != "cold_per_gate"
        or vision.get("gate_order")
        != ["text_route_preflight", "text_minimal_json", "image_minimal_json"]
        or vision.get("stop_on_first_failed_gate") is not True
        or vision.get("expected_rows_maximum") != 3
    ):
        raise ValueError("e4b_vision must keep the reasoning-off text-before-image gate")
    repeated = _mapping(phases.get("repeated_context_12b"), "phases.repeated_context_12b")
    if (
        repeated.get("reasoning") != "off"
        or repeated.get("lifecycle") != "loaded_session_per_comparison"
        or repeated.get("comparison_order") != ["exact_same_input", "stable_prefix_dynamic_suffix"]
        or repeated.get("requests_per_comparison") != 3
        or repeated.get("store_server_conversation") is not False
        or repeated.get("interpretation") != "timing_and_response_quality_only"
        or repeated.get("kv_reuse_claim_allowed") is not False
        or repeated.get("memory_claim_allowed_over_remote_link") is not False
    ):
        raise ValueError("repeated_context_12b must keep the bounded reasoning-off contract")
    strict = _mapping(phases.get("strict_json_investigation"), "phases.strict_json_investigation")
    if (
        strict.get("route") != "/v1/chat/completions"
        or strict.get("response_format") != "json_schema"
        or strict.get("request_reasoning_control") != "unavailable_unproven"
        or strict.get("probe_enabled") is not False
        or strict.get("expected_rows") != 0
    ):
        raise ValueError(
            "strict JSON generation must remain disabled while reasoning-off is unproven"
        )


def execution_plan(contract: Mapping[str, Any]) -> dict[str, Any]:
    phases = _mapping(contract["phases"], "phases")
    return {
        "schema_version": contract["schema_version"],
        "ordered_launch": ["moe_8k", "moe_16k", "e4b_vision", "repeated_context_12b"],
        "maximum_generation_rows": 13,
        "strict_generation_rows": 0,
        "phases": {
            name: {
                "model_id": phase["model_id"],
                "context_length": phase["context_length"],
                "expected_rows": phase.get("expected_rows", phase.get("expected_rows_maximum")),
                "conditional": name == "moe_16k",
            }
            for name, phase in phases.items()
            if name != "strict_json_investigation"
        },
        "stop_conditions": list(contract["stop_conditions"]),
    }


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _blocks_contract(contract: Mapping[str, Any]) -> ResponseContract:
    blocks = _mapping(_mapping(contract["contracts"], "contracts")["blocks"], "contracts.blocks")
    return ResponseContract(
        mode="json",
        schema=_mapping(blocks["schema"], "contracts.blocks.schema"),
        expected_ids=(0, 1, 2),
        id_paths=("blocks[*].id",),
        preserve_order=True,
        language_policy="skip",
        length_ratio_policy="off",
        schema_family="blocks",
        response_schema_complexity="blocks",
    )


def _marker_contract(contract: Mapping[str, Any], marker: str) -> ResponseContract:
    marker_contract = _mapping(
        _mapping(contract["contracts"], "contracts")["tiny_marker"],
        "contracts.tiny_marker",
    )
    schema = json.loads(json.dumps(marker_contract["schema"], ensure_ascii=False))
    schema["properties"]["marker"]["const"] = marker
    return ResponseContract(
        mode="json",
        schema=schema,
        expected_output={"marker": marker, "status": "ok", "warnings": []},
        language_policy="skip",
        length_ratio_policy="off",
        schema_family="simple",
        response_schema_complexity="simple",
    )


def _vision_contract() -> ResponseContract:
    return ResponseContract(
        mode="json",
        schema={
            "type": "object",
            "required": ["settings_dialog"],
            "additionalProperties": False,
            "properties": {"settings_dialog": {"type": "boolean", "const": True}},
        },
        expected_output={"settings_dialog": True},
        language_policy="skip",
        length_ratio_policy="off",
        schema_family="minimal_vision_route",
        response_schema_complexity="simple",
    )


def _minimal_text_contract() -> ResponseContract:
    return ResponseContract(
        mode="json",
        schema={
            "type": "object",
            "required": ["route_ok"],
            "additionalProperties": False,
            "properties": {"route_ok": {"type": "boolean", "const": True}},
        },
        expected_output={"route_ok": True},
        language_policy="skip",
        length_ratio_policy="off",
        schema_family="minimal_native_route",
        response_schema_complexity="simple",
    )


def _safe_row(
    *,
    request_id: str,
    reasoning: str,
    context_length: int,
    result: Any,
    contract: ResponseContract | None,
) -> dict[str, Any]:
    validation = (
        validate_response(result.message_text, contract, finish_reason=result.finish_reason)
        if contract is not None
        else None
    )
    return {
        "request_id": request_id,
        "context_length": context_length,
        "reasoning": reasoning,
        "http_status": result.http_status,
        "content_type": result.content_type,
        "finish_reason": result.finish_reason,
        "boundary": result.boundary,
        "reasoning_allowed_options": list(result.reasoning_allowed_options),
        "reasoning_default": result.reasoning_default,
        "numeric_stats": result.numeric_stats,
        "reasoning_char_count": len(result.reasoning_text),
        "reasoning_sha256": _hash_text(result.reasoning_text),
        "message_char_count": len(result.message_text),
        "message_sha256": _hash_text(result.message_text),
        "validation_status": validation.status if validation is not None else "plain_text",
        "validation_failures": [
            {"name": item.name, "category": item.category}
            for item in validation.results
            if item.status == "fail"
        ]
        if validation is not None
        else [],
        "private_local_pack_exists": result.forensics_handle is not None,
    }


def _assert_clean(host: LocalLMStudioHostRunner, boundary: str) -> None:
    count = host.count_all_loaded_instances()
    if count != 0:
        raise RuntimeError(f"{boundary}: global loaded_count must be zero, observed {count!r}")


def _preflight_phase(
    host: LocalLMStudioHostRunner,
    *,
    phase_name: str,
    phase: Mapping[str, Any],
) -> None:
    model_id = str(phase["model_id"])
    metadata = host.model_metadata(model_id=model_id)
    if not isinstance(metadata, Mapping):
        raise RuntimeError(f"exact installed model key was not found: {model_id}")
    capabilities = metadata.get("capabilities")
    reasoning_capability = (
        capabilities.get("reasoning") if isinstance(capabilities, Mapping) else None
    )
    allowed = (
        reasoning_capability.get("allowed_options")
        if isinstance(reasoning_capability, Mapping)
        else None
    )
    requested = phase.get("reasoning_modes", [phase.get("reasoning")])
    if (
        not isinstance(allowed, Sequence)
        or isinstance(allowed, (str, bytes, bytearray))
        or any(mode not in allowed for mode in requested)
    ):
        raise RuntimeError(
            f"exact model {model_id} does not advertise every requested reasoning mode"
        )
    if phase_name == "e4b_vision" and (
        not isinstance(capabilities, Mapping) or capabilities.get("vision") is not True
    ):
        raise RuntimeError("exact E4B metadata did not advertise vision=true")


def _load_verified_once(
    host: LocalLMStudioHostRunner, *, model_id: str, context_length: int
) -> dict[str, Any]:
    _assert_clean(host, "pre-load")
    load = host.load_model(model_id=model_id, context_length=context_length, parallel=1)
    try:
        if not isinstance(load, Mapping) or load.get("load_verified") is not True:
            raise RuntimeError("model load response was not verified")
        applied = load.get("applied_load_config", load.get("load_config"))
        if not isinstance(applied, Mapping):
            raise RuntimeError("model load response did not expose applied load config")
        if int(applied.get("context_length", -1)) != context_length:
            raise RuntimeError("applied model context did not match the requested context")
        if int(applied.get("parallel", applied.get("n_parallel", -1))) != 1:
            raise RuntimeError("applied model parallelism did not equal one")
        if host.count_loaded_instances(model_id=model_id) != 1:
            raise RuntimeError("target model must materialize exactly one loaded instance")
        if host.count_all_loaded_instances() != 1:
            raise RuntimeError("exactly one global loaded instance is allowed")
    except Exception:
        host.cleanup_model(model_id=model_id)
        _assert_clean(host, "failed-load-cleanup")
        raise
    return dict(load)


def _run_loaded_requests(
    *,
    host: LocalLMStudioHostRunner,
    forensics: LocalFailureForensics,
    model_id: str,
    context_length: int,
    requests: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    _load_verified_once(host, model_id=model_id, context_length=context_length)
    rows: list[dict[str, Any]] = []
    handles: list[Any] = []
    cleanup: object = {"cleanup_verified": False}
    final_target: int | None = None
    try:
        for index, request in enumerate(requests, start=1):
            result = host.native_chat_diagnostic(
                model_id=model_id,
                messages=({"role": "user", "content": str(request["prompt"])},),
                reasoning=str(request["reasoning"]),
                max_output_tokens=1024,
                timeout_s=float(request.get("timeout_s", 600.0)),
                stream=True,
                request_id=str(request["request_id"]),
                attempt_index=index,
                context_length=context_length,
                image_data_url=request.get("image_data_url"),
            )
            if result.forensics_handle is not None:
                handles.append(result.forensics_handle)
            else:
                raise RuntimeError("native diagnostic did not create a private forensic record")
            row = _safe_row(
                request_id=str(request["request_id"]),
                reasoning=str(request["reasoning"]),
                context_length=context_length,
                result=result,
                contract=request.get("contract"),
            )
            row["latency_ms"] = result.forensics_handle.safe_manifest["latency_ms"]
            rows.append(row)
            if result.http_status != 200 or result.boundary != "terminal":
                raise RuntimeError(
                    f"{request['request_id']}: native request did not reach a successful terminal boundary"
                )
    finally:
        cleanup = host.cleanup_model(model_id=model_id)
        final_target = host.count_loaded_instances(model_id=model_id)
        for handle in handles:
            forensics.finalize_attempt(
                handle,
                cleanup_result=cleanup,
                final_loaded_instances=final_target,
            )
    if not isinstance(cleanup, Mapping) or cleanup.get("cleanup_verified") is not True:
        raise RuntimeError("target cleanup was not verified")
    if final_target != 0:
        raise RuntimeError("target loaded_count must be zero after cleanup")
    _assert_clean(host, "post-phase")
    for row in rows:
        row["cleanup_verified"] = True
        row["final_loaded_global_count"] = 0
    return rows


def _run_cold_pair(
    contract: Mapping[str, Any],
    phase_name: str,
    host: LocalLMStudioHostRunner,
    forensics: LocalFailureForensics,
) -> dict[str, Any]:
    phase = _mapping(contract["phases"][phase_name], f"phases.{phase_name}")
    rows: list[dict[str, Any]] = []
    prompt = str(contract["contracts"]["blocks"]["prompt"])
    response_contract = _blocks_contract(contract)
    for reasoning in phase["reasoning_modes"]:
        rows.extend(
            _run_loaded_requests(
                host=host,
                forensics=forensics,
                model_id=str(phase["model_id"]),
                context_length=int(phase["context_length"]),
                requests=(
                    {
                        "request_id": f"{phase_name}-{reasoning}",
                        "prompt": prompt,
                        "reasoning": reasoning,
                        "contract": response_contract,
                    },
                ),
            )
        )
    interpretable = all(
        row["http_status"] == 200
        and row["boundary"] == "terminal"
        and row["private_local_pack_exists"] is True
        and row["cleanup_verified"] is True
        and row["final_loaded_global_count"] == 0
        for row in rows
    )
    return {"phase": phase_name, "rows": rows, "interpretable_pair": interpretable}


def _prior_is_interpretable(path: str | Path | None) -> bool:
    if path is None:
        return False
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("phase") == "moe_8k" and payload.get("interpretable_pair") is True


def _run_vision(
    contract: Mapping[str, Any],
    host: LocalLMStudioHostRunner,
    forensics: LocalFailureForensics,
) -> dict[str, Any]:
    phase = _mapping(contract["phases"]["e4b_vision"], "phases.e4b_vision")
    text_rows = _run_loaded_requests(
        host=host,
        forensics=forensics,
        model_id=str(phase["model_id"]),
        context_length=int(phase["context_length"]),
        requests=(
            {
                "request_id": "e4b-vision-text-route-preflight",
                "prompt": "Reply with exactly ROUTE_OK.",
                "reasoning": "off",
                "contract": None,
            },
        ),
    )
    text_pass = (
        text_rows[0]["http_status"] == 200
        and text_rows[0]["boundary"] == "terminal"
        and text_rows[0]["message_char_count"] > 0
    )
    if not text_pass:
        return {"phase": "e4b_vision", "rows": text_rows, "stopped_by": "text_route_preflight"}
    structured_rows = _run_loaded_requests(
        host=host,
        forensics=forensics,
        model_id=str(phase["model_id"]),
        context_length=int(phase["context_length"]),
        requests=(
            {
                "request_id": "e4b-vision-text-minimal-json",
                "prompt": 'Return only {"route_ok":true}.',
                "reasoning": "off",
                "contract": _minimal_text_contract(),
            },
        ),
    )
    if structured_rows[0]["validation_status"] != "pass":
        return {
            "phase": "e4b_vision",
            "rows": text_rows + structured_rows,
            "stopped_by": "text_minimal_json",
        }
    fixture = (REPO_ROOT / str(phase["image_fixture"])).resolve(strict=True)
    image_bytes = fixture.read_bytes()
    if sha256(image_bytes).hexdigest() != phase["image_sha256"]:
        raise RuntimeError("vision fixture hash mismatch")
    image_data_url = "data:image/webp;base64," + base64.b64encode(image_bytes).decode("ascii")
    image_rows = _run_loaded_requests(
        host=host,
        forensics=forensics,
        model_id=str(phase["model_id"]),
        context_length=int(phase["context_length"]),
        requests=(
            {
                "request_id": "e4b-vision-minimal-json",
                "prompt": (
                    "Inspect this public-safe synthetic settings image. Return only "
                    '{"settings_dialog":true} if it is a settings dialog.'
                ),
                "reasoning": "off",
                "contract": _vision_contract(),
                "image_data_url": image_data_url,
            },
        ),
    )
    image_pass = image_rows[0]["validation_status"] == "pass"
    return {
        "phase": "e4b_vision",
        "rows": text_rows + structured_rows + image_rows,
        "stopped_by": None if image_pass else "image_minimal_json",
    }


def _synthetic_prefix() -> str:
    lines = [
        f"SYNTHETIC-{index:04d}: alpha beta gamma delta epsilon; number {index}; control line."
        for index in range(250)
    ]
    return "Deterministic public-safe repeated context.\n" + "\n".join(lines)


def _run_repeated_context(
    contract: Mapping[str, Any],
    host: LocalLMStudioHostRunner,
    forensics: LocalFailureForensics,
) -> dict[str, Any]:
    phase = _mapping(contract["phases"]["repeated_context_12b"], "phases.repeated_context_12b")
    prefix = _synthetic_prefix()
    all_rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for comparison in phase["comparison_order"]:
        requests: list[dict[str, Any]] = []
        for index in range(1, int(phase["requests_per_comparison"]) + 1):
            marker = "EXACT" if comparison == "exact_same_input" else f"VAR-{index}"
            suffix = (
                "CONTROL_MODE: exact same input."
                if comparison == "exact_same_input"
                else f"CONTROL_MODE: stable prefix with dynamic suffix {index}."
            )
            prompt = (
                f"{prefix}\n{suffix}\nReturn JSON only with marker={marker!r}, "
                "status='ok', warnings=[]. Do not repeat the reference context."
            )
            requests.append(
                {
                    "request_id": f"12b-{comparison}-{index}",
                    "prompt": prompt,
                    "reasoning": "off",
                    "contract": _marker_contract(contract, marker),
                }
            )
        rows = _run_loaded_requests(
            host=host,
            forensics=forensics,
            model_id=str(phase["model_id"]),
            context_length=int(phase["context_length"]),
            requests=tuple(requests),
        )
        all_rows.extend(rows)
        comparisons.append(
            {
                "name": comparison,
                "rows": len(rows),
                "valid_rows": sum(row["validation_status"] == "pass" for row in rows),
                "first_latency_ms": rows[0]["latency_ms"],
                "measured_median_latency_ms": round(
                    statistics.median(float(row["latency_ms"]) for row in rows[1:]), 3
                ),
            }
        )
    return {
        "phase": "repeated_context_12b",
        "rows": all_rows,
        "comparisons": comparisons,
        "kv_reuse_claimed": False,
        "memory_claimed": False,
        "interpretation": "timing_and_response_quality_only",
    }


def run_phase(
    *,
    contract: Mapping[str, Any],
    phase_name: str,
    base_url: str,
    private_dir: str | Path,
    prior_summary: str | Path | None = None,
) -> dict[str, Any]:
    if phase_name not in _ALLOWED_PHASES:
        raise ValueError(f"unsupported live phase: {phase_name}")
    if phase_name == "moe_16k" and not _prior_is_interpretable(prior_summary):
        raise ValueError("moe_16k requires an interpretable moe_8k prior summary")
    forensics = LocalFailureForensics(private_dir, repo_root=REPO_ROOT, enabled=True)
    host = LocalLMStudioHostRunner(
        base_url=base_url,
        default_timeout_s=600.0,
        allow_remote_base_url=True,
        allow_native_diagnostics=True,
        failure_forensics=forensics,
    )
    _assert_clean(host, "run-start")
    phase = _mapping(contract["phases"][phase_name], f"phases.{phase_name}")
    _preflight_phase(host, phase_name=phase_name, phase=phase)
    if phase_name in {"moe_8k", "moe_16k"}:
        result = _run_cold_pair(contract, phase_name, host, forensics)
    elif phase_name == "e4b_vision":
        result = _run_vision(contract, host, forensics)
    else:
        result = _run_repeated_context(contract, host, forensics)
    _assert_clean(host, "run-end")
    result["schema_version"] = contract["schema_version"]
    result["final_loaded_global_count"] = 0
    result["private_forensics_exists"] = True
    result["private_forensics_path_exposed"] = False
    result["raw_prompt_response_in_summary"] = False
    return result


def _write_summary(output_dir: str | Path, phase: str, payload: Mapping[str, Any]) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{phase}.sanitized.json"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing summary: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="L3.38 bounded reasoning-off follow-up launcher")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("plan")
    run = sub.add_parser("run")
    run.add_argument("--phase", required=True, choices=_ALLOWED_PHASES)
    run.add_argument("--base-url", required=True)
    run.add_argument("--private-dir", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--prior-summary")
    run.add_argument("--live", action="store_true")
    run.add_argument("--allow-model-loads", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    contract = load_contract(args.contract)
    if args.command == "validate":
        print(json.dumps({"status": "pass", "contract": str(args.contract)}, sort_keys=True))
        return 0
    if args.command == "plan":
        print(json.dumps(execution_plan(contract), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.live or not args.allow_model_loads:
        raise SystemExit("run requires both --live and --allow-model-loads")
    payload = run_phase(
        contract=contract,
        phase_name=args.phase,
        base_url=args.base_url,
        private_dir=args.private_dir,
        prior_summary=args.prior_summary,
    )
    path = _write_summary(args.output_dir, args.phase, payload)
    print(json.dumps({"status": "ok", "summary": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
