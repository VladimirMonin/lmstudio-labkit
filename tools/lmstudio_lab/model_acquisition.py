from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urlsplit, urlunsplit

import yaml

from .model_probe import (
    _LOCALHOST_NAMES,
    _normalize_base_url,
    _safe_float,
    _safe_int,
    _safe_model_id,
    _sha256_text,
)

logger = logging.getLogger(__name__)

type ModelAcquisitionTransport = Callable[[urllib_request.Request, float], bytes]
type SleepFunc = Callable[[float], None]

MODEL_ACQUISITION_ENDPOINT_PATH = "/api/v1/models/download"
MODEL_ACQUISITION_STATUS_ENDPOINT_TEMPLATE = "/api/v1/models/download/status/:job_id"
MODEL_ACQUISITION_ENDPOINT_KIND = "download"
MODEL_ACQUISITION_STATUS_ENDPOINT_KIND = "download_status"
MODEL_ACQUISITION_RESULT_FILE_NAMES = (
    "environment.json",
    "model_acquisition.json",
    "download_status.jsonl",
    "report.md",
)

_ALLOWED_DOWNLOAD_STATUSES = frozenset(
    {"downloading", "paused", "completed", "failed", "already_downloaded"}
)
_SAFE_LAB_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
_SAFE_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SAFE_QUANTIZATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class ModelAcquisitionResult:
    summary: dict[str, object]
    status_records: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class _DownloadPlan:
    request_payload: dict[str, str]
    download_model_ref_hash: str
    download_model_ref_kind: str
    source_id_hash: str | None
    quantization: str | None


def _default_transport(request: urllib_request.Request, timeout_s: float) -> bytes:
    with urllib_request.urlopen(request, timeout=timeout_s) as response:
        return response.read()


def _safe_lab_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _SAFE_LAB_KEY_RE.fullmatch(text) is None:
        return None
    return text


def _safe_api_token_env(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("api_token_env must be a safe environment variable name")
    text = value.strip()
    if _SAFE_ENV_VAR_RE.fullmatch(text) is None:
        raise ValueError("api_token_env must be a safe environment variable name")
    return text


def _require_positive_float(value: object, *, field_name: str) -> float:
    float_value = _safe_float(value)
    if float_value is None or float_value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return float_value


def _require_positive_int(value: object, *, field_name: str) -> int:
    int_value = _safe_int(value)
    if int_value is None or int_value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return int_value


def _safe_non_negative_int(value: object) -> int | None:
    int_value = _safe_int(value)
    if int_value is None or int_value < 0:
        return None
    return int_value


def _safe_non_negative_float(value: object) -> float | None:
    float_value = _safe_float(value)
    if float_value is None or float_value < 0:
        return None
    return float_value


def is_local_model_acquisition_base_url(base_url: str) -> bool:
    return _normalize_base_url(base_url).hostname.lower() in _LOCALHOST_NAMES


def build_model_acquisition_url(base_url: str) -> str:
    parsed = _normalize_base_url(base_url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, MODEL_ACQUISITION_ENDPOINT_PATH, "", "")
    )


def build_model_acquisition_status_url(base_url: str, job_id: str) -> str:
    parsed = _normalize_base_url(base_url)
    safe_job_id = quote(job_id, safe="")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            f"/api/v1/models/download/status/{safe_job_id}",
            "",
            "",
        )
    )


def _base_summary(
    *,
    lab_key: str,
    allow_remote: bool,
    is_localhost: bool,
    timeout_s: float,
    execute_download: bool,
    poll_enabled: bool,
    api_token_present: bool,
) -> dict[str, object]:
    endpoint_kinds_planned = [MODEL_ACQUISITION_ENDPOINT_KIND]
    if poll_enabled:
        endpoint_kinds_planned.append(MODEL_ACQUISITION_STATUS_ENDPOINT_KIND)
    return {
        "probe_kind": "model_acquisition",
        "lab_key": lab_key,
        "allow_remote": allow_remote,
        "is_localhost": is_localhost,
        "timeout_s": timeout_s,
        "execute_download": execute_download,
        "poll_enabled": poll_enabled,
        "endpoint_kinds_planned": endpoint_kinds_planned,
        "endpoint_kinds_used": [],
        "registry_written": False,
        "load_called": False,
        "generation_called": False,
        "candidate_found": False,
        "download_request_planned": False,
        "quantization_verified": False,
        "native_key_verified": False,
        "api_token_present": api_token_present,
    }


def _load_registry_candidate(registry_path: Path, *, lab_key: str) -> Mapping[str, object] | None:
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("registry payload must be a mapping")
    candidates = payload.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes, bytearray)):
        raise ValueError("registry candidates must be a sequence")
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("registry candidates must contain only mappings")
        if _safe_lab_key(candidate.get("lab_key")) == lab_key:
            return candidate
    return None


def _derive_quantization_from_filename(filename: str) -> str | None:
    if not filename or "." not in filename:
        return None
    stem = filename.rsplit(".", 1)[0]
    if "-" not in stem:
        return None
    candidate = stem.rsplit("-", 1)[-1]
    if not candidate:
        return None
    normalized = candidate.upper()
    if not normalized.startswith(("Q", "IQ")):
        return None
    if _SAFE_QUANTIZATION_RE.fullmatch(candidate) is None:
        return None
    return candidate


def _build_hf_repo_plan_from_source(source_id: str) -> _DownloadPlan:
    source_id_hash = _sha256_text(source_id)
    if "://" in source_id:
        parsed = urlsplit(source_id.strip())
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.netloc.lower() != "huggingface.co"
        ):
            raise ValueError("source_id must use a supported Hugging Face shape")
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 2:
            raise ValueError("source_id must include a Hugging Face owner and repo")
        repo_url = f"https://huggingface.co/{segments[0]}/{segments[1]}"
        filename = segments[-1] if segments and segments[-1].lower().endswith(".gguf") else ""
        quantization = _derive_quantization_from_filename(filename)
    else:
        segments = [segment.strip() for segment in re.split(r"[\\/]", source_id) if segment.strip()]
        if len(segments) < 3:
            raise ValueError("source_id must include owner/repo/file.gguf")
        filename = segments[-1]
        if not filename.lower().endswith(".gguf"):
            raise ValueError("source_id must end with a GGUF filename")
        repo_url = f"https://huggingface.co/{segments[0]}/{segments[1]}"
        quantization = _derive_quantization_from_filename(filename)

    request_payload = {"model": repo_url}
    if quantization is not None:
        request_payload["quantization"] = quantization
    return _DownloadPlan(
        request_payload=request_payload,
        download_model_ref_hash=_sha256_text(repo_url),
        download_model_ref_kind="huggingface_repo",
        source_id_hash=source_id_hash,
        quantization=quantization,
    )


def _build_download_plan(candidate: Mapping[str, object]) -> _DownloadPlan:
    raw_source_id = candidate.get("source_id")
    if isinstance(raw_source_id, str) and raw_source_id.strip():
        return _build_hf_repo_plan_from_source(raw_source_id.strip())

    compat_model_id = _safe_model_id(candidate.get("compat_model_id"))
    if compat_model_id is not None:
        return _DownloadPlan(
            request_payload={"model": compat_model_id},
            download_model_ref_hash=_sha256_text(compat_model_id),
            download_model_ref_kind="compat_catalog_fallback",
            source_id_hash=None,
            quantization=None,
        )
    raise ValueError("candidate does not provide a supported download source")


def _categorize_transport_error(error: Exception) -> tuple[str, str, int | None]:
    if isinstance(error, urllib_error.HTTPError):
        if error.code in {401, 403}:
            return "transport_error", "auth_required", error.code
        if error.code == 404:
            return "transport_error", "not_found", error.code
        return "transport_error", "http_error", error.code
    if isinstance(error, urllib_error.URLError):
        if isinstance(error.reason, (socket.timeout, TimeoutError)):
            return "transport_error", "timeout", None
        return "transport_error", "network", None
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "transport_error", "timeout", None
    return "transport_error", "unknown", None


def _safe_status_payload(payload: object) -> tuple[dict[str, object], str | None, str | None]:
    if not isinstance(payload, Mapping):
        raise ValueError("shape")
    raw_status = payload.get("status")
    if not isinstance(raw_status, str) or raw_status not in _ALLOWED_DOWNLOAD_STATUSES:
        raise ValueError("status")

    record: dict[str, object] = {"download_status": raw_status}
    job_id = payload.get("job_id") if isinstance(payload.get("job_id"), str) else None
    if job_id:
        record["job_id_hash"] = _sha256_text(job_id)
    total_size_bytes = _safe_non_negative_int(payload.get("total_size_bytes"))
    if total_size_bytes is not None:
        record["total_size_bytes"] = total_size_bytes
    downloaded_bytes = _safe_non_negative_int(payload.get("downloaded_bytes"))
    if downloaded_bytes is not None:
        record["downloaded_bytes"] = downloaded_bytes
    bytes_per_second = _safe_non_negative_float(payload.get("bytes_per_second"))
    if bytes_per_second is not None:
        record["bytes_per_second"] = bytes_per_second
    if total_size_bytes and downloaded_bytes is not None:
        progress_percent = round(min(downloaded_bytes / total_size_bytes, 1.0) * 100.0, 2)
        record["progress_percent"] = progress_percent
    return record, raw_status, job_id


def _request_headers(*, api_token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    if api_token is not None:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def _append_endpoint_kind(summary: dict[str, object], endpoint_kind: str) -> None:
    endpoint_kinds_used = summary.setdefault("endpoint_kinds_used", [])
    if isinstance(endpoint_kinds_used, list):
        endpoint_kinds_used.append(endpoint_kind)


def _execute_request(
    *,
    request: urllib_request.Request,
    timeout_s: float,
    transport: ModelAcquisitionTransport,
) -> tuple[dict[str, object], str | None, str | None]:
    response_bytes = transport(request, timeout_s)
    response_text = response_bytes.decode("utf-8", errors="replace")
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ValueError("json") from error
    return _safe_status_payload(payload)


def _speed_mbps_from_record(record: Mapping[str, object]) -> float | None:
    bytes_per_second = _safe_non_negative_float(record.get("bytes_per_second"))
    if bytes_per_second is None:
        return None
    return round((bytes_per_second * 8.0) / 1_000_000.0, 4)


def _log_plan_built(
    *,
    lab_key: str,
    execute_download: bool,
    poll_enabled: bool,
    api_token_present: bool,
    download_model_ref_kind: str,
    quantization: str | None,
) -> None:
    logger.info(
        "model acquisition plan built lab_key=%s execute_download=%s poll_enabled=%s api_token_present=%s download_model_ref_kind=%s quantization=%s",
        lab_key,
        execute_download,
        poll_enabled,
        api_token_present,
        download_model_ref_kind,
        quantization,
    )


def _log_download_status_received(
    *,
    lab_key: str,
    download_status: object,
    progress_percent: object,
    bytes_per_second: object,
    poll_index: int | None,
) -> None:
    speed_mbps = _speed_mbps_from_record({"bytes_per_second": bytes_per_second})
    if poll_index is None:
        logger.info(
            "model acquisition POST status received lab_key=%s status=%s progress_percent=%s speed_mbps=%s",
            lab_key,
            download_status,
            progress_percent,
            speed_mbps,
        )
        return
    logger.info(
        "model acquisition poll status received lab_key=%s status=%s progress_percent=%s speed_mbps=%s poll_index=%s",
        lab_key,
        download_status,
        progress_percent,
        speed_mbps,
        poll_index,
    )


def _log_terminal_state(summary: Mapping[str, object], *, warning: bool) -> None:
    log_method = logger.warning if warning else logger.info
    log_method(
        "model acquisition terminal state lab_key=%s status=%s download_status=%s ready_on_disk=%s error_category=%s http_status=%s",
        summary.get("lab_key"),
        summary.get("status"),
        summary.get("download_status"),
        summary.get("ready_on_disk"),
        summary.get("error_category"),
        summary.get("http_status"),
    )


def acquire_candidate_model(
    base_url: str,
    *,
    registry_path: str | Path,
    lab_key: str,
    allow_remote: bool = False,
    timeout_s: float = 10.0,
    api_token_env: str = "LM_API_TOKEN",
    execute_download: bool = False,
    poll: bool = False,
    max_polls: int = 60,
    poll_interval_s: float = 1.0,
    transport: ModelAcquisitionTransport | None = None,
    sleep: SleepFunc | None = None,
) -> ModelAcquisitionResult:
    safe_lab_key = _safe_lab_key(lab_key)
    if safe_lab_key is None:
        raise ValueError("lab_key must use a safe lab identifier")
    request_timeout_s = _require_positive_float(timeout_s, field_name="timeout_s")
    safe_api_token_env = _safe_api_token_env(api_token_env)
    if poll and not execute_download:
        raise ValueError("poll requires execute_download")
    safe_max_polls = _require_positive_int(max_polls, field_name="max_polls")
    safe_poll_interval_s = _require_positive_float(
        poll_interval_s,
        field_name="poll_interval_s",
    )

    parsed = _normalize_base_url(base_url)
    is_localhost = parsed.hostname.lower() in _LOCALHOST_NAMES
    if not allow_remote and not is_localhost:
        raise ValueError("base_url must stay on localhost unless allow_remote is true")

    api_token = os.getenv(safe_api_token_env)
    api_token = api_token.strip() if isinstance(api_token, str) else None
    if not api_token:
        api_token = None
    api_token_present = api_token is not None

    summary = _base_summary(
        lab_key=safe_lab_key,
        allow_remote=allow_remote,
        is_localhost=is_localhost,
        timeout_s=request_timeout_s,
        execute_download=execute_download,
        poll_enabled=poll,
        api_token_present=api_token_present,
    )
    status_records: list[dict[str, object]] = []

    try:
        candidate = _load_registry_candidate(Path(registry_path), lab_key=safe_lab_key)
    except (OSError, yaml.YAMLError, ValueError):
        summary["status"] = "validation_error"
        summary["error_category"] = "validation"
        _log_terminal_state(summary, warning=True)
        return ModelAcquisitionResult(summary=summary, status_records=())

    if candidate is None:
        summary["status"] = "validation_error"
        summary["error_category"] = "candidate"
        _log_terminal_state(summary, warning=True)
        return ModelAcquisitionResult(summary=summary, status_records=())

    summary["candidate_found"] = True
    try:
        plan = _build_download_plan(candidate)
    except ValueError:
        summary["status"] = "validation_error"
        summary["error_category"] = "validation"
        _log_terminal_state(summary, warning=True)
        return ModelAcquisitionResult(summary=summary, status_records=())

    summary["download_request_planned"] = True
    summary["download_model_ref_kind"] = plan.download_model_ref_kind
    summary["download_model_ref_hash"] = plan.download_model_ref_hash
    summary["quantization"] = plan.quantization
    if plan.source_id_hash is not None:
        summary["source_id_hash"] = plan.source_id_hash
    _log_plan_built(
        lab_key=safe_lab_key,
        execute_download=execute_download,
        poll_enabled=poll,
        api_token_present=api_token_present,
        download_model_ref_kind=plan.download_model_ref_kind,
        quantization=plan.quantization,
    )

    if not execute_download:
        summary["status"] = "planned"
        summary["error_category"] = None
        summary["download_status"] = "planned"
        logger.info(
            "model acquisition dry-run planned lab_key=%s execute_download=%s poll_enabled=%s api_token_present=%s download_model_ref_kind=%s quantization=%s status=%s",
            safe_lab_key,
            execute_download,
            poll,
            api_token_present,
            plan.download_model_ref_kind,
            plan.quantization,
            summary["status"],
        )
        _log_terminal_state(summary, warning=False)
        return ModelAcquisitionResult(summary=summary, status_records=())

    effective_transport = transport or _default_transport
    request_body = json.dumps(
        plan.request_payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    request = urllib_request.Request(
        build_model_acquisition_url(base_url),
        data=request_body,
        method="POST",
        headers=_request_headers(api_token=api_token),
    )

    try:
        safe_record, download_status, job_id = _execute_request(
            request=request,
            timeout_s=request_timeout_s,
            transport=effective_transport,
        )
    except Exception as error:
        if (
            isinstance(error, ValueError)
            and error.args
            and error.args[0] in {"json", "shape", "status"}
        ):
            summary["status"] = "decode_error" if error.args[0] == "json" else "invalid_shape"
            summary["error_category"] = "json" if error.args[0] == "json" else str(error.args[0])
            _log_terminal_state(summary, warning=True)
            return ModelAcquisitionResult(summary=summary, status_records=())
        status, error_category, http_status = _categorize_transport_error(error)
        summary["status"] = status
        summary["error_category"] = error_category
        if http_status is not None:
            summary["http_status"] = http_status
        _log_terminal_state(summary, warning=True)
        return ModelAcquisitionResult(summary=summary, status_records=())

    _append_endpoint_kind(summary, MODEL_ACQUISITION_ENDPOINT_KIND)
    summary.update(safe_record)
    _log_download_status_received(
        lab_key=safe_lab_key,
        download_status=safe_record.get("download_status"),
        progress_percent=safe_record.get("progress_percent"),
        bytes_per_second=safe_record.get("bytes_per_second"),
        poll_index=None,
    )
    status_records.append(
        {
            "endpoint_kind": MODEL_ACQUISITION_ENDPOINT_KIND,
            "phase": "download",
            **safe_record,
        }
    )

    if download_status == "failed":
        summary["status"] = "download_failed"
        summary["error_category"] = "download_failed"
        _log_terminal_state(summary, warning=True)
        return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))
    if download_status in {"already_downloaded", "completed"}:
        summary["status"] = "ok"
        summary["error_category"] = None
        summary["ready_on_disk"] = True
        _log_terminal_state(summary, warning=False)
        return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))
    if not poll or not job_id:
        summary["status"] = "ok"
        summary["error_category"] = None
        summary["ready_on_disk"] = False
        _log_terminal_state(summary, warning=False)
        return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))

    sleeper = sleep or time.sleep
    for poll_index in range(1, safe_max_polls + 1):
        sleeper(safe_poll_interval_s)
        poll_request = urllib_request.Request(
            build_model_acquisition_status_url(base_url, job_id),
            method="GET",
            headers=_request_headers(api_token=api_token),
        )
        try:
            safe_record, download_status, _ = _execute_request(
                request=poll_request,
                timeout_s=request_timeout_s,
                transport=effective_transport,
            )
        except Exception as error:
            if (
                isinstance(error, ValueError)
                and error.args
                and error.args[0] in {"json", "shape", "status"}
            ):
                summary["status"] = "decode_error" if error.args[0] == "json" else "invalid_shape"
                summary["error_category"] = (
                    "json" if error.args[0] == "json" else str(error.args[0])
                )
                _log_terminal_state(summary, warning=True)
                return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))
            status, error_category, http_status = _categorize_transport_error(error)
            summary["status"] = status
            summary["error_category"] = error_category
            if http_status is not None:
                summary["http_status"] = http_status
            _log_terminal_state(summary, warning=True)
            return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))

        summary.update(safe_record)
        _append_endpoint_kind(summary, MODEL_ACQUISITION_STATUS_ENDPOINT_KIND)
        _log_download_status_received(
            lab_key=safe_lab_key,
            download_status=safe_record.get("download_status"),
            progress_percent=safe_record.get("progress_percent"),
            bytes_per_second=safe_record.get("bytes_per_second"),
            poll_index=poll_index,
        )
        status_records.append(
            {
                "endpoint_kind": MODEL_ACQUISITION_STATUS_ENDPOINT_KIND,
                "phase": "poll",
                "poll_index": poll_index,
                **safe_record,
            }
        )
        if download_status == "completed":
            summary["status"] = "ok"
            summary["error_category"] = None
            summary["ready_on_disk"] = True
            _log_terminal_state(summary, warning=False)
            return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))
        if download_status == "failed":
            summary["status"] = "download_failed"
            summary["error_category"] = "download_failed"
            _log_terminal_state(summary, warning=True)
            return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))

    summary["status"] = "poll_exhausted"
    summary["error_category"] = "poll_limit"
    summary["ready_on_disk"] = False
    _log_terminal_state(summary, warning=True)
    return ModelAcquisitionResult(summary=summary, status_records=tuple(status_records))


def render_model_acquisition_report(
    *,
    run_id: str,
    summary: Mapping[str, object],
    output_files: Sequence[str] = MODEL_ACQUISITION_RESULT_FILE_NAMES,
) -> str:
    lines = [
        "# LM Studio Model Acquisition Report",
        "",
        "## Run",
        "",
        "- command: `acquire-candidate`",
        f"- run_id: `{run_id}`",
        f"- lab_key: `{summary.get('lab_key')}`",
        f"- execute_download: `{str(bool(summary.get('execute_download'))).lower()}`",
        f"- poll_enabled: `{str(bool(summary.get('poll_enabled'))).lower()}`",
        f"- allow_remote: `{str(bool(summary.get('allow_remote'))).lower()}`",
        f"- is_localhost: `{str(bool(summary.get('is_localhost'))).lower()}`",
        f"- timeout_s: `{summary.get('timeout_s')}`",
        f"- endpoint_kinds_planned: `{summary.get('endpoint_kinds_planned')}`",
        f"- endpoint_kinds_used: `{summary.get('endpoint_kinds_used')}`",
        "",
        "## Result",
        "",
        f"- status: `{summary.get('status')}`",
        f"- error_category: `{summary.get('error_category')}`",
        f"- candidate_found: `{summary.get('candidate_found')}`",
        f"- download_request_planned: `{summary.get('download_request_planned')}`",
        f"- download_model_ref_kind: `{summary.get('download_model_ref_kind')}`",
        f"- download_model_ref_hash: `{summary.get('download_model_ref_hash')}`",
        f"- source_id_hash: `{summary.get('source_id_hash')}`",
        f"- quantization: `{summary.get('quantization')}`",
        f"- quantization_verified: `{summary.get('quantization_verified')}`",
        f"- native_key_verified: `{summary.get('native_key_verified')}`",
        f"- download_status: `{summary.get('download_status')}`",
        f"- job_id_hash: `{summary.get('job_id_hash')}`",
        f"- progress_percent: `{summary.get('progress_percent')}`",
        f"- downloaded_bytes: `{summary.get('downloaded_bytes')}`",
        f"- total_size_bytes: `{summary.get('total_size_bytes')}`",
        f"- bytes_per_second: `{summary.get('bytes_per_second')}`",
        f"- api_token_present: `{summary.get('api_token_present')}`",
        "",
        "## Policy",
        "",
        "- dry-run does not call network",
        "- execute mode uses endpoint kind `download` only",
        "- optional polling uses endpoint kind `download_status` only",
        "- no load/unload/generation",
        "- registry not written",
        "- quant/native key not verified by compat-only download plan",
        "",
        "## Output Files",
        "",
        *(f"- `{file_name}`" for file_name in output_files),
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "MODEL_ACQUISITION_ENDPOINT_PATH",
    "MODEL_ACQUISITION_RESULT_FILE_NAMES",
    "MODEL_ACQUISITION_STATUS_ENDPOINT_TEMPLATE",
    "ModelAcquisitionResult",
    "ModelAcquisitionTransport",
    "acquire_candidate_model",
    "build_model_acquisition_status_url",
    "build_model_acquisition_url",
    "is_local_model_acquisition_base_url",
    "render_model_acquisition_report",
]
