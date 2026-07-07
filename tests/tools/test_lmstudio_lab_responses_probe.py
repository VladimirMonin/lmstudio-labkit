from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from tools.lmstudio_lab import ManagedLabRunner
from tools.lmstudio_lab.tokens import estimate_input_tokens_from_chars


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path(name: str) -> Path:
    return _project_root() / "experiments" / "lmstudio" / "configs" / name


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


class _FakeResponsesTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.raw_response_ids: list[str] = []
        self.raw_previous_response_ids: list[str] = []

    def __call__(self, request, timeout_s: float) -> bytes:
        payload = json.loads(request.data.decode("utf-8"))
        response_id = f"resp-raw-{len(self.calls) + 1:04d}"
        previous_response_id = payload.get("previous_response_id")
        if isinstance(previous_response_id, str):
            self.raw_previous_response_ids.append(previous_response_id)
        self.raw_response_ids.append(response_id)
        self.calls.append(
            {
                "url": request.full_url,
                "timeout_s": timeout_s,
                "payload": payload,
            }
        )

        input_text = str(payload["input"])
        input_tokens = estimate_input_tokens_from_chars(len(input_text))
        output_tokens = 24 if int(payload["max_output_tokens"]) == 64 else 36
        usage: dict[str, object] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        if isinstance(previous_response_id, str):
            usage["input_tokens_details"] = {"cached_tokens": max(1, input_tokens // 2)}
        elif input_text.endswith("repeated-prefix answer beta."):
            usage["input_tokens_details"] = {"cached_tokens": max(1, input_tokens // 3)}
        elif input_text.endswith("mutated-prefix changed answer."):
            usage["input_tokens_details"] = {"cached_tokens": 0}

        return json.dumps(
            {
                "id": response_id,
                "status": "completed",
                "output_text": "Synthetic safe response text.",
                "usage": usage,
            }
        ).encode("utf-8")


class _FakeEmptyResponsesTransport(_FakeResponsesTransport):
    def __call__(self, request, timeout_s: float) -> bytes:
        payload = json.loads(request.data.decode("utf-8"))
        response_id = f"resp-empty-{len(self.calls) + 1:04d}"
        previous_response_id = payload.get("previous_response_id")
        if isinstance(previous_response_id, str):
            self.raw_previous_response_ids.append(previous_response_id)
        self.raw_response_ids.append(response_id)
        self.calls.append(
            {
                "url": request.full_url,
                "timeout_s": timeout_s,
                "payload": payload,
            }
        )

        input_text = str(payload["input"])
        input_tokens = estimate_input_tokens_from_chars(len(input_text))
        return json.dumps(
            {
                "id": response_id,
                "status": "completed",
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": 12,
                    "total_tokens": input_tokens + 12,
                    "input_tokens_details": {"cached_tokens": max(1, input_tokens // 4)},
                },
            }
        ).encode("utf-8")


class _FakeNoCacheResponsesTransport(_FakeResponsesTransport):
    def __call__(self, request, timeout_s: float) -> bytes:
        payload = json.loads(request.data.decode("utf-8"))
        response_id = f"resp-nocache-{len(self.calls) + 1:04d}"
        previous_response_id = payload.get("previous_response_id")
        if isinstance(previous_response_id, str):
            self.raw_previous_response_ids.append(previous_response_id)
        self.raw_response_ids.append(response_id)
        self.calls.append(
            {
                "url": request.full_url,
                "timeout_s": timeout_s,
                "payload": payload,
            }
        )

        input_text = str(payload["input"])
        input_tokens = estimate_input_tokens_from_chars(len(input_text))
        output_tokens = 24 if int(payload["max_output_tokens"]) == 64 else 36

        return json.dumps(
            {
                "id": response_id,
                "status": "completed",
                "output_text": "Synthetic safe response text.",
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            }
        ).encode("utf-8")


def test_runner_writes_responses_probe_artifacts_without_raw_ids_or_urls(tmp_path: Path) -> None:
    config_path = _config_path("l3_5r_responses_cache_probe_gemma4_e2b.yaml")
    run_dir = tmp_path / "responses-probe"
    transport = _FakeResponsesTransport()

    summary = ManagedLabRunner(lambda request: None).run_responses_cache_probe(
        config_path=config_path,
        run_dir=run_dir,
        run_id="responses-cache-probe-cli",
        responses_transport=transport,
    )

    expected_files = {
        "environment.json",
        "run_config.json",
        "requests.jsonl",
        "metrics.jsonl",
        "responses_usage_summary.json",
        "privacy_scan.json",
        "report.md",
    }
    assert {path.name for path in run_dir.iterdir()} == expected_files

    requests_rows = _read_jsonl(run_dir / "requests.jsonl")
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    environment_payload = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    run_config_payload = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    summary_payload = json.loads(
        (run_dir / "responses_usage_summary.json").read_text(encoding="utf-8")
    )
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    assert len(transport.calls) == 48
    assert len(requests_rows) == 48
    assert len(metrics_rows) == 48
    assert all(urlsplit(str(call["url"])).path == "/v1/responses" for call in transport.calls)
    assert all("/api/v1/" not in str(call["url"]) for call in transport.calls)

    assert summary["responses_cache_probe_status"] == "responses_cache_accounting_candidate"
    assert summary_payload["responses_cache_probe_status"] == "responses_cache_accounting_candidate"
    assert summary_payload["cached_tokens_available"] is True
    assert summary_payload["cached_tokens_observed"] is True
    assert summary_payload["previous_response_id_supported"] is True
    assert summary_payload["request_count"] == 48
    assert summary_payload["success_count"] == 48
    assert summary_payload["error_count"] == 0
    assert summary_payload["raw_usage_keys"] == [
        "input_tokens",
        "input_tokens_details",
        "input_tokens_details.cached_tokens",
        "output_tokens",
        "total_tokens",
    ]

    assert environment_payload["endpoint_family"] == "openai_responses"
    assert environment_payload["inference_endpoint_called"] is True
    assert environment_payload["production_default"] is False
    assert environment_payload["wvm_runtime_integration"] is False
    assert environment_payload["live_25k_authorized"] is False
    assert environment_payload["kv_reuse_proven"] is False
    assert run_config_payload["allow_real_user_content"] is False
    assert run_config_payload["store_raw_prompt_response"] is False
    assert run_config_payload["store_response_id_raw"] is False
    assert run_config_payload["hash_response_id"] is True
    assert run_config_payload["kv_reuse_proven"] is False

    for row in metrics_rows:
        assert row["endpoint_family"] == "openai_responses"
        assert row["inference_endpoint_called"] is True
        assert row["production_default"] is False
        assert row["wvm_runtime_integration"] is False
        assert row["live_25k_authorized"] is False
        assert row["kv_reuse_proven"] is False
        assert "prompt_processing_ms" not in row
        assert "model_load" not in json.dumps(row, sort_keys=True)
        assert "chat.end" not in json.dumps(row, sort_keys=True)

    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0
    assert "This probe does not replace native /api/v1/chat L3 instrumentation." in report_text
    assert (
        "The isolated /v1/responses spike can submit the configured synthetic request shapes"
        in report_text
    )

    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir())
    assert "http://127.0.0.1:1234" not in artifact_text
    for raw_response_id in transport.raw_response_ids:
        assert raw_response_id not in artifact_text
    for raw_previous_response_id in transport.raw_previous_response_ids:
        assert raw_previous_response_id not in artifact_text
    assert "sha256:" in artifact_text


def test_runner_blocks_when_responses_output_is_empty(tmp_path: Path) -> None:
    config_path = _config_path("l3_5r_responses_cache_probe_gemma4_e2b.yaml")
    run_dir = tmp_path / "responses-empty"
    transport = _FakeEmptyResponsesTransport()

    summary = ManagedLabRunner(lambda request: None).run_responses_cache_probe(
        config_path=config_path,
        run_dir=run_dir,
        run_id="responses-empty-probe",
        responses_transport=transport,
    )

    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    summary_payload = json.loads(
        (run_dir / "responses_usage_summary.json").read_text(encoding="utf-8")
    )
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))

    assert summary["responses_cache_probe_status"] == "responses_blocked"
    assert summary_payload["responses_cache_probe_status"] == "responses_blocked"
    assert summary_payload["success_count"] == 0
    assert summary_payload["error_count"] == 48
    assert all(row["error_type"] == "empty_output" for row in metrics_rows)
    assert all(row["finish_status"] == "empty_output" for row in metrics_rows)
    assert all(row["content_nonempty"] is False for row in metrics_rows)
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0

    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir())
    for raw_response_id in transport.raw_response_ids:
        assert raw_response_id not in artifact_text
    for raw_previous_response_id in transport.raw_previous_response_ids:
        assert raw_previous_response_id not in artifact_text


def test_runner_writes_16k_responses_probe_artifacts_without_raw_ids_or_urls(
    tmp_path: Path,
) -> None:
    config_path = _config_path("l3_5r_16k_responses_cache_probe_gemma4_e2b.yaml")
    run_dir = tmp_path / "responses-probe-16k"
    transport = _FakeResponsesTransport()

    summary = ManagedLabRunner(lambda request: None).run_responses_cache_probe(
        config_path=config_path,
        run_dir=run_dir,
        run_id="responses-cache-probe-16k-cli",
        responses_transport=transport,
    )

    requests_rows = _read_jsonl(run_dir / "requests.jsonl")
    metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
    run_config_payload = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    summary_payload = json.loads(
        (run_dir / "responses_usage_summary.json").read_text(encoding="utf-8")
    )
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))

    assert len(transport.calls) == 24
    assert summary_payload["request_count"] == 24
    assert summary_payload["success_count"] == 24
    assert summary_payload["error_count"] == 0
    assert len(requests_rows) == 24
    assert len(metrics_rows) == 24
    assert all(urlsplit(str(call["url"])).path == "/v1/responses" for call in transport.calls)
    assert all("/api/v1/" not in str(call["url"]) for call in transport.calls)
    assert all("/v1/chat/completions" not in str(call["url"]) for call in transport.calls)
    assert summary["responses_cache_probe_status"] == "responses_cache_accounting_candidate_16k"
    assert (
        summary_payload["responses_cache_probe_status"]
        == "responses_cache_accounting_candidate_16k"
    )
    assert summary_payload["cached_tokens_available"] is True
    assert summary_payload["cached_tokens_observed"] is True
    assert summary_payload["previous_response_id_supported"] is True
    assert run_config_payload["max_context_tokens"] == 16384
    assert run_config_payload["datasets"] == ["synthetic_16k_root"]
    assert run_config_payload["kv_reuse_proven"] is False
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0

    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir())
    assert "http://127.0.0.1:1234" not in artifact_text
    for raw_response_id in transport.raw_response_ids:
        assert raw_response_id not in artifact_text
    for raw_previous_response_id in transport.raw_previous_response_ids:
        assert raw_previous_response_id not in artifact_text
    assert "sha256:" in artifact_text


def test_runner_reports_16k_responses_probe_without_cached_token_accounting(
    tmp_path: Path,
) -> None:
    config_path = _config_path("l3_5r_16k_responses_cache_probe_gemma4_e2b.yaml")
    run_dir = tmp_path / "responses-probe-16k-no-cache"
    transport = _FakeNoCacheResponsesTransport()

    summary = ManagedLabRunner(lambda request: None).run_responses_cache_probe(
        config_path=config_path,
        run_dir=run_dir,
        run_id="responses-cache-probe-16k-no-cache-cli",
        responses_transport=transport,
    )

    summary_payload = json.loads(
        (run_dir / "responses_usage_summary.json").read_text(encoding="utf-8")
    )
    privacy_scan = json.loads((run_dir / "privacy_scan.json").read_text(encoding="utf-8"))

    assert summary_payload["request_count"] > 0
    assert summary_payload["request_count"] == 24
    assert summary_payload["success_count"] == summary_payload["request_count"]
    assert summary_payload["error_count"] == 0
    assert summary_payload["cached_tokens_available"] is False
    assert summary_payload["cached_tokens_observed"] is False
    assert summary_payload["responses_cache_probe_status"] == "responses_usable_no_cache_at_16k"
    assert summary_payload["kv_reuse_proven"] is False
    assert summary["responses_cache_probe_status"] == "responses_usable_no_cache_at_16k"
    assert summary["kv_reuse_proven"] is False
    assert privacy_scan["status"] == "pass"
    assert privacy_scan["violation_count"] == 0


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        (
            "max_context_tokens: 16384",
            "max_context_tokens: 8192",
            "responses cache probe requires safety.max_context_tokens=16384",
        ),
        (
            "  - synthetic_16k_root",
            "  - synthetic_8k_root",
            "responses cache probe requires datasets ['synthetic_16k_root']",
        ),
    ],
)
def test_runner_rejects_invalid_16k_responses_probe_config(
    tmp_path: Path,
    needle: str,
    replacement: str,
    message: str,
) -> None:
    config_text = _config_path("l3_5r_16k_responses_cache_probe_gemma4_e2b.yaml").read_text(
        encoding="utf-8"
    )
    config_path = tmp_path / "invalid-16k-responses-probe.yaml"
    config_path.write_text(config_text.replace(needle, replacement), encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape(message)):
        ManagedLabRunner(lambda request: None).run_responses_cache_probe(
            config_path=config_path,
            run_dir=tmp_path / "invalid-run",
            run_id="responses-cache-probe-invalid-16k",
            responses_transport=_FakeResponsesTransport(),
        )
