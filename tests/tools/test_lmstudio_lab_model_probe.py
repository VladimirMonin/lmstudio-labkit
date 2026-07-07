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
    "C:/Users/Private/weights.gguf",
    "/var/tmp/private.gguf",
    "/mnt/private/model.gguf",
    "models/private.gguf",
    "weights.gguf",
    "https://private.example/native/models",
    "secret-token-value-1234567890",
    "top secret message",
    "raw response text",
    "prompt should not leak",
    "response should not leak",
    "message should not leak",
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


def _fake_models_payload() -> bytes:
    return json.dumps(
        {
            "data": [
                {
                    "id": "qwen/test-model",
                    "loaded": True,
                    "loaded_instances": [
                        {
                            "context_length": 8192,
                            "n_parallel": 2,
                            "config": {
                                "context_length": 16384,
                                "parallel": 4,
                                "file_path": "C:/Users/Private/weights.gguf",
                                "provider_url": "https://private.example/native/models",
                            },
                        }
                    ],
                    "capabilities": {
                        "vision": True,
                        "max_batch_size": 16,
                        "labels": [
                            "chat",
                            "local",
                            "top secret message",
                            "secret-token-value-1234567890",
                        ],
                        "status_label": "ready",
                        "display_name": "top secret message",
                        "provider_url": "https://private.example/native/models",
                        "secret_token": "secret-token-value-1234567890",
                        "message": "top secret message",
                    },
                    "response": "raw response text",
                    "content": "raw response text",
                },
                {
                    "id": "idle/model",
                    "state": "unloaded",
                    "capabilities": {
                        "vision": False,
                        "tool_calling": True,
                    },
                },
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    if not text:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _fake_models_payload_with_unix_paths() -> bytes:
    return json.dumps(
        {
            "data": [
                {
                    "id": "/var/tmp/private.gguf",
                    "loaded": True,
                    "capabilities": {
                        "vision": True,
                        "labels": ["chat", "/mnt/private/model.gguf"],
                    },
                },
                {
                    "id": "google/gemma-4-e2b",
                    "loaded": False,
                    "capabilities": {
                        "vision": False,
                    },
                },
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _fake_models_payload_with_sensitive_model_ids() -> bytes:
    return json.dumps(
        {
            "data": [
                {
                    "id": "secret-token-value-1234567890",
                    "loaded": True,
                    "capabilities": {
                        "vision": True,
                    },
                },
                {
                    "id": "google/gemma-4-e2b",
                    "loaded": False,
                    "capabilities": {
                        "vision": False,
                    },
                },
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _fake_top_level_models_payload_with_relative_paths_and_compact_keys() -> bytes:
    return json.dumps(
        [
            {
                "id": "models/private.gguf",
                "loaded": True,
                "capabilities": {
                    "vision": True,
                    "labels": ["chat", "models/private.gguf"],
                    "artifact_name": "weights.gguf",
                    "prompttext": "prompt should not leak",
                    "responsebody": "response should not leak",
                    "messagebody": "message should not leak",
                    "secrettoken": "secret-token-value-1234567890",
                },
            },
            {
                "id": "google/gemma-4-e2b",
                "loaded": False,
                "capabilities": {
                    "vision": False,
                },
            },
            {
                "id": "qwen/test-model",
                "loaded": False,
                "capabilities": {
                    "tool_calling": True,
                    "labels": ["local"],
                },
            },
        ],
        ensure_ascii=False,
    ).encode("utf-8")


def test_probe_lmstudio_models_uses_native_models_get_request_and_no_payload() -> None:
    captured: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append((request.full_url, request.get_method(), request.data))
        assert timeout_s == 10.0
        return b"[]"

    for base_url in (
        "http://127.0.0.1:1234/",
        "http://127.0.0.1:1234/api/v1",
    ):
        result = lmstudio_lab.probe_lmstudio_models(base_url, transport=fake_transport)
        assert result.summary["status"] == "ok"

    assert captured == [
        ("http://127.0.0.1:1234/api/v1/models", "GET", None),
        ("http://127.0.0.1:1234/api/v1/models", "GET", None),
    ]


def test_probe_lmstudio_models_parses_target_loaded_instances_and_capabilities() -> None:
    result = lmstudio_lab.probe_lmstudio_models(
        "http://127.0.0.1:1234",
        target_model_id="qwen/test-model",
        transport=lambda _request, _timeout_s: _fake_models_payload(),
    )

    assert result.summary["status"] == "ok"
    assert result.summary["target_model_id"] == "qwen/test-model"
    assert result.summary["target_model_found"] is True
    assert result.summary["model_count"] == 2
    assert result.summary["loaded_model_count"] == 1
    assert result.summary["loaded_instance_total"] == 1

    target = result.summary["target_model"]
    assert isinstance(target, dict)
    assert target["model_id"] == "qwen/test-model"
    assert target["loaded"] is True
    assert target["loaded_instance_count"] == 1
    assert target["context_length_candidates"] == [8192, 16384]
    assert target["parallel_candidates"] == [2, 4]
    assert target["capabilities"] == {
        "vision": True,
        "max_batch_size": 16,
        "labels": ["chat", "local"],
        "status_label": "ready",
    }


def test_probe_lmstudio_models_strips_sensitive_strings_nested_under_safe_keys() -> None:
    result = lmstudio_lab.probe_lmstudio_models(
        "http://127.0.0.1:1234",
        target_model_id="qwen/test-model",
        transport=lambda _request, _timeout_s: _fake_models_payload(),
    )

    target = result.summary["target_model"]
    assert isinstance(target, dict)
    capabilities = target["capabilities"]
    assert isinstance(capabilities, dict)
    assert capabilities["labels"] == ["chat", "local"]
    assert capabilities["status_label"] == "ready"
    assert "display_name" not in capabilities

    serialized = json.dumps(
        {"summary": result.summary, "model_records": result.model_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "top secret message" not in serialized
    assert "secret-token-value-1234567890" not in serialized


def test_probe_models_cli_writes_safe_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]

    def fake_probe(
        base_url: str,
        *,
        target_model_id: str | None = None,
        allow_remote: bool = False,
        timeout_s: float = 10.0,
    ) -> lmstudio_lab.ModelProbeResult:
        return lmstudio_lab.probe_lmstudio_models(
            base_url,
            target_model_id=target_model_id,
            allow_remote=allow_remote,
            timeout_s=timeout_s,
            transport=lambda _request, _timeout_s: _fake_models_payload(),
        )

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_models", fake_probe)

    exit_code = lmstudio_benchmark.main(
        [
            "probe-models",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-safe",
            "--model-id",
            "qwen/test-model",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_probe-safe_model_probe"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "model_probe.json",
        "models.jsonl",
        "report.md",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    model_probe_text = (run_dir / "model_probe.json").read_text(encoding="utf-8")
    models_text = (run_dir / "models.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, model_probe_text, models_text, report_text):
        _assert_safe_text(text, project_root=project_root)

    environment_payload = json.loads(environment_text)
    assert environment_payload["command"] == "probe-models"
    assert environment_payload["allow_remote"] is False
    assert environment_payload["run_id"] == "probe-safe"
    assert "base_url" not in environment_payload

    model_probe_payload = json.loads(model_probe_text)
    assert model_probe_payload["status"] == "ok"
    assert model_probe_payload["target_model_id_safe"] is True
    assert model_probe_payload["target_model_found"] is True
    assert model_probe_payload["target_model"]["model_id"] == "qwen/test-model"
    assert model_probe_payload["target_model"]["capabilities"] == {
        "vision": True,
        "max_batch_size": 16,
        "labels": ["chat", "local"],
        "status_label": "ready",
    }

    model_rows = _read_jsonl(run_dir / "models.jsonl")
    assert [row["model_id"] for row in model_rows] == ["qwen/test-model", "idle/model"]
    assert model_rows[0]["schema_version"] == "1.0"
    assert {row["run_id"] for row in model_rows} == {"probe-safe"}
    assert model_rows[0]["capabilities"] == {
        "vision": True,
        "max_batch_size": 16,
        "labels": ["chat", "local"],
        "status_label": "ready",
    }

    assert "# LM Studio Model Probe Report" in report_text
    assert "endpoint_path: `/api/v1/models`" in report_text
    assert "prompts/chat endpoints: not used" in report_text


def test_probe_models_cli_rejects_unsafe_posix_run_id_before_output_dir_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_probe(*args, **kwargs):
        raise AssertionError("probe should not run for invalid run_id")

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_models", fail_probe)

    with pytest.raises(ValueError, match="safe local identifier") as exc_info:
        lmstudio_benchmark.main(
            [
                "probe-models",
                "--output-root",
                str(tmp_path),
                "--run-id",
                "/var/tmp/private.gguf",
            ]
        )

    message = str(exc_info.value)
    assert "/var/tmp/private.gguf" not in message
    assert not (tmp_path / "run_/var/tmp/private.gguf_model_probe").exists()
    assert list(tmp_path.iterdir()) == []


def test_probe_models_cli_rejects_unsafe_url_run_id_before_output_dir_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_probe(*args, **kwargs):
        raise AssertionError("probe should not run for invalid run_id")

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_models", fail_probe)

    with pytest.raises(ValueError, match="safe local identifier") as exc_info:
        lmstudio_benchmark.main(
            [
                "probe-models",
                "--output-root",
                str(tmp_path),
                "--run-id",
                "https://private.example/native/models",
            ]
        )

    message = str(exc_info.value)
    assert "https://private.example/native/models" not in message
    assert not (tmp_path / "run_https://private.example/native/models_model_probe").exists()
    assert list(tmp_path.iterdir()) == []


def test_probe_lmstudio_models_rejects_remote_without_allow_remote() -> None:
    with pytest.raises(ValueError, match="allow_remote"):
        lmstudio_lab.probe_lmstudio_models(
            "https://example.com:1234",
            transport=lambda _request, _timeout_s: b"[]",
        )


def test_probe_lmstudio_models_allows_remote_with_flag() -> None:
    captured: list[str] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        captured.append(request.full_url)
        return b'{"models": []}'

    result = lmstudio_lab.probe_lmstudio_models(
        "https://example.com:1234/v1",
        allow_remote=True,
        transport=fake_transport,
    )

    assert result.summary["status"] == "ok"
    assert result.summary["is_localhost"] is False
    assert captured == ["https://example.com:1234/api/v1/models"]


def test_probe_lmstudio_models_maps_transport_errors_without_leaking_url() -> None:
    result = lmstudio_lab.probe_lmstudio_models(
        "http://127.0.0.1:1234",
        target_model_id="qwen/test-model",
        transport=lambda _request, _timeout_s: (_ for _ in ()).throw(
            urllib_error.URLError(TimeoutError("boom"))
        ),
    )

    assert result.summary["status"] == "transport_error"
    assert result.summary["error_category"] == "timeout"
    assert result.summary["target_model_found"] is False
    serialized = json.dumps(result.summary, sort_keys=True)
    assert "127.0.0.1" not in serialized
    assert "boom" not in serialized
    assert "response_hash" not in result.summary


def test_probe_lmstudio_models_sanitizes_unix_paths_and_unsafe_target_model_id() -> None:
    result = lmstudio_lab.probe_lmstudio_models(
        "http://127.0.0.1:1234",
        target_model_id="/var/tmp/private.gguf",
        transport=lambda _request, _timeout_s: _fake_models_payload_with_unix_paths(),
    )

    assert result.summary["status"] == "ok"
    assert result.summary.get("target_model_id") is None
    assert result.summary["target_model_id_safe"] is False
    assert result.summary["target_model_found"] is False
    assert result.summary["model_ids"] == ["model_0001", "google/gemma-4-e2b"]

    assert result.model_records[0]["model_id"] == "model_0001"
    assert result.model_records[0]["capabilities"] == {
        "vision": True,
        "labels": ["chat"],
    }

    serialized = json.dumps(
        {"summary": result.summary, "model_records": result.model_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "/var/tmp/private.gguf" not in serialized
    assert "/mnt/private/model.gguf" not in serialized


def test_probe_lmstudio_models_redacts_sensitive_target_model_id_from_summary_and_report() -> None:
    result = lmstudio_lab.probe_lmstudio_models(
        "http://127.0.0.1:1234",
        target_model_id="secret-token-value-1234567890",
        transport=lambda _request, _timeout_s: _fake_models_payload_with_sensitive_model_ids(),
    )

    assert result.summary["status"] == "ok"
    assert result.summary.get("target_model_id") is None
    assert result.summary["target_model_id_safe"] is False
    assert result.summary["target_model_found"] is False
    assert result.summary["model_ids"] == ["model_0001", "google/gemma-4-e2b"]
    assert result.model_records[0]["model_id"] == "model_0001"

    serialized = json.dumps(
        {"summary": result.summary, "model_records": result.model_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_probe_report(
        run_id="probe-sensitive-target",
        summary=result.summary,
    )
    assert "secret-token-value-1234567890" not in serialized
    assert "secret-token-value-1234567890" not in report_text


def test_probe_models_cli_writes_safe_outputs_for_unsafe_target_and_unix_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]

    def fake_probe(
        base_url: str,
        *,
        target_model_id: str | None = None,
        allow_remote: bool = False,
        timeout_s: float = 10.0,
    ) -> lmstudio_lab.ModelProbeResult:
        return lmstudio_lab.probe_lmstudio_models(
            base_url,
            target_model_id=target_model_id,
            allow_remote=allow_remote,
            timeout_s=timeout_s,
            transport=lambda _request, _timeout_s: _fake_models_payload_with_unix_paths(),
        )

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_models", fake_probe)

    exit_code = lmstudio_benchmark.main(
        [
            "probe-models",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-unsafe",
            "--model-id",
            "/var/tmp/private.gguf",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_probe-unsafe_model_probe"
    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    model_probe_text = (run_dir / "model_probe.json").read_text(encoding="utf-8")
    models_text = (run_dir / "models.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, model_probe_text, models_text, report_text):
        _assert_safe_text(text, project_root=project_root)

    model_probe_payload = json.loads(model_probe_text)
    assert model_probe_payload["target_model_id_safe"] is False
    assert model_probe_payload["target_model_found"] is False
    assert model_probe_payload.get("target_model_id") is None

    model_rows = _read_jsonl(run_dir / "models.jsonl")
    assert [row["model_id"] for row in model_rows] == ["model_0001", "google/gemma-4-e2b"]

    assert "target_model_id_safe: `False`" in report_text
    assert "/var/tmp/private.gguf" not in report_text
    assert "/mnt/private/model.gguf" not in report_text


def test_probe_models_cli_redacts_sensitive_target_model_id_from_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]

    def fake_probe(
        base_url: str,
        *,
        target_model_id: str | None = None,
        allow_remote: bool = False,
        timeout_s: float = 10.0,
    ) -> lmstudio_lab.ModelProbeResult:
        return lmstudio_lab.probe_lmstudio_models(
            base_url,
            target_model_id=target_model_id,
            allow_remote=allow_remote,
            timeout_s=timeout_s,
            transport=lambda _request, _timeout_s: _fake_models_payload_with_sensitive_model_ids(),
        )

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_models", fake_probe)

    exit_code = lmstudio_benchmark.main(
        [
            "probe-models",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-sensitive",
            "--model-id",
            "secret-token-value-1234567890",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_probe-sensitive_model_probe"
    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    model_probe_text = (run_dir / "model_probe.json").read_text(encoding="utf-8")
    models_text = (run_dir / "models.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, model_probe_text, models_text, report_text):
        _assert_safe_text(text, project_root=project_root)

    model_probe_payload = json.loads(model_probe_text)
    assert model_probe_payload["target_model_id_safe"] is False
    assert model_probe_payload["target_model_found"] is False
    assert model_probe_payload.get("target_model_id") is None

    model_rows = _read_jsonl(run_dir / "models.jsonl")
    assert [row["model_id"] for row in model_rows] == ["model_0001", "google/gemma-4-e2b"]


def test_probe_lmstudio_models_accepts_safe_google_gemma_target_model_id() -> None:
    result = lmstudio_lab.probe_lmstudio_models(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda _request, _timeout_s: _fake_models_payload_with_unix_paths(),
    )

    assert result.summary["target_model_id"] == "google/gemma-4-e2b"
    assert result.summary["target_model_id_safe"] is True
    assert result.summary["target_model_found"] is True
    assert result.summary["target_model"]["model_id"] == "google/gemma-4-e2b"

    report_text = lmstudio_lab.render_model_probe_report(
        run_id="probe-safe-gemma",
        summary=result.summary,
    )
    assert "google/gemma-4-e2b" in report_text
    assert "/var/tmp/private.gguf" not in report_text


def test_probe_lmstudio_models_sanitizes_relative_paths_and_compact_keys_from_top_level_list_payload() -> (
    None
):
    result = lmstudio_lab.probe_lmstudio_models(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda _request, _timeout_s: (
            _fake_top_level_models_payload_with_relative_paths_and_compact_keys()
        ),
    )

    assert result.summary["status"] == "ok"
    assert result.summary["target_model_id"] == "google/gemma-4-e2b"
    assert result.summary["target_model_id_safe"] is True
    assert result.summary["target_model_found"] is True
    assert result.summary["model_ids"] == ["model_0001", "google/gemma-4-e2b", "qwen/test-model"]
    assert result.model_records[0]["model_id"] == "model_0001"
    assert result.model_records[0]["capabilities"] == {
        "vision": True,
        "labels": ["chat"],
    }
    assert result.model_records[2]["model_id"] == "qwen/test-model"
    assert result.model_records[2]["capabilities"] == {
        "tool_calling": True,
        "labels": ["local"],
    }

    serialized = json.dumps(
        {"summary": result.summary, "model_records": result.model_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_probe_report(
        run_id="probe-relative-paths",
        summary=result.summary,
    )

    for text in (serialized, report_text):
        assert "models/private.gguf" not in text
        assert "weights.gguf" not in text
        assert "prompt should not leak" not in text
        assert "response should not leak" not in text
        assert "message should not leak" not in text
        assert "secret-token-value-1234567890" not in text

    assert "google/gemma-4-e2b" in serialized
    assert "qwen/test-model" in serialized
    assert '"chat"' in serialized
    assert '"local"' in serialized
    assert "google/gemma-4-e2b" in report_text
    assert "qwen/test-model" in report_text
