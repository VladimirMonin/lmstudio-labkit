"""Explicit local-only capture for diagnosing broken LM Studio responses."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


class FailureForensicsError(ValueError):
    """Raised when private failure capture is not safely configured."""


@dataclass(frozen=True, slots=True)
class SSEFrame:
    sequence: int
    received_at: str
    event: str | None
    data: object
    raw_data: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "received_at": self.received_at,
            "event": self.event,
            "data": _json_safe(self.data),
            "raw_data": self.raw_data,
        }


@dataclass(frozen=True, slots=True)
class ForensicsRecordHandle:
    path: Path
    safe_manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class NativeChatDiagnosticResult:
    http_status: int
    content_type: str
    raw_body: bytes
    raw_envelope: Mapping[str, object]
    sse_frames: tuple[SSEFrame, ...]
    reasoning_text: str
    message_text: str
    numeric_stats: dict[str, int | float]
    finish_reason: str | None
    boundary: str
    reasoning_allowed_options: tuple[str, ...] = ()
    reasoning_default: str | None = None
    forensics_handle: ForensicsRecordHandle | None = None


class LocalFailureForensics:
    """Atomic private attempt records kept strictly outside the repository.

    Capture is disabled unless ``enabled=True`` is explicit. Public callers receive
    only a path-free manifest with counters, presence flags, lengths, hashes, and
    parse categories. Raw envelopes and malformed tails remain in the private pack.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        repo_root: str | Path,
        enabled: bool = False,
    ) -> None:
        self.enabled = enabled
        self.repo_root = Path(repo_root).expanduser().resolve(strict=True)
        self.root = Path(root).expanduser()
        if not enabled:
            return
        resolved = self.root.resolve(strict=False)
        self._reject_repo_path(resolved)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        resolved_after_create = self.root.resolve(strict=True)
        self._reject_repo_path(resolved_after_create)
        self.root = resolved_after_create

    def _reject_repo_path(self, resolved: Path) -> None:
        if resolved == self.repo_root or resolved.is_relative_to(self.repo_root):
            raise FailureForensicsError(
                "local failure forensics destination must remain outside the repository"
            )

    def capture_attempt(
        self,
        *,
        request_id: str,
        attempt_index: int,
        context_length: int,
        output_cap: int | None,
        reasoning_mode: str | None,
        started_at: str,
        latency_ms: float,
        http_status: int | None,
        content_type: str | None,
        raw_envelope: object,
        sse_frames: Sequence[SSEFrame | Mapping[str, object]] = (),
        reasoning_text: str = "",
        message_text: str = "",
        finish_reason: str | None = None,
        boundary: str | None = None,
    ) -> ForensicsRecordHandle | None:
        if not self.enabled:
            return None
        if attempt_index < 1:
            raise FailureForensicsError("attempt_index must be positive")
        frame_rows = [
            frame.to_dict() if isinstance(frame, SSEFrame) else _json_safe(frame)
            for frame in sse_frames
        ]
        parse = _json_parse_diagnostics(message_text)
        numeric_stats = _numeric_stats_tree(raw_envelope)
        record = {
            "schema_version": "local-failure-forensics-v1",
            "request": {
                "request_id_hash": _hash_text(request_id),
                "request_id_char_count": len(request_id),
            },
            "attempt": {
                "index": attempt_index,
                "context_length": context_length,
                "output_cap": output_cap,
                "reasoning_mode": reasoning_mode,
                "started_at": started_at,
                "latency_ms": latency_ms,
            },
            "transport": {
                "http_status": http_status,
                "content_type": content_type,
                "boundary": boundary,
            },
            "raw": {
                "envelope": _json_safe(raw_envelope),
                "sse_frames": frame_rows,
                "reasoning": reasoning_text,
                "message": message_text,
            },
            "numeric_stats": numeric_stats,
            "observed": {"finish_reason": finish_reason},
            "json_parse": parse,
            "cleanup": {
                "status": "pending",
                "result": None,
                "final_loaded_instances": None,
            },
        }
        safe_manifest = {
            "attempt_index": attempt_index,
            "context_length": context_length,
            "output_cap": output_cap,
            "reasoning_mode": reasoning_mode,
            "http_status": http_status,
            "content_type": content_type,
            "finish_reason": finish_reason,
            "latency_ms": latency_ms,
            "numeric_stats": numeric_stats,
            "reasoning": _text_presence(reasoning_text),
            "message": _text_presence(message_text),
            "parse": {
                "category": parse["category"],
                "line": parse["line"],
                "column": parse["column"],
                "offset": parse["offset"],
            },
            "private_local_pack_exists": True,
        }
        filename = f"attempt-{attempt_index:04d}-{time.time_ns()}-{uuid.uuid4().hex[:12]}.json"
        path = self.root / filename
        _atomic_private_json(path, record)
        return ForensicsRecordHandle(path=path, safe_manifest=safe_manifest)

    def finalize_attempt(
        self,
        handle: ForensicsRecordHandle | None,
        *,
        cleanup_result: object,
        final_loaded_instances: int | None,
    ) -> None:
        if handle is None or not self.enabled:
            return
        resolved = handle.path.resolve(strict=True)
        if resolved.parent != self.root:
            raise FailureForensicsError("forensics record escaped the private destination")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        payload["cleanup"] = {
            "status": "verified"
            if _cleanup_verified(cleanup_result) and final_loaded_instances == 0
            else "not_verified",
            "result": _json_safe(cleanup_result),
            "final_loaded_instances": final_loaded_instances,
        }
        _atomic_private_json(resolved, payload)

    def safe_manifest_entry(self, handle: ForensicsRecordHandle | None) -> dict[str, object]:
        if handle is None:
            return {"private_local_pack_exists": False}
        return _json_safe(handle.safe_manifest)


def parse_native_chat_response(
    raw_body: bytes,
    *,
    content_type: str,
    http_status: int,
) -> NativeChatDiagnosticResult:
    """Parse native JSON or SSE while retaining the complete diagnostic envelope."""

    text = raw_body.decode("utf-8", errors="replace")
    normalized_type = content_type.split(";", 1)[0].strip().casefold()
    if normalized_type == "text/event-stream":
        frames = _parse_sse_frames(text)
        reasoning_parts: list[str] = []
        message_parts: list[str] = []
        terminal: Mapping[str, object] | None = None
        boundary = "disconnect"
        for frame in frames:
            data = frame.data
            event_type = frame.event
            if isinstance(data, Mapping):
                maybe_type = data.get("type")
                if isinstance(maybe_type, str):
                    event_type = maybe_type
            delta = _event_text_delta(data)
            if event_type in {"reasoning.delta", "reasoning"} and delta is not None:
                reasoning_parts.append(delta)
            elif event_type in {"message.delta", "message"} and delta is not None:
                message_parts.append(delta)
            if event_type == "chat.end" and isinstance(data, Mapping):
                terminal = data
                boundary = "terminal"
            elif event_type in {"error", "chat.error"}:
                boundary = "error"
        terminal_result = (
            terminal.get("result")
            if isinstance(terminal, Mapping) and isinstance(terminal.get("result"), Mapping)
            else terminal
        )
        envelope: Mapping[str, object] = (
            {"result": _json_safe(terminal_result)}
            if isinstance(terminal_result, Mapping)
            else {"result": None}
        )
        finish_reason = _observed_stop_reason(terminal_result)
        numeric_stats = _numeric_stats_tree(terminal_result)
        return NativeChatDiagnosticResult(
            http_status=http_status,
            content_type=content_type,
            raw_body=raw_body,
            raw_envelope=envelope,
            sse_frames=frames,
            reasoning_text="".join(reasoning_parts),
            message_text="".join(message_parts),
            numeric_stats=numeric_stats,
            finish_reason=finish_reason,
            boundary=boundary,
        )

    try:
        decoded = json.loads(text) if text else {}
    except json.JSONDecodeError:
        decoded = {"non_json_body": text}
    envelope = decoded if isinstance(decoded, Mapping) else {"value": decoded}
    reasoning_text, message_text = _native_output_text(envelope)
    return NativeChatDiagnosticResult(
        http_status=http_status,
        content_type=content_type,
        raw_body=raw_body,
        raw_envelope=envelope,
        sse_frames=(),
        reasoning_text=reasoning_text,
        message_text=message_text,
        numeric_stats=_numeric_stats_tree(envelope),
        finish_reason=_observed_stop_reason(envelope),
        boundary="terminal" if http_status < 400 else "error",
    )


def _parse_sse_frames(text: str) -> tuple[SSEFrame, ...]:
    frames: list[SSEFrame] = []
    event: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event, data_lines
        if event is None and not data_lines:
            return
        raw_data = "\n".join(data_lines)
        try:
            data: object = json.loads(raw_data) if raw_data else None
        except json.JSONDecodeError:
            data = raw_data
        frames.append(
            SSEFrame(
                sequence=len(frames) + 1,
                received_at=_utc_now(),
                event=event,
                data=data,
                raw_data=raw_data,
            )
        )
        event = None
        data_lines = []

    for line in text.splitlines():
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)
    flush()
    return tuple(frames)


def _event_text_delta(data: object) -> str | None:
    if isinstance(data, str):
        return data
    if not isinstance(data, Mapping):
        return None
    for key in ("delta", "content", "text"):
        value = data.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            nested = value.get("content", value.get("text"))
            if isinstance(nested, str):
                return nested
    return None


def _native_output_text(payload: Mapping[str, object]) -> tuple[str, str]:
    reasoning: list[str] = []
    message: list[str] = []
    output = payload.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes, bytearray)):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            kind = item.get("type")
            text = _event_text_delta(item)
            if text is None:
                continue
            if kind == "reasoning":
                reasoning.append(text)
            elif kind == "message":
                message.append(text)
    direct_reasoning = payload.get("reasoning")
    direct_message = payload.get("message")
    if isinstance(direct_reasoning, str):
        reasoning.append(direct_reasoning)
    if isinstance(direct_message, str):
        message.append(direct_message)
    return "".join(reasoning), "".join(message)


def _observed_stop_reason(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("finish_reason", "stop_reason", "reason"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _json_parse_diagnostics(text: str) -> dict[str, object]:
    if not text:
        return {
            "category": "empty",
            "line": None,
            "column": None,
            "offset": None,
            "malformed_tail": "",
        }
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        return {
            "category": "not_json",
            "line": error.lineno,
            "column": error.colno,
            "offset": error.pos,
            "malformed_tail": text[max(0, error.pos - 64) :],
        }
    return {
        "category": "valid_json",
        "line": None,
        "column": None,
        "offset": None,
        "malformed_tail": "",
    }


def _numeric_stats_tree(value: object) -> dict[str, int | float]:
    output: dict[str, int | float] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"stats", "usage"} and isinstance(item, Mapping):
                output.update(_numeric_leaf_paths(item, key_text))
            elif isinstance(item, Mapping | Sequence) and not isinstance(
                item, (str, bytes, bytearray)
            ):
                output.update(_numeric_stats_tree(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            output.update(_numeric_stats_tree(item))
    return dict(sorted(output.items()))


def _numeric_leaf_paths(value: object, prefix: str = "") -> dict[str, int | float]:
    output: dict[str, int | float] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            output.update(_numeric_leaf_paths(item, child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            child = f"{prefix}[{index}]"
            output.update(_numeric_leaf_paths(item, child))
    elif isinstance(value, int | float) and not isinstance(value, bool) and prefix:
        output[prefix] = value
    return dict(sorted(output.items()))


def _text_presence(text: str) -> dict[str, object]:
    return {
        "present": bool(text),
        "char_count": len(text),
        "sha256": _hash_text(text),
    }


def _hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _cleanup_verified(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        return value.get("cleanup_verified") is True
    return False


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_json_safe(item) for item in value]
    return repr(value)


def _atomic_private_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "FailureForensicsError",
    "ForensicsRecordHandle",
    "LocalFailureForensics",
    "NativeChatDiagnosticResult",
    "SSEFrame",
    "parse_native_chat_response",
]
