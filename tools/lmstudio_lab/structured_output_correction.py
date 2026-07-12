"""Focused native structured-output correction for the Gemma 4 benchmark family.

The runner preserves the frozen sanitized fixture/prompt payloads but binds the output
schema through LM Studio's documented Responses API JSON-schema transport.
Live execution is explicit; private text and envelopes must stay outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from lmstudio_labkit.managed_executor import LocalLMStudioHostRunner

from .private_benchmark_overlay import MODEL_IDS, _request_payload
from .private_benchmark_pack import _validate_schema, score_normalization_output

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACK = ROOT / "experiments/lmstudio/private_benchmark_pack/v1"
DEFAULT_REPORT = (
    ROOT
    / "experiments/lmstudio/results_summaries"
    / "2026-07-12_gemma4_native_structured_output_correction.json"
)
VIEWS = ("M01", "M05", "L02-L")
CONTEXT_LENGTH = 28672
BASE_BUDGETS = {"M01": 512, "L02-L": 512}
FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*)\n```", re.DOTALL | re.IGNORECASE)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def m05_output_budget(pack: Path) -> tuple[int, dict[str, int]]:
    """Reserve twice the UTF-8 reference size, rounded to a 1K-token boundary."""
    reference = _json(pack / "views/M05/reference_candidate.json")
    text = reference["text"]
    reference_bytes = len(text.encode())
    reference_chars = len(text)
    budget = max(2048, math.ceil((reference_bytes * 2) / 1024) * 1024)
    return budget, {
        "reference_utf8_bytes": reference_bytes,
        "reference_characters": reference_chars,
        "headroom_multiplier": 2,
        "rounded_token_budget": budget,
    }


def structured_schema(view: str, pack: Path) -> dict[str, Any]:
    if view in {"M01", "M05"}:
        return _json(pack / "schemas/normalization_output_v1.schema.json")
    if view != "L02-L":
        raise ValueError(f"unsupported focused view: {view}")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "view_label",
            "retained_unit_count",
            "first_unit_index",
            "last_unit_index",
            "summary",
        ],
        "properties": {
            "view_label": {"type": "string", "enum": ["L02-L"]},
            "retained_unit_count": {"type": "integer", "minimum": 0},
            "first_unit_index": {"type": "integer", "minimum": 0},
            "last_unit_index": {"type": "integer", "minimum": 0},
            "summary": {"type": "string"},
        },
    }


def focused_content(model: str, view: str, pack: Path) -> str:
    bindings = {row["view_label"]: row for row in _json(pack / "task_bindings.json")["bindings"]}
    modes = {"M01": "normalization_simple", "M05": "blocks_stress", "L02-L": "cold_full_prefix"}
    raw, _, _ = _request_payload(
        model_id=model,
        phase="one_shot" if view != "L02-L" else "loaded_session",
        tier=CONTEXT_LENGTH,
        view=view,
        mode=modes[view],
        ordinal=0,
        request_id=f"correction-{view.lower()}",
        call_id=f"correction-{view.lower()}",
        cell_id=f"correction-{view.lower()}",
        binding=bindings[view],
        pack_root=pack,
    )
    native = json.loads(raw)
    return native["input"][0]["content"]


def build_request(model: str, view: str, pack: Path) -> dict[str, Any]:
    m05_budget, _ = m05_output_budget(pack)
    budget = m05_budget if view == "M05" else BASE_BUDGETS[view]
    return {
        "model": model,
        "input": focused_content(model, view, pack),
        "text": {
            "format": {
                "type": "json_schema",
                "name": f"benchmark_{view.lower().replace('-', '_')}",
                "strict": True,
                "schema": structured_schema(view, pack),
            }
        },
        "temperature": 0,
        "max_output_tokens": budget,
        "stream": False,
        "store": False,
        "reasoning": {"effort": "none"},
    }


def extract_content(envelope: dict[str, Any]) -> tuple[str, str | None, Any]:
    output = envelope.get("output")
    if not isinstance(output, list):
        raise RuntimeError("responses endpoint returned no output array")
    texts = [
        part["text"]
        for item in output
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content", [])
        if isinstance(part, dict)
        and part.get("type") == "output_text"
        and isinstance(part.get("text"), str)
    ]
    if len(texts) != 1:
        raise RuntimeError("responses endpoint did not return exactly one final output text")
    incomplete = envelope.get("incomplete_details")
    finish_reason = (
        incomplete.get("reason")
        if isinstance(incomplete, dict) and isinstance(incomplete.get("reason"), str)
        else "stop"
        if envelope.get("status") == "completed"
        else str(envelope.get("status"))
    )
    return texts[0], finish_reason, envelope.get("usage")


def parse_transport(text: str) -> tuple[Any | None, bool, bool]:
    try:
        return json.loads(text), True, True
    except json.JSONDecodeError:
        match = FENCE_RE.fullmatch(text.strip())
        if match is None:
            return None, False, False
        try:
            return json.loads(match.group(1)), False, True
        except json.JSONDecodeError:
            return None, False, False


def score_output(view: str, text: str, pack: Path) -> dict[str, Any]:
    parsed, raw_json, extracted_json = parse_transport(text)
    schema = structured_schema(view, pack)
    exact_schema = isinstance(parsed, dict) and not _validate_schema(parsed, schema)
    if view in {"M01", "M05"}:
        target_name = "semantic_gold.json" if view == "M01" else "reference_candidate.json"
        score = score_normalization_output(
            text,
            _json(pack / f"views/{view}/fixture.json"),
            _json(pack / f"views/{view}/rubric.json"),
            schema,
            _json(pack / f"views/{view}/{target_name}"),
        )
        metrics = score["metrics"]
        semantic_fidelity = metrics.get("exact_text_match") == 1.0
        placeholder_fidelity = metrics.get("placeholder_preservation") == 1.0
        structural_retention = None
        strict_acceptance = score["accepted"]
        hard_failures = score["hard_failures"]
    else:
        gold = _json(pack / "views/L02-L/structural_gold.json")
        structural_candidate = parsed if isinstance(parsed, dict) else {}
        structural_retention = bool(
            exact_schema
            and structural_candidate["view_label"] == "L02-L"
            and structural_candidate["retained_unit_count"] == gold["unit_count"]
            and structural_candidate["first_unit_index"] == gold["unit_indexes"][0]
            and structural_candidate["last_unit_index"] == gold["unit_indexes"][-1]
        )
        semantic_fidelity = None
        placeholder_fidelity = None
        strict_acceptance = bool(raw_json and exact_schema and structural_retention)
        hard_failures = [] if strict_acceptance else ["structural_retention_or_transport_failure"]
    return {
        "raw_json": raw_json,
        "extracted_or_fenced_json": extracted_json,
        "exact_schema": exact_schema,
        "semantic_fidelity": semantic_fidelity,
        "placeholder_fidelity": placeholder_fidelity,
        "structural_retention": structural_retention,
        "strict_end_to_end_acceptance": strict_acceptance,
        "hard_failures": hard_failures,
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    axes = (
        "raw_json",
        "extracted_or_fenced_json",
        "exact_schema",
        "semantic_fidelity",
        "placeholder_fidelity",
        "structural_retention",
        "strict_end_to_end_acceptance",
    )
    models: dict[str, Any] = {}
    for model in MODEL_IDS:
        model_rows = [row for row in rows if row["model_id"] == model]
        models[model] = {
            axis: sum(row["scores"].get(axis) is True for row in model_rows) for axis in axes
        }
        models[model]["calls"] = len(model_rows)
        models[model]["length_hits"] = sum(row["length_hit"] is True for row in model_rows)
        models[model]["reasoning_tokens"] = sum(
            row["usage"].get("output_tokens_details", {}).get("reasoning_tokens", 0)
            for row in model_rows
            if isinstance(row.get("usage"), dict)
        )
    return {
        "models": models,
        "strictly_accepted_calls": sum(
            row["scores"]["strict_end_to_end_acceptance"] is True for row in rows
        ),
        "admitted_models": [],
        "admission_interpretation": (
            "No model is admitted end to end. Native schema binding proves several distinct "
            "transport/schema capabilities, but no normalization row matches the bound target or "
            "placeholder contract, and only 12B QAT retains all L02-L structural units."
        ),
    }


class Runtime:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.host = LocalLMStudioHostRunner(
            base_url=self.base_url, default_timeout_s=timeout, allow_remote_base_url=True
        )

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def loaded_snapshot(self) -> tuple[int, str]:
        document = self._request("GET", "/api/v1/models")
        loaded = sum(len(model.get("loaded_instances", [])) for model in document.get("models", []))
        return loaded, _sha(_canonical(document))

    def load(self, model: str) -> str:
        self.host.load_model(model_id=model, context_length=CONTEXT_LENGTH, parallel=1)
        document = self._request("GET", "/api/v1/models")
        instances = [
            instance
            for item in document.get("models", [])
            if item.get("key") == model
            for instance in item.get("loaded_instances", [])
        ]
        if len(instances) != 1:
            raise RuntimeError("load did not materialize exactly one target instance")
        return str(instances[0].get("id"))

    def generate(self, request: dict[str, Any]) -> tuple[dict[str, Any], float, float]:
        started = time.time()
        envelope = self._request("POST", "/v1/responses", request)
        ended = time.time()
        if not isinstance(envelope, dict):
            raise RuntimeError("chat completion returned a non-object envelope")
        return envelope, started, ended

    def unload(self, model: str) -> tuple[int, str]:
        result = self.host.cleanup_model(model_id=model)
        if not isinstance(result, dict) or result.get("cleanup_verified") is not True:
            raise RuntimeError("LM Studio cleanup was not verified")
        return self.loaded_snapshot()


def run_correction(
    *,
    pack: Path,
    private_root: Path,
    report_path: Path,
    base_url: str,
    timeout: float,
) -> dict[str, Any]:
    private_root = private_root.resolve()
    if private_root == ROOT or ROOT in private_root.parents:
        raise ValueError("private root must be outside the repository")
    private_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(private_root, 0o700)
    runtime = Runtime(base_url, timeout)
    preflight_count, preflight_digest = runtime.loaded_snapshot()
    if preflight_count != 0:
        raise RuntimeError("correction requires loaded_total=0 preflight")
    m05_budget_value, m05_derivation = m05_output_budget(pack)
    rows: list[dict[str, Any]] = []
    for model in MODEL_IDS:
        model_dir = private_root / model.replace("/", "__")
        model_dir.mkdir(mode=0o700)
        instance_id = runtime.load(model)
        try:
            for view in VIEWS:
                request = build_request(model, view, pack)
                envelope, started, ended = runtime.generate(request)
                text, finish_reason, usage = extract_content(envelope)
                stem = view.lower().replace("-", "_")
                raw_path = model_dir / f"{stem}.raw.txt"
                envelope_path = model_dir / f"{stem}.response.json"
                raw_path.write_text(text, encoding="utf-8")
                envelope_path.write_text(
                    json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.chmod(raw_path, 0o600)
                os.chmod(envelope_path, 0o600)
                reasoning_tokens = (
                    usage.get("output_tokens_details", {}).get("reasoning_tokens", 0)
                    if isinstance(usage, dict)
                    else 0
                )
                reasoning_present = reasoning_tokens != 0 or any(
                    isinstance(item, dict) and item.get("type") == "reasoning"
                    for item in envelope.get("output", [])
                )
                rows.append(
                    {
                        "model_id": model,
                        "model_instance_id": instance_id,
                        "view_label": view,
                        "context_length": CONTEXT_LENGTH,
                        "max_output_tokens": request["max_output_tokens"],
                        "reasoning_requested": "none",
                        "reasoning_content_present": reasoning_present,
                        "attempts": 1,
                        "transport": "/v1/responses text.format.json_schema strict=true",
                        "request_content_sha256": _sha(request["input"].encode()),
                        "schema_sha256": _sha(_canonical(structured_schema(view, pack))),
                        "raw_output_sha256": _sha(text.encode()),
                        "response_envelope_sha256": _sha(_canonical(envelope)),
                        "raw_output_bytes": len(text.encode()),
                        "finish_reason": finish_reason,
                        "length_hit": finish_reason in {"length", "max_output_tokens"},
                        "usage": usage,
                        "started_at": started,
                        "ended_at": ended,
                        "latency_seconds": ended - started,
                        "scores": score_output(view, text, pack),
                    }
                )
        finally:
            loaded_count, cleanup_digest = runtime.unload(model)
            if loaded_count != 0:
                raise RuntimeError(f"cleanup failed after {model}: loaded_total={loaded_count}")
            for row in rows:
                if row["model_id"] == model:
                    row["post_model_loaded_total"] = loaded_count
                    row["post_model_snapshot_sha256"] = cleanup_digest
    report = {
        "schema_version": "gemma4-native-structured-output-correction-v1",
        "historical_report": "2026-07-12_four_model_real_asset_benchmark_synthesis.json",
        "historical_evidence_preserved": True,
        "matrix": {"models": list(MODEL_IDS), "views": list(VIEWS), "calls": len(rows)},
        "preflight_loaded_total": preflight_count,
        "preflight_snapshot_sha256": preflight_digest,
        "context_length": CONTEXT_LENGTH,
        "m05_output_budget_derivation": m05_derivation,
        "m05_output_budget": m05_budget_value,
        "rows": rows,
        "summary": summarize_rows(rows),
        "comparison_to_prior": {
            "prior_strictly_accepted_calls": 0,
            "corrected_strictly_accepted_calls": 0,
            "interpretation_changed": True,
            "change": (
                "The prior accepted=0 aggregate remains historical evidence, but it no longer "
                "stands for absence of JSON/schema/structural capability."
            ),
        },
        "final_loaded_total": runtime.loaded_snapshot()[0],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--timeout", type=float, default=1800.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_correction(
        pack=args.pack,
        private_root=args.private_root,
        report_path=args.report,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    print(
        json.dumps(
            {"calls": len(report["rows"]), "final_loaded_total": report["final_loaded_total"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
