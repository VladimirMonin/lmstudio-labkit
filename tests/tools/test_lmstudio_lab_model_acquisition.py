from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from pathlib import Path
from urllib import error as urllib_error

import pytest
import yaml

from tools import lmstudio_benchmark, lmstudio_lab

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home|var|tmp|mnt)/[^\"\r\n]+"),
)
FORBIDDEN_OUTPUT_SNIPPETS = (
    "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf",
    "https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF",
    "Qwen3.5-4B-Q4_K_M.gguf",
    "secret-token-value-1234567890",
    "job-12345",
    "/api/v1/models",
    "/api/v1/models/download",
    "/api/v1/models/download/status",
    "/api/v1/models/load",
    "/api/v1/models/unload",
    "/v1/chat/completions",
    "endpoint_paths",
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


def _assert_no_raw_endpoint_paths(*texts: str) -> None:
    forbidden_endpoint_paths = (
        "/api/v1/models",
        "/api/v1/models/download",
        "/api/v1/models/download/status",
        "/v1/chat/completions",
        "endpoint_paths",
    )
    for text in texts:
        for endpoint_path in forbidden_endpoint_paths:
            assert endpoint_path not in text


def _write_registry(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "registry_kind": "lmstudio_lab_candidates",
        "candidates": [
            {
                "lab_key": "qwen35_4b_q4km",
                "family": "qwen",
                "size_class": "small",
                "source_id": "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf",
                "compat_model_id": None,
                "compat_model_id_status": "pending_safe_resolution",
            },
            {
                "lab_key": "gemma4_e2b_q4km",
                "family": "gemma",
                "size_class": "small",
                "source_id": None,
                "compat_model_id": "google/gemma-4-e2b",
                "compat_model_id_status": "measured_baseline",
            },
        ],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def test_acquire_candidate_cli_dry_run_writes_safe_artifacts_and_skips_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)
    captured: list[str] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append(request.full_url)
        raise AssertionError("dry-run must not call transport")

    def fake_acquire(base_url: str, **kwargs) -> lmstudio_lab.ModelAcquisitionResult:
        return lmstudio_lab.acquire_candidate_model(
            base_url,
            transport=fake_transport,
            sleep=lambda _seconds: None,
            **kwargs,
        )

    monkeypatch.setattr(lmstudio_benchmark, "acquire_candidate_model", fake_acquire)

    with caplog.at_level(logging.INFO, logger="tools.lmstudio_lab.model_acquisition"):
        exit_code = lmstudio_benchmark.main(
            [
                "acquire-candidate",
                "--registry-path",
                str(registry_path),
                "--output-root",
                str(tmp_path),
                "--run-id",
                "acquire-dry-run",
                "--lab-key",
                "qwen35_4b_q4km",
            ]
        )

    assert exit_code == 0
    assert captured == []

    run_dir = tmp_path / "run_acquire-dry-run_model_acquisition"
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "download_status.jsonl",
        "environment.json",
        "model_acquisition.json",
        "report.md",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    acquisition_text = (run_dir / "model_acquisition.json").read_text(encoding="utf-8")
    status_text = (run_dir / "download_status.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, acquisition_text, status_text, report_text):
        _assert_safe_text(text, project_root=project_root)

    assert status_text == ""

    environment_payload = json.loads(environment_text)
    assert environment_payload["command"] == "acquire-candidate"
    assert environment_payload["execute_download"] is False
    assert environment_payload["poll_enabled"] is False
    assert "base_url" not in environment_payload
    assert "registry_path" not in environment_payload

    acquisition_payload = json.loads(acquisition_text)
    assert acquisition_payload["probe_kind"] == "model_acquisition"
    assert acquisition_payload["execute_download"] is False
    assert acquisition_payload["download_request_planned"] is True
    assert acquisition_payload["status"] == "planned"
    assert acquisition_payload["endpoint_kinds_planned"] == ["download"]
    assert acquisition_payload["endpoint_kinds_used"] == []
    assert "endpoint_paths_planned" not in acquisition_payload
    assert "endpoint_paths_used" not in acquisition_payload
    _assert_no_raw_endpoint_paths(acquisition_text, report_text, status_text)

    log_text = caplog.text
    _assert_safe_text(log_text, project_root=project_root)
    assert "model acquisition plan built" in log_text
    assert "model acquisition dry-run planned" in log_text
    assert "download_model_ref_kind=huggingface_repo" in log_text
    assert "quantization=Q4_K_M" in log_text

    assert "dry-run does not call network" in report_text
    assert "endpoint_kinds_planned" in report_text
    assert "endpoint_kinds_used" in report_text
    assert "execute mode uses endpoint kind `download` only" in report_text
    assert "optional polling uses endpoint kind `download_status` only" in report_text
    assert "no load/unload/generation" in report_text


def test_acquire_candidate_plan_derives_hf_repo_and_quantization_without_leaking_source() -> None:
    registry_path = (
        Path(__file__).resolve().parents[2]
        / "experiments"
        / "lmstudio"
        / "models"
        / "candidates.yaml"
    )

    result = lmstudio_lab.acquire_candidate_model(
        "http://127.0.0.1:1234",
        registry_path=registry_path,
        lab_key="qwen35_4b_q4km",
    )

    assert result.summary["status"] == "planned"
    assert result.summary["download_model_ref_kind"] == "huggingface_repo"
    assert result.summary["download_model_ref_hash"] == _sha256_text(
        "https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF"
    )
    assert result.summary["source_id_hash"] == _sha256_text(
        "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf"
    )
    assert result.summary["quantization"] == "Q4_K_M"
    assert result.summary["quantization_verified"] is False
    assert result.summary["native_key_verified"] is False

    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    assert "https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF" not in serialized
    assert "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf" not in serialized
    assert "Qwen3.5-4B-Q4_K_M.gguf" not in serialized
    _assert_no_raw_endpoint_paths(serialized)


def test_acquire_candidate_execute_posts_expected_body_and_optional_auth_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)
    monkeypatch.setenv("LM_API_TOKEN", "secret-token-value-1234567890")
    captured: list[dict[str, object]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "data": request.data,
                "headers": {key.lower(): value for key, value in request.header_items()},
                "timeout_s": timeout_s,
            }
        )
        return b'{"status":"already_downloaded"}'

    def fake_acquire(base_url: str, **kwargs) -> lmstudio_lab.ModelAcquisitionResult:
        return lmstudio_lab.acquire_candidate_model(
            base_url,
            transport=fake_transport,
            sleep=lambda _seconds: None,
            **kwargs,
        )

    monkeypatch.setattr(lmstudio_benchmark, "acquire_candidate_model", fake_acquire)

    exit_code = lmstudio_benchmark.main(
        [
            "acquire-candidate",
            "--registry-path",
            str(registry_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "acquire-execute",
            "--lab-key",
            "qwen35_4b_q4km",
            "--execute-download",
        ]
    )

    assert exit_code == 0
    assert len(captured) == 1
    assert captured[0]["url"] == "http://127.0.0.1:1234/api/v1/models/download"
    assert captured[0]["method"] == "POST"
    assert captured[0]["timeout_s"] == 10.0
    assert captured[0]["headers"]["authorization"] == "Bearer secret-token-value-1234567890"
    assert json.loads(captured[0]["data"].decode("utf-8")) == {
        "model": "https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF",
        "quantization": "Q4_K_M",
    }
    captured_serialized = json.dumps(
        [
            {
                **record,
                "data": record["data"].decode("utf-8")
                if isinstance(record["data"], bytes)
                else record["data"],
            }
            for record in captured
        ],
        ensure_ascii=False,
    )
    assert all(
        endpoint not in captured_serialized
        for endpoint in ("/api/v1/models/load", "/api/v1/models/unload", "/v1/chat/completions")
    )

    run_dir = tmp_path / "run_acquire-execute_model_acquisition"
    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    acquisition_text = (run_dir / "model_acquisition.json").read_text(encoding="utf-8")
    status_rows = _read_jsonl(run_dir / "download_status.jsonl")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    for text in (environment_text, acquisition_text, report_text):
        _assert_safe_text(text, project_root=project_root)
    assert "secret-token-value-1234567890" not in acquisition_text

    acquisition_payload = json.loads(acquisition_text)
    assert acquisition_payload["api_token_present"] is True
    assert acquisition_payload["download_status"] == "already_downloaded"
    assert acquisition_payload["ready_on_disk"] is True
    assert acquisition_payload["endpoint_kinds_planned"] == ["download"]
    assert acquisition_payload["endpoint_kinds_used"] == ["download"]
    assert "endpoint_paths_planned" not in acquisition_payload
    assert "endpoint_paths_used" not in acquisition_payload
    assert status_rows == [
        {
            "download_status": "already_downloaded",
            "endpoint_kind": "download",
            "phase": "download",
            "run_id": "acquire-execute",
            "schema_version": "1.0",
        }
    ]
    assert all("privacy_redaction_count" not in row for row in status_rows)
    _assert_no_raw_endpoint_paths(
        acquisition_text,
        report_text,
        json.dumps(status_rows, ensure_ascii=False, sort_keys=True),
    )


def test_acquire_candidate_already_downloaded_marks_ready_without_polling(tmp_path: Path) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)
    captured: list[str] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append(request.full_url)
        return b'{"status":"already_downloaded"}'

    result = lmstudio_lab.acquire_candidate_model(
        "http://127.0.0.1:1234",
        registry_path=registry_path,
        lab_key="qwen35_4b_q4km",
        execute_download=True,
        poll=True,
        transport=fake_transport,
        sleep=lambda _seconds: None,
    )

    assert result.summary["status"] == "ok"
    assert result.summary["download_status"] == "already_downloaded"
    assert result.summary["ready_on_disk"] is True
    assert "job_id_hash" not in result.summary
    assert captured == ["http://127.0.0.1:1234/api/v1/models/download"]
    assert len(result.status_records) == 1
    assert result.summary["endpoint_kinds_planned"] == ["download", "download_status"]
    assert result.summary["endpoint_kinds_used"] == ["download"]
    serialized = json.dumps(
        {"summary": result.summary, "status_records": result.status_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    _assert_no_raw_endpoint_paths(serialized)


def test_acquire_candidate_polls_download_status_and_stores_job_hash_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)
    captured: list[str] = []
    raw_job_id = "job-12345"

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append(request.full_url)
        if request.full_url.endswith("/api/v1/models/download"):
            return json.dumps(
                {"status": "downloading", "job_id": raw_job_id, "total_size_bytes": 100}
            ).encode("utf-8")
        if request.full_url.endswith(f"/api/v1/models/download/status/{raw_job_id}"):
            index = len([url for url in captured if "/status/" in url])
            if index == 1:
                return json.dumps(
                    {
                        "status": "downloading",
                        "job_id": raw_job_id,
                        "downloaded_bytes": 25,
                        "total_size_bytes": 100,
                        "bytes_per_second": 1_250_000,
                    }
                ).encode("utf-8")
            return json.dumps(
                {
                    "status": "completed",
                    "job_id": raw_job_id,
                    "downloaded_bytes": 100,
                    "total_size_bytes": 100,
                    "bytes_per_second": 0,
                }
            ).encode("utf-8")
        raise AssertionError(f"unexpected URL {request.full_url}")

    with caplog.at_level(logging.INFO, logger="tools.lmstudio_lab.model_acquisition"):
        result = lmstudio_lab.acquire_candidate_model(
            "http://127.0.0.1:1234",
            registry_path=registry_path,
            lab_key="qwen35_4b_q4km",
            execute_download=True,
            poll=True,
            max_polls=3,
            poll_interval_s=0.01,
            transport=fake_transport,
            sleep=lambda _seconds: None,
        )

    assert result.summary["status"] == "ok"
    assert result.summary["download_status"] == "completed"
    assert result.summary["job_id_hash"] == _sha256_text(raw_job_id)
    assert result.summary["progress_percent"] == 100.0
    assert result.summary["downloaded_bytes"] == 100
    assert result.summary["total_size_bytes"] == 100
    assert result.summary["endpoint_kinds_planned"] == ["download", "download_status"]
    assert result.summary["endpoint_kinds_used"] == [
        "download",
        "download_status",
        "download_status",
    ]
    assert all(
        endpoint not in json.dumps(captured, ensure_ascii=False)
        for endpoint in ("/api/v1/models/load", "/api/v1/models/unload", "/v1/chat/completions")
    )

    serialized = json.dumps(
        {"summary": result.summary, "status_records": result.status_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    assert raw_job_id not in serialized
    assert len(result.status_records) == 3
    assert result.status_records[0]["endpoint_kind"] == "download"
    assert result.status_records[1]["endpoint_kind"] == "download_status"
    assert result.status_records[2]["endpoint_kind"] == "download_status"
    assert result.status_records[1]["progress_percent"] == 25.0
    assert result.status_records[2]["download_status"] == "completed"
    _assert_no_raw_endpoint_paths(serialized)

    log_text = caplog.text
    _assert_safe_text(log_text, project_root=project_root)
    assert "model acquisition POST status received" in log_text
    assert "model acquisition poll status received" in log_text
    assert "progress_percent=25.0" in log_text
    assert "speed_mbps=10.0" in log_text


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_error_category"),
    [
        ({"status": "failed", "job_id": "job-12345"}, "download_failed", "download_failed"),
    ],
)
def test_acquire_candidate_failed_status_is_classified_safely(
    tmp_path: Path,
    payload: dict[str, object],
    expected_status: str,
    expected_error_category: str,
) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)

    result = lmstudio_lab.acquire_candidate_model(
        "http://127.0.0.1:1234",
        registry_path=registry_path,
        lab_key="qwen35_4b_q4km",
        execute_download=True,
        transport=lambda _request, _timeout_s: json.dumps(payload).encode("utf-8"),
        sleep=lambda _seconds: None,
    )

    assert result.summary["status"] == expected_status
    assert result.summary["error_category"] == expected_error_category
    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    assert "job-12345" not in serialized
    _assert_no_raw_endpoint_paths(serialized)


@pytest.mark.parametrize(
    ("http_code", "expected_category"),
    [(401, "auth_required"), (403, "auth_required"), (404, "not_found")],
)
def test_acquire_candidate_http_errors_are_classified_safely(
    tmp_path: Path,
    http_code: int,
    expected_category: str,
) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)

    def fake_transport(request, timeout_s: float) -> bytes:
        raise urllib_error.HTTPError(
            request.full_url, http_code, "error", None, io.BytesIO(b"secret")
        )

    result = lmstudio_lab.acquire_candidate_model(
        "http://127.0.0.1:1234",
        registry_path=registry_path,
        lab_key="qwen35_4b_q4km",
        execute_download=True,
        transport=fake_transport,
        sleep=lambda _seconds: None,
    )

    assert result.summary["status"] == "transport_error"
    assert result.summary["error_category"] == expected_category
    assert result.summary["http_status"] == http_code
    assert result.status_records == ()
    _assert_no_raw_endpoint_paths(json.dumps(result.summary, ensure_ascii=False, sort_keys=True))


def test_acquire_candidate_rejects_remote_without_allow_remote(tmp_path: Path) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)

    with pytest.raises(ValueError, match="allow_remote"):
        lmstudio_lab.acquire_candidate_model(
            "https://example.com:1234",
            registry_path=registry_path,
            lab_key="qwen35_4b_q4km",
        )


def test_lmstudio_lab_exports_model_acquisition_symbols() -> None:
    assert lmstudio_lab.MODEL_ACQUISITION_ENDPOINT_PATH == "/api/v1/models/download"
    assert lmstudio_lab.MODEL_ACQUISITION_STATUS_ENDPOINT_TEMPLATE.endswith(":job_id")
    assert "model_acquisition.json" in lmstudio_lab.MODEL_ACQUISITION_RESULT_FILE_NAMES
    assert callable(lmstudio_lab.acquire_candidate_model)
    assert callable(lmstudio_lab.render_model_acquisition_report)
