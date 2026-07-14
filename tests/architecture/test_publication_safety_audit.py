from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("private_value", "expected_label"),
    (
        ("/home/other-user/models/file.gguf", "generic POSIX user profile path"),
        ("/Users/other-user/models/file.gguf", "generic POSIX user profile path"),
        ("/srv/private-user/models/file.gguf", "generic private POSIX root"),
        ("/mnt/private-user/models/file.gguf", "generic private POSIX root"),
        (r"C:\Users\private-user\models\file.gguf", "Windows user profile path"),
    ),
)
def test_publication_audit_rejects_generic_private_paths(
    tmp_path: Path,
    private_value: str,
    expected_label: str,
) -> None:
    source_script = Path(__file__).parents[2] / "scripts/audit_publication_safety.py"
    script = tmp_path / "scripts/audit_publication_safety.py"
    script.parent.mkdir()
    shutil.copyfile(source_script, script)
    fixture = tmp_path / "docs/sample.md"
    fixture.parent.mkdir()
    fixture.write_text(private_value, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert expected_label in result.stdout


def test_publication_audit_allows_public_repository_artifact_identity(tmp_path: Path) -> None:
    source_script = Path(__file__).parents[2] / "scripts/audit_publication_safety.py"
    script = tmp_path / "scripts/audit_publication_safety.py"
    script.parent.mkdir()
    shutil.copyfile(source_script, script)
    fixture = tmp_path / "docs/sample.md"
    fixture.parent.mkdir()
    fixture.write_text("publisher/model/file.gguf", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Publication safety audit passed." in result.stdout
