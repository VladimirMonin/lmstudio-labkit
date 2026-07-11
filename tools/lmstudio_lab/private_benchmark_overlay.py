"""Fail-closed, offline contracts for the four-model benchmark overlay.

The module builds immutable request artifacts and validates execution evidence.  It
does not contain an LM Studio transport: a live driver must implement the returned
event contract, while this module independently checks its trace and private files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .private_benchmark_pack import score_normalization_output, validate_pack

MODEL_IDS = (
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
)
CONTEXT_TIERS = (8192, 16384, 28672)
PARALLELISM_LEVELS = (1, 2, 4)
SESSION_SEQUENCE = (
    "cold_full_prefix",
    "loaded_first",
    "loaded_changing_1",
    "loaded_changing_2",
    "loaded_changing_3",
    "loaded_exact_repeat_1",
    "loaded_exact_repeat_2",
)
HEX_FIELDS = {"request_sha256", "tokenizer_artifact_sha256", "token_ids_sha256"}
OUTPUT_TOKEN_BUDGETS = {
    "short_semantic_normalization": 512,
    "long_whisper_normalization": 2048,
    "structural_retention": 512,
}
SAFETY_MARGIN = 256
_AUTHORITY_STORE = Path.home() / ".local/share/lmstudio-labkit/tokenizer-authority"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return _sha(_canonical(value))


def _hex(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def compute_bound_scorecard(
    raw_output: str, request: dict[str, Any], pack_root: str | Path
) -> dict[str, Any]:
    """Compute a scorecard from immutable pack bindings, never from caller verdicts."""
    root = Path(pack_root)
    binding = next(
        row
        for row in _json(root / "task_bindings.json")["bindings"]
        if row["view_label"] == request["view_label"]
    )
    if _digest(binding) != request["scorer_binding"]["task_binding_sha256"]:
        raise ValueError("task binding digest mismatch")
    scorer_binding = request["scorer_binding"]
    if (
        binding["view_label"] != request["view_label"]
        or binding["task_family"] != scorer_binding["task_family"]
    ):
        raise ValueError("view/task family binding mismatch")
    view_root = root / "views" / request["view_label"]
    paths = {
        "prompt_sha256": root / binding["prompt_path"] if binding.get("prompt_path") else None,
        "output_schema_sha256": root / "schemas" / "normalization_output_v1.schema.json"
        if binding.get("output_schema_version") == "normalization-v1"
        else None,
        "target_sha256": root / binding["target_path"] if binding.get("target_path") else None,
        "rubric_sha256": view_root / "rubric.json",
    }
    for field, path in paths.items():
        observed = _sha(path.read_bytes()) if path else None
        if scorer_binding.get(field) != observed:
            raise ValueError(f"{field} mismatch")
    if binding["task_family"] == "normalization":
        return score_normalization_output(
            raw_output,
            _json(view_root / "fixture.json"),
            _json(view_root / "rubric.json"),
            _json(root / "schemas" / "normalization_output_v1.schema.json"),
            _json(root / binding["target_path"]),
        )
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        parsed = None
    return {
        "schema_version": "structural-scorecard-v1",
        "view_label": request["view_label"],
        "task_family": binding["task_family"],
        "json_object": isinstance(parsed, dict),
        "accepted": False,
        "acceptance_scope": "structural_only_no_semantic_acceptance",
    }


def _trusted_scorer_binding(request: dict[str, Any], pack_root: Path) -> dict[str, Any]:
    binding = next(
        row
        for row in _json(pack_root / "task_bindings.json")["bindings"]
        if row["view_label"] == request["view_label"]
    )
    prompt = pack_root / binding["prompt_path"] if binding.get("prompt_path") else None
    target = pack_root / binding["target_path"] if binding.get("target_path") else None
    schema = (
        pack_root / "schemas" / "normalization_output_v1.schema.json"
        if binding.get("output_schema_version") == "normalization-v1"
        else None
    )
    return {
        "view_label": binding["view_label"],
        "task_family": binding["task_family"],
        "task_binding_sha256": _digest(binding),
        "prompt_sha256": _sha(prompt.read_bytes()) if prompt else None,
        "output_schema_version": binding.get("output_schema_version"),
        "output_schema_sha256": _sha(schema.read_bytes()) if schema else None,
        "target_sha256": _sha(target.read_bytes()) if target else None,
        "rubric_version": binding["rubric_version"],
        "rubric_sha256": _sha(
            (pack_root / "views" / binding["view_label"] / "rubric.json").read_bytes()
        ),
        "scorer_sha256": _sha(compute_bound_scorecard.__code__.co_code),
    }


def _task_axis(view: str, task_family: str) -> str:
    if view == "M01":
        return "short_semantic_normalization"
    if task_family == "normalization":
        return "long_whisper_normalization"
    return "structural_retention"


def context_fits(input_tokens: Any, max_output_tokens: Any, loaded_context: Any) -> bool:
    """Admit exact equality and reject any input/output overflow."""
    return input_tokens + max_output_tokens <= loaded_context


_TRACE_AUTHORITY = object()


class ValidatedTraceHandle:
    """Opaque, single-use-per-call result minted by the runtime capture boundary."""

    __slots__ = ("_authority", "_calls", "_consumed", "plan_sha256", "trace_sha256")

    def __init__(
        self,
        authority: object,
        plan_sha256: str,
        trace_sha256: str,
        calls: dict[str, dict[str, Any]],
    ) -> None:
        if authority is not _TRACE_AUTHORITY:
            raise TypeError("validated trace handles are minted only by the capture boundary")
        self._authority = authority
        self.plan_sha256 = plan_sha256
        self.trace_sha256 = trace_sha256
        self._calls = calls
        self._consumed: set[str] = set()

    def consume(self, request: dict[str, Any]) -> dict[str, Any]:
        if self._authority is not _TRACE_AUTHORITY:
            raise ValueError("unauthenticated validated trace handle")
        call_id = request.get("call_id")
        if call_id in self._consumed:
            raise ValueError("validated trace call handle already consumed")
        call = self._calls.get(call_id)
        if call is None or call.get("request_sha256") != request.get("request_sha256"):
            raise ValueError("validated trace handle does not bind planned request")
        self._consumed.add(call_id)
        return dict(call)


@dataclass(frozen=True, slots=True)
class OverlayPlan:
    manifest_sha256: str
    pack_tree_sha256: str
    cells: tuple[dict[str, Any], ...]
    requests: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "four-model-execution-plan-v2",
            "manifest_sha256": self.manifest_sha256,
            "pack_tree_sha256": self.pack_tree_sha256,
            "planned_cells": len(self.cells),
            "planned_model_calls": len(self.requests),
            "live": False,
            "cells": list(self.cells),
            "requests": list(self.requests),
        }


def validate_overlay_manifest(manifest: dict[str, Any], pack_root: Path) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != "four-model-overlay-v2":
        errors.append("schema_version must be four-model-overlay-v2")
    if tuple(x.get("model_id") for x in manifest.get("models", [])) != MODEL_IDS:
        errors.append("models must contain the exact canonical inventory")
    if tuple(manifest.get("context_tiers", [])) != CONTEXT_TIERS:
        errors.append("context_tiers must be canonical")
    if tuple(manifest.get("parallelism_levels", [])) != PARALLELISM_LEVELS:
        errors.append("parallelism_levels must be canonical")
    models = manifest.get("models", [])
    for model in models:
        if model.get("admission_status") == "unavailable":
            if model.get("model_revision") is not None or not model.get("admission_reason"):
                errors.append("unavailable models require null revision and an admission reason")
        elif not isinstance(model.get("model_revision"), str) or not model["model_revision"]:
            errors.append("available models require a non-empty runtime model revision")
    if manifest.get("max_model_calls") != 80 or manifest.get("live") is not False:
        errors.append("manifest must be offline with max_model_calls=80")
    if manifest.get("raw_output_policy") != "private_outside_repository":
        errors.append("raw_output_policy must be private_outside_repository")
    pack = _json(pack_root / "pack.json")
    if manifest.get("pack_tree_sha256") != pack.get("public_tree_sha256"):
        errors.append("pack digest mismatch")
    bindings = {x.get("view_label") for x in _json(pack_root / "task_bindings.json")["bindings"]}
    profiles = manifest.get("structure_profiles", [])
    if {x.get("complexity") for x in profiles} != {"simple", "stress", "long_structural"}:
        errors.append("structure profiles are incomplete")
    if not {x.get("view_label") for x in profiles} <= bindings:
        errors.append("structure profile view is unknown")
    return errors


def _request_payload(
    *,
    model_id: str,
    phase: str,
    tier: int,
    view: str,
    mode: str,
    ordinal: int,
    request_id: str,
    call_id: str,
    cell_id: str,
    binding: dict[str, Any],
    pack_root: Path,
) -> tuple[bytes, bytes, bytes]:
    """Build the exact native-chat request, including its bound public benchmark assets."""
    fixture = _json(pack_root / "views" / view / "fixture.json")
    prompt = (
        (pack_root / binding["prompt_path"]).read_text(encoding="utf-8")
        if binding.get("prompt_path")
        else (
            "Evaluate structural context retention. Return one JSON object with keys "
            "view_label, retained_unit_count, first_unit_index, last_unit_index, and summary. "
            "Do not add facts or alter protected placeholder tokens."
        )
    )
    schema = (
        _json(pack_root / "schemas" / "normalization_output_v1.schema.json")
        if binding.get("output_schema_version") == "normalization-v1"
        else {
            "type": "object",
            "required": [
                "view_label",
                "retained_unit_count",
                "first_unit_index",
                "last_unit_index",
                "summary",
            ],
        }
    )
    stable = {
        "task_prompt": prompt,
        "sanitized_input": fixture,
        "output_schema": schema,
        "task_binding": {
            "view_label": view,
            "task_family": binding["task_family"],
            "rubric_version": binding["rubric_version"],
        },
    }
    prefix = _canonical(stable)
    suffix_key = (
        "changing-base"
        if mode in {"loaded_changing_3", "loaded_exact_repeat_1", "loaded_exact_repeat_2"}
        else mode
    )
    suffix = _canonical(
        {
            "chunk_control": suffix_key,
            "ordinal_source": 4 if mode.startswith("loaded_exact") else ordinal,
        }
    )
    content = prefix.decode("utf-8") + "\n" + suffix.decode("utf-8")
    task_axis = _task_axis(view, binding["task_family"])
    document = {
        "schema_version": "lmstudio-benchmark-request-v1",
        "request_id": request_id,
        "call_id": call_id,
        "cell_id": cell_id,
        "model": model_id,
        "input": [{"type": "text", "content": content}],
        "context_length": tier,
        "temperature": 0,
        "max_output_tokens": OUTPUT_TOKEN_BUDGETS[task_axis],
        "benchmark_binding": stable["task_binding"],
    }
    return _canonical(document), prefix, suffix


def materialize_request_artifacts(
    manifest_path: str | Path, pack_root: str | Path, artifact_root: str | Path
) -> tuple[dict[str, Any], ...]:
    """Create the 80 immutable canonical request files needed before tokenization."""
    manifest_path, pack_root, artifact_root = (
        Path(manifest_path),
        Path(pack_root),
        Path(artifact_root),
    )
    manifest = _json(manifest_path)
    issues = validate_pack(pack_root) or validate_overlay_manifest(manifest, pack_root)
    if issues:
        raise ValueError(f"invalid overlay inputs: {issues}")
    artifact_root.mkdir(parents=True, exist_ok=True)
    bindings = {x["view_label"]: x for x in _json(pack_root / "task_bindings.json")["bindings"]}
    model_revisions = {x["model_id"]: x["model_revision"] for x in manifest["models"]}
    specs: list[tuple[str, int, str, str, int | None, int, int]] = []
    for tier in CONTEXT_TIERS:
        specs += [
            ("one_shot", tier, "M01", "normalization_simple", None, 1, 0),
            ("one_shot", tier, "M05", "blocks_stress", None, 1, 0),
        ]
    specs += [
        ("loaded_session", 16384, "L02-L", mode, i, 1, 0) for i, mode in enumerate(SESSION_SEQUENCE)
    ]
    for p in PARALLELISM_LEVELS:
        specs += [
            ("parallelism", 16384, "M05", f"parallel_fanout_p{p}", None, p, worker_slot)
            for worker_slot in range(p)
        ]
    rows: list[dict[str, Any]] = []
    cell_index = 1
    for model_index, model_id in enumerate(MODEL_IDS):
        session_id = f"session-{model_index + 1}"
        previous_cell_key: tuple[str, int, str, str, int] | None = None
        for phase, tier, view, mode, ordinal, parallelism, worker_slot in specs:
            cell_key = (phase, tier, view, mode, parallelism)
            if previous_cell_key is not None and cell_key != previous_cell_key:
                cell_index += 1
            previous_cell_key = cell_key
            request_index = sum(1 for row in rows if row["model_id"] == model_id)
            call_id = f"call-{model_index + 1:02d}-{request_index + 1:02d}"
            request_id = f"request-{model_index + 1:02d}-{request_index + 1:02d}"
            cell_id = f"overlay_{cell_index:03d}"
            binding = bindings[view]
            raw, prefix, suffix = _request_payload(
                model_id=model_id,
                phase=phase,
                tier=tier,
                view=view,
                mode=mode,
                ordinal=ordinal if ordinal is not None else worker_slot,
                request_id=request_id,
                call_id=call_id,
                cell_id=cell_id,
                binding=binding,
                pack_root=pack_root,
            )
            path = artifact_root / f"{request_id}.request.json"
            if path.exists():
                if path.read_bytes() != raw:
                    raise FileExistsError(f"immutable request artifact differs: {path}")
            else:
                path.write_bytes(raw)
                os.chmod(path, 0o444)
            target = pack_root / binding["target_path"] if binding.get("target_path") else None
            scorer_binding = {
                "view_label": view,
                "task_family": binding["task_family"],
                "task_binding_sha256": _digest(binding),
                "prompt_sha256": _sha((pack_root / binding["prompt_path"]).read_bytes())
                if binding.get("prompt_path")
                else None,
                "output_schema_version": binding.get("output_schema_version"),
                "output_schema_sha256": _sha(
                    (pack_root / "schemas" / "normalization_output_v1.schema.json").read_bytes()
                )
                if binding.get("output_schema_version") == "normalization-v1"
                else None,
                "target_sha256": _sha(target.read_bytes()) if target else None,
                "rubric_version": binding["rubric_version"],
                "rubric_sha256": _sha((pack_root / "views" / view / "rubric.json").read_bytes()),
                "scorer_sha256": _sha(compute_bound_scorecard.__code__.co_code),
            }
            rows.append(
                {
                    "call_id": call_id,
                    "request_id": request_id,
                    "cell_id": cell_id,
                    "cell_request_index": worker_slot,
                    "model_id": model_id,
                    "model_revision": model_revisions[model_id],
                    "phase": phase,
                    "context_tier": tier,
                    "view_label": view,
                    "mode": mode,
                    "parallelism": parallelism,
                    "worker_slot": worker_slot if phase == "parallelism" else None,
                    "session_id": session_id if phase == "loaded_session" else None,
                    "ordinal": ordinal if phase == "loaded_session" else None,
                    "predecessor_call_id": rows[-1]["call_id"]
                    if phase == "loaded_session" and ordinal
                    else None,
                    "request_path": path.name,
                    "request_sha256": _sha(raw),
                    "byte_length": len(raw),
                    "task_axis": _task_axis(view, binding["task_family"]),
                    "max_tokens": OUTPUT_TOKEN_BUDGETS[_task_axis(view, binding["task_family"])],
                    "prefix_sha256": _sha(prefix),
                    "prefix_byte_length": len(prefix),
                    "suffix_sha256": _sha(suffix),
                    "sentinels": [f"SENTINEL_{model_index + 1}_{request_index + 1}"],
                    "expected_absent_sentinels": [],
                    "scorer_binding": scorer_binding,
                }
            )
        cell_index += 1
    for row in rows:
        if row["phase"] in {"loaded_session", "parallelism"}:
            row["expected_absent_sentinels"] = [
                marker
                for other in rows
                if other["model_id"] == row["model_id"]
                and other["phase"] == row["phase"]
                and other["call_id"] != row["call_id"]
                for marker in other["sentinels"]
            ]
    return tuple(rows)


def _sealed_capture_authority(plan_sha256: str) -> dict[str, Any]:
    """Load the owner-sealed authority for one immutable plan generation."""
    if not _hex(plan_sha256):
        raise ValueError("capture plan digest is invalid")
    store = _AUTHORITY_STORE
    generation_path = store / "generations" / f"{plan_sha256}.json"
    if (
        not store.is_dir()
        or store.is_symlink()
        or store.stat().st_mode & 0o077
        or not generation_path.is_file()
        or generation_path.is_symlink()
        or generation_path.stat().st_mode & 0o077
    ):
        raise ValueError("owner-sealed capture authority generation is unavailable")
    generation = _json(generation_path)
    expected_keys = {
        "schema_version",
        "plan_sha256",
        "authority_identity_sha256",
        "authority_public_key_pem",
        "authority_ledger_path",
        "private_evidence_root",
    }
    if (
        set(generation) != expected_keys
        or generation.get("schema_version") != "lmstudio-sdk-capture-authority-generation-v1"
        or generation.get("plan_sha256") != plan_sha256
    ):
        raise ValueError("owner-sealed capture authority generation is invalid")
    for field in ("authority_ledger_path", "private_evidence_root"):
        path = Path(str(generation.get(field, "")))
        if (
            not path.is_absolute()
            or not path.exists()
            or path.is_symlink()
            or path.stat().st_mode & 0o077
        ):
            raise ValueError("owner-sealed capture authority path is invalid")
    try:
        public_key = serialization.load_pem_public_key(
            str(generation["authority_public_key_pem"]).encode("ascii")
        )
    except (ValueError, TypeError):
        public_key = None
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("owner-sealed capture authority key is invalid")
    public_der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if _sha(public_der) != generation.get("authority_identity_sha256"):
        raise ValueError("owner-sealed capture authority identity mismatch")
    return generation | {"public_key": public_key}


def validate_token_map(
    token_map: dict[str, Any],
    requests: Iterable[dict[str, Any]],
    artifact_root: str | Path,
    *,
    consume: bool = True,
) -> list[str]:
    """Validate closed evidence emitted by isolated LM Studio SDK capture subprocesses."""
    errors: list[str] = []
    request_rows = {row["request_id"]: row for row in requests}
    captures = token_map.get("captures")
    if (
        token_map.get("schema_version") != "lmstudio-sdk-tokenizer-capture-set-v1"
        or not isinstance(captures, list)
        or len(captures) != len(MODEL_IDS)
    ):
        return ["token map must contain four LM Studio SDK runtime captures"]
    expected_capture_keys = {
        "schema_version",
        "authority",
        "capture_id",
        "nonce",
        "issued_at",
        "session_id",
        "model_key",
        "instance_id",
        "instance_config",
        "instance_config_sha256",
        "plan_sha256",
        "preflight",
        "post_unload",
        "private_evidence_relative_path",
        "private_evidence_sha256",
        "rows",
        "evidence_sha256",
        "authority_signature",
    }
    expected_row_keys = {
        "request_id",
        "model_id",
        "request_sha256",
        "byte_length",
        "chat_sha256",
        "formatted_prompt_sha256",
        "token_ids_sha256",
        "exact_token_count",
        "output_token_reserve",
        "safety_margin",
        "effective_context",
        "admitted",
    }
    models = [capture.get("model_key") for capture in captures if isinstance(capture, dict)]
    instances = [capture.get("instance_id") for capture in captures if isinstance(capture, dict)]
    plans = [capture.get("plan_sha256") for capture in captures if isinstance(capture, dict)]
    if tuple(models) != MODEL_IDS:
        errors.append(
            "captures must follow the exact canonical model inventory; aliases are forbidden"
        )
    if len(instances) != len(set(instances)) or any(not value for value in instances):
        errors.append("captures require globally unique loaded instance identifiers")
    if len(set(plans)) != 1 or not plans or not _hex(plans[0]):
        errors.append("captures do not bind one valid frozen plan digest")
    rows: list[dict[str, Any]] = []
    verified_issuances: list[dict[str, Any]] = []
    try:
        capture_plans = {
            capture.get("plan_sha256") for capture in captures if isinstance(capture, dict)
        }
        if len(capture_plans) != 1:
            raise ValueError("capture set does not bind one plan generation")
        expected_plan_sha256 = str(next(iter(capture_plans)))
        authority_generation = _sealed_capture_authority(str(expected_plan_sha256))
    except ValueError as exc:
        return [str(exc)]
    public_key = authority_generation["public_key"]
    expected_authority_identity_sha256 = authority_generation["authority_identity_sha256"]
    ledger_path = Path(authority_generation["authority_ledger_path"])
    private_evidence_root = Path(authority_generation["private_evidence_root"])
    ledger_records: list[dict[str, Any]] = []
    if ledger_path.is_file() and not ledger_path.stat().st_mode & 0o077:
        try:
            ledger_records = [
                json.loads(line) for line in ledger_path.read_text().splitlines() if line
            ]
        except (json.JSONDecodeError, OSError):
            ledger_records = []
    issued = {row.get("capture_id"): row for row in ledger_records if row.get("event") == "issued"}
    consumed = {row.get("capture_id") for row in ledger_records if row.get("event") == "consumed"}
    for capture_index, capture in enumerate(captures):
        if not isinstance(capture, dict) or set(capture) != expected_capture_keys:
            errors.append(f"captures[{capture_index}] schema is not closed")
            continue
        signed = dict(capture)
        signature = signed.pop("authority_signature")
        sealed = dict(signed)
        evidence_sha256 = sealed.pop("evidence_sha256")
        if evidence_sha256 != _digest(sealed):
            errors.append(f"captures[{capture_index}] evidence digest mismatch")
        authority = capture.get("authority")
        signature_valid = False
        if isinstance(public_key, Ed25519PublicKey):
            try:
                public_key.verify(
                    base64.b64decode(str(signature), validate=True), _canonical(signed)
                )
                signature_valid = True
            except (InvalidSignature, ValueError):
                pass
        if (
            not signature_valid
            or not isinstance(authority, dict)
            or authority
            != {
                "package": "lmstudio",
                "version": "1.5.0",
                "identity_sha256": expected_authority_identity_sha256,
                "signature_algorithm": "ed25519-v1",
            }
        ):
            errors.append(f"captures[{capture_index}] SDK authority authentication failed")
        if not isinstance(authority, dict):
            authority = {}
        if capture.get("schema_version") != "lmstudio-sdk-tokenizer-capture-v2":
            errors.append(f"captures[{capture_index}] schema version mismatch")
        if capture.get("plan_sha256") != expected_plan_sha256:
            errors.append(f"captures[{capture_index}] plan replay/binding mismatch")
        config = capture.get("instance_config")
        if not isinstance(config, dict) or capture.get("instance_config_sha256") != _digest(config):
            errors.append(f"captures[{capture_index}] instance config mismatch")
        issuance = issued.get(capture.get("capture_id"))
        expected_issuance = {
            "event": "issued",
            "capture_id": capture.get("capture_id"),
            "nonce": capture.get("nonce"),
            "issued_at": capture.get("issued_at"),
            "session_id": capture.get("session_id"),
            "authority_identity_sha256": expected_authority_identity_sha256,
            "plan_sha256": capture.get("plan_sha256"),
            "model_key": capture.get("model_key"),
            "instance_id": capture.get("instance_id"),
            "instance_config_sha256": capture.get("instance_config_sha256"),
            "request_ids_sha256": _digest(
                [row.get("request_id") for row in capture.get("rows", [])]
            ),
        }
        try:
            issued_at = datetime.fromisoformat(str(capture.get("issued_at")))
            fresh = datetime.now(UTC) - timedelta(hours=1) <= issued_at <= datetime.now(UTC)
        except ValueError:
            fresh = False
        if (
            issuance != expected_issuance
            or not isinstance(capture.get("capture_id"), int)
            or capture.get("capture_id") in consumed
            or not isinstance(capture.get("nonce"), str)
            or len(capture["nonce"]) != 64
            or not isinstance(capture.get("session_id"), str)
            or len(capture["session_id"]) != 32
            or not fresh
        ):
            errors.append(f"captures[{capture_index}] capture issuance/freshness/replay mismatch")
        else:
            verified_issuances.append(expected_issuance)
        for stage in ("preflight", "post_unload"):
            snapshot = capture.get(stage)
            if (
                not isinstance(snapshot, dict)
                or set(snapshot) != {"loaded_count", "instance_bindings_sha256", "response_sha256"}
                or snapshot.get("loaded_count") != 0
                or not _hex(snapshot.get("instance_bindings_sha256"))
                or not _hex(snapshot.get("response_sha256"))
            ):
                errors.append(f"captures[{capture_index}] {stage} is not a sealed zero read-back")
        capture_rows = capture.get("rows")
        if not isinstance(capture_rows, list):
            errors.append(f"captures[{capture_index}] rows missing")
            continue
        for row in capture_rows:
            if not isinstance(row, dict) or set(row) != expected_row_keys:
                errors.append(f"captures[{capture_index}] row schema is not closed")
                continue
            if row.get("model_id") != capture.get("model_key"):
                errors.append(f"captures[{capture_index}] row model binding mismatch")
            rows.append(row)
        private_path = Path(private_evidence_root) / str(
            capture.get("private_evidence_relative_path")
        )
        if not private_path.is_file() or private_path.stat().st_mode & 0o077:
            errors.append(f"captures[{capture_index}] private evidence missing or not owner-only")
            continue
        private_bytes = private_path.read_bytes().rstrip(b"\n")
        if _sha(private_bytes) != capture.get("private_evidence_sha256"):
            errors.append(f"captures[{capture_index}] private evidence digest mismatch")
            continue
        try:
            private = json.loads(private_bytes)
        except json.JSONDecodeError:
            errors.append(f"captures[{capture_index}] private evidence is invalid JSON")
            continue
        if (
            private.get("schema_version") != "lmstudio-sdk-tokenizer-private-evidence-v1"
            or private.get("authority_identity_sha256") != authority.get("identity_sha256")
            or any(
                private.get(field) != capture.get(field)
                for field in (
                    "capture_id",
                    "nonce",
                    "issued_at",
                    "session_id",
                    "plan_sha256",
                    "model_key",
                    "instance_id",
                    "instance_config",
                )
            )
        ):
            errors.append(f"captures[{capture_index}] private capture binding mismatch")
            continue
        private_rows = {
            row.get("request_id"): row for row in private.get("rows", []) if isinstance(row, dict)
        }
        for public_row in capture_rows:
            private_row = private_rows.get(public_row.get("request_id"))
            if not isinstance(private_row, dict):
                errors.append(f"captures[{capture_index}] private row evidence missing")
                continue
            try:
                prompt = base64.b64decode(private_row["formatted_prompt_base64"], validate=True)
                token_ids = private_row["token_ids"]
            except (KeyError, TypeError, ValueError):
                errors.append(f"captures[{capture_index}] private row evidence missing")
                continue
            if (
                private_row.get("model_id") != public_row.get("model_id")
                or private_row.get("request_sha256") != public_row.get("request_sha256")
                or _sha(prompt) != public_row.get("formatted_prompt_sha256")
                or _digest(token_ids) != public_row.get("token_ids_sha256")
                or len(token_ids) != public_row.get("exact_token_count")
                or any(type(token) is not int for token in token_ids)
            ):
                errors.append(f"captures[{capture_index}] private prompt/token replay mismatch")
    observed: set[str] = set()
    root = Path(artifact_root)
    for i, row in enumerate(rows):
        rid = row.get("request_id")
        if rid in observed:
            errors.append(f"rows[{i}] duplicate request binding")
        observed.add(rid)
        request = request_rows.get(rid)
        if request is None:
            errors.append(f"rows[{i}] unknown request_id")
            continue
        data = (root / request["request_path"]).read_bytes()
        if (
            row.get("request_sha256") != request["request_sha256"]
            or row.get("byte_length") != request["byte_length"]
            or _sha(data) != request["request_sha256"]
            or len(data) != request["byte_length"]
        ):
            errors.append(f"rows[{i}] request digest/length mismatch")
        for field in {
            "request_sha256",
            "chat_sha256",
            "formatted_prompt_sha256",
            "token_ids_sha256",
        }:
            if not _hex(row.get(field)):
                errors.append(f"rows[{i}].{field} must be SHA-256")
        history = {
            "messages": [
                {
                    "role": "user",
                    "content": data.decode("utf-8"),
                }
            ]
        }
        if row.get("chat_sha256") != _digest(history) or row.get("model_id") != request["model_id"]:
            errors.append(f"rows[{i}] chat/model binding mismatch")
        count = row.get("exact_token_count")
        reserve, margin, effective = (
            row.get("output_token_reserve"),
            row.get("safety_margin"),
            row.get("effective_context"),
        )
        if not all(
            isinstance(x, int) and not isinstance(x, bool) and x >= 0
            for x in (count, reserve, margin, effective)
        ):
            errors.append(f"rows[{i}] invalid token arithmetic")
        elif (
            reserve != request["max_tokens"]
            or margin != SAFETY_MARGIN
            or effective != request["context_tier"]
            or not context_fits(count, reserve, effective)
            or row.get("admitted") is not True
        ):
            errors.append(f"rows[{i}] context admission failed")
    missing = set(request_rows) - observed
    if missing:
        errors.append(f"token evidence missing for {len(missing)} requests")
    if not errors and consume:
        errors.extend(
            _consume_capture_issuances(ledger_path, verified_issuances, expected_plan_sha256)
        )
    return errors


def _consume_capture_issuances(
    ledger_path: Path, issuances: list[dict[str, Any]], expected_plan_sha256: str
) -> list[str]:
    """Atomically make authenticated captures single-use for one frozen plan."""
    fd = os.open(ledger_path, os.O_RDWR | os.O_APPEND)
    with os.fdopen(fd, "r+b", closefd=True) as stream:
        flock(stream.fileno(), LOCK_EX)
        stream.seek(0)
        records = [json.loads(line) for line in stream if line.strip()]
        consumed = {row.get("capture_id") for row in records if row.get("event") == "consumed"}
        ids = [row["capture_id"] for row in issuances]
        if len(ids) != len(set(ids)) or consumed.intersection(ids):
            flock(stream.fileno(), LOCK_UN)
            return ["capture set already consumed or contains duplicate capture IDs"]
        stream.seek(0, os.SEEK_END)
        for issuance in issuances:
            stream.write(
                _canonical(
                    {
                        "event": "consumed",
                        "capture_id": issuance["capture_id"],
                        "plan_sha256": expected_plan_sha256,
                        "session_id": issuance["session_id"],
                        "consumed_at": datetime.now(UTC).isoformat(),
                    }
                )
                + b"\n"
            )
        stream.flush()
        os.fsync(stream.fileno())
        flock(stream.fileno(), LOCK_UN)
    return []


def _validate_request_contract(requests: tuple[dict[str, Any], ...]) -> None:
    if (
        len(requests) != 80
        or len({r["call_id"] for r in requests}) != 80
        or len({r["request_id"] for r in requests}) != 80
    ):
        raise ValueError("request plan must contain 80 unique calls and requests")
    by_model = {model: [r for r in requests if r["model_id"] == model] for model in MODEL_IDS}
    if any(len(rows) != 20 for rows in by_model.values()):
        raise ValueError("every model must have exactly 20 calls")
    expected_axes = {
        (row["view_label"], row["mode"], row["task_axis"], row["max_tokens"])
        for row in by_model[MODEL_IDS[0]]
    }
    for rows in by_model.values():
        if {
            (row["view_label"], row["mode"], row["task_axis"], row["max_tokens"]) for row in rows
        } != expected_axes:
            raise ValueError("task axes and output budgets must be identical across models")
        session = [r for r in rows if r["phase"] == "loaded_session"]
        if [r["ordinal"] for r in session] != list(range(7)):
            raise ValueError("loaded session ordinals must be 0..6")
        if len({r["prefix_sha256"] for r in session}) != 1:
            raise ValueError("loaded session prefix bytes differ")
        changing = session[2:5]
        if len({r["suffix_sha256"] for r in changing}) != 3:
            raise ValueError("changing suffixes must be distinct")
        if not all(
            r["prefix_sha256"] == session[4]["prefix_sha256"]
            and r["suffix_sha256"] == session[4]["suffix_sha256"]
            for r in session[5:]
        ):
            raise ValueError("exact repeat model-input bytes differ")
        for cell_id in {r["cell_id"] for r in rows if r["phase"] == "parallelism"}:
            cell = [r for r in rows if r["cell_id"] == cell_id]
            p = cell[0]["parallelism"]
            if len(cell) != p or {r["worker_slot"] for r in cell} != set(range(p)):
                raise ValueError(f"{cell_id} does not materialize exact P{p} fan-out")


def build_overlay_plan(
    manifest_path: str | Path,
    token_map_path: str | Path,
    pack_root: str | Path,
    artifact_root: str | Path,
    frozen_plan_path: str | Path,
) -> OverlayPlan:
    manifest_path, pack_root = Path(manifest_path), Path(pack_root)
    requests = materialize_request_artifacts(manifest_path, pack_root, artifact_root)
    frozen = _json(Path(frozen_plan_path))
    if frozen.get("requests") != list(requests):
        raise ValueError("frozen execution plan digest/content mismatch")
    token_map = _json(Path(token_map_path))
    frozen_plan_sha256 = capture_plan_digest(frozen)
    if {
        capture.get("plan_sha256")
        for capture in token_map.get("captures", [])
        if isinstance(capture, dict)
    } != {frozen_plan_sha256}:
        raise ValueError("token evidence does not bind the frozen plan generation")
    errors = validate_token_map(
        token_map,
        requests,
        artifact_root,
    )
    if errors:
        raise ValueError("invalid exact token evidence: " + "; ".join(errors))
    _validate_request_contract(requests)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for request in requests:
        grouped.setdefault(request["cell_id"], []).append(request)
    cells = tuple(
        {
            "cell_id": cid,
            "request_count": len(rows),
            "call_ids": [r["call_id"] for r in rows],
            "cell_sha256": _digest(rows),
        }
        for cid, rows in grouped.items()
    )
    if len(cells) != 64:
        raise AssertionError("planner violated 64-cell contract")
    return OverlayPlan(
        _sha(manifest_path.read_bytes()), _json(manifest_path)["pack_tree_sha256"], cells, requests
    )


def capture_plan_digest(plan: dict[str, Any]) -> str:
    """Reproduce the authority digest from a retained frozen plan artifact."""
    requests = plan.get("requests")
    if not isinstance(requests, list):
        raise ValueError("plan requests must be a list")
    return _digest(
        {
            "schema_version": plan.get("schema_version"),
            "manifest_sha256": plan.get("manifest_sha256"),
            "pack_tree_sha256": plan.get("pack_tree_sha256"),
            "requests": [
                {
                    "request_id": row.get("request_id"),
                    "model_id": row.get("model_id"),
                    "request_path": row.get("request_path"),
                    "request_sha256": row.get("request_sha256"),
                    "context_tier": row.get("context_tier"),
                    "task_axis": row.get("task_axis"),
                    "max_tokens": row.get("max_tokens"),
                }
                for row in requests
            ],
        }
    )


def freeze_overlay_plan(
    manifest_path: str | Path, pack_root: str | Path, artifact_root: str | Path
) -> OverlayPlan:
    """Materialize and close the canonical 64-cell/80-call plan before capture."""
    manifest_path = Path(manifest_path)
    requests = materialize_request_artifacts(manifest_path, pack_root, artifact_root)
    _validate_request_contract(requests)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for request in requests:
        grouped.setdefault(request["cell_id"], []).append(request)
    cells = tuple(
        {
            "cell_id": cell_id,
            "request_count": len(rows),
            "call_ids": [row["call_id"] for row in rows],
            "cell_sha256": _digest(rows),
        }
        for cell_id, rows in grouped.items()
    )
    if len(cells) != 64:
        raise AssertionError("planner violated 64-cell contract")
    return OverlayPlan(
        _sha(manifest_path.read_bytes()), _json(manifest_path)["pack_tree_sha256"], cells, requests
    )


def write_overlay_plan(plan: OverlayPlan, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def validate_resource_admission(request: dict[str, Any], admission: dict[str, Any]) -> list[str]:
    """Fail closed unless observed capacity admits every requested resident instance."""
    p = request["parallelism"]
    required = admission.get("bytes_per_instance")
    available = admission.get("available_bytes")
    if not all(
        isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in (required, available)
    ):
        return ["resource envelope/capacity missing"]
    if admission.get("observed_at") is None or not _hex(admission.get("snapshot_sha256")):
        return ["capacity observation provenance missing"]
    if required * p > available or admission.get("admitted") is not True:
        return [f"P{p} resource admission failed"]
    if len(set(admission.get("instance_ids", []))) != 1:
        return [f"P{p} requires exactly one loaded model instance"]
    return []


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def validate_execution_trace(plan: OverlayPlan, events: list[dict[str, Any]]) -> list[str]:
    """Validate lifecycle, order, provenance, fan-out, and cleanup from driver events."""
    errors: list[str] = []
    identity_fields = {
        "call": "call_id",
        "load": "load_event_id",
        "unload": "unload_event_id",
        "resource_admission": "admission_event_id",
        "start_barrier": "barrier_event_id",
    }
    groups = {kind: [e for e in events if e.get("event") == kind] for kind in identity_fields}
    for kind, rows in groups.items():
        identities = [row.get(identity_fields[kind]) for row in rows]
        if None in identities or len(identities) != len(set(identities)):
            errors.append(f"duplicate or missing {kind} event identity")

    calls = {e["call_id"]: e for e in groups["call"] if e.get("call_id") is not None}
    planned_calls = {r["call_id"] for r in plan.requests}
    if set(calls) != planned_calls:
        errors.append("trace call IDs do not exactly reconcile with plan")
    indexes = {id(event): index for index, event in enumerate(events)}
    loads = {e["load_event_id"]: e for e in groups["load"] if e.get("load_event_id")}
    unloads = {e["load_event_id"]: e for e in groups["unload"] if e.get("load_event_id")}
    admissions = {e.get("cell_id"): e for e in groups["resource_admission"]}
    barriers = {e.get("cell_id"): e for e in groups["start_barrier"]}
    snapshots = [e for e in events if e.get("event") == "loaded_snapshot"]
    unload_load_ids = [e.get("load_event_id") for e in groups["unload"]]
    snapshot_keys = [(e.get("call_id"), e.get("stage")) for e in snapshots]
    expected_snapshot_keys = {(None, "global_preflight"), (None, "global_final")}
    expected_snapshot_keys.update(
        (request["call_id"], stage)
        for request in plan.requests
        if request["phase"] == "one_shot"
        for stage in ("preflight", "post_unload")
    )
    if set(unload_load_ids) != set(loads) or len(unload_load_ids) != len(set(unload_load_ids)):
        errors.append("loads and unloads must have a one-to-one binding")
    if (
        len(snapshot_keys) != len(set(snapshot_keys))
        or set(snapshot_keys) != expected_snapshot_keys
    ):
        errors.append("loaded-state read-backs must exactly and uniquely bind lifecycle boundaries")

    required_call_fields = {
        "instance_id",
        "load_event_id",
        "endpoint",
        "backend_version",
        "model_id",
        "model_revision",
        "parameters_sha256",
        "request_sha256",
        "started_at",
        "ended_at",
        "terminal_state",
        "worker_slot",
    }
    for request in plan.requests:
        call = calls.get(request["call_id"])
        if call is None:
            continue
        started = _timestamp(call.get("started_at"))
        ended = _timestamp(call.get("ended_at"))
        if (
            required_call_fields - call.keys()
            or call.get("request_sha256") != request["request_sha256"]
            or call.get("model_id") != request["model_id"]
            or call.get("model_revision") != request["model_revision"]
            or call.get("endpoint") != "/api/v1/chat"
            or call.get("worker_slot") != request.get("worker_slot")
            or not _hex(call.get("parameters_sha256"))
            or started is None
            or ended is None
            or started >= ended
            or call.get("terminal_state") != "completed"
        ):
            errors.append(f"{request['call_id']} provenance incomplete or mismatched")
        load = loads.get(call.get("load_event_id"))
        unload = unloads.get(call.get("load_event_id"))
        if (
            load is None
            or unload is None
            or not indexes[id(load)] < indexes[id(call)] < indexes[id(unload)]
        ):
            errors.append(f"{request['call_id']} load/call/unload lifecycle invalid")
        elif any(
            event.get(field) != expected
            for event in (load, unload)
            for field, expected in (
                ("instance_id", call.get("instance_id")),
                ("model_id", request["model_id"]),
                ("model_revision", request["model_revision"]),
            )
        ):
            errors.append(f"{request['call_id']} lifecycle model/instance binding mismatch")

        if request["phase"] == "one_shot":
            preflight = [
                e
                for e in snapshots
                if e.get("call_id") == request["call_id"] and e.get("stage") == "preflight"
            ]
            cleanup = [
                e
                for e in snapshots
                if e.get("call_id") == request["call_id"] and e.get("stage") == "post_unload"
            ]
            load_users = [
                e for e in groups["call"] if e.get("load_event_id") == call.get("load_event_id")
            ]
            if (
                len(preflight) != 1
                or len(cleanup) != 1
                or preflight[0].get("loaded_count") != 0
                or cleanup[0].get("loaded_count") != 0
                or load is None
                or unload is None
                or not indexes[id(preflight[0])]
                < indexes[id(load)]
                < indexes[id(call)]
                < indexes[id(unload)]
                < indexes[id(cleanup[0])]
                or len(load_users) != 1
            ):
                errors.append(f"{request['call_id']} cold lifecycle/cleanup ordering invalid")
        if request["phase"] == "loaded_session" and request["ordinal"]:
            predecessor = calls.get(request["predecessor_call_id"])
            if predecessor is None or indexes[id(predecessor)] >= indexes[id(call)]:
                errors.append("loaded session executed out of order")
        if request["phase"] == "parallelism":
            admission = admissions.get(request["cell_id"])
            barrier = barriers.get(request["cell_id"])
            if admission is None or validate_resource_admission(request, admission):
                errors.append(f"{request['cell_id']} resource admission missing or failed")
            elif call.get("instance_id") not in admission["instance_ids"]:
                errors.append(f"{request['call_id']} is not mapped to an admitted instance")
            if (
                barrier is None
                or barrier.get("participants") != request["parallelism"]
                or barrier.get("participant_bindings")
                != [
                    {"worker_slot": slot, "instance_id": admission["instance_ids"][0]}
                    for slot in range(request["parallelism"])
                ]
                or _timestamp(admission.get("observed_at")) is None
                or _timestamp(barrier.get("observed_at")) is None
                or not _timestamp(admission.get("observed_at"))
                <= _timestamp(barrier.get("observed_at"))
                <= started
                or indexes[id(barrier)] >= indexes[id(call)]
            ):
                errors.append(
                    f"{request['cell_id']} P{request['parallelism']} start barrier invalid"
                )

    for model in {request["model_id"] for request in plan.requests}:
        session_calls = [
            calls.get(r["call_id"])
            for r in plan.requests
            if r["model_id"] == model and r["phase"] == "loaded_session"
        ]
        if (
            any(x is None for x in session_calls)
            or len({x["instance_id"] for x in session_calls if x}) != 1
        ):
            errors.append(f"{model} loaded session did not use one instance")
        elif len({x["load_event_id"] for x in session_calls if x}) != 1:
            errors.append(f"{model} loaded session did not use one load event")

    global_snapshots = [e for e in snapshots if e.get("call_id") is None]
    if (
        len(global_snapshots) != 2
        or global_snapshots[0].get("stage") != "global_preflight"
        or global_snapshots[1].get("stage") != "global_final"
        or snapshots[0] is not global_snapshots[0]
        or snapshots[-1] is not global_snapshots[1]
        or global_snapshots[0].get("loaded_count") != 0
        or global_snapshots[1].get("loaded_count") != 0
        or indexes[id(global_snapshots[0])] >= min(indexes[id(x)] for x in groups["load"])
        or indexes[id(global_snapshots[1])] <= max(indexes[id(x)] for x in groups["unload"])
    ):
        errors.append("preflight/final zero-loaded read-back missing")
    if any(not _hex(x.get("response_sha256")) or x.get("observed_at") is None for x in snapshots):
        errors.append("loaded-state snapshot provenance missing")

    for cell_id in {r["cell_id"] for r in plan.requests if r["phase"] == "parallelism"}:
        requests = [r for r in plan.requests if r["cell_id"] == cell_id]
        cell_calls = [calls.get(r["call_id"]) for r in requests]
        if any(call is None for call in cell_calls):
            continue
        p = requests[0]["parallelism"]
        slots = {call["worker_slot"] for call in cell_calls if call}
        instances = {call["instance_id"] for call in cell_calls if call}
        pairs = {(call["worker_slot"], call["instance_id"]) for call in cell_calls if call}
        starts = [_timestamp(call["started_at"]) for call in cell_calls if call]
        ends = [_timestamp(call["ended_at"]) for call in cell_calls if call]
        if (
            slots != set(range(p))
            or len(instances) != 1
            or len(pairs) != p
            or any(value is None for value in starts + ends)
            or max(starts) >= min(ends)
        ):
            errors.append(f"{cell_id} P{p} slot-instance bijection/overlap invalid")
    return errors


def capture_validated_execution_trace(
    plan: OverlayPlan, observed_events: list[dict[str, Any]]
) -> ValidatedTraceHandle:
    """Detach, validate, and seal one whole independently observed runtime trace."""
    captured = json.loads(_canonical(observed_events))
    errors = validate_execution_trace(plan, captured)
    if errors:
        raise ValueError("invalid observed runtime trace: " + "; ".join(errors))
    plan_sha256 = _digest(plan.as_dict())
    trace_sha256 = _digest(
        {"schema_version": "trace-v1", "plan_sha256": plan_sha256, "events": captured}
    )
    calls = {event["call_id"]: event for event in captured if event.get("event") == "call"}
    return ValidatedTraceHandle(_TRACE_AUTHORITY, plan_sha256, trace_sha256, calls)


def scan_contamination(
    raw_output: str, request: dict[str, Any], prior_outputs: dict[str, str]
) -> dict[str, Any]:
    present = [x for x in request["sentinels"] if x in raw_output]
    forbidden = [x for x in request["expected_absent_sentinels"] if x in raw_output]
    repeat_source = (
        request.get("predecessor_call_id")
        if request["mode"].startswith("loaded_exact_repeat")
        else None
    )
    repeat_equal = None if repeat_source is None else prior_outputs.get(repeat_source) == raw_output
    return {
        "algorithm": "literal-sentinel-v1",
        "present": present,
        "forbidden": forbidden,
        "exact_repeat_equal": repeat_equal,
        "passed": not forbidden and (repeat_equal is not False),
    }


def record_private_output(
    private_root: str | Path,
    *,
    request: dict[str, Any],
    raw_output: str,
    response_envelope: dict[str, Any] | None = None,
    finish_reason: str | None = None,
    native_usage: Any = None,
    sanitized_evidence_path: str | Path,
    pack_root: str | Path,
    validated_trace: ValidatedTraceHandle,
) -> dict[str, Any]:
    """Create one immutable raw file and one internally computed ledger row per call."""
    if request["scorer_binding"]["scorer_sha256"] != _sha(compute_bound_scorecard.__code__.co_code):
        raise ValueError("scorer code digest mismatch")
    if type(validated_trace) is not ValidatedTraceHandle:
        raise ValueError("authenticated validated trace handle required")
    call_provenance = validated_trace.consume(request)
    if call_provenance.pop("event", None) != "call":
        raise ValueError("validated trace handle contains a non-call event")
    required_provenance = {
        "call_id",
        "instance_id",
        "load_event_id",
        "endpoint",
        "backend_version",
        "model_id",
        "model_revision",
        "parameters_sha256",
        "request_sha256",
        "started_at",
        "ended_at",
        "terminal_state",
        "worker_slot",
    }
    if set(call_provenance) != required_provenance:
        raise ValueError("call provenance incomplete")

    if (
        call_provenance["call_id"] != request["call_id"]
        or call_provenance["model_id"] != request["model_id"]
        or call_provenance["model_revision"] != request["model_revision"]
        or call_provenance["request_sha256"] != request["request_sha256"]
        or call_provenance["worker_slot"] != request.get("worker_slot")
        or call_provenance["endpoint"] != "/api/v1/chat"
        or call_provenance["terminal_state"] != "completed"
        or any(
            not isinstance(call_provenance[field], str) or not call_provenance[field]
            for field in ("instance_id", "load_event_id", "backend_version")
        )
        or not _hex(call_provenance["parameters_sha256"])
        or _timestamp(call_provenance["started_at"]) is None
        or _timestamp(call_provenance["ended_at"]) is None
        or _timestamp(call_provenance["started_at"]) >= _timestamp(call_provenance["ended_at"])
    ):
        raise ValueError("call provenance does not bind planned request")
    root = Path(private_root).resolve()
    repo = Path(__file__).resolve().parents[2]
    if root == repo or repo in root.parents:
        raise ValueError("private output root must be outside the repository")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise PermissionError("private root must have mode 0700")
    prior_outputs = {
        path.name.removesuffix(".raw.txt"): path.read_text(encoding="utf-8")
        for path in root.glob("*.raw.txt")
    }
    contamination = scan_contamination(raw_output, request, prior_outputs)
    scorecard = compute_bound_scorecard(raw_output, request, pack_root)
    raw = raw_output.encode()
    raw_path = root / f"{request['call_id']}.raw.txt"
    fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    envelope_raw = _canonical({} if response_envelope is None else response_envelope)
    envelope_path = root / f"{request['call_id']}.response.json"
    fd = os.open(envelope_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(envelope_raw)
    row = {
        "schema_version": "four-model-result-ledger-v2",
        "call_id": request["call_id"],
        "request_id": request["request_id"],
        "cell_id": request["cell_id"],
        "cell_request_index": request["cell_request_index"],
        "request_sha256": request["request_sha256"],
        "scorer_binding": request["scorer_binding"],
        "raw_relative_path": raw_path.name,
        "raw_output_sha256": _sha(raw),
        "raw_output_bytes": len(raw),
        "response_envelope_relative_path": envelope_path.name,
        "response_envelope_sha256": _sha(envelope_raw),
        "response_envelope_bytes": len(envelope_raw),
        "finish_reason": classify_finish_reason(finish_reason, native_usage, request["max_tokens"]),
        "native_usage": native_usage,
        "scorecard_sha256": _digest(scorecard),
        "scorecard": scorecard,
        "contamination": contamination,
        "call_provenance": call_provenance,
        "validated_trace_sha256": validated_trace.trace_sha256,
    }
    evidence_path = Path(sanitized_evidence_path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with evidence_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def classify_finish_reason(
    finish_reason: str | None, native_usage: Any, max_output_tokens: int
) -> str | None:
    """Normalize native length-limit signals without inventing completion."""
    if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
        return "length"
    if isinstance(native_usage, dict):
        output_tokens = native_usage.get("output_tokens")
        if isinstance(output_tokens, int) and output_tokens >= max_output_tokens:
            return "length"
    return finish_reason


def validate_run_closure(
    plan: OverlayPlan,
    private_root: str | Path,
    ledger_path: str | Path,
    scorecard_root: str | Path,
    pack_root: str | Path,
) -> list[str]:
    """Prove closed-schema plan/raw/ledger/scorecard field-level bindings."""
    errors: list[str] = []
    try:
        rows = [
            json.loads(line)
            for line in Path(ledger_path).read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        return [f"ledger is unreadable or malformed: {exc}"]
    if any(not isinstance(row, dict) for row in rows):
        return ["ledger rows must be JSON objects"]
    planned_by_call = {r["call_id"]: r for r in plan.requests}
    call_ids = [row.get("call_id") for row in rows]
    if (
        len(rows) != len(plan.requests)
        or set(call_ids) != set(planned_by_call)
        or len(call_ids) != len(set(call_ids))
    ):
        errors.append(f"ledger does not bijectively cover {len(plan.requests)} planned calls")
    expected_keys = {
        "schema_version",
        "call_id",
        "request_id",
        "cell_id",
        "cell_request_index",
        "request_sha256",
        "scorer_binding",
        "raw_relative_path",
        "raw_output_sha256",
        "raw_output_bytes",
        "response_envelope_relative_path",
        "response_envelope_sha256",
        "response_envelope_bytes",
        "finish_reason",
        "native_usage",
        "scorecard_sha256",
        "scorecard",
        "contamination",
        "call_provenance",
        "validated_trace_sha256",
    }
    provenance_keys = {
        "call_id",
        "instance_id",
        "load_event_id",
        "endpoint",
        "backend_version",
        "model_id",
        "model_revision",
        "parameters_sha256",
        "request_sha256",
        "started_at",
        "ended_at",
        "terminal_state",
        "worker_slot",
    }
    contamination_keys = {"algorithm", "present", "forbidden", "exact_repeat_equal", "passed"}
    raw_files = {p.name for p in Path(private_root).glob("*.raw.txt")}
    expected_raw = {f"{call}.raw.txt" for call in planned_by_call}
    if raw_files != expected_raw:
        errors.append("private raw files do not bijectively cover plan")
    envelope_files = {p.name for p in Path(private_root).glob("*.response.json")}
    expected_envelopes = {f"{call}.response.json" for call in planned_by_call}
    if envelope_files != expected_envelopes:
        errors.append("private response envelopes do not bijectively cover plan")
    raw_outputs = {
        request["call_id"]: (Path(private_root) / f"{request['call_id']}.raw.txt").read_text(
            encoding="utf-8"
        )
        for request in plan.requests
        if (Path(private_root) / f"{request['call_id']}.raw.txt").is_file()
    }
    prior_outputs: dict[str, str] = {}
    score_root = Path(scorecard_root)
    for row in rows:
        call_id = row.get("call_id")
        request = planned_by_call.get(call_id)
        if request is None:
            continue
        if set(row) != expected_keys or row.get("schema_version") != "four-model-result-ledger-v2":
            errors.append(f"{call_id} ledger schema is not closed")
            continue
        if not _hex(row.get("validated_trace_sha256")):
            errors.append(f"{call_id} validated trace digest missing")
        expected_plan_fields = {
            "request_id": request["request_id"],
            "cell_id": request["cell_id"],
            "cell_request_index": request["cell_request_index"],
            "request_sha256": request["request_sha256"],
            "scorer_binding": request["scorer_binding"],
            "raw_relative_path": f"{call_id}.raw.txt",
        }
        try:
            trusted_scorer_binding = _trusted_scorer_binding(request, Path(pack_root))
        except (ValueError, KeyError, OSError, StopIteration, json.JSONDecodeError) as exc:
            errors.append(f"{call_id} scorer binding invalid: {exc}")
            continue
        if request.get("scorer_binding") != trusted_scorer_binding:
            errors.append(f"{call_id} independently recomputed scorer binding mismatch")
        if any(row.get(field) != value for field, value in expected_plan_fields.items()):
            errors.append(f"{call_id} plan-to-ledger field binding mismatch")
        provenance = row.get("call_provenance")
        if (
            not isinstance(provenance, dict)
            or set(provenance) != provenance_keys
            or (
                provenance.get("call_id") != call_id
                or provenance.get("model_id") != request["model_id"]
                or provenance.get("model_revision") != request["model_revision"]
                or provenance.get("request_sha256") != request["request_sha256"]
                or provenance.get("worker_slot") != request.get("worker_slot")
                or provenance.get("endpoint") != "/api/v1/chat"
                or provenance.get("terminal_state") != "completed"
                or not _hex(provenance.get("parameters_sha256"))
                or any(
                    not isinstance(provenance.get(field), str) or not provenance.get(field)
                    for field in ("instance_id", "load_event_id", "backend_version")
                )
                or _timestamp(provenance.get("started_at")) is None
                or _timestamp(provenance.get("ended_at")) is None
                or _timestamp(provenance.get("started_at"))
                >= _timestamp(provenance.get("ended_at"))
            )
        ):
            errors.append(f"{call_id} provenance binding mismatch")
        contamination = row.get("contamination")
        expected_contamination = scan_contamination(
            raw_outputs.get(call_id, ""), request, prior_outputs
        )
        if (
            not isinstance(contamination, dict)
            or set(contamination) != contamination_keys
            or contamination != expected_contamination
        ):
            errors.append(f"{call_id} contamination evidence mismatch")
        raw_path = Path(private_root) / row["raw_relative_path"]
        if (
            not raw_path.is_file()
            or _sha(raw_path.read_bytes()) != row.get("raw_output_sha256")
            or raw_path.stat().st_size != row.get("raw_output_bytes")
        ):
            errors.append(f"{call_id} raw binding mismatch")
            continue
        envelope_path = Path(private_root) / row["response_envelope_relative_path"]
        if (
            row["response_envelope_relative_path"] != f"{call_id}.response.json"
            or not envelope_path.is_file()
            or _sha(envelope_path.read_bytes()) != row.get("response_envelope_sha256")
            or envelope_path.stat().st_size != row.get("response_envelope_bytes")
        ):
            errors.append(f"{call_id} response envelope binding mismatch")
        try:
            expected_scorecard = compute_bound_scorecard(
                raw_path.read_text(encoding="utf-8"), request, pack_root
            )
        except (ValueError, KeyError, OSError, StopIteration, json.JSONDecodeError) as exc:
            errors.append(f"{call_id} scorer binding invalid: {exc}")
            continue
        score_path = score_root / f"{call_id}.scorecard.json"
        try:
            external_scorecard = _json(score_path)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            errors.append(f"{call_id} scorecard binding mismatch: {exc}")
            prior_outputs[call_id] = raw_outputs.get(call_id, "")
            continue
        if (
            row.get("scorecard") != expected_scorecard
            or row.get("scorecard_sha256") != _digest(expected_scorecard)
            or external_scorecard != expected_scorecard
        ):
            errors.append(f"{call_id} scorecard binding mismatch")
        prior_outputs[call_id] = raw_outputs.get(call_id, "")
    return errors


__all__ = [
    "CONTEXT_TIERS",
    "MODEL_IDS",
    "OverlayPlan",
    "PARALLELISM_LEVELS",
    "build_overlay_plan",
    "classify_finish_reason",
    "context_fits",
    "materialize_request_artifacts",
    "record_private_output",
    "scan_contamination",
    "validate_execution_trace",
    "validate_overlay_manifest",
    "validate_resource_admission",
    "validate_run_closure",
    "validate_token_map",
    "write_overlay_plan",
]
