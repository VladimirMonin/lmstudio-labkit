from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from lmstudio_labkit import (
    FailureForensicsError,
    LocalFailureForensics,
    parse_native_chat_response,
)


def _capture(forensics: LocalFailureForensics, *, attempt_index: int, message: str) -> Any:
    return forensics.capture_attempt(
        request_id="cell-private",
        attempt_index=attempt_index,
        context_length=8192,
        output_cap=1024 * attempt_index,
        reasoning_mode="off",
        started_at="2026-07-10T00:00:00Z",
        latency_ms=12.5,
        http_status=200,
        content_type="application/json",
        raw_envelope={
            "output": [{"type": "message", "content": message}],
            "stats": {"total_output_tokens": 7, "nested": {"float": 1.5}},
        },
        reasoning_text="private reasoning",
        message_text=message,
        finish_reason="length",
    )


def test_private_forensics_rejects_repo_and_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(FailureForensicsError, match="outside the repository"):
        LocalFailureForensics(repo / "private", repo_root=repo, enabled=True)

    external = tmp_path / "external"
    external.mkdir()
    link = external / "repo-link"
    try:
        link.symlink_to(repo, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(FailureForensicsError, match="outside the repository"):
        LocalFailureForensics(link / "private", repo_root=repo, enabled=True)


def test_private_forensics_writes_private_atomic_records_and_retains_attempts(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "private-pack"
    forensics = LocalFailureForensics(root, repo_root=repo, enabled=True)

    first = _capture(forensics, attempt_index=1, message='{"id":')
    second = _capture(forensics, attempt_index=2, message='{"id":"ok"}')
    forensics.finalize_attempt(
        first, cleanup_result={"cleanup_verified": True}, final_loaded_instances=0
    )
    forensics.finalize_attempt(
        second, cleanup_result={"cleanup_verified": True}, final_loaded_instances=0
    )

    files = sorted(root.glob("attempt-*.json"))
    assert len(files) == 2
    assert not list(root.glob(".*.tmp-*"))
    assert os.stat(root).st_mode & 0o777 == 0o700
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in files)
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    assert [item["attempt"]["index"] for item in payloads] == [1, 2]
    assert payloads[0]["raw"]["message"] == '{"id":'
    assert payloads[0]["numeric_stats"] == {
        "stats.nested.float": 1.5,
        "stats.total_output_tokens": 7,
    }
    assert payloads[0]["cleanup"]["final_loaded_instances"] == 0


def test_public_manifest_is_path_free_and_raw_free(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    forensics = LocalFailureForensics(tmp_path / "private", repo_root=repo, enabled=True)

    handle = _capture(forensics, attempt_index=1, message="private response text")
    manifest = forensics.safe_manifest_entry(handle)
    encoded = json.dumps(manifest, ensure_ascii=False)

    assert manifest["private_local_pack_exists"] is True
    assert manifest["message"]["char_count"] == len("private response text")
    assert manifest["reasoning"]["present"] is True
    assert manifest["parse"]["category"] == "not_json"
    assert "private response text" not in encoded
    assert "private reasoning" not in encoded
    assert str(tmp_path) not in encoded
    assert set(manifest) == {
        "attempt_index",
        "context_length",
        "output_cap",
        "reasoning_mode",
        "http_status",
        "content_type",
        "finish_reason",
        "latency_ms",
        "numeric_stats",
        "reasoning",
        "message",
        "parse",
        "private_local_pack_exists",
    }


def test_malformed_json_location_and_exact_tail_are_private(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    forensics = LocalFailureForensics(tmp_path / "private", repo_root=repo, enabled=True)

    handle = _capture(forensics, attempt_index=1, message='{"id": 1,\n"text": broken-tail')
    payload = json.loads(handle.path.read_text(encoding="utf-8"))
    manifest = forensics.safe_manifest_entry(handle)

    assert payload["json_parse"]["line"] == 2
    assert payload["json_parse"]["column"] > 1
    assert payload["json_parse"]["offset"] > 0
    assert payload["json_parse"]["malformed_tail"].endswith("broken-tail")
    assert "malformed_tail" not in json.dumps(manifest)


def test_sse_aggregation_retains_frames_and_separates_reasoning_message() -> None:
    raw = "\n".join(
        [
            "event: reasoning.delta",
            'data: {"type":"reasoning.delta","delta":"think "}',
            "",
            "event: reasoning.delta",
            'data: {"type":"reasoning.delta","delta":"more"}',
            "",
            "event: message.delta",
            'data: {"type":"message.delta","delta":"{\\"id\\":1}"}',
            "",
            "event: chat.end",
            'data: {"type":"chat.end","result":{"stats":{"total_output_tokens":9,"reasoning_output_tokens":6},"stop_reason":"eos"}}',
            "",
        ]
    )

    parsed = parse_native_chat_response(
        raw.encode("utf-8"), content_type="text/event-stream", http_status=200
    )

    assert parsed.reasoning_text == "think more"
    assert parsed.message_text == '{"id":1}'
    assert parsed.boundary == "terminal"
    assert parsed.finish_reason == "eos"
    assert parsed.numeric_stats == {
        "stats.reasoning_output_tokens": 6,
        "stats.total_output_tokens": 9,
    }
    assert [frame.sequence for frame in parsed.sse_frames] == [1, 2, 3, 4]
    assert parsed.raw_envelope["result"]["stats"]["reasoning_output_tokens"] == 6
