from __future__ import annotations

import hashlib
import json
import math
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import SplitResult, urlsplit, urlunsplit

type ModelProbeTransport = Callable[[urllib_request.Request, float], bytes]

MODEL_PROBE_ENDPOINT_PATH = "/api/v1/models"
MODEL_PROBE_RESULT_FILE_NAMES = (
    "environment.json",
    "model_probe.json",
    "models.jsonl",
    "report.md",
)

_LOCALHOST_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_FORBIDDEN_KEY_SEGMENTS = frozenset(
    {
        "path",
        "file",
        "folder",
        "dir",
        "url",
        "uri",
        "secret",
        "token",
        "key",
        "body",
        "prompt",
        "response",
        "message",
        "content",
        "env",
        "user",
    }
)
_FORBIDDEN_KEY_COMPACT_SUBSTRINGS = frozenset(
    {
        "prompt",
        "response",
        "message",
        "content",
        "secret",
        "token",
        "password",
        "bearer",
        "apikey",
        "path",
        "file",
        "folder",
        "dir",
        "url",
        "uri",
        "env",
        "user",
        "body",
    }
)
_CONTEXT_KEY_ALIASES = frozenset(
    {
        "context_length",
        "context_window",
        "max_context_length",
        "max_context_window",
        "max_sequence_length",
        "n_ctx",
        "n_context",
        "ctx_len",
    }
)
_PARALLEL_KEY_ALIASES = frozenset(
    {
        "parallel",
        "n_parallel",
        "parallelism",
        "max_parallel",
        "max_parallelism",
    }
)
_CAPABILITY_CONTAINER_KEYS = frozenset({"capabilities", "capability", "features"})
_SAFE_STATUS_VALUES = frozenset({"loaded", "ready", "active", "idle", "unloaded", "inactive"})
_SENSITIVE_STRING_SEGMENTS = frozenset(
    {
        "secret",
        "token",
        "password",
        "bearer",
        "message",
        "content",
        "prompt",
        "response",
        "env",
        "user",
    }
)
_SENSITIVE_STRING_PATTERNS = frozenset({"api_key", "apikey"})
_UNSAFE_MODEL_ID_SEGMENTS = frozenset(
    {
        "secret",
        "token",
        "password",
        "bearer",
        "message",
        "content",
        "prompt",
        "response",
        "env",
        "user",
    }
)
_UNSAFE_MODEL_ID_PATTERNS = frozenset({"api_key", "apikey"})
_UNSAFE_PATH_PREFIXES = frozenset(
    {
        "models",
        "model",
        "weights",
        "checkpoints",
        "data",
        "tmp",
        "temp",
        "private",
    }
)
_UNSAFE_FILE_EXTENSIONS = (
    ".gguf",
    ".bin",
    ".safetensors",
    ".pt",
    ".pth",
    ".onnx",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".log",
    ".db",
    ".sqlite",
    ".zip",
)


@dataclass(frozen=True, slots=True)
class ModelProbeResult:
    summary: dict[str, object]
    model_records: tuple[dict[str, object], ...]


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _normalize_key(value: object) -> str:
    text = str(value).strip()
    normalized: list[str] = []
    previous_was_separator = False
    for character in text:
        if character.isalnum():
            if character.isupper() and normalized and normalized[-1] != "_":
                normalized.append("_")
            normalized.append(character.lower())
            previous_was_separator = False
            continue
        if not previous_was_separator and normalized:
            normalized.append("_")
        previous_was_separator = True
    return "".join(normalized).strip("_") or "unnamed"


def _key_is_forbidden(value: object) -> bool:
    normalized = _normalize_key(value)
    segments = [segment for segment in normalized.split("_") if segment]
    if any(segment in _FORBIDDEN_KEY_SEGMENTS for segment in segments):
        return True
    compact = normalized.replace("_", "")
    return any(pattern in compact for pattern in _FORBIDDEN_KEY_COMPACT_SUBSTRINGS)


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return number
    return None


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            try:
                return int(text)
            except ValueError:
                return None
    return None


def _safe_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _looks_like_url(value: str) -> bool:
    lowered = value.lower()
    return "://" in lowered or lowered.startswith("www.")


def _looks_like_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith("\\\\"):
        return True
    if len(text) >= 3 and text[1:3] in {":\\", ":/"} and text[0].isalpha():
        return True
    if text.startswith("/"):
        return True
    normalized = text.lower().replace("\\", "/")
    if normalized.startswith(("./", "../")):
        return True
    if normalized.endswith(_UNSAFE_FILE_EXTENSIONS):
        return True
    if "\\" in text:
        return True
    if "/" not in normalized:
        return False
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return False
    if any(segment in {".", ".."} for segment in segments):
        return True
    if len(segments) > 2:
        return True
    if segments[0] in _UNSAFE_PATH_PREFIXES:
        return True
    return False


def _looks_like_secret_blob(value: str) -> bool:
    compact = value.replace("-", "").replace("_", "")
    return len(compact) >= 40 and compact.isalnum()


def _looks_like_sensitive_text(value: str) -> bool:
    normalized = _normalize_key(value)
    if not normalized:
        return False
    segments = [segment for segment in normalized.split("_") if segment]
    if any(segment in _SENSITIVE_STRING_SEGMENTS for segment in segments):
        return True
    return any(pattern in normalized for pattern in _SENSITIVE_STRING_PATTERNS)


def _safe_short_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > 120 or "\n" in text or "\r" in text:
        return None
    if (
        _looks_like_url(text)
        or _looks_like_path(text)
        or _looks_like_secret_blob(text)
        or _looks_like_sensitive_text(text)
    ):
        return None
    return text


def _safe_model_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 200 or "\n" in text or "\r" in text:
        return None
    normalized = _normalize_key(text)
    normalized_segments = [segment for segment in normalized.split("_") if segment]
    if _looks_like_url(text) or _looks_like_path(text) or _looks_like_secret_blob(text):
        return None
    if any(segment in _UNSAFE_MODEL_ID_SEGMENTS for segment in normalized_segments):
        return None
    if any(pattern in normalized for pattern in _UNSAFE_MODEL_ID_PATTERNS):
        return None
    return text


def _sanitize_target_model_id(value: object) -> tuple[str | None, bool | None]:
    if value is None:
        return None, None
    safe_model_id = _safe_model_id(value)
    return safe_model_id, safe_model_id is not None


def _normalize_base_url(base_url: str) -> SplitResult:
    candidate = base_url.strip()
    if not candidate:
        raise ValueError("base_url must be a non-empty string")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError("base_url must use http or https")
    if not parsed.hostname:
        raise ValueError("base_url must include a hostname")
    return parsed


def is_local_model_probe_base_url(base_url: str) -> bool:
    return _normalize_base_url(base_url).hostname.lower() in _LOCALHOST_NAMES


def build_model_probe_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, MODEL_PROBE_ENDPOINT_PATH, "", ""))


def _default_transport(request: urllib_request.Request, timeout_s: float) -> bytes:
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        return response.read()


def _extract_model_list(payload: object) -> list[object] | None:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return list(payload)
    if isinstance(payload, Mapping):
        for key in ("data", "models"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return list(value)
    return None


def _collect_int_candidates(payload: object, aliases: frozenset[str], output: set[int]) -> None:
    if isinstance(payload, Mapping):
        for raw_key, raw_value in payload.items():
            normalized_key = _normalize_key(raw_key)
            if normalized_key in aliases:
                candidate = _safe_int(raw_value)
                if candidate is not None:
                    output.add(candidate)
            _collect_int_candidates(raw_value, aliases, output)
        return
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for item in payload:
            _collect_int_candidates(item, aliases, output)


def _sanitize_external_value(value: object, *, depth: int) -> object | None:
    if depth > 4:
        return None
    boolean_value = _safe_bool(value)
    if boolean_value is not None:
        return boolean_value
    integer_value = _safe_int(value)
    if integer_value is not None:
        return integer_value
    float_value = _safe_float(value)
    if float_value is not None:
        return float_value
    short_string = _safe_short_string(value)
    if short_string is not None:
        return short_string
    if isinstance(value, Mapping):
        sanitized = _sanitize_external_mapping(value, depth=depth + 1)
        return sanitized if sanitized else None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sanitized_items: list[object] = []
        for index, item in enumerate(value):
            if index >= 20:
                break
            sanitized_item = _sanitize_external_value(item, depth=depth + 1)
            if sanitized_item is not None:
                sanitized_items.append(sanitized_item)
        return sanitized_items or None
    return None


def _sanitize_external_mapping(
    payload: Mapping[str, object], *, depth: int = 0
) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for raw_key, raw_value in payload.items():
        key = str(raw_key)
        if _key_is_forbidden(key):
            continue
        sanitized_value = _sanitize_external_value(raw_value, depth=depth + 1)
        if sanitized_value is not None:
            sanitized[key] = sanitized_value
    return sanitized


def _extract_capabilities(model_payload: Mapping[str, object]) -> dict[str, object] | None:
    for raw_key, raw_value in model_payload.items():
        if _normalize_key(raw_key) not in _CAPABILITY_CONTAINER_KEYS:
            continue
        if isinstance(raw_value, Mapping):
            sanitized = _sanitize_external_mapping(raw_value)
            if sanitized:
                return sanitized
        if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray)):
            sanitized_value = _sanitize_external_value(raw_value, depth=0)
            if isinstance(sanitized_value, list) and sanitized_value:
                return {"items": sanitized_value}
    return None


def _extract_model_id(model_payload: Mapping[str, object], model_index: int) -> str:
    for key in ("id", "model_id", "model", "identifier"):
        if key not in model_payload:
            continue
        model_id = _safe_model_id(model_payload.get(key))
        if model_id is not None:
            return model_id
    return f"model_{model_index:04d}"


def _extract_loaded_instance_count(model_payload: Mapping[str, object]) -> int:
    for key in ("loaded_instances", "instances"):
        value = model_payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return len(value)
    return 0


def _extract_loaded_flag(
    model_payload: Mapping[str, object], loaded_instance_count: int
) -> bool | None:
    for key in ("loaded", "is_loaded"):
        if key in model_payload:
            loaded = _safe_bool(model_payload.get(key))
            if loaded is not None:
                return loaded
    for key in ("status", "state"):
        value = _safe_short_string(model_payload.get(key))
        if value is None:
            continue
        normalized = _normalize_key(value)
        if normalized in _SAFE_STATUS_VALUES:
            return normalized in {"loaded", "ready", "active", "idle"}
    if loaded_instance_count > 0:
        return True
    return None


def _attach_candidate_fields(
    record: dict[str, object], *, field_name: str, values: set[int]
) -> None:
    if not values:
        return
    candidates = sorted(values)
    if len(candidates) == 1:
        record[field_name] = candidates[0]
        return
    record[f"{field_name}_candidates"] = candidates


def _build_model_record(
    model_payload: Mapping[str, object], *, model_index: int
) -> dict[str, object]:
    context_candidates: set[int] = set()
    parallel_candidates: set[int] = set()
    _collect_int_candidates(model_payload, _CONTEXT_KEY_ALIASES, context_candidates)
    _collect_int_candidates(model_payload, _PARALLEL_KEY_ALIASES, parallel_candidates)

    loaded_instance_count = _extract_loaded_instance_count(model_payload)
    record: dict[str, object] = {
        "model_id": _extract_model_id(model_payload, model_index),
        "loaded": _extract_loaded_flag(model_payload, loaded_instance_count),
        "loaded_instance_count": loaded_instance_count,
    }
    _attach_candidate_fields(record, field_name="context_length", values=context_candidates)
    _attach_candidate_fields(record, field_name="parallel", values=parallel_candidates)

    capabilities = _extract_capabilities(model_payload)
    if capabilities is not None:
        record["capabilities"] = capabilities
    return record


def _base_summary(
    *,
    target_model_id: str | None,
    target_model_id_safe: bool | None,
    allow_remote: bool,
    is_localhost: bool,
    timeout_s: float,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "probe_kind": "native_models",
        "endpoint_path": MODEL_PROBE_ENDPOINT_PATH,
        "allow_remote": allow_remote,
        "is_localhost": is_localhost,
        "timeout_s": timeout_s,
    }
    if target_model_id_safe is not None:
        summary["target_model_id_safe"] = target_model_id_safe
        summary["target_model_found"] = False
        if target_model_id is not None:
            summary["target_model_id"] = target_model_id
    return summary


def _categorize_transport_error(error: Exception) -> tuple[str, str, int | None]:
    if isinstance(error, urllib_error.HTTPError):
        return "transport_error", "http_error", error.code
    if isinstance(error, urllib_error.URLError):
        if isinstance(error.reason, (socket.timeout, TimeoutError)):
            return "transport_error", "timeout", None
        return "transport_error", "network", None
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "transport_error", "timeout", None
    return "transport_error", "unknown", None


def probe_lmstudio_models(
    base_url: str,
    *,
    target_model_id: str | None = None,
    allow_remote: bool = False,
    timeout_s: float = 10.0,
    transport: ModelProbeTransport | None = None,
) -> ModelProbeResult:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")

    parsed = _normalize_base_url(base_url)
    is_localhost = parsed.hostname.lower() in _LOCALHOST_NAMES
    if not allow_remote and not is_localhost:
        raise ValueError("base_url must stay on localhost unless allow_remote is true")

    safe_target_model_id, target_model_id_safe = _sanitize_target_model_id(target_model_id)

    summary = _base_summary(
        target_model_id=safe_target_model_id,
        target_model_id_safe=target_model_id_safe,
        allow_remote=allow_remote,
        is_localhost=is_localhost,
        timeout_s=timeout_s,
    )
    request = urllib_request.Request(
        build_model_probe_url(base_url),
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
        return ModelProbeResult(summary=summary, model_records=())

    response_text = response_bytes.decode("utf-8", errors="replace")
    summary["response_hash"] = _sha256_text(response_text)
    summary["response_chars"] = len(response_text)

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        summary["status"] = "decode_error"
        summary["error_category"] = "json"
        return ModelProbeResult(summary=summary, model_records=())

    raw_models = _extract_model_list(payload)
    if raw_models is None:
        summary["status"] = "invalid_shape"
        summary["error_category"] = "unknown"
        return ModelProbeResult(summary=summary, model_records=())

    model_records = tuple(
        _build_model_record(model_payload, model_index=index)
        for index, model_payload in enumerate(raw_models, start=1)
        if isinstance(model_payload, Mapping)
    )
    summary["status"] = "ok"
    summary["error_category"] = None
    summary["model_count"] = len(model_records)
    summary["loaded_model_count"] = sum(
        1 for record in model_records if record.get("loaded") is True
    )
    summary["loaded_instance_total"] = sum(
        int(record.get("loaded_instance_count", 0)) for record in model_records
    )
    summary["model_ids"] = [str(record["model_id"]) for record in model_records]

    if safe_target_model_id is not None:
        for record in model_records:
            if record.get("model_id") == safe_target_model_id:
                summary["target_model_found"] = True
                summary["target_model"] = dict(record)
                break

    return ModelProbeResult(summary=summary, model_records=model_records)


def render_model_probe_report(
    *,
    run_id: str,
    summary: Mapping[str, object],
    output_files: Sequence[str] = MODEL_PROBE_RESULT_FILE_NAMES,
) -> str:
    lines = [
        "# LM Studio Model Probe Report",
        "",
        "## Run",
        "",
        "- command: `probe-models`",
        f"- run_id: `{run_id}`",
        f"- endpoint_path: `{summary.get('endpoint_path')}`",
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
    if summary.get("model_count") is not None:
        lines.append(f"- model_count: `{summary.get('model_count')}`")
    if summary.get("loaded_model_count") is not None:
        lines.append(f"- loaded_model_count: `{summary.get('loaded_model_count')}`")
    if summary.get("loaded_instance_total") is not None:
        lines.append(f"- loaded_instance_total: `{summary.get('loaded_instance_total')}`")
    if summary.get("target_model_id_safe") is not None:
        if summary.get("target_model_id") is not None:
            lines.append(f"- target_model_id: `{summary.get('target_model_id')}`")
        lines.append(f"- target_model_id_safe: `{summary.get('target_model_id_safe')}`")
        lines.append(f"- target_model_found: `{summary.get('target_model_found')}`")
    if isinstance(summary.get("model_ids"), Sequence) and not isinstance(
        summary.get("model_ids"), (str, bytes, bytearray)
    ):
        lines.append(
            "- model_ids: `" + ", ".join(str(item) for item in summary.get("model_ids", [])) + "`"
        )

    lines.extend(
        [
            "",
            "## Privacy",
            "",
            "- raw response body: not stored",
            "- raw base URL: not stored",
            "- prompts/chat endpoints: not used",
            "- raw paths/urls/secrets/messages/content: stripped",
            "",
            "## Output Files",
            "",
            *(f"- `{file_name}`" for file_name in output_files),
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "MODEL_PROBE_ENDPOINT_PATH",
    "MODEL_PROBE_RESULT_FILE_NAMES",
    "ModelProbeResult",
    "ModelProbeTransport",
    "build_model_probe_url",
    "is_local_model_probe_base_url",
    "probe_lmstudio_models",
    "render_model_probe_report",
]
