from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib import request as urllib_request
from urllib.parse import urlunsplit

import yaml

from .model_probe import (
    _LOCALHOST_NAMES,
    _categorize_transport_error,
    _extract_model_list,
    _normalize_base_url,
    _safe_model_id,
    _sha256_text,
)

CandidateResolutionTransport = Callable[[urllib_request.Request, float], bytes]

CANDIDATE_RESOLUTION_ENDPOINT_PATH = "/v1/models"
CANDIDATE_RESOLUTION_RESULT_FILE_NAMES = (
    "environment.json",
    "candidate_resolution.json",
    "candidate_suggestions.jsonl",
    "report.md",
)

_MATCH_TYPE_PRIORITY = {
    "exact": 0,
    "case_insensitive": 1,
    "basename_normalized": 2,
    "family_size_quant_tokens": 3,
}
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
_RAW_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_SPLIT_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")
_SAFE_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_DETAIL_TOKEN_RE = re.compile(r"^(?:e?\d+b|q\d+[a-z0-9]*|[a-z]+\d+[a-z0-9]*|\d+[a-z]+)$")
_STOP_TOKENS = frozenset(
    {
        "chat",
        "community",
        "gguf",
        "google",
        "instruct",
        "it",
        "k",
        "local",
        "m",
        "model",
        "models",
        "small",
        "medium",
    }
)


@dataclass(frozen=True, slots=True)
class CandidateResolutionResult:
    summary: dict[str, object]
    candidate_records: tuple[dict[str, object], ...]
    suggestion_records: tuple[dict[str, object], ...]


def _default_transport(request: urllib_request.Request, timeout_s: float) -> bytes:
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        return response.read()


def _safe_label(value: object, *, fallback: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if _SAFE_LABEL_RE.fullmatch(text):
            return text
    return fallback


def _extract_source_basename(source_id: object) -> str:
    if not isinstance(source_id, str):
        return ""
    text = source_id.strip()
    if not text:
        return ""
    return re.split(r"[\\/]", text)[-1]


def _strip_extension(value: str) -> str:
    if "." not in value:
        return value
    return value.rsplit(".", 1)[0]


def _tokenize_text(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    tokens: set[str] = set()
    for raw_part in _RAW_TOKEN_RE.findall(value.lower()):
        if raw_part:
            tokens.add(raw_part)
        for segment in _SPLIT_BOUNDARY_RE.split(raw_part):
            if segment:
                tokens.add(segment)
    if {"q4", "k", "m"}.issubset(tokens) or {"q4k", "m"}.issubset(tokens):
        tokens.add("q4km")
    filtered = {
        token
        for token in tokens
        if _SAFE_TOKEN_RE.fullmatch(token) and token not in _STOP_TOKENS and not token.isdigit()
    }
    return tuple(sorted(filtered))


def _candidate_detail_tokens(tokens: Sequence[str], *, family: str) -> tuple[str, ...]:
    family_lower = family.lower()
    detail_tokens = {
        token
        for token in tokens
        if token != family_lower and _DETAIL_TOKEN_RE.fullmatch(token) is not None
    }
    return tuple(sorted(detail_tokens))


def _visible_model_ids(raw_models: Sequence[object]) -> tuple[str, ...]:
    visible: list[str] = []
    for model_payload in raw_models:
        if not isinstance(model_payload, Mapping):
            continue
        safe_model_id = _safe_model_id(model_payload.get("id"))
        if safe_model_id is not None:
            visible.append(safe_model_id)
    return tuple(dict.fromkeys(visible))


def _safe_matched_tokens(tokens: Sequence[str]) -> list[str]:
    return [token for token in tokens if _SAFE_TOKEN_RE.fullmatch(token) is not None][:5]


def _candidate_hint_strings(
    *,
    lab_key: str,
    existing_compat_model_id: str | None,
    source_stem: str,
) -> tuple[str, ...]:
    hints = [lab_key]
    if existing_compat_model_id:
        hints.append(existing_compat_model_id)
    if source_stem:
        hints.append(source_stem)
    return tuple(dict.fromkeys(hint for hint in hints if hint))


def _source_basename_core_tokens(source_stem: str) -> tuple[str, ...]:
    tokens = [token for token in _tokenize_text(source_stem) if token not in {"q4", "q4k", "q4km"}]
    return tuple(tokens)


def _build_suggestion(
    *,
    suggested_model_id: str,
    match_type: str,
    confidence: str,
    score: float,
    matched_tokens: Sequence[str],
) -> dict[str, object]:
    return {
        "suggested_compat_model_id": suggested_model_id,
        "match_type": match_type,
        "confidence": confidence,
        "requires_user_confirmation": True,
        "score": round(score, 4),
        "matched_tokens": _safe_matched_tokens(matched_tokens),
    }


def _match_visible_model(
    *,
    visible_model_id: str,
    family: str,
    candidate_tokens: Sequence[str],
    candidate_detail_tokens: Sequence[str],
    hint_strings: Sequence[str],
    source_basename_tokens: Sequence[str],
) -> dict[str, object] | None:
    visible_tokens = set(_tokenize_text(visible_model_id))
    visible_lower = visible_model_id.lower()
    hint_lowers = {hint.lower() for hint in hint_strings}

    if visible_model_id in hint_strings:
        return _build_suggestion(
            suggested_model_id=visible_model_id,
            match_type="exact",
            confidence="high",
            score=1.0,
            matched_tokens=sorted(set(_tokenize_text(visible_model_id)) & set(candidate_tokens)),
        )

    if visible_lower in hint_lowers:
        return _build_suggestion(
            suggested_model_id=visible_model_id,
            match_type="case_insensitive",
            confidence="high",
            score=0.95,
            matched_tokens=sorted(set(_tokenize_text(visible_model_id)) & set(candidate_tokens)),
        )

    source_token_set = set(source_basename_tokens)
    if (
        source_token_set
        and family.lower() in visible_tokens
        and source_token_set.issubset(visible_tokens)
    ):
        return _build_suggestion(
            suggested_model_id=visible_model_id,
            match_type="basename_normalized",
            confidence="high" if len(source_token_set) >= 3 else "medium",
            score=0.85 + min(0.04 * max(len(source_token_set) - 2, 0), 0.1),
            matched_tokens=sorted(source_token_set),
        )

    matched_tokens = set(candidate_tokens) & visible_tokens
    if family.lower() not in matched_tokens:
        return None

    detail_matches = set(candidate_detail_tokens) & visible_tokens
    if not detail_matches:
        return None

    score = 0.55 + min(0.15 * len(detail_matches), 0.25)
    if len(matched_tokens) > len(detail_matches):
        score += min(0.03 * (len(matched_tokens) - len(detail_matches)), 0.09)
    return _build_suggestion(
        suggested_model_id=visible_model_id,
        match_type="family_size_quant_tokens",
        confidence="medium" if len(detail_matches) >= 2 else "low",
        score=min(score, 0.89),
        matched_tokens=sorted(detail_matches | {family.lower()}),
    )


def _ranked_suggestions(
    *,
    visible_model_ids: Sequence[str],
    family: str,
    candidate_tokens: Sequence[str],
    candidate_detail_tokens: Sequence[str],
    hint_strings: Sequence[str],
    source_basename_tokens: Sequence[str],
) -> tuple[dict[str, object], ...]:
    suggestions_by_id: dict[str, dict[str, object]] = {}
    for visible_model_id in visible_model_ids:
        suggestion = _match_visible_model(
            visible_model_id=visible_model_id,
            family=family,
            candidate_tokens=candidate_tokens,
            candidate_detail_tokens=candidate_detail_tokens,
            hint_strings=hint_strings,
            source_basename_tokens=source_basename_tokens,
        )
        if suggestion is None:
            continue
        previous = suggestions_by_id.get(visible_model_id)
        if previous is None or float(suggestion["score"]) > float(previous["score"]):
            suggestions_by_id[visible_model_id] = suggestion

    ranked = sorted(
        suggestions_by_id.values(),
        key=lambda item: (
            -float(item["score"]),
            _MATCH_TYPE_PRIORITY[str(item["match_type"])],
            str(item["suggested_compat_model_id"]),
        ),
    )
    return tuple(ranked[:3])


def _base_summary(
    *,
    candidate_count: int,
    allow_remote: bool,
    is_localhost: bool,
    timeout_s: float,
) -> dict[str, object]:
    return {
        "probe_kind": "candidate_model_resolution",
        "endpoint_path": CANDIDATE_RESOLUTION_ENDPOINT_PATH,
        "allow_remote": allow_remote,
        "is_localhost": is_localhost,
        "timeout_s": timeout_s,
        "status": "validation_error",
        "error_category": "registry",
        "candidate_count": candidate_count,
        "visible_model_count": 0,
        "exact_confirmed_count": 0,
        "unresolved_count": candidate_count,
        "suggestion_count": 0,
        "requires_user_confirmation_count": 0,
        "raw_response_body_stored": False,
        "registry_written": False,
    }


def _load_registry_candidates(registry_path: Path) -> tuple[list[Mapping[str, object]], int]:
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("registry payload must be a mapping")
    candidates = payload.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes, bytearray)):
        raise ValueError("registry candidates must be a sequence")
    normalized_candidates = [
        candidate for candidate in candidates if isinstance(candidate, Mapping)
    ]
    if len(normalized_candidates) != len(candidates):
        raise ValueError("registry candidates must contain only mappings")
    return normalized_candidates, len(normalized_candidates)


def build_candidate_resolution_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, CANDIDATE_RESOLUTION_ENDPOINT_PATH, "", "")
    )


def is_local_candidate_resolution_base_url(base_url: str) -> bool:
    return _normalize_base_url(base_url).hostname.lower() in _LOCALHOST_NAMES


def resolve_candidate_models(
    base_url: str,
    *,
    registry_path: str | Path,
    allow_remote: bool = False,
    timeout_s: float = 10.0,
    transport: CandidateResolutionTransport | None = None,
) -> CandidateResolutionResult:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")

    parsed = _normalize_base_url(base_url)
    is_localhost = parsed.hostname.lower() in _LOCALHOST_NAMES
    if not allow_remote and not is_localhost:
        raise ValueError("base_url must stay on localhost unless allow_remote is true")

    try:
        registry_candidates, candidate_count = _load_registry_candidates(Path(registry_path))
    except (OSError, yaml.YAMLError, ValueError):
        summary = _base_summary(
            candidate_count=0,
            allow_remote=allow_remote,
            is_localhost=is_localhost,
            timeout_s=timeout_s,
        )
        return CandidateResolutionResult(
            summary=summary, candidate_records=(), suggestion_records=()
        )

    summary = _base_summary(
        candidate_count=candidate_count,
        allow_remote=allow_remote,
        is_localhost=is_localhost,
        timeout_s=timeout_s,
    )
    request = urllib_request.Request(
        build_candidate_resolution_url(base_url),
        method="GET",
        headers={"Accept": "application/json"},
    )
    effective_transport = transport or _default_transport

    try:
        response_bytes = effective_transport(request, timeout_s)
    except Exception as error:
        status, error_category, http_status = _categorize_transport_error(error)
        summary["status"] = status
        summary["error_category"] = error_category
        if http_status is not None:
            summary["http_status"] = http_status
        return CandidateResolutionResult(
            summary=summary, candidate_records=(), suggestion_records=()
        )

    response_text = response_bytes.decode("utf-8", errors="replace")
    summary["response_hash"] = _sha256_text(response_text)
    summary["response_chars"] = len(response_text)

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        summary["status"] = "decode_error"
        summary["error_category"] = "json"
        return CandidateResolutionResult(
            summary=summary, candidate_records=(), suggestion_records=()
        )

    raw_models = _extract_model_list(payload)
    if raw_models is None:
        summary["status"] = "invalid_shape"
        summary["error_category"] = "shape"
        return CandidateResolutionResult(
            summary=summary, candidate_records=(), suggestion_records=()
        )

    visible_model_ids = _visible_model_ids(raw_models)
    visible_model_id_set = set(visible_model_ids)
    summary["visible_model_count"] = len(visible_model_ids)

    candidate_records: list[dict[str, object]] = []
    suggestion_records: list[dict[str, object]] = []
    exact_confirmed_count = 0
    unresolved_count = 0

    for index, candidate in enumerate(registry_candidates, start=1):
        lab_key = _safe_label(candidate.get("lab_key"), fallback=f"candidate_{index:04d}")
        family = _safe_label(candidate.get("family"), fallback="unknown")
        size_class = _safe_label(candidate.get("size_class"), fallback="unknown")
        compat_status = _safe_label(
            candidate.get("compat_model_id_status"),
            fallback="unknown",
        )
        existing_compat_model_id = _safe_model_id(candidate.get("compat_model_id"))
        raw_source_id = candidate.get("source_id")
        source_basename = _extract_source_basename(raw_source_id)
        source_stem = _strip_extension(source_basename)
        source_basename_tokens = _source_basename_core_tokens(source_stem)
        candidate_tokens = tuple(
            sorted(
                set(_tokenize_text(lab_key))
                | set(_tokenize_text(family))
                | set(_tokenize_text(size_class))
                | set(_tokenize_text(source_stem))
                | set(_tokenize_text(existing_compat_model_id or ""))
            )
        )
        detail_tokens = _candidate_detail_tokens(candidate_tokens, family=family)
        hint_strings = _candidate_hint_strings(
            lab_key=lab_key,
            existing_compat_model_id=existing_compat_model_id,
            source_stem=source_stem,
        )

        existing_compat_exact_match = (
            existing_compat_model_id is not None
            and existing_compat_model_id in visible_model_id_set
        )
        suggestions: tuple[dict[str, object], ...] = ()
        if existing_compat_exact_match:
            status = "confirmed"
            exact_confirmed_count += 1
        else:
            suggestions = _ranked_suggestions(
                visible_model_ids=visible_model_ids,
                family=family,
                candidate_tokens=candidate_tokens,
                candidate_detail_tokens=detail_tokens,
                hint_strings=hint_strings,
                source_basename_tokens=source_basename_tokens,
            )
            status = "suggested" if suggestions else "unresolved"
            unresolved_count += 1

        candidate_record: dict[str, object] = {
            "lab_key": lab_key,
            "family": family,
            "size_class": size_class,
            "compat_model_id_status": compat_status,
            "existing_compat_exact_match": existing_compat_exact_match,
            "source_id_present": isinstance(raw_source_id, str) and bool(raw_source_id.strip()),
            "status": status,
            "suggestions": list(suggestions),
        }
        if existing_compat_model_id is not None:
            candidate_record["existing_compat_model_id"] = existing_compat_model_id
        if isinstance(raw_source_id, str) and raw_source_id.strip():
            candidate_record["source_id_hash"] = _sha256_text(raw_source_id)
        if source_basename:
            candidate_record["source_basename_hash"] = _sha256_text(source_basename)
        candidate_records.append(candidate_record)

        for suggestion in suggestions:
            suggestion_records.append(
                {
                    "lab_key": lab_key,
                    "family": family,
                    "size_class": size_class,
                    "compat_model_id_status": compat_status,
                    "existing_compat_exact_match": existing_compat_exact_match,
                    "candidate_status": status,
                    **suggestion,
                }
            )

    summary["status"] = "ok"
    summary["error_category"] = None
    summary["exact_confirmed_count"] = exact_confirmed_count
    summary["unresolved_count"] = unresolved_count
    summary["suggestion_count"] = len(suggestion_records)
    summary["requires_user_confirmation_count"] = len(suggestion_records)
    return CandidateResolutionResult(
        summary=summary,
        candidate_records=tuple(candidate_records),
        suggestion_records=tuple(suggestion_records),
    )


def render_candidate_resolution_report(
    *,
    run_id: str,
    summary: Mapping[str, object],
    candidate_records: Sequence[Mapping[str, object]],
    output_files: Sequence[str] = CANDIDATE_RESOLUTION_RESULT_FILE_NAMES,
) -> str:
    lines = [
        "# LM Studio Candidate Resolution Report",
        "",
        "## Run",
        "",
        "- command: `resolve-candidates`",
        f"- run_id: `{run_id}`",
        f"- endpoint_path: `{summary.get('endpoint_path')}`",
        "- request_method: `GET`",
        "- request_scope: `OpenAI-compatible /v1/models only`",
        f"- allow_remote: `{str(bool(summary.get('allow_remote'))).lower()}`",
        f"- is_localhost: `{str(bool(summary.get('is_localhost'))).lower()}`",
        f"- timeout_s: `{summary.get('timeout_s')}`",
        "",
        "## Result",
        "",
        f"- status: `{summary.get('status')}`",
        f"- error_category: `{summary.get('error_category')}`",
    ]
    if summary.get("http_status") is not None:
        lines.append(f"- http_status: `{summary.get('http_status')}`")
    if summary.get("response_hash") is not None:
        lines.append(f"- response_hash: `{summary.get('response_hash')}`")
    if summary.get("response_chars") is not None:
        lines.append(f"- response_chars: `{summary.get('response_chars')}`")
    for key in (
        "candidate_count",
        "visible_model_count",
        "exact_confirmed_count",
        "unresolved_count",
        "suggestion_count",
        "requires_user_confirmation_count",
    ):
        lines.append(f"- {key}: `{summary.get(key)}`")

    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- GET `/v1/models` only",
            "- no generation/load/unload/download endpoints used",
            "- registry not written",
            "- fuzzy suggestions require user confirmation",
            "- raw response body/base URL/source_id not stored",
            "",
            "## Candidate Status",
            "",
        ]
    )
    for candidate_record in candidate_records:
        suggestion_ids = [
            str(item.get("suggested_compat_model_id"))
            for item in candidate_record.get("suggestions", [])
            if isinstance(item, Mapping) and item.get("suggested_compat_model_id")
        ]
        line = f"- `{candidate_record.get('lab_key')}` -> `{candidate_record.get('status')}`"
        if candidate_record.get("existing_compat_exact_match"):
            line += " (existing compat exact match)"
        elif suggestion_ids:
            line += " suggestions: `" + "`, `".join(suggestion_ids) + "`"
        lines.append(line)

    lines.extend(
        [
            "",
            "## Output Files",
            "",
            *(f"- `{file_name}`" for file_name in output_files),
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "CANDIDATE_RESOLUTION_ENDPOINT_PATH",
    "CANDIDATE_RESOLUTION_RESULT_FILE_NAMES",
    "CandidateResolutionResult",
    "CandidateResolutionTransport",
    "build_candidate_resolution_url",
    "is_local_candidate_resolution_base_url",
    "render_candidate_resolution_report",
    "resolve_candidate_models",
]
