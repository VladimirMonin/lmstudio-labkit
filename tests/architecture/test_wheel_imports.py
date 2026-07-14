from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_built_wheel_imports_managed_lab_and_console_modules_without_source_tree(
    tmp_path: Path,
) -> None:
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = tuple(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0].resolve()
    script = """
import os
import sys

wheel = os.path.realpath(sys.argv[1])
repo = os.path.realpath(sys.argv[2])
blocked = {repo, os.path.join(repo, 'libs'), os.path.join(repo, 'tools')}
sys.path[:] = [wheel] + [
    item for item in sys.path if item and os.path.realpath(item) not in blocked
]
for name in (
    'lmstudio_managed',
    'lmstudio_lab.matrix',
    'lmstudio_lab.system_metrics',
    'lmstudio_lab.report',
    'lmstudio_labkit.cli',
):
    module = __import__(name, fromlist=['*'])
    if wheel not in os.path.realpath(module.__file__):
        raise AssertionError(f'{name} resolved outside the wheel: {module.__file__}')
"""
    imported = subprocess.run(
        [sys.executable, "-c", script, str(wheel), str(PROJECT_ROOT)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert imported.returncode == 0, imported.stdout + imported.stderr
