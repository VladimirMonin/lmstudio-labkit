from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from urllib import request as urllib_request
from urllib.parse import urlunsplit

from .model_probe import (
    _CONTEXT_KEY_ALIASES,
    _LOCALHOST_NAMES,
    _categorize_transport_error,
    _collect_int_candidates,
    _extract_capabilities,
    _extract_model_list,
    _normalize_base_url,
    _normalize_key,
    _safe_float,
    _safe_int,
    _safe_model_id,
    _safe_short_string,
    _sanitize_external_mapping,
    _sha256_text,
)

type IdentityProbeTransport = Callable[[urllib_request.Request, float], bytes]

IDENTITY_PROBE_COMPAT_ENDPOINT_PATH = "/v1/models"
IDENTITY_PROBE_NATIVE_ENDPOINT_PATH = "/api/v1/models"
IDENTITY_PROBE_COMPAT_ENDPOINT_KIND = "compat_models"
IDENTITY_PROBE_NATIVE_ENDPOINT_KIND = "native_models"
IDENTITY_PROBE_RESULT_FILE_NAMES = (
    "environment.json",
    "identity_probe.json",
    "report.md",
)

_TARGET_CANDIDATE_KEYS = (
    "key",
    "id",
    "model",
    "model_id",
    "identifier",
    "catalog_id",
    "load_id",
    "path",
)

_NATIVE_LOAD_ID_PRIORITY_KEYS = (
    "key",
    "load_id",
    "id",
    "model_id",
    "model",
    "identifier",
    "catalog_id",
)

_COMPAT_VERIFIED_MATCH_KEYS = frozenset({"id"})
_NATIVE_VERIFIED_MATCH_KEYS = frozenset(
    {"key", "id", "model_id", "model", "identifier", "catalog_id"}
)
_NATIVE_FORMAT_KEY_ALIASES = frozenset({"format", "model_format", "file_format"})
_NATIVE_QUANTIZATION_KEY_ALIASES = frozenset({"quantization", "quantization_type", "quant"})
_NATIVE_BITS_PER_WEIGHT_KEY_ALIASES = frozenset({"bits_per_weight", "bpw"})
_NATIVE_PARAMS_KEY_ALIASES = frozenset({"params", "parameter_size", "parameter_count_text"})
_NATIVE_SIZE_BYTES_KEY_ALIASES = frozenset({"size_bytes", "model_size_bytes", "file_size_bytes"})


@dataclass(frozen=True, slots=True)
class IdentityProbeResult:
    summary: dict[str, object]
    native_load_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _PlaneOutcome:
    status: str
    error_category: str | None
    response_hash: str | None = None
    response_chars: int | None = None
    record_count: int = 0
    safe_record_count: int = 0
    capability_keys: tuple[str, ...] = ()
    context_candidates: tuple[int, ...] = ()
    target_found: bool = False
    match_fields: tuple[str, ...] = ()
    target_hash_match: bool = False
    http_status: int | None = None
    raw_lookup_before_sanitization: bool = False
    native_load_id_resolved: bool = False
    native_load_id_hash: str | None = None
    model_id_verified: bool = False
    loaded_instances_count: int | None = None
    format: str | None = None
    quantization: str | None = None
    bits_per_weight: int | float | None = None
    params: str | None = None
    size_bytes: int | None = None
    native_load_id: str | None = field(default=None, repr=False)


def _default_transport(request: urllib_request.Request, timeout_s: float) -> bytes:
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        return response.read()


def build_identity_probe_compat_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, IDENTITY_PROBE_COMPAT_ENDPOINT_PATH, "", "")
    )


def build_identity_probe_native_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, IDENTITY_PROBE_NATIVE_ENDPOINT_PATH, "", "")
    )


def is_local_identity_probe_base_url(base_url: str) -> bool:
    return _normalize_base_url(base_url).hostname.lower() in _LOCALHOST_NAMES


def _build_request(url: str) -> urllib_request.Request:
    return urllib_request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json"},
    )


def _safe_target_flags(target_model_id: str) -> tuple[str, bool]:
    return _sha256_text(target_model_id), _safe_model_id(target_model_id) == target_model_id


def _extract_raw_candidate_strings(
    payload: Mapping[str, object], *, include_nested: bool = False
) -> tuple[str, ...]:
    return tuple(
        value
        for _field_name, value in _extract_raw_candidate_pairs(
            payload,
            include_nested=include_nested,
        )
    )


def _extract_raw_candidate_pairs(
    payload: Mapping[str, object], *, include_nested: bool = True
) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []
    for key in _TARGET_CANDIDATE_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            candidates.append((key, value))

    if not include_nested:
        return tuple(candidates)

    raw_variants = payload.get("variants")
    if isinstance(raw_variants, Sequence) and not isinstance(raw_variants, (str, bytes, bytearray)):
        for variant in raw_variants:
            if isinstance(variant, str):
                candidates.append(("variants", variant))
                continue
            if not isinstance(variant, Mapping):
                continue
            for key in _TARGET_CANDIDATE_KEYS:
                value = variant.get(key)
                if isinstance(value, str):
                    candidates.append(("variants", value))

    for container_name in ("loaded_instances", "instances"):
        raw_items = payload.get(container_name)
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes, bytearray)):
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            for key in _TARGET_CANDIDATE_KEYS:
                value = raw_item.get(key)
                if isinstance(value, str):
                    candidates.append((f"{container_name}.{key}", value))

    return tuple(candidates)


def _collect_match_fields(
    candidate_pairs: Sequence[tuple[str, str]], *, target_model_id: str
) -> tuple[bool, bool, tuple[str, ...]]:
    target_hash = _sha256_text(target_model_id)
    target_found = False
    target_hash_match = False
    match_fields: list[str] = []
    for field_name, candidate in candidate_pairs:
        if candidate == target_model_id:
            target_found = True
            if field_name not in match_fields:
                match_fields.append(field_name)
        if _sha256_text(candidate) == target_hash:
            target_hash_match = True
    return target_found, target_hash_match, tuple(match_fields)


def _collect_capability_keys(payload: Mapping[str, object]) -> tuple[str, ...]:
    capabilities = _extract_capabilities(payload)
    if not isinstance(capabilities, Mapping):
        return ()
    return tuple(sorted(str(key) for key in capabilities))


def _collect_context_candidates(payload: Mapping[str, object]) -> tuple[int, ...]:
    candidates: set[int] = set()
    _collect_int_candidates(payload, _CONTEXT_KEY_ALIASES, candidates)
    return tuple(sorted(value for value in candidates if value > 0))


def _find_nested_value(
    payload: object,
    *,
    aliases: frozenset[str],
    depth: int = 0,
) -> object | None:
    if depth > 4:
        return None
    if isinstance(payload, Mapping):
        for raw_key, raw_value in payload.items():
            if _normalize_key(raw_key) in aliases:
                return raw_value
        for raw_value in payload.values():
            nested_value = _find_nested_value(raw_value, aliases=aliases, depth=depth + 1)
            if nested_value is not None:
                return nested_value
        return None
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for item in payload:
            nested_value = _find_nested_value(item, aliases=aliases, depth=depth + 1)
            if nested_value is not None:
                return nested_value
    return None


def _safe_non_negative_int(value: object) -> int | None:
    candidate = _safe_int(value)
    if candidate is None or candidate < 0:
        return None
    return candidate


def _safe_non_negative_number(value: object) -> int | float | None:
    integer_candidate = _safe_int(value)
    if integer_candidate is not None:
        return integer_candidate if integer_candidate >= 0 else None
    float_candidate = _safe_float(value)
    if float_candidate is None or float_candidate < 0:
        return None
    return float_candidate


def _extract_safe_string_by_aliases(
    payload: Mapping[str, object], aliases: frozenset[str]
) -> str | None:
    return _safe_short_string(_find_nested_value(payload, aliases=aliases))


def _extract_loaded_instances_count(payload: Mapping[str, object]) -> int | None:
    for key in ("loaded_instances", "instances"):
        if key not in payload:
            continue
        raw_value = payload.get(key)
        if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray)):
            return len(raw_value)
        return None
    return None


def _field_matches_target(
    payload: Mapping[str, object], *, target_model_id: str, field_aliases: frozenset[str]
) -> bool:
    for raw_key, raw_value in payload.items():
        if _normalize_key(raw_key) not in field_aliases:
            continue
        if isinstance(raw_value, str) and raw_value == target_model_id:
            return True
    return False


def _resolve_native_load_id(
    payload: Mapping[str, object],
    *,
    target_model_id: str,
) -> str | None:
    raw_candidates = _extract_raw_candidate_strings(payload, include_nested=False)
    if target_model_id not in raw_candidates:
        return None
    for key in _NATIVE_LOAD_ID_PRIORITY_KEYS:
        safe_value = _safe_model_id(payload.get(key))
        if safe_value is not None:
            return safe_value
    return None


def _project_target_record(
    payload: Mapping[str, object],
    *,
    target_model_id: str,
    include_native_fields: bool,
) -> dict[str, object]:
    model_id_verified = _field_matches_target(
        payload,
        target_model_id=target_model_id,
        field_aliases=(
            _NATIVE_VERIFIED_MATCH_KEYS if include_native_fields else _COMPAT_VERIFIED_MATCH_KEYS
        ),
    )
    record: dict[str, object] = {"model_id_verified": model_id_verified}
    if not include_native_fields:
        return record
    record["loaded_instances_count"] = _extract_loaded_instances_count(payload)
    record["format"] = _extract_safe_string_by_aliases(payload, _NATIVE_FORMAT_KEY_ALIASES)
    record["quantization"] = _extract_safe_string_by_aliases(
        payload,
        _NATIVE_QUANTIZATION_KEY_ALIASES,
    )
    record["bits_per_weight"] = _safe_non_negative_number(
        _find_nested_value(payload, aliases=_NATIVE_BITS_PER_WEIGHT_KEY_ALIASES)
    )
    record["params"] = _extract_safe_string_by_aliases(payload, _NATIVE_PARAMS_KEY_ALIASES)
    record["size_bytes"] = _safe_non_negative_int(
        _find_nested_value(payload, aliases=_NATIVE_SIZE_BYTES_KEY_ALIASES)
    )
    return record


def _probe_plane(
    *,
    url: str,
    target_model_id: str,
    timeout_s: float,
    transport: IdentityProbeTransport,
    include_native_load_id: bool,
) -> _PlaneOutcome:
    request = _build_request(url)
    try:
        response_bytes = transport(request, timeout_s)
    except Exception as error:
        status, error_category, http_status = _categorize_transport_error(error)
        return _PlaneOutcome(
            status=status,
            error_category=error_category,
            http_status=http_status,
        )

    response_text = response_bytes.decode("utf-8", errors="replace")
    response_hash = _sha256_text(response_text)
    response_chars = len(response_text)

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return _PlaneOutcome(
            status="decode_error",
            error_category="json",
            response_hash=response_hash,
            response_chars=response_chars,
        )

    raw_models = _extract_model_list(payload)
    if raw_models is None:
        return _PlaneOutcome(
            status="invalid_shape",
            error_category="unknown",
            response_hash=response_hash,
            response_chars=response_chars,
        )

    record_count = 0
    safe_record_count = 0
    capability_keys: set[str] = set()
    context_candidates: set[int] = set()
    target_found = False
    target_hash_match = False
    match_fields: set[str] = set()
    native_load_ids: set[str] = set()
    raw_lookup_before_sanitization = False
    matched_record_projection: dict[str, object] | None = None
    matched_record_score = -1

    for item in raw_models:
        if not isinstance(item, Mapping):
            continue
        raw_lookup_before_sanitization = True
        record_count += 1
        raw_candidate_pairs = _extract_raw_candidate_pairs(item)
        item_target_found, item_target_hash_match, item_match_fields = _collect_match_fields(
            raw_candidate_pairs,
            target_model_id=target_model_id,
        )
        target_found = target_found or item_target_found
        target_hash_match = target_hash_match or item_target_hash_match
        match_fields.update(item_match_fields)
        if item_target_found:
            record_projection = _project_target_record(
                item,
                target_model_id=target_model_id,
                include_native_fields=include_native_load_id,
            )
            record_score = 1 + int(bool(record_projection.get("model_id_verified")))
            if record_score > matched_record_score:
                matched_record_projection = record_projection
                matched_record_score = record_score
        if include_native_load_id:
            native_load_id = _resolve_native_load_id(
                item,
                target_model_id=target_model_id,
            )
            if native_load_id is not None:
                native_load_ids.add(native_load_id)
        if _sanitize_external_mapping(item):
            safe_record_count += 1
        capability_keys.update(_collect_capability_keys(item))
        context_candidates.update(_collect_context_candidates(item))

    native_load_id = None
    native_load_id_hash = None
    if len(native_load_ids) == 1:
        native_load_id = next(iter(native_load_ids))
        native_load_id_hash = _sha256_text(native_load_id)

    model_id_verified = False
    loaded_instances_count = None
    format_value = None
    quantization = None
    bits_per_weight = None
    params = None
    size_bytes = None
    if matched_record_projection is not None:
        model_id_verified = bool(matched_record_projection.get("model_id_verified"))
        loaded_instances_count = matched_record_projection.get("loaded_instances_count")
        format_value = matched_record_projection.get("format")
        quantization = matched_record_projection.get("quantization")
        bits_per_weight = matched_record_projection.get("bits_per_weight")
        params = matched_record_projection.get("params")
        size_bytes = matched_record_projection.get("size_bytes")

    return _PlaneOutcome(
        status="ok",
        error_category=None,
        response_hash=response_hash,
        response_chars=response_chars,
        record_count=record_count,
        safe_record_count=safe_record_count,
        capability_keys=tuple(sorted(capability_keys)),
        context_candidates=tuple(sorted(context_candidates)),
        target_found=target_found,
        match_fields=tuple(sorted(match_fields)),
        target_hash_match=target_hash_match,
        raw_lookup_before_sanitization=raw_lookup_before_sanitization,
        native_load_id_resolved=native_load_id is not None,
        native_load_id_hash=native_load_id_hash,
        model_id_verified=model_id_verified,
        loaded_instances_count=loaded_instances_count,
        format=format_value,
        quantization=quantization,
        bits_per_weight=bits_per_weight,
        params=params,
        size_bytes=size_bytes,
        native_load_id=native_load_id,
    )


def _base_summary(
    *,
    target_hash: str,
    target_model_id_safe: bool,
    allow_remote: bool,
    is_localhost: bool,
    timeout_s: float,
) -> dict[str, object]:
    return {
        "probe_kind": "model_identity_visibility",
        "compat_endpoint_kind": IDENTITY_PROBE_COMPAT_ENDPOINT_KIND,
        "native_endpoint_kind": IDENTITY_PROBE_NATIVE_ENDPOINT_KIND,
        "endpoint_kinds_used": [
            IDENTITY_PROBE_COMPAT_ENDPOINT_KIND,
            IDENTITY_PROBE_NATIVE_ENDPOINT_KIND,
        ],
        "allow_remote": allow_remote,
        "is_localhost": is_localhost,
        "timeout_s": timeout_s,
        "target_hash": target_hash,
        "target_model_id_safe": target_model_id_safe,
        "resolution_status": "identity_error",
        "raw_lookup_before_sanitization": False,
        "target_found_compat": False,
        "target_found_native": False,
        "compat_match_fields": [],
        "native_match_fields": [],
        "target_hash_match": False,
        "compat_model_id_verified": False,
        "native_model_key_verified": False,
        "native_loaded_instances_count": None,
        "native_format": None,
        "native_quantization": None,
        "native_bits_per_weight": None,
        "native_params": None,
        "native_size_bytes": None,
        "candidate_capability_keys": [],
        "native_load_id_resolved": False,
        "safe_record_count": 0,
    }


def _merge_plane(summary: dict[str, object], *, prefix: str, outcome: _PlaneOutcome) -> None:
    summary[f"{prefix}_status"] = outcome.status
    summary[f"{prefix}_error_category"] = outcome.error_category
    summary[f"{prefix}_record_count"] = outcome.record_count
    if outcome.response_hash is not None:
        summary[f"{prefix}_response_hash"] = outcome.response_hash
    if outcome.response_chars is not None:
        summary[f"{prefix}_response_chars"] = outcome.response_chars
    if outcome.http_status is not None:
        summary[f"{prefix}_http_status"] = outcome.http_status
    summary["safe_record_count"] = (
        int(summary.get("safe_record_count", 0)) + outcome.safe_record_count
    )
    summary["raw_lookup_before_sanitization"] = (
        bool(summary.get("raw_lookup_before_sanitization"))
        or outcome.raw_lookup_before_sanitization
    )
    summary[f"{prefix}_match_fields"] = list(outcome.match_fields)
    summary[f"{prefix}_capability_keys"] = list(outcome.capability_keys)
    summary[f"{prefix}_context_candidates"] = list(outcome.context_candidates)
    if prefix == "compat":
        summary["compat_model_id_verified"] = outcome.model_id_verified
        return
    summary["native_model_key_verified"] = outcome.model_id_verified
    summary["native_loaded_instances_count"] = outcome.loaded_instances_count
    summary["native_format"] = outcome.format
    summary["native_quantization"] = outcome.quantization
    summary["native_bits_per_weight"] = outcome.bits_per_weight
    summary["native_params"] = outcome.params
    summary["native_size_bytes"] = outcome.size_bytes


def _resolve_identity_mapping_status(*, compat: _PlaneOutcome, native: _PlaneOutcome) -> str:
    if compat.status != "ok" or native.status != "ok":
        return "identity_error"
    if compat.target_found and native.target_found and native.native_load_id_resolved:
        return "resolved"
    if native.target_found and not compat.target_found:
        return "compat_missing"
    if compat.target_found and not native.target_found:
        return "native_missing"
    return "unresolved"


def _finalize_status(*, compat: _PlaneOutcome, native: _PlaneOutcome) -> tuple[str, str | None]:
    failures = []
    if compat.status != "ok":
        failures.append(("compat", compat.status, compat.error_category))
    if native.status != "ok":
        failures.append(("native", native.status, native.error_category))
    if not failures:
        return "ok", None
    if len(failures) == 1:
        plane, status, error_category = failures[0]
        return f"{plane}_{status}", error_category
    return "multiple_errors", "multiple"


def probe_lmstudio_identity(
    base_url: str,
    *,
    target_model_id: str,
    allow_remote: bool = False,
    timeout_s: float = 10.0,
    transport: IdentityProbeTransport | None = None,
) -> IdentityProbeResult:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")

    parsed = _normalize_base_url(base_url)
    is_localhost = parsed.hostname.lower() in _LOCALHOST_NAMES
    if not allow_remote and not is_localhost:
        raise ValueError("base_url must stay on localhost unless allow_remote is true")

    target_hash, target_model_id_safe = _safe_target_flags(target_model_id)
    summary = _base_summary(
        target_hash=target_hash,
        target_model_id_safe=target_model_id_safe,
        allow_remote=allow_remote,
        is_localhost=is_localhost,
        timeout_s=timeout_s,
    )
    if not target_model_id_safe:
        summary["status"] = "invalid_target_model_id"
        summary["error_category"] = "validation"
        summary["compat_record_count"] = 0
        summary["native_record_count"] = 0
        summary["compat_capability_keys"] = []
        summary["native_capability_keys"] = []
        summary["compat_context_candidates"] = []
        summary["native_context_candidates"] = []
        return IdentityProbeResult(summary=summary)

    effective_transport = transport or _default_transport
    compat = _probe_plane(
        url=build_identity_probe_compat_url(base_url),
        target_model_id=target_model_id,
        timeout_s=timeout_s,
        transport=effective_transport,
        include_native_load_id=False,
    )
    native = _probe_plane(
        url=build_identity_probe_native_url(base_url),
        target_model_id=target_model_id,
        timeout_s=timeout_s,
        transport=effective_transport,
        include_native_load_id=True,
    )

    _merge_plane(summary, prefix="compat", outcome=compat)
    _merge_plane(summary, prefix="native", outcome=native)
    summary["target_found_compat"] = compat.target_found
    summary["target_found_native"] = native.target_found
    summary["target_hash_match"] = compat.target_hash_match and native.target_hash_match
    summary["candidate_capability_keys"] = list(native.capability_keys)
    summary["native_load_id_resolved"] = native.native_load_id_resolved
    if native.native_load_id_hash is not None:
        summary["native_load_id_hash"] = native.native_load_id_hash
    summary["status"], summary["error_category"] = _finalize_status(
        compat=compat,
        native=native,
    )
    summary["resolution_status"] = _resolve_identity_mapping_status(
        compat=compat,
        native=native,
    )
    return IdentityProbeResult(summary=summary, native_load_id=native.native_load_id)


def render_identity_probe_report(
    *,
    run_id: str,
    summary: Mapping[str, object],
    output_files: Sequence[str] = IDENTITY_PROBE_RESULT_FILE_NAMES,
) -> str:
    lines = [
        "# LM Studio Identity Probe Report",
        "",
        "## Run",
        "",
        "- command: `probe-identity`",
        f"- run_id: `{run_id}`",
        f"- compat_endpoint_kind: `{summary.get('compat_endpoint_kind')}`",
        f"- native_endpoint_kind: `{summary.get('native_endpoint_kind')}`",
        f"- endpoint_kinds_used: `{summary.get('endpoint_kinds_used')}`",
        f"- allow_remote: `{str(bool(summary.get('allow_remote'))).lower()}`",
        f"- is_localhost: `{str(bool(summary.get('is_localhost'))).lower()}`",
        f"- timeout_s: `{summary.get('timeout_s')}`",
        "",
        "## Result",
        "",
        f"- status: `{summary.get('status')}`",
        f"- error_category: `{summary.get('error_category')}`",
        f"- target_model_id_safe: `{summary.get('target_model_id_safe')}`",
        f"- target_hash: `{summary.get('target_hash')}`",
        f"- resolution_status: `{summary.get('resolution_status')}`",
        f"- raw_lookup_before_sanitization: `{summary.get('raw_lookup_before_sanitization')}`",
        f"- target_found_compat: `{summary.get('target_found_compat')}`",
        f"- target_found_native: `{summary.get('target_found_native')}`",
        f"- compat_match_fields: `{summary.get('compat_match_fields')}`",
        f"- native_match_fields: `{summary.get('native_match_fields')}`",
        f"- compat_model_id_verified: `{summary.get('compat_model_id_verified')}`",
        f"- native_model_key_verified: `{summary.get('native_model_key_verified')}`",
        f"- target_hash_match: `{summary.get('target_hash_match')}`",
        f"- candidate_capability_keys: `{summary.get('candidate_capability_keys')}`",
        f"- native_load_id_resolved: `{summary.get('native_load_id_resolved')}`",
    ]
    if summary.get("native_load_id_hash") is not None:
        lines.append(f"- native_load_id_hash: `{summary.get('native_load_id_hash')}`")
    for field_name in (
        "compat_status",
        "compat_error_category",
        "compat_response_hash",
        "compat_response_chars",
        "compat_record_count",
        "compat_capability_keys",
        "compat_context_candidates",
        "native_status",
        "native_error_category",
        "native_response_hash",
        "native_response_chars",
        "native_record_count",
        "native_capability_keys",
        "native_context_candidates",
        "native_loaded_instances_count",
        "native_format",
        "native_quantization",
        "native_bits_per_weight",
        "native_params",
        "native_size_bytes",
        "safe_record_count",
    ):
        if field_name in summary:
            lines.append(f"- {field_name}: `{summary.get(field_name)}`")

    lines.extend(
        [
            "",
            "## Privacy",
            "",
            "- raw response bodies: not stored",
            "- raw target model id: not stored",
            "- raw lookup proof persists field names/hashes only, not raw values",
            "- raw base URL: not stored",
            "- requests are GET-only to endpoint kinds `compat_models` and `native_models`",
            "- chat/load/unload/download/generation endpoints: not used",
            "- raw paths/urls/secrets/messages/content/provider records: stripped",
            "",
            "## Output Files",
            "",
            *(f"- `{file_name}`" for file_name in output_files),
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "IDENTITY_PROBE_COMPAT_ENDPOINT_PATH",
    "IDENTITY_PROBE_NATIVE_ENDPOINT_PATH",
    "IDENTITY_PROBE_RESULT_FILE_NAMES",
    "IdentityProbeResult",
    "IdentityProbeTransport",
    "build_identity_probe_compat_url",
    "build_identity_probe_native_url",
    "is_local_identity_probe_base_url",
    "probe_lmstudio_identity",
    "render_identity_probe_report",
]
