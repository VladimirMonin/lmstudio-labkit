from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DENYLIST = ("private app name",)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("raw_prompt_key", re.compile(r'"raw_prompt"\s*:')),
    ("raw_response_key", re.compile(r'"raw_response"\s*:')),
    ("localhost_url", re.compile(r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?", re.I)),
    ("home_path", re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+/")),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\\\Users\\\\[^\\\\]+\\\\")),
    (
        "secret_assignment",
        re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"][^'\"]+['\"]"),
    ),
)
_HASH_RE = re.compile(r"^(sha256:)?[a-f0-9]{64}$", re.I)


@dataclass(frozen=True, slots=True)
class PrivacyViolation:
    artifact: str
    category: str
    line: int
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "category": self.category,
            "line": self.line,
            "evidence_hash": self.evidence_hash,
        }


def scan_text(
    text: str,
    *,
    artifact_name: str = "<memory>",
    denylist: tuple[str, ...] = DEFAULT_DENYLIST,
) -> list[PrivacyViolation]:
    from .requests import stable_hash

    violations: list[PrivacyViolation] = []
    for category, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            if _HASH_RE.match(value.strip('"')):
                continue
            line = text.count("\n", 0, match.start()) + 1
            violations.append(
                PrivacyViolation(artifact_name, category, line, stable_hash(value)[:16])
            )
    lowered = text.lower()
    for item in denylist:
        if not item:
            continue
        index = lowered.find(item.lower())
        if index >= 0:
            violations.append(
                PrivacyViolation(
                    artifact_name,
                    "denylist_term",
                    text.count("\n", 0, index) + 1,
                    stable_hash(item)[:16],
                )
            )
    return violations


def scan_artifact_files(
    paths: list[Path] | tuple[Path, ...],
    *,
    denylist: tuple[str, ...] = DEFAULT_DENYLIST,
) -> dict[str, Any]:
    violations: list[PrivacyViolation] = []
    scanned: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        scanned.append(path.name)
        text = path.read_text(encoding="utf-8")
        violations.extend(scan_text(text, artifact_name=path.name, denylist=denylist))
    return {
        "status": "pass" if not violations else "fail",
        "policy": "artifact-privacy-v1",
        "scanned_artifacts": scanned,
        "violation_count": len(violations),
        "violations": [item.to_dict() for item in violations],
    }


def assert_privacy_scan_passed(scan: dict[str, Any]) -> None:
    if scan.get("status") != "pass":
        raise ValueError(json.dumps(scan, sort_keys=True))


__all__ = ["PrivacyViolation", "assert_privacy_scan_passed", "scan_artifact_files", "scan_text"]
