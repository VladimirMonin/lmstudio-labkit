"""Internal helpers for privacy-safe contract DTOs."""

from __future__ import annotations

from hashlib import sha256

SAFE_HASH_PREFIX = "sha256:"


def safe_hash_ref(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore").strip()
    else:
        text = str(value).strip()
    if not text:
        return None
    if text.startswith(SAFE_HASH_PREFIX) and len(text) > len(SAFE_HASH_PREFIX):
        return text
    return f"{SAFE_HASH_PREFIX}{sha256(text.encode('utf-8')).hexdigest()}"


def safe_text_hash(value: str | None) -> str | None:
    if value is None:
        return None
    return safe_hash_ref(value)


def as_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None
