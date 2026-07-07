from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "libs" / "lmstudio_managed"
FORBIDDEN_TOP_LEVEL_MODULES = {
    "src",
    "PySide6",
    "peewee",
    "transformers",
    "tokenizers",
    "tiktoken",
    "jsonschema",
    "pydantic",
    "fastjsonschema",
    "requests",
    "httpx",
    "urllib",
    "tools",
}
FORBIDDEN_MODULE_PREFIXES = {
    "tools.lmstudio_lab",
}


def _iter_python_files() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if path.is_file())


def _collect_forbidden_imports() -> list[str]:
    offenders: list[str] = []

    for file_path in _iter_python_files():
        module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        relative_path = file_path.relative_to(PROJECT_ROOT).as_posix()

        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    forbidden = _classify_forbidden_module(alias.name)
                    if forbidden is not None:
                        offenders.append(f"{relative_path}:{forbidden}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                forbidden = _classify_forbidden_module(node.module)
                if forbidden is not None:
                    offenders.append(f"{relative_path}:{forbidden}")

    return sorted(offenders)


def _classify_forbidden_module(module_name: str) -> str | None:
    if module_name in FORBIDDEN_MODULE_PREFIXES:
        return module_name

    for prefix in FORBIDDEN_MODULE_PREFIXES:
        if module_name.startswith(f"{prefix}."):
            return prefix

    top_level = module_name.split(".", 1)[0]
    if top_level in FORBIDDEN_TOP_LEVEL_MODULES:
        return top_level

    return None


def test_lmstudio_managed_package_stays_pure_local() -> None:
    offenders = _collect_forbidden_imports()
    assert not offenders, "Forbidden imports in libs/lmstudio_managed:\n" + "\n".join(offenders)
