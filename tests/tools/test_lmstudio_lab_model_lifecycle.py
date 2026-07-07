from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path
from urllib import error as urllib_error

import pytest

from tools import lmstudio_benchmark, lmstudio_lab
from tools.lmstudio_lab import model_lifecycle as lmstudio_model_lifecycle

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home|var|tmp|mnt)/[^\"\r\n]+"),
)
FORBIDDEN_OUTPUT_SNIPPETS = (
    "instance-secret-12345",
    "instance-primary-12345",
    "instance-secondary-67890",
    "secret-token-value-1234567890",
    "raw body should not leak",
    "C:/Users/Private/model.gguf",
    "/var/tmp/private.gguf",
    "/api/v1/models",
    "/api/v1/models/load",
    "/api/v1/models/unload",
    "/v1/chat/completions",
    "/api/v1/models/download",
    "/api/v1/downloads",
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
        "/api/v1/models/load",
        "/api/v1/models/unload",
        "/v1/chat/completions",
        "/api/v1/models/download",
    )
    for text in texts:
        for endpoint_path in forbidden_endpoint_paths:
            assert endpoint_path not in text


def _instance_hash(raw_instance_id: str) -> str:
    return f"sha256:{__import__('hashlib').sha256(raw_instance_id.encode('utf-8')).hexdigest()}"


def _load_payload(instance_id: str, *, context_length: int = 8192, parallel: int = 1) -> bytes:
    return json.dumps(
        {
            "status": "loaded",
            "instance_id": instance_id,
            "load_config": {
                "context_length": context_length,
                "parallel": parallel,
                "provider_url": "https://private.example/native/load",
                "file_path": "C:/Users/Private/model.gguf",
                "body": "raw body should not leak",
                "secret_token": "secret-token-value-1234567890",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _load_payload_dict(*, model_id: str = "qwen3.5-4b") -> dict[str, object]:
    return {
        "model": model_id,
        "context_length": 8192,
        "parallel": 1,
        "echo_load_config": True,
    }


def _models_payload_map(model_instances: dict[str, tuple[str, ...]]) -> bytes:
    models = []
    for model_id, instance_ids in model_instances.items():
        models.append(
            {
                "key": model_id,
                "loaded_instances": [
                    {
                        "instance_id": instance_id,
                        "cache_path": "C:/Users/Private/model.gguf",
                        "response": "raw body should not leak",
                    }
                    for instance_id in instance_ids
                ],
                "selected_variant": {
                    "context_length": 8192,
                    "parallel": 1,
                    "local_path": "/var/tmp/private.gguf",
                },
            }
        )
    return json.dumps({"models": models}, ensure_ascii=False).encode("utf-8")


def _wrap_probe_with_transport(transport, *, sleep=None):
    def _wrapped(base_url: str, **kwargs):
        return lmstudio_lab.probe_model_lifecycle(
            base_url,
            transport=transport,
            sleep=sleep,
            **kwargs,
        )

    return _wrapped


def _policy_backed_smoke_happy_transport(
    calls: list[tuple[str, str, bytes | None]],
    *,
    raw_instance_id: str,
    unload_payloads: list[dict[str, object]] | None = None,
):
    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            return _models_payload_map({"qwen3.5-4b": ()})
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
            return _load_payload(raw_instance_id)
        if len(calls) in {3, 4, 5}:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        if len(calls) == 6:
            payload = json.loads(request.data.decode("utf-8"))
            assert payload == {"instance_id": raw_instance_id}
            if unload_payloads is not None:
                unload_payloads.append(payload)
            return b'{"status":"ok"}'
        if len(calls) in {7, 8}:
            return _models_payload_map({"qwen3.5-4b": ()})
        raise AssertionError(f"unexpected policy_backed_smoke request #{len(calls)}")

    return fake_transport


def _policy_two_model_swap_happy_transport(
    calls: list[tuple[str, str, bytes | None]],
    *,
    raw_primary_instance_id: str,
    raw_secondary_instance_id: str,
    unload_payloads: list[dict[str, object]] | None = None,
):
    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            return _models_payload_map(
                {
                    "qwen3.5-4b": (),
                    "google/gemma-4-e4b": (),
                }
            )
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict(
                model_id="qwen3.5-4b"
            )
            return _load_payload(raw_primary_instance_id)
        if len(calls) == 3:
            return _models_payload_map(
                {
                    "qwen3.5-4b": (raw_primary_instance_id,),
                    "google/gemma-4-e4b": (),
                }
            )
        if len(calls) == 4:
            payload = json.loads(request.data.decode("utf-8"))
            assert payload == {"instance_id": raw_primary_instance_id}
            if unload_payloads is not None:
                unload_payloads.append(payload)
            return b'{"status":"ok"}'
        if len(calls) == 5:
            return _models_payload_map(
                {
                    "qwen3.5-4b": (),
                    "google/gemma-4-e4b": (),
                }
            )
        if len(calls) == 6:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict(
                model_id="google/gemma-4-e4b"
            )
            return _load_payload(raw_secondary_instance_id)
        if len(calls) == 7:
            return _models_payload_map(
                {
                    "qwen3.5-4b": (),
                    "google/gemma-4-e4b": (raw_secondary_instance_id,),
                }
            )
        if len(calls) == 8:
            payload = json.loads(request.data.decode("utf-8"))
            assert payload == {"instance_id": raw_secondary_instance_id}
            if unload_payloads is not None:
                unload_payloads.append(payload)
            return b'{"status":"ok"}'
        if len(calls) == 9:
            return _models_payload_map(
                {
                    "qwen3.5-4b": (),
                    "google/gemma-4-e4b": (),
                }
            )
        raise AssertionError(f"unexpected policy_two_model_swap request #{len(calls)}")

    return fake_transport


def test_run_exact_model_operation_keeps_raw_ids_internal_and_unloads_exact_instance() -> None:
    raw_instance_id = "instance-secret-12345"
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": "google/gemma-4-e2b",
                "context_length": 8192,
                "parallel": 1,
                "echo_load_config": True,
            }
            return _load_payload(raw_instance_id)
        if len(calls) == 2:
            return _models_payload_map({"google/gemma-4-e2b": (raw_instance_id,)})
        if len(calls) == 3:
            payload = json.loads(request.data.decode("utf-8"))
            assert payload == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 4:
            return _models_payload_map({"google/gemma-4-e2b": ()})
        raise AssertionError(f"unexpected request #{len(calls)}")

    callback_state: dict[str, object] = {}

    result = lmstudio_model_lifecycle.run_exact_model_operation(
        "http://127.0.0.1:1234",
        model_id="google/gemma-4-e2b",
        context_length=8192,
        parallel=1,
        timeout_s=120.0,
        transport=fake_transport,
        operation=lambda state: callback_state.update(state) or {"operation_status": "ok"},
    )

    assert [(method, url) for method, url, _data in calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert callback_state["verified_context_length"] == 8192
    assert callback_state["applied_parallel"] == 1
    assert callback_state["load_verified"] is True
    assert "instance_id" not in callback_state
    assert result["operation_status"] == "ok"
    assert result["load_verified"] is True
    assert result["cleanup_status"] == "cleanup_verified"
    assert result["cleanup_verified_count"] == 1
    assert result["final_loaded_instances"] == 0
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert raw_instance_id not in serialized


def test_run_exact_model_operation_prefers_operation_error_over_cleanup_failure() -> None:
    raw_instance_id = "instance-secret-12345"
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            return _load_payload(raw_instance_id)
        if len(calls) == 2:
            return _models_payload_map({"google/gemma-4-e2b": (raw_instance_id,)})
        if len(calls) == 3:
            payload = json.loads(request.data.decode("utf-8"))
            assert payload == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 4:
            return _models_payload_map({"google/gemma-4-e2b": (raw_instance_id,)})
        raise AssertionError(f"unexpected request #{len(calls)}")

    with pytest.raises(RuntimeError, match="operation boom"):
        lmstudio_model_lifecycle.run_exact_model_operation(
            "http://127.0.0.1:1234",
            model_id="google/gemma-4-e2b",
            context_length=8192,
            parallel=1,
            timeout_s=120.0,
            transport=fake_transport,
            operation=lambda _state: (_ for _ in ()).throw(RuntimeError("operation boom")),
        )

    unload_payload = json.loads(calls[2][2].decode("utf-8"))
    assert unload_payload != {"instance_id": "*"}
    assert unload_payload != {"instance_id": "all"}


def test_probe_lifecycle_cli_dry_run_writes_artifacts_without_transport_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    calls: list[str] = []

    def fail_transport(request, timeout_s: float) -> bytes:
        calls.append(f"{request.get_method()} {request.full_url} {timeout_s}")
        raise AssertionError("transport must not be used in dry-run")

    monkeypatch.setenv("LM_API_TOKEN", "secret-token-value-1234567890")
    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fail_transport),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-dry",
            "--model-id",
            "qwen3.5-4b",
            "--scenario",
            "controlled_load_echo",
        ]
    )

    assert exit_code == 0
    assert calls == []

    run_dir = tmp_path / "run_probe-lifecycle-dry_model_lifecycle"
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "lifecycle_summary.json",
        "lifecycle_events.jsonl",
        "report.md",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    summary_text = (run_dir / "lifecycle_summary.json").read_text(encoding="utf-8")
    events_text = (run_dir / "lifecycle_events.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, summary_text, report_text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(summary_text, events_text, report_text)
    assert events_text == ""

    summary_payload = json.loads(summary_text)
    assert summary_payload["status"] == "planned"
    assert summary_payload["execute_lifecycle"] is False
    assert summary_payload["endpoint_kinds_planned"] == ["native_load", "native_list"]
    assert summary_payload["endpoint_kinds_used"] == []
    assert "endpoint_paths_planned" not in summary_payload
    assert "endpoint_paths_used" not in summary_payload
    assert summary_payload["scenario"] == "controlled_load_echo"
    assert "endpoint_kinds_planned" in report_text
    assert "endpoint_kinds_used" in report_text
    assert "no network, load, or unload actions" in report_text


def test_probe_lifecycle_cli_dry_run_load_timeout_reconcile_uses_endpoint_kinds_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    calls: list[str] = []

    def fail_transport(request, timeout_s: float) -> bytes:
        calls.append(f"{request.get_method()} {request.full_url} {timeout_s}")
        raise AssertionError("transport must not be used in dry-run")

    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fail_transport),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-timeout-dry",
            "--model-id",
            "qwen3.5-4b",
            "--scenario",
            "load_timeout_reconcile",
        ]
    )

    assert exit_code == 0
    assert calls == []

    run_dir = tmp_path / "run_probe-lifecycle-timeout-dry_model_lifecycle"
    summary_text = (run_dir / "lifecycle_summary.json").read_text(encoding="utf-8")
    events_text = (run_dir / "lifecycle_events.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (summary_text, report_text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(summary_text, events_text, report_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["status"] == "planned"
    assert summary_payload["scenario"] == "load_timeout_reconcile"
    assert summary_payload["endpoint_kinds_planned"] == ["native_load", "native_list"]
    assert summary_payload["endpoint_kinds_used"] == []
    assert "endpoint_paths_planned" not in summary_payload
    assert "endpoint_paths_used" not in summary_payload


def test_probe_lifecycle_controlled_load_echo_uses_post_then_get_and_hashes_only() -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-secret-12345"

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if request.get_method() == "POST":
            payload = json.loads(request.data.decode("utf-8"))
            assert payload == {
                "model": "qwen3.5-4b",
                "context_length": 8192,
                "parallel": 1,
                "echo_load_config": True,
            }
            return _load_payload(raw_instance_id)
        return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="controlled_load_echo",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert [(method, url) for method, url, _data in calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "ok"
    assert result.summary["load_verified"] is True
    assert result.summary["applied_context_length"] == 8192
    assert result.summary["applied_parallel"] == 1
    assert result.summary["context_length_verified"] is True
    assert result.summary["parallel_verified"] is True
    assert result.summary["instance_id_hash"] == _instance_hash(raw_instance_id)
    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    assert raw_instance_id not in serialized


def test_probe_lifecycle_cli_unload_happy_path_keeps_artifacts_and_logs_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    raw_instance_id = "instance-secret-12345"
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        if len(calls) == 2:
            assert request.get_method() == "POST"
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        return _models_payload_map({"qwen3.5-4b": ()})

    monkeypatch.setenv("LM_API_TOKEN", "secret-token-value-1234567890")
    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fake_transport),
    )
    caplog.set_level(logging.INFO, logger="tools.lmstudio_lab.model_lifecycle")

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-unload",
            "--model-id",
            "qwen3.5-4b",
            "--scenario",
            "unload_happy_path",
            "--execute-lifecycle",
        ]
    )

    assert exit_code == 0
    assert [(method, url) for method, url, _data in calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]

    run_dir = tmp_path / "run_probe-lifecycle-unload_model_lifecycle"
    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    summary_text = (run_dir / "lifecycle_summary.json").read_text(encoding="utf-8")
    events_text = (run_dir / "lifecycle_events.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, summary_text, events_text, report_text, caplog.text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(summary_text, events_text, report_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["status"] == "ok"
    assert summary_payload["instance_id_hash"] == _instance_hash(raw_instance_id)
    assert summary_payload["endpoint_kinds_planned"] == [
        "native_list",
        "native_unload",
        "native_list",
    ]
    assert summary_payload["endpoint_kinds_used"] == [
        "native_list",
        "native_unload",
        "native_list",
    ]
    assert "endpoint_paths_planned" not in summary_payload
    assert "endpoint_paths_used" not in summary_payload


def test_external_unload_detected_after_poll(capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-secret-12345"

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        if len(calls) == 1:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": "qwen3.5-4b",
                "context_length": 8192,
                "parallel": 1,
                "echo_load_config": True,
            }
            return _load_payload(raw_instance_id)
        if len(calls) == 2:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        if len(calls) == 3:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="external_unload_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
        sleep=lambda _seconds: None,
    )

    stdout_text = capsys.readouterr().out
    assert "MANUAL_ACTION_REQUIRED" in stdout_text
    assert raw_instance_id not in stdout_text
    assert [(method, url) for method, url, _data in calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "externally_unloaded"
    assert result.summary["load_called"] is True
    assert result.summary["load_verified"] is True
    assert result.summary["unload_called"] is False
    assert result.summary["observed_loaded_count_initial"] == 1
    assert result.summary["observed_loaded_count_final"] == 0
    assert result.summary["poll_count"] == 2


def test_external_unload_timeout_without_unload_post(capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-secret-12345"

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        if request.get_method() == "POST":
            return _load_payload(raw_instance_id)
        return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="external_unload_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
        sleep=lambda _seconds: None,
        max_polls=2,
    )

    stdout_text = capsys.readouterr().out
    assert "MANUAL_ACTION_REQUIRED" in stdout_text
    assert [(method, url) for method, url, _data in calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "manual_unload_not_observed"
    assert result.summary["unload_called"] is False
    assert result.summary["cleanup_not_performed"] is True
    assert result.summary["poll_count"] == 2
    assert result.summary["observed_loaded_count_final"] == 1


def test_manual_unload_does_not_persist_raw_instance_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_instance_id = "instance-secret-12345"

    def fake_transport(request, _timeout_s: float) -> bytes:
        if request.get_method() == "POST":
            return _load_payload(raw_instance_id)
        return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="external_unload_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
        sleep=lambda _seconds: None,
        max_polls=1,
    )

    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_lifecycle_report(
        run_id="manual-unload-persist-check",
        summary=result.summary,
    )
    stdout_text = capsys.readouterr().out

    assert raw_instance_id not in serialized
    assert raw_instance_id not in report_text
    assert raw_instance_id not in stdout_text


def test_external_unload_artifacts_privacy_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    raw_instance_id = "instance-secret-12345"
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            return _load_payload(raw_instance_id)
        if len(calls) == 2:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        return _models_payload_map({"qwen3.5-4b": ()})

    monkeypatch.setenv("LM_API_TOKEN", "secret-token-value-1234567890")
    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fake_transport),
    )
    caplog.set_level(logging.INFO, logger="tools.lmstudio_lab.model_lifecycle")

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-external-unload",
            "--model-id",
            "qwen3.5-4b",
            "--scenario",
            "external_unload_reconcile",
            "--execute-lifecycle",
        ]
    )

    stdout_text = capsys.readouterr().out
    assert exit_code == 0
    assert [(method, url) for method, url, _data in calls] == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]

    run_dir = tmp_path / "run_probe-lifecycle-external-unload_model_lifecycle"
    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    summary_text = (run_dir / "lifecycle_summary.json").read_text(encoding="utf-8")
    events_text = (run_dir / "lifecycle_events.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (
        environment_text,
        summary_text,
        events_text,
        report_text,
        caplog.text,
        stdout_text,
    ):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(summary_text, events_text, report_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["status"] == "externally_unloaded"
    assert summary_payload["instance_id_hash"] == _instance_hash(raw_instance_id)
    assert summary_payload["unload_called"] is False
    assert summary_payload["endpoint_kinds_planned"] == ["native_load", "native_list"]
    assert summary_payload["endpoint_kinds_used"] == [
        "native_load",
        "native_list",
        "native_list",
    ]
    assert "endpoint_paths_planned" not in summary_payload
    assert "endpoint_paths_used" not in summary_payload
    assert "MANUAL_ACTION_REQUIRED" in stdout_text


def test_external_unload_loaded_count_zero_clears_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_instance_id = "instance-secret-12345"
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST":
            return _load_payload(raw_instance_id)
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="external_unload_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    stdout_text = capsys.readouterr().out
    assert stdout_text == ""
    assert calls == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "already_unloaded"
    assert result.summary["observed_loaded_count_initial"] == 0
    assert result.summary["observed_loaded_count_final"] == 0
    assert result.summary["poll_count"] == 0
    assert result.summary["unload_called"] is False


def test_external_unload_still_loaded_returns_not_observed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_instance_id = "instance-secret-12345"

    def fake_transport(request, _timeout_s: float) -> bytes:
        if request.get_method() == "POST":
            return _load_payload(raw_instance_id)
        return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="external_unload_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
        sleep=lambda _seconds: None,
        max_polls=1,
    )

    stdout_text = capsys.readouterr().out
    assert "MANUAL_ACTION_REQUIRED" in stdout_text
    assert result.summary["status"] == "manual_unload_not_observed"
    assert result.summary["observed_loaded_count_final"] == 1
    assert result.summary["cleanup_not_performed"] is True


def test_probe_lifecycle_duplicate_load_guard_detects_duplicates_without_post() -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        return _models_payload_map(
            {"qwen3.5-4b": ("instance-secret-12345", "instance-secondary-67890")}
        )

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="duplicate_load_guard",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [("GET", "http://127.0.0.1:1234/api/v1/models")]
    assert result.summary["status"] == "duplicate_instances"
    assert result.summary["load_called"] is False
    assert result.summary["unload_called"] is False


def test_probe_lifecycle_duplicate_load_behavior_dry_run_plans_safe_endpoint_kinds_without_transport_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    calls: list[str] = []

    def fail_transport(request, timeout_s: float) -> bytes:
        calls.append(f"{request.get_method()} {request.full_url} {timeout_s}")
        raise AssertionError("transport must not be used in dry-run")

    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fail_transport),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-duplicate-load-behavior-dry",
            "--model-id",
            "qwen3.5-4b",
            "--scenario",
            "duplicate_load_behavior",
        ]
    )

    assert exit_code == 0
    assert calls == []

    run_dir = tmp_path / "run_probe-lifecycle-duplicate-load-behavior-dry_model_lifecycle"
    summary_text = (run_dir / "lifecycle_summary.json").read_text(encoding="utf-8")
    events_text = (run_dir / "lifecycle_events.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (summary_text, report_text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(summary_text, events_text, report_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["status"] == "planned"
    assert summary_payload["endpoint_kinds_planned"] == [
        "native_list",
        "native_load",
        "native_list",
        "native_load",
        "native_list",
        "native_unload",
        "native_unload",
        "native_list",
    ]
    assert summary_payload["endpoint_kinds_used"] == []
    assert "endpoint_paths_planned" not in summary_payload
    assert "endpoint_paths_used" not in summary_payload


def test_probe_lifecycle_policy_backed_smoke_dry_run_plans_safe_endpoint_kinds_without_transport_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    calls: list[str] = []

    def fail_transport(request, timeout_s: float) -> bytes:
        calls.append(f"{request.get_method()} {request.full_url} {timeout_s}")
        raise AssertionError("transport must not be used in dry-run")

    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fail_transport),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-policy-smoke-dry",
            "--model-id",
            "qwen3.5-4b",
            "--scenario",
            "policy_backed_smoke",
        ]
    )

    assert exit_code == 0
    assert calls == []

    run_dir = tmp_path / "run_probe-lifecycle-policy-smoke-dry_model_lifecycle"
    summary_text = (run_dir / "lifecycle_summary.json").read_text(encoding="utf-8")
    events_text = (run_dir / "lifecycle_events.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (summary_text, report_text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(summary_text, events_text, report_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["status"] == "planned"
    assert summary_payload["endpoint_kinds_planned"] == [
        "native_list",
        "native_load",
        "native_list",
        "native_list",
        "native_list",
        "native_unload",
        "native_list",
        "native_list",
    ]
    assert summary_payload["endpoint_kinds_used"] == []
    assert "endpoint_paths_planned" not in summary_payload
    assert "endpoint_paths_used" not in summary_payload


def test_probe_lifecycle_policy_two_model_swap_dry_run_requires_secondary_and_uses_endpoint_kinds_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    calls: list[str] = []

    with pytest.raises(ValueError, match="secondary_model_id"):
        lmstudio_lab.probe_model_lifecycle(
            "http://127.0.0.1:1234",
            model_id="qwen3.5-4b",
            scenario="policy_two_model_swap",
            execute_lifecycle=False,
        )

    def fail_transport(request, timeout_s: float) -> bytes:
        calls.append(f"{request.get_method()} {request.full_url} {timeout_s}")
        raise AssertionError("transport must not be used in dry-run")

    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fail_transport),
    )

    missing_secondary_run_dir = (
        tmp_path / "run_probe-lifecycle-policy-two-swap-missing-secondary_model_lifecycle"
    )
    with pytest.raises(
        ValueError,
        match=r"--secondary-model-id.*policy_two_model_swap",
    ):
        lmstudio_benchmark.main(
            [
                "probe-lifecycle",
                "--output-root",
                str(tmp_path),
                "--run-id",
                "probe-lifecycle-policy-two-swap-missing-secondary",
                "--model-id",
                "qwen3.5-4b",
                "--scenario",
                "policy_two_model_swap",
            ]
        )

    assert calls == []
    assert not missing_secondary_run_dir.exists()

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-policy-two-swap-dry",
            "--model-id",
            "qwen3.5-4b",
            "--secondary-model-id",
            "google/gemma-4-e4b",
            "--scenario",
            "policy_two_model_swap",
        ]
    )

    assert exit_code == 0
    assert calls == []

    run_dir = tmp_path / "run_probe-lifecycle-policy-two-swap-dry_model_lifecycle"
    summary_text = (run_dir / "lifecycle_summary.json").read_text(encoding="utf-8")
    events_text = (run_dir / "lifecycle_events.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (summary_text, report_text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(summary_text, events_text, report_text)

    summary_payload = json.loads(summary_text)
    assert summary_payload["status"] == "planned"
    assert summary_payload["secondary_model_id"] == "google/gemma-4-e4b"
    assert summary_payload["swap_policy"] == "single_model_safe_wvm_owned_only"
    assert summary_payload["endpoint_kinds_planned"] == [
        "native_list",
        "native_load",
        "native_list",
        "native_unload",
        "native_list",
        "native_load",
        "native_list",
        "native_unload",
        "native_list",
    ]
    assert summary_payload["endpoint_kinds_used"] == []
    assert "endpoint_paths_planned" not in summary_payload
    assert "endpoint_paths_used" not in summary_payload


def test_probe_lifecycle_duplicate_load_behavior_preloaded_not_clean_skips_post_load_and_unload() -> (
    None
):
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        return _models_payload_map({"qwen3.5-4b": ("instance-secret-12345",)})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="duplicate_load_behavior",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [("GET", "http://127.0.0.1:1234/api/v1/models")]
    assert result.summary["status"] == "preloaded_not_clean"
    assert result.summary["baseline_loaded_count"] == 1
    assert result.summary["final_loaded_count"] == 1
    assert result.summary["load_called"] is False
    assert result.summary["second_load_called"] is False
    assert result.summary["unload_called"] is False
    assert result.summary["cleanup_called"] is False
    assert result.summary["cleanup_not_performed"] is True


def test_probe_lifecycle_duplicate_load_behavior_idempotent_reuse_outcome_final_count_one() -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-primary-12345"

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            return _models_payload_map({"qwen3.5-4b": ()})
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
            return _load_payload(raw_instance_id)
        if len(calls) == 3:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        if len(calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
            return _load_payload(raw_instance_id)
        if len(calls) == 5:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        if len(calls) == 6:
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="duplicate_load_behavior",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert [(method, url) for method, url, _data in calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "duplicate_reused_or_idempotent"
    assert result.summary["duplicate_outcome"] == "duplicate_reused_or_idempotent"
    assert result.summary["baseline_loaded_count"] == 0
    assert result.summary["first_load_verified"] is True
    assert result.summary["second_load_called"] is True
    assert result.summary["final_loaded_count"] == 1
    assert result.summary["distinct_instance_hash_count"] == 1
    assert result.summary["cleanup_called"] is True
    assert result.summary["cleanup_verified_count"] == 1
    assert result.summary["cleanup_remaining_count"] == 0
    assert result.summary["owned_instance_hashes"] == [_instance_hash(raw_instance_id)]


def test_probe_lifecycle_duplicate_load_behavior_duplicate_instances_confirmed_and_cleanup_exact_ids_only() -> (
    None
):
    calls: list[tuple[str, str, bytes | None]] = []
    raw_primary_instance_id = "instance-primary-12345"
    raw_secondary_instance_id = "instance-secondary-67890"

    def fake_transport(request, timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        assert timeout_s == 120.0
        if len(calls) == 1:
            return _models_payload_map({"qwen3.5-4b": ()})
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
            return _load_payload(raw_primary_instance_id)
        if len(calls) == 3:
            return _models_payload_map({"qwen3.5-4b": (raw_primary_instance_id,)})
        if len(calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
            return _load_payload(raw_secondary_instance_id)
        if len(calls) == 5:
            return _models_payload_map(
                {"qwen3.5-4b": (raw_primary_instance_id, raw_secondary_instance_id)}
            )
        if len(calls) == 6:
            assert json.loads(request.data.decode("utf-8")) == {
                "instance_id": raw_primary_instance_id
            }
            return b'{"status":"ok"}'
        if len(calls) == 7:
            assert json.loads(request.data.decode("utf-8")) == {
                "instance_id": raw_secondary_instance_id
            }
            return b'{"status":"ok"}'
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="duplicate_load_behavior",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    unload_payloads = [
        json.loads(data.decode("utf-8"))
        for method, url, data in calls
        if method == "POST" and url.endswith("/api/v1/models/unload") and data is not None
    ]
    assert result.summary["status"] == "duplicate_instances_confirmed"
    assert result.summary["duplicate_outcome"] == "duplicate_instances_confirmed"
    assert result.summary["final_loaded_count"] == 2
    assert result.summary["duplicate_instance_count"] == 2
    assert result.summary["distinct_instance_hash_count"] == 2
    assert result.summary["cleanup_called"] is True
    assert result.summary["cleanup_verified_count"] == 2
    assert result.summary["cleanup_remaining_count"] == 0
    assert result.summary["owned_instance_hashes"] == [
        _instance_hash(raw_primary_instance_id),
        _instance_hash(raw_secondary_instance_id),
    ]
    assert unload_payloads == [
        {"instance_id": raw_primary_instance_id},
        {"instance_id": raw_secondary_instance_id},
    ]


def test_probe_lifecycle_duplicate_load_behavior_duplicate_rejected_is_safe_and_observes_final_state_when_possible(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_instance_id = "instance-primary-12345"
    calls: list[tuple[str, str]] = []
    caplog.set_level(logging.INFO, logger="tools.lmstudio_lab.model_lifecycle")

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        if len(calls) == 1:
            return _models_payload_map({"qwen3.5-4b": ()})
        if len(calls) == 2:
            return _load_payload(raw_instance_id)
        if len(calls) == 3:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        if len(calls) == 4:
            raise urllib_error.HTTPError(
                request.full_url,
                409,
                "Conflict",
                hdrs=None,
                fp=io.BytesIO(
                    b'{"error":"raw body should not leak","token":"secret-token-value-1234567890"}'
                ),
            )
        if len(calls) == 5:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        if len(calls) == 6:
            assert json.loads(request.data.decode("utf-8")) == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="duplicate_load_behavior",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_lifecycle_report(
        run_id="duplicate-load-rejected",
        summary=result.summary,
    )

    assert calls == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "duplicate_rejected"
    assert result.summary["duplicate_outcome"] == "duplicate_rejected"
    assert result.summary["error_category"] == "http_error"
    assert result.summary["http_status"] == 409
    assert result.summary["final_loaded_count"] == 1
    assert result.summary["cleanup_verified_count"] == 1
    assert result.summary["cleanup_remaining_count"] == 0
    _assert_safe_text(serialized, project_root=Path(__file__).resolve().parents[2])
    _assert_safe_text(report_text, project_root=Path(__file__).resolve().parents[2])
    _assert_safe_text(caplog.text, project_root=Path(__file__).resolve().parents[2])


def test_probe_lifecycle_duplicate_load_behavior_raw_instance_ids_are_not_persisted_or_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_primary_instance_id = "instance-primary-12345"
    raw_secondary_instance_id = "instance-secondary-67890"
    caplog.set_level(logging.INFO, logger="tools.lmstudio_lab.model_lifecycle")

    calls = iter(
        [
            _models_payload_map({"qwen3.5-4b": ()}),
            _load_payload(raw_primary_instance_id),
            _models_payload_map({"qwen3.5-4b": (raw_primary_instance_id,)}),
            _load_payload(raw_secondary_instance_id),
            _models_payload_map(
                {"qwen3.5-4b": (raw_primary_instance_id, raw_secondary_instance_id)}
            ),
            b'{"status":"ok"}',
            b'{"status":"ok"}',
            _models_payload_map({"qwen3.5-4b": ()}),
        ]
    )

    def fake_transport(_request, _timeout_s: float) -> bytes:
        return next(calls)

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="duplicate_load_behavior",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_lifecycle_report(
        run_id="duplicate-load-privacy",
        summary=result.summary,
    )

    assert raw_primary_instance_id not in serialized
    assert raw_secondary_instance_id not in serialized
    assert raw_primary_instance_id not in report_text
    assert raw_secondary_instance_id not in report_text
    assert raw_primary_instance_id not in caplog.text
    assert raw_secondary_instance_id not in caplog.text


def test_probe_lifecycle_duplicate_load_behavior_never_sends_wildcard_unload() -> None:
    raw_primary_instance_id = "instance-primary-12345"
    raw_secondary_instance_id = "instance-secondary-67890"
    unload_payloads: list[dict[str, object]] = []
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        if len(calls) == 1:
            return _models_payload_map({"qwen3.5-4b": ()})
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
            return _load_payload(raw_primary_instance_id)
        if len(calls) == 3:
            return _models_payload_map({"qwen3.5-4b": (raw_primary_instance_id,)})
        if len(calls) == 4:
            assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
            return _load_payload(raw_secondary_instance_id)
        if len(calls) == 5:
            return _models_payload_map(
                {"qwen3.5-4b": (raw_primary_instance_id, raw_secondary_instance_id)}
            )
        if len(calls) in {6, 7}:
            unload_payloads.append(json.loads(request.data.decode("utf-8")))
            return b'{"status":"ok"}'
        return _models_payload_map({"qwen3.5-4b": ()})

    lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="duplicate_load_behavior",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert unload_payloads == [
        {"instance_id": raw_primary_instance_id},
        {"instance_id": raw_secondary_instance_id},
    ]
    assert all(sorted(payload) == ["instance_id"] for payload in unload_payloads)


def test_probe_lifecycle_policy_backed_smoke_happy_path_records_decisions_and_prevents_duplicate_load() -> (
    None
):
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-primary-12345"

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="policy_backed_smoke",
        execute_lifecycle=True,
        transport=_policy_backed_smoke_happy_transport(calls, raw_instance_id=raw_instance_id),
    )

    assert [(method, url) for method, url, _data in calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "policy_smoke_ok"
    assert result.summary["policy_step_decisions"] == [
        "load_required",
        "reuse_existing",
        "unload_required",
        "already_unloaded",
    ]
    assert result.summary["duplicate_prevented"] is True
    assert result.summary["load_call_count"] == 1
    assert result.summary["unload_call_count"] == 1
    assert result.summary["observed_loaded_count_after_load"] == 1
    assert result.summary["observed_loaded_count_after_unload"] == 0
    assert result.summary["instance_id_hash"] == _instance_hash(raw_instance_id)
    assert result.summary["owned_instance_hashes"] == [_instance_hash(raw_instance_id)]

    decision_actions = [
        event["decision_action"]
        for event in result.event_records
        if event.get("event_kind") == "policy_decision"
    ]
    assert decision_actions == [
        "load_required",
        "reuse_existing",
        "unload_required",
        "already_unloaded",
    ]


def test_probe_lifecycle_policy_backed_smoke_preloaded_not_clean_skips_post_actions() -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        return _models_payload_map({"qwen3.5-4b": ("instance-secret-12345",)})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="policy_backed_smoke",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [("GET", "http://127.0.0.1:1234/api/v1/models")]
    assert result.summary["status"] == "policy_smoke_preloaded_not_clean"
    assert result.summary["baseline_loaded_count"] == 1
    assert result.summary["load_called"] is False
    assert result.summary["unload_called"] is False
    assert result.summary["load_call_count"] == 0
    assert result.summary["unload_call_count"] == 0


def test_probe_lifecycle_policy_backed_smoke_reuse_step_does_not_call_load() -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-primary-12345"

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="policy_backed_smoke",
        execute_lifecycle=True,
        transport=_policy_backed_smoke_happy_transport(calls, raw_instance_id=raw_instance_id),
    )

    load_calls = [
        (method, url)
        for method, url, _data in calls
        if method == "POST" and url.endswith("/api/v1/models/load")
    ]
    assert load_calls == [("POST", "http://127.0.0.1:1234/api/v1/models/load")]
    assert result.summary["policy_step_decisions"][:2] == [
        "load_required",
        "reuse_existing",
    ]
    assert result.summary["duplicate_prevented"] is True
    assert result.summary["load_call_count"] == 1


def test_probe_lifecycle_policy_backed_smoke_already_gone_step_does_not_call_unload() -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-primary-12345"

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="policy_backed_smoke",
        execute_lifecycle=True,
        transport=_policy_backed_smoke_happy_transport(calls, raw_instance_id=raw_instance_id),
    )

    unload_calls = [
        (method, url)
        for method, url, _data in calls
        if method == "POST" and url.endswith("/api/v1/models/unload")
    ]
    assert unload_calls == [("POST", "http://127.0.0.1:1234/api/v1/models/unload")]
    assert result.summary["policy_step_decisions"][-1] == "already_unloaded"
    assert result.summary["unload_call_count"] == 1


def test_probe_lifecycle_policy_backed_smoke_keeps_outputs_private_and_unloads_exact_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    calls: list[tuple[str, str, bytes | None]] = []
    raw_instance_id = "instance-primary-12345"
    unload_payloads: list[dict[str, object]] = []
    caplog.set_level(logging.INFO, logger="tools.lmstudio_lab.model_lifecycle")

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="policy_backed_smoke",
        execute_lifecycle=True,
        transport=_policy_backed_smoke_happy_transport(
            calls,
            raw_instance_id=raw_instance_id,
            unload_payloads=unload_payloads,
        ),
    )

    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_lifecycle_report(
        run_id="policy-backed-smoke-privacy",
        summary=result.summary,
    )

    for text in (serialized, report_text, caplog.text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(serialized, report_text, caplog.text)
    assert raw_instance_id not in serialized
    assert raw_instance_id not in report_text
    assert raw_instance_id not in caplog.text
    assert unload_payloads == [{"instance_id": raw_instance_id}]
    assert all(sorted(payload) == ["instance_id"] for payload in unload_payloads)


def test_probe_lifecycle_unload_already_gone_returns_success_without_post() -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="unload_already_gone",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [("GET", "http://127.0.0.1:1234/api/v1/models")]
    assert result.summary["status"] == "already_unloaded"
    assert result.summary["unload_called"] is False


def test_probe_lifecycle_load_timeout_reconcile_classifies_response_lost_and_cleans_exact_id() -> (
    None
):
    calls: list[tuple[str, str]] = []
    raw_instance_id = "instance-secret-12345"
    unload_payloads: list[dict[str, object]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST":
            if request.full_url.endswith("/api/v1/models/load"):
                assert json.loads(request.data.decode("utf-8")) == _load_payload_dict()
                raise TimeoutError("timeout")
            unload_payloads.append(json.loads(request.data.decode("utf-8")))
            assert unload_payloads[-1] == {"instance_id": raw_instance_id}
            return b'{"status":"ok"}'
        if len(calls) == 2:
            return _models_payload_map({"qwen3.5-4b": (raw_instance_id,)})
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="load_timeout_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert unload_payloads == [{"instance_id": raw_instance_id}]
    assert all(sorted(payload) == ["instance_id"] for payload in unload_payloads)
    assert result.summary["status"] == "load_succeeded_but_response_lost"
    assert result.summary["error_category"] is None
    assert result.summary["load_verified"] is True
    assert result.summary["instance_id_hash"] == _instance_hash(raw_instance_id)
    assert result.summary["cleanup_called"] is True
    assert result.summary["cleanup_target_instance_hashes"] == [_instance_hash(raw_instance_id)]
    assert result.summary["cleanup_verification_observed"] is True
    assert result.summary["cleanup_final_loaded_count"] == 0
    assert result.summary["cleanup_remaining_count"] == 0
    assert result.summary["observed_loaded_count_initial"] == 1
    assert result.summary["observed_loaded_count_final"] == 0

    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_lifecycle_report(
        run_id="load-timeout-reconcile",
        summary=result.summary,
    )

    assert raw_instance_id not in serialized
    assert raw_instance_id not in report_text


def test_probe_lifecycle_load_timeout_reconcile_absent_after_timeout_skips_unload() -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST":
            raise TimeoutError("timeout")
        return _models_payload_map({"qwen3.5-4b": ()})

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="load_timeout_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "load_unknown_or_failed"
    assert result.summary["error_category"] == "timeout"
    assert result.summary["load_verified"] is False
    assert result.summary["unload_called"] is False
    assert result.summary["cleanup_called"] is False
    assert result.summary["observed_loaded_count_initial"] == 0
    assert result.summary["observed_loaded_count_final"] == 0


@pytest.mark.parametrize(
    ("reconcile_response", "expected_status", "expected_category"),
    [
        (TimeoutError("second timeout"), "transport_error", "timeout"),
        (
            b'{"body":"raw body should not leak","path":"/api/v1/models"',
            "decode_error",
            "json",
        ),
    ],
)
def test_probe_lifecycle_load_timeout_reconcile_safe_error_when_list_reconcile_fails(
    reconcile_response: object,
    expected_status: str,
    expected_category: str,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        if len(calls) == 1:
            raise TimeoutError("timeout")
        if isinstance(reconcile_response, Exception):
            raise reconcile_response
        return reconcile_response

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        scenario="load_timeout_reconcile",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "load_reconcile_error"
    assert result.summary["error_category"] == "reconcile"
    assert result.summary["reconcile_status"] == expected_status
    assert result.summary["reconcile_error_category"] == expected_category
    assert result.summary["cleanup_not_performed"] is True
    assert result.summary["unload_called"] is False

    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_lifecycle_report(
        run_id="load-timeout-reconcile-error",
        summary=result.summary,
    )
    _assert_no_raw_endpoint_paths(serialized, report_text)
    assert "raw body should not leak" not in serialized
    assert "raw body should not leak" not in report_text


def test_probe_lifecycle_two_model_swap_plan_dry_run_requires_secondary_and_execute_swaps() -> None:
    with pytest.raises(ValueError, match="secondary_model_id"):
        lmstudio_lab.probe_model_lifecycle(
            "http://127.0.0.1:1234",
            model_id="qwen3.5-4b",
            scenario="two_model_swap_plan",
            execute_lifecycle=False,
        )

    dry_run_result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        secondary_model_id="qwen3.5-1.5b",
        scenario="two_model_swap_plan",
        execute_lifecycle=False,
        transport=lambda _request, _timeout_s: (_ for _ in ()).throw(
            AssertionError("no transport")
        ),
    )
    assert dry_run_result.summary["status"] == "planned"
    assert dry_run_result.summary["secondary_model_id"] == "qwen3.5-1.5b"
    assert dry_run_result.summary["swap_policy"] == "single_model_safe_wvm_owned_only"

    calls: list[tuple[str, str, bytes | None]] = []
    raw_primary_instance_id = "instance-primary-12345"
    raw_secondary_instance_id = "instance-secondary-67890"

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url, request.data))
        if len(calls) == 1:
            return _models_payload_map({"qwen3.5-4b": (raw_primary_instance_id,)})
        if len(calls) == 2:
            assert json.loads(request.data.decode("utf-8")) == {
                "instance_id": raw_primary_instance_id
            }
            return b'{"status":"ok"}'
        if len(calls) == 3:
            assert json.loads(request.data.decode("utf-8")) == {
                "model": "qwen3.5-1.5b",
                "context_length": 8192,
                "parallel": 1,
                "echo_load_config": True,
            }
            return _load_payload(raw_secondary_instance_id)
        return _models_payload_map(
            {
                "qwen3.5-4b": (),
                "qwen3.5-1.5b": (raw_secondary_instance_id,),
            }
        )

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        secondary_model_id="qwen3.5-1.5b",
        scenario="two_model_swap_plan",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert [(method, url) for method, url, _data in calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]
    assert result.summary["status"] == "ok"
    assert result.summary["secondary_load_verified"] is True
    assert result.summary["swap_policy"] == "single_model_safe_wvm_owned_only"


def test_probe_lifecycle_policy_two_model_swap_happy_path_uses_exact_load_unload_sequence() -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    unload_payloads: list[dict[str, object]] = []
    raw_primary_instance_id = "instance-primary-12345"
    raw_secondary_instance_id = "instance-secondary-67890"

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        secondary_model_id="google/gemma-4-e4b",
        scenario="policy_two_model_swap",
        execute_lifecycle=True,
        transport=_policy_two_model_swap_happy_transport(
            calls,
            raw_primary_instance_id=raw_primary_instance_id,
            raw_secondary_instance_id=raw_secondary_instance_id,
            unload_payloads=unload_payloads,
        ),
    )

    assert [(method, url) for method, url, _data in calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]

    load_payloads = [
        json.loads(data.decode("utf-8"))
        for method, url, data in calls
        if method == "POST" and url.endswith("/api/v1/models/load") and data is not None
    ]
    assert load_payloads == [
        _load_payload_dict(model_id="qwen3.5-4b"),
        _load_payload_dict(model_id="google/gemma-4-e4b"),
    ]
    assert unload_payloads == [
        {"instance_id": raw_primary_instance_id},
        {"instance_id": raw_secondary_instance_id},
    ]
    assert all(sorted(payload) == ["instance_id"] for payload in unload_payloads)

    assert result.summary["status"] == "policy_swap_ok"
    assert result.summary["swap_policy"] == "single_model_safe_wvm_owned_only"
    assert result.summary["policy_step_decisions"] == [
        "primary_load_required",
        "primary_unload_required",
        "secondary_load_required",
        "secondary_cleanup_unload_required",
    ]
    assert result.summary["load_call_count"] == 2
    assert result.summary["unload_call_count"] == 2
    assert result.summary["primary_load_call_count"] == 1
    assert result.summary["primary_unload_call_count"] == 1
    assert result.summary["secondary_load_call_count"] == 1
    assert result.summary["secondary_unload_call_count"] == 1
    assert result.summary["primary_loaded_after_load"] == 1
    assert result.summary["primary_loaded_after_unload"] == 0
    assert result.summary["secondary_loaded_after_load"] == 1
    assert result.summary["primary_loaded_after_secondary_load"] == 0
    assert result.summary["secondary_loaded_after_cleanup"] == 0
    assert result.summary["primary_loaded_after_cleanup"] == 0
    assert result.summary["single_model_safe_verified"] is True
    assert result.summary["cleanup_called"] is True
    assert result.summary["cleanup_secondary_target_instance_hashes"] == [
        _instance_hash(raw_secondary_instance_id)
    ]
    assert result.summary["cleanup_secondary_verified_count"] == 1
    assert result.summary["cleanup_secondary_remaining_count"] == 0
    assert result.summary["cleanup_secondary_verification_observed"] is True
    assert result.summary["primary_instance_id_hash"] == _instance_hash(raw_primary_instance_id)
    assert result.summary["secondary_instance_id_hash"] == _instance_hash(raw_secondary_instance_id)


def test_probe_lifecycle_cli_policy_two_model_swap_happy_path_returns_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bytes | None]] = []

    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(
            _policy_two_model_swap_happy_transport(
                calls,
                raw_primary_instance_id="instance-primary-12345",
                raw_secondary_instance_id="instance-secondary-67890",
            )
        ),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-policy-two-model-swap",
            "--model-id",
            "qwen3.5-4b",
            "--secondary-model-id",
            "google/gemma-4-e4b",
            "--scenario",
            "policy_two_model_swap",
            "--execute-lifecycle",
        ]
    )

    assert exit_code == 0
    assert [(method, url) for method, url, _data in calls] == [
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/load"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
        ("POST", "http://127.0.0.1:1234/api/v1/models/unload"),
        ("GET", "http://127.0.0.1:1234/api/v1/models"),
    ]

    run_dir = tmp_path / "run_probe-lifecycle-policy-two-model-swap_model_lifecycle"
    summary_payload = json.loads((run_dir / "lifecycle_summary.json").read_text(encoding="utf-8"))
    assert summary_payload["status"] == "policy_swap_ok"


@pytest.mark.parametrize(
    ("preloaded_instances", "expected_primary", "expected_secondary"),
    [
        ({"qwen3.5-4b": ("instance-primary-12345",), "google/gemma-4-e4b": ()}, 1, 0),
        ({"qwen3.5-4b": (), "google/gemma-4-e4b": ("instance-secondary-67890",)}, 0, 1),
    ],
)
def test_probe_lifecycle_policy_two_model_swap_preloaded_not_clean_skips_post_actions(
    preloaded_instances: dict[str, tuple[str, ...]],
    expected_primary: int,
    expected_secondary: int,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        return _models_payload_map(preloaded_instances)

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        secondary_model_id="google/gemma-4-e4b",
        scenario="policy_two_model_swap",
        execute_lifecycle=True,
        transport=fake_transport,
    )

    assert calls == [("GET", "http://127.0.0.1:1234/api/v1/models")]
    assert result.summary["status"] == "policy_swap_preloaded_not_clean"
    assert result.summary["baseline_primary_loaded_count"] == expected_primary
    assert result.summary["baseline_secondary_loaded_count"] == expected_secondary
    assert result.summary["load_called"] is False
    assert result.summary["unload_called"] is False
    assert result.summary["load_call_count"] == 0
    assert result.summary["unload_call_count"] == 0


@pytest.mark.parametrize(
    "preloaded_instances",
    [
        {"qwen3.5-4b": ("instance-primary-12345",), "google/gemma-4-e4b": ()},
        {"qwen3.5-4b": (), "google/gemma-4-e4b": ("instance-secondary-67890",)},
    ],
)
def test_probe_lifecycle_cli_policy_two_model_swap_preloaded_not_clean_returns_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preloaded_instances: dict[str, tuple[str, ...]],
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        calls.append((request.get_method(), request.full_url))
        return _models_payload_map(preloaded_instances)

    monkeypatch.setattr(
        lmstudio_benchmark,
        "probe_model_lifecycle",
        _wrap_probe_with_transport(fake_transport),
    )

    exit_code = lmstudio_benchmark.main(
        [
            "probe-lifecycle",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-lifecycle-policy-two-model-swap-preloaded",
            "--model-id",
            "qwen3.5-4b",
            "--secondary-model-id",
            "google/gemma-4-e4b",
            "--scenario",
            "policy_two_model_swap",
            "--execute-lifecycle",
        ]
    )

    assert exit_code == 0
    assert calls == [("GET", "http://127.0.0.1:1234/api/v1/models")]

    run_dir = tmp_path / "run_probe-lifecycle-policy-two-model-swap-preloaded_model_lifecycle"
    summary_payload = json.loads((run_dir / "lifecycle_summary.json").read_text(encoding="utf-8"))
    assert summary_payload["status"] == "policy_swap_preloaded_not_clean"


def test_probe_lifecycle_policy_two_model_swap_keeps_outputs_private_and_uses_endpoint_kinds_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    calls: list[tuple[str, str, bytes | None]] = []
    raw_primary_instance_id = "instance-primary-12345"
    raw_secondary_instance_id = "instance-secondary-67890"
    caplog.set_level(logging.INFO, logger="tools.lmstudio_lab.model_lifecycle")

    result = lmstudio_lab.probe_model_lifecycle(
        "http://127.0.0.1:1234",
        model_id="qwen3.5-4b",
        secondary_model_id="google/gemma-4-e4b",
        scenario="policy_two_model_swap",
        execute_lifecycle=True,
        transport=_policy_two_model_swap_happy_transport(
            calls,
            raw_primary_instance_id=raw_primary_instance_id,
            raw_secondary_instance_id=raw_secondary_instance_id,
        ),
    )

    serialized = json.dumps(
        {"summary": result.summary, "events": result.event_records},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_text = lmstudio_lab.render_model_lifecycle_report(
        run_id="policy-two-model-swap-privacy",
        summary=result.summary,
    )

    for text in (serialized, report_text, caplog.text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(serialized, report_text, caplog.text)
    assert raw_primary_instance_id not in serialized
    assert raw_secondary_instance_id not in serialized
    assert raw_primary_instance_id not in report_text
    assert raw_secondary_instance_id not in report_text
    assert raw_primary_instance_id not in caplog.text
    assert raw_secondary_instance_id not in caplog.text
    assert {event.get("endpoint_kind") for event in result.event_records} <= {
        "native_list",
        "native_load",
        "native_unload",
        "policy",
    }


def test_probe_lifecycle_cli_rejects_remote_url_without_allow_remote(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="allow-remote"):
        lmstudio_benchmark.main(
            [
                "probe-lifecycle",
                "--output-root",
                str(tmp_path),
                "--model-id",
                "qwen3.5-4b",
                "--scenario",
                "controlled_load_echo",
                "--base-url",
                "http://10.10.10.10:1234",
            ]
        )

    assert list(tmp_path.iterdir()) == []
