from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".txt", ".py", ".toml", ".yaml", ".yml", ".json", ".csv", ".rst"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
PATTERNS = [
    ("source product full name", re.compile(r"Whisper\s+Voice\s+Machine", re.I)),
    ("source product abbreviation", re.compile(r"\bWVM\b|\bVWM\b", re.I)),
    ("private marketplace/support keyword", re.compile(r"skladchik|складчик", re.I)),
    (
        "build-protection keyword",
        re.compile(r"pyarmor|obfuscat|обфускац|anti[- ]?tamper|protected runtime", re.I),
    ),
    (
        "secret-looking token",
        re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"][^'\"]+['\"]"),
    ),
    ("private home path", re.compile(r"/home/v/(Syncthing|\.hermes|code/Whisper-Voice-Machine)")),
    (
        "generic POSIX user profile path",
        re.compile(r"/(?:home/(?!v(?:/|$))|Users/)[^/\s]+(?:/[^\s`'\"]+)+"),
    ),
    (
        "generic private POSIX root",
        re.compile(r"/(?:srv|mnt)/[^\s`'\"]+(?:/[^\s`'\"]+)+"),
    ),
    (
        "Windows user profile path",
        re.compile(r"(?i)\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\\/\s]+"),
    ),
]
ALLOWLIST = {
    "scripts/audit_publication_safety.py",
    "instructions/SEC.publication_safety.instructions.md",
    "AGENTS.MD",
}
PATH_FIXTURE_ALLOWLIST = {
    "tests/architecture/test_publication_safety_audit.py",
    "tests/lmstudio_labkit/test_privacy_scanner.py",
    "tests/tools/test_lmstudio_lab_memory_recommendations.py",
    "tests/tools/test_lmstudio_lab_metrics.py",
    "tests/tools/test_lmstudio_lab_model_probe.py",
}
PATH_LABELS = {
    "generic POSIX user profile path",
    "generic private POSIX root",
    "Windows user profile path",
}


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT).parts
    for part in rel:
        if part in SKIP_DIRS:
            return True
    return False


failures = []
for path in ROOT.rglob("*"):
    if should_skip(path) or not path.is_file():
        continue
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"AGENTS.MD", "AGENTS.md"}:
        continue
    rel = path.relative_to(ROOT).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    for label, pattern in PATTERNS:
        allow_terms = {
            "source product full name",
            "source product abbreviation",
            "private marketplace/support keyword",
            "build-protection keyword",
            "private home path",
        }
        if rel in ALLOWLIST and label in allow_terms:
            continue
        if (
            rel in PATH_FIXTURE_ALLOWLIST
            or rel.startswith("tests/")
            or rel == "tools/lmstudio_lab/private_benchmark_pack.py"
        ) and label in PATH_LABELS:
            continue
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            failures.append(f"{rel}:{line}: {label}: {match.group(0)[:80]}")

if failures:
    print("Publication safety audit failed:")
    print("\n".join(failures[:200]))
    if len(failures) > 200:
        print(f"... {len(failures) - 200} more")
    sys.exit(1)
print("Publication safety audit passed.")
