from __future__ import annotations

import json
import re
from pathlib import Path
from urllib import error as urllib_error

import pytest

from tools import lmstudio_benchmark, lmstudio_lab

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home|var|tmp|mnt)/[^\"\r\n]+"),
)
FORBIDDEN_OUTPUT_SNIPPETS = (
    "/v1/chat/completions",
    "/api/v1/models/unload",
    "/api/v1/downloads",
    "C:/Users/Private/weights.gguf",
    "/var/tmp/private.gguf",
    "https://private.example/native/load",
    "secret-token-value-1234567890",
    "top secret message",
    "raw response text",
    "message should not leak",
    "content should not leak",
)


def _assert_safe_text(text: str, *, project_root: Path) -> None:
    for forbidden in FORBIDDEN_OUTPUT_SNIPPETS:
        assert forbidden not in text
    known_private_values = {
        str(project_root),
        project_root.as_posix(),
        str(Path.home()),
        Path.home().as_posix(),
    }
    for value in known_private_values:
        if value:
            assert value not in text
    for pattern in ABSOLUTE_PATH_PATTERNS:
        assert pattern.search(text) is None


def _fake_load_payload(*, context_length: int = 32768, parallel: int = 1) -> bytes:
    return json.dumps(
        {
            "status": "loaded",
            "load_config": {
                "context_length": context_length,
                "parallel": parallel,
                "provider_url": "https://private.example/native/load",
                "file_path": "C:/Users/Private/weights.gguf",
                "message": "message should not leak",
                "content": "content should not leak",
                "secret_token": "secret-token-value-1234567890",
            },
            "meta": {
                "effective_config": {
                    "context_length": context_length,
                    "parallel": parallel,
                },
                "response": "raw response text",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def test_probe_lmstudio_load_uses_single_native_load_post_with_minimal_payload() -> None:
    captured: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append((request.full_url, request.get_method(), request.data))
        assert timeout_s == 120.0
        return _fake_load_payload()

    result = lmstudio_lab.probe_lmstudio_load(
        "http://127.0.0.1:1234/api/v1",
        model_id="google/gemma-4-e2b",
        transport=fake_transport,
    )

    assert result.summary["status"] == "ok"
    assert captured == [
        (
            "http://127.0.0.1:1234/api/v1/models/load",
            "POST",
            b'{"model":"google/gemma-4-e2b","context_length":32768,"parallel":1,"echo_load_config":true}',
        )
    ]
    payload = json.loads(captured[0][2].decode("utf-8"))
    assert payload == {
        "model": "google/gemma-4-e2b",
        "context_length": 32768,
        "parallel": 1,
        "echo_load_config": True,
    }
    serialized = json.dumps({"url": captured[0][0], "payload": payload}, sort_keys=True)
    assert "/api/v1/models/load" in serialized
    assert '/api/v1/models"' not in serialized
    assert "/v1/chat/completions" not in serialized
    assert "/api/v1/models/unload" not in serialized
    assert "/api/v1/downloads" not in serialized


def test_probe_lmstudio_load_verifies_echoed_config_on_success() -> None:
    result = lmstudio_lab.probe_lmstudio_load(
        "http://127.0.0.1:1234",
        model_id="google/gemma-4-e2b",
        context_length=32768,
        parallel=1,
        transport=lambda _request, _timeout_s: _fake_load_payload(),
    )

    assert result.summary["status"] == "ok"
    assert result.summary["model_id"] == "google/gemma-4-e2b"
    assert result.summary["applied_context_length"] == 32768
    assert result.summary["applied_parallel"] == 1
    assert result.summary["context_length_verified"] is True
    assert result.summary["parallel_verified"] is True
    assert result.summary["sanitized_applied_config"] == {
        "load_config": {
            "context_length": 32768,
            "parallel": 1,
        },
        "effective_config": {
            "context_length": 32768,
            "parallel": 1,
        },
    }


def test_probe_lmstudio_load_marks_context_mismatch_without_leaking_response() -> None:
    result = lmstudio_lab.probe_lmstudio_load(
        "http://127.0.0.1:1234",
        model_id="google/gemma-4-e2b",
        context_length=32768,
        parallel=1,
        transport=lambda _request, _timeout_s: _fake_load_payload(context_length=8192),
    )

    assert result.summary["status"] == "ok"
    assert result.summary["applied_context_length"] == 8192
    assert result.summary["context_length_verified"] is False
    assert result.summary["parallel_verified"] is True
    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    assert "C:/Users/Private/weights.gguf" not in serialized
    assert "top secret message" not in serialized


def test_probe_load_cli_writes_safe_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    resolved_native_load_id = "native/gemma-4-e2b"
    expected_resolved_native_load_id_hash = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: {
            "http://127.0.0.1:1234/v1/models": json.dumps(
                {"data": [{"id": "google/gemma-4-e2b"}]}, ensure_ascii=False
            ).encode("utf-8"),
            "http://127.0.0.1:1234/api/v1/models": json.dumps(
                {"models": [{"id": "google/gemma-4-e2b", "load_id": resolved_native_load_id}]},
                ensure_ascii=False,
            ).encode("utf-8"),
        }[request.full_url],
    ).summary["native_load_id_hash"]

    def fake_identity_probe(
        base_url: str,
        *,
        target_model_id: str,
        allow_remote: bool = False,
        timeout_s: float = 10.0,
    ) -> lmstudio_lab.IdentityProbeResult:
        assert base_url == "http://127.0.0.1:1234"
        assert target_model_id == "google/gemma-4-e2b"
        assert allow_remote is False
        assert timeout_s == 120.0
        return lmstudio_lab.IdentityProbeResult(
            summary={
                "status": "ok",
                "error_category": None,
                "target_hash": "safe-target-hash",
                "target_found_compat": True,
                "target_found_native": True,
                "target_hash_match": True,
                "native_load_id_resolved": True,
                "native_load_id_hash": expected_resolved_native_load_id_hash,
            },
            native_load_id=resolved_native_load_id,
        )

    def fake_probe(
        base_url: str,
        *,
        model_id: str,
        context_length: int = 32768,
        parallel: int = 1,
        allow_remote: bool = False,
        timeout_s: float = 120.0,
        display_model_id: str | None = None,
        resolved_native_load_id_hash: str | None = None,
    ) -> lmstudio_lab.LoadProbeResult:
        assert model_id == resolved_native_load_id
        assert display_model_id == "google/gemma-4-e2b"
        assert resolved_native_load_id_hash == expected_resolved_native_load_id_hash
        return lmstudio_lab.probe_lmstudio_load(
            base_url,
            model_id=model_id,
            context_length=context_length,
            parallel=parallel,
            allow_remote=allow_remote,
            timeout_s=timeout_s,
            display_model_id=display_model_id,
            resolved_native_load_id_hash=resolved_native_load_id_hash,
            transport=lambda _request, _timeout_s: _fake_load_payload(),
        )

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_identity", fake_identity_probe)
    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_load", fake_probe)

    exit_code = lmstudio_benchmark.main(
        [
            "probe-load",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-load-safe",
            "--model-id",
            "google/gemma-4-e2b",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_probe-load-safe_load_probe"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "load_probe.json",
        "report.md",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    load_probe_text = (run_dir / "load_probe.json").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, load_probe_text, report_text):
        _assert_safe_text(text, project_root=project_root)

    environment_payload = json.loads(environment_text)
    assert environment_payload["command"] == "probe-load"
    assert environment_payload["allow_remote"] is False
    assert environment_payload["model_id"] == "google/gemma-4-e2b"
    assert environment_payload["requested_context_length"] == 32768
    assert environment_payload["requested_parallel"] == 1
    assert "base_url" not in environment_payload

    load_probe_payload = json.loads(load_probe_text)
    assert load_probe_payload["status"] == "ok"
    assert load_probe_payload["model_id"] == "google/gemma-4-e2b"
    assert (
        load_probe_payload["resolved_native_load_id_hash"] == expected_resolved_native_load_id_hash
    )
    assert load_probe_payload["applied_context_length"] == 32768
    assert load_probe_payload["applied_parallel"] == 1
    assert load_probe_payload["context_length_verified"] is True
    assert load_probe_payload["parallel_verified"] is True
    assert load_probe_payload["sanitized_applied_config"] == {
        "effective_config": {
            "context_length": 32768,
            "parallel": 1,
        },
        "load_config": {
            "context_length": 32768,
            "parallel": 1,
        },
    }
    assert resolved_native_load_id not in load_probe_text
    assert resolved_native_load_id not in report_text

    assert "# LM Studio Load Probe Report" in report_text
    assert "endpoint_path: `/api/v1/models/load`" in report_text
    assert "model list/chat/generate/unload/download endpoints: not used" in report_text


def test_probe_load_cli_aborts_when_identity_is_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]

    def fake_identity_probe(
        base_url: str,
        *,
        target_model_id: str,
        allow_remote: bool = False,
        timeout_s: float = 10.0,
    ) -> lmstudio_lab.IdentityProbeResult:
        assert base_url == "http://127.0.0.1:1234"
        assert target_model_id == "google/gemma-4-e2b"
        assert allow_remote is False
        assert timeout_s == 120.0
        return lmstudio_lab.IdentityProbeResult(
            summary={
                "status": "ok",
                "error_category": None,
                "target_hash": "safe-target-hash",
                "target_found_compat": True,
                "target_found_native": True,
                "target_hash_match": True,
                "native_load_id_resolved": False,
            },
        )

    def fail_probe(*args, **kwargs):
        raise AssertionError("load probe must not run when identity is unresolved")

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_identity", fake_identity_probe)
    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_load", fail_probe)

    exit_code = lmstudio_benchmark.main(
        [
            "probe-load",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-load-identity-unresolved",
            "--model-id",
            "google/gemma-4-e2b",
        ]
    )

    assert exit_code == 2

    run_dir = tmp_path / "run_probe-load-identity-unresolved_load_probe"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "load_probe.json",
        "report.md",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    load_probe_text = (run_dir / "load_probe.json").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, load_probe_text, report_text):
        _assert_safe_text(text, project_root=project_root)

    load_probe_payload = json.loads(load_probe_text)
    assert load_probe_payload["status"] == "model_identity_unresolved"
    assert load_probe_payload["error_category"] == "identity"
    assert load_probe_payload["model_id"] == "google/gemma-4-e2b"
    assert load_probe_payload["requested_context_length"] == 32768
    assert load_probe_payload["requested_parallel"] == 1
    assert load_probe_payload["target_found_compat"] is True
    assert load_probe_payload["target_found_native"] is True
    assert load_probe_payload["target_hash_match"] is True
    assert load_probe_payload["native_load_id_resolved"] is False


def test_probe_load_cli_rejects_unsafe_model_id_before_output_dir_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_probe(*args, **kwargs):
        raise AssertionError("probe should not run for invalid model_id")

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_load", fail_probe)

    with pytest.raises(ValueError, match="safe model identifier") as exc_info:
        lmstudio_benchmark.main(
            [
                "probe-load",
                "--output-root",
                str(tmp_path),
                "--model-id",
                "/var/tmp/private.gguf",
            ]
        )

    assert "/var/tmp/private.gguf" not in str(exc_info.value)
    assert list(tmp_path.iterdir()) == []


def test_probe_load_cli_rejects_unsafe_run_id_before_output_dir_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_probe(*args, **kwargs):
        raise AssertionError("probe should not run for invalid run_id")

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_load", fail_probe)

    with pytest.raises(ValueError, match="safe local identifier") as exc_info:
        lmstudio_benchmark.main(
            [
                "probe-load",
                "--output-root",
                str(tmp_path),
                "--model-id",
                "google/gemma-4-e2b",
                "--run-id",
                "https://private.example/native/load",
            ]
        )

    assert "https://private.example/native/load" not in str(exc_info.value)
    assert list(tmp_path.iterdir()) == []


def test_probe_lmstudio_load_rejects_remote_without_allow_remote() -> None:
    with pytest.raises(ValueError, match="allow_remote"):
        lmstudio_lab.probe_lmstudio_load(
            "https://example.com:1234",
            model_id="google/gemma-4-e2b",
            transport=lambda _request, _timeout_s: _fake_load_payload(),
        )


def test_probe_lmstudio_load_allows_remote_with_flag() -> None:
    captured: list[str] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        captured.append(request.full_url)
        return _fake_load_payload()

    result = lmstudio_lab.probe_lmstudio_load(
        "https://example.com:1234/v1",
        model_id="google/gemma-4-e2b",
        allow_remote=True,
        transport=fake_transport,
    )

    assert result.summary["status"] == "ok"
    assert result.summary["is_localhost"] is False
    assert captured == ["https://example.com:1234/api/v1/models/load"]


def test_probe_lmstudio_load_maps_transport_and_decode_errors_safely() -> None:
    transport_error_result = lmstudio_lab.probe_lmstudio_load(
        "http://127.0.0.1:1234",
        model_id="google/gemma-4-e2b",
        transport=lambda _request, _timeout_s: (_ for _ in ()).throw(
            urllib_error.URLError(TimeoutError("top secret message"))
        ),
    )

    assert transport_error_result.summary["status"] == "transport_error"
    assert transport_error_result.summary["error_category"] == "timeout"
    transport_serialized = json.dumps(transport_error_result.summary, sort_keys=True)
    assert "127.0.0.1" not in transport_serialized
    assert "top secret message" not in transport_serialized

    decode_error_result = lmstudio_lab.probe_lmstudio_load(
        "http://127.0.0.1:1234",
        model_id="google/gemma-4-e2b",
        transport=lambda _request, _timeout_s: b"not-json content should not leak",
    )

    assert decode_error_result.summary["status"] == "decode_error"
    assert decode_error_result.summary["error_category"] == "json"
    decode_serialized = json.dumps(decode_error_result.summary, sort_keys=True)
    assert "127.0.0.1" not in decode_serialized
    assert "content should not leak" not in decode_serialized
