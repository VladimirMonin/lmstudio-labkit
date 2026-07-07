from __future__ import annotations

import ast
import json
from pathlib import Path

from tools import lmstudio_lab


def test_metric_record_rejects_legacy_live_error_categories() -> None:
    legacy_categories = (
        "json_decode_error",
        "schema_error",
        "business_error",
        "reasoning_leak",
        "empty_content",
        "finish_length",
        "network_error",
    )

    for category in legacy_categories:
        record = lmstudio_lab.LMStudioLabMetricRecord.from_parts(
            run_id="run-legacy-category",
            error_category=category,
        )
        assert record.error_category == "unknown"


def test_metric_record_serializes_null_token_fields() -> None:
    record = lmstudio_lab.LMStudioLabMetricRecord.from_parts(
        run_id="run-001",
        experiment_id="exp-alpha",
        dataset_id="blocks_json_small",
        dataset_hash="sha256:abc123",
        model_key="qwen-small",
        model_id="qwen/qwen3-4b-instruct",
        endpoint_kind="compat_chat",
        mode="structured_json",
        configured_parallel=2,
        applied_parallel=2,
        parallel_verified=None,
        queue_pressure_mode=False,
        parallel_semantics="true_parallel",
        structured_schema_variant="per_position_id_const",
        content_empty=False,
        reasoning_content_present=False,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "factual_blocks_v1",
                "strict": True,
                "schema": {"type": "object"},
            },
        },
        applied_load_config={
            "context_length": 8192,
            "flash_attention": True,
            "prompt": "SENTINEL_PROMPT",
        },
        tokens=lmstudio_lab.TokenMetrics(
            estimated_input_tokens=128,
            prompt_tokens=128,
            completion_tokens=None,
            total_tokens=None,
        ),
        validation=lmstudio_lab.ValidationMetrics(
            json_parse_pass=True,
            schema_pass=True,
            business_pass=True,
            non_empty_text_pass=True,
            reasoning_leak=False,
            retry_count=0,
            finish_reason="stop",
            expected_count=2,
            returned_count=2,
            expected_ids=(101, 102),
            returned_ids=(101, 102),
            duplicate_ids=(),
            missing_ids=(),
            extra_ids=(),
            reordered_positions=(),
            reordered_count=0,
            reordered_positions_truncated=False,
        ),
    )

    payload = record.to_dict()

    assert payload["response_format"] == {
        "kind": "json_schema",
        "schema_name": "factual_blocks_v1",
        "strict": True,
    }
    assert payload["applied_load_config"]["context_length"] == 8192
    assert payload["applied_load_config"]["other_field_names"] == []
    assert payload["tokens"]["estimate_scope"] == "dataset_only"
    assert payload["tokens"]["completion_tokens"] is None
    assert payload["tokens"]["total_tokens"] is None
    assert payload["tokens"]["actual_output_tokens"] is None
    assert payload["content_empty"] is False
    assert payload["reasoning_content_present"] is False
    assert payload["validation"]["expected_count"] == 2
    assert payload["validation"]["returned_count"] == 2
    assert payload["validation"]["expected_ids"] == [101, 102]
    assert payload["validation"]["returned_ids"] == [101, 102]
    assert payload["validation"]["duplicate_ids"] == []
    assert payload["validation"]["missing_ids"] == []
    assert payload["validation"]["extra_ids"] == []
    assert payload["validation"]["reordered_positions"] == []
    assert payload["validation"]["reordered_count"] == 0
    assert payload["validation"]["reordered_positions_truncated"] is False
    assert payload["configured_parallel"] == 2
    assert payload["applied_parallel"] == 2
    assert payload["parallel_verified"] is None
    assert payload["queue_pressure_mode"] is False
    assert payload["parallel_semantics"] == "true_parallel"
    assert payload["structured_schema_variant"] == "per_position_id_const"
    assert payload["privacy_redaction_count"] == 1

    serialized = json.dumps(payload, sort_keys=True)
    assert "SENTINEL_PROMPT" not in serialized
    assert '"completion_tokens": null' in serialized
    assert '"content_empty": false' in serialized
    assert '"parallel_semantics": "true_parallel"' in serialized
    assert '"reasoning_content_present": false' in serialized


def test_jsonl_writer_keeps_id_diagnostics_and_never_stores_text_fields(tmp_path) -> None:
    target = tmp_path / "structured_errors.jsonl"
    payload = {
        "run_id": "run-id-diagnostics",
        "error_category": "business",
        "expected_count": 4,
        "returned_count": 4,
        "expected_ids": [10, 20, 30, 40],
        "returned_ids": [10, 30, 30, 50],
        "duplicate_ids": [30],
        "missing_ids": [20, 40],
        "extra_ids": [50],
        "reordered_positions": [
            {"position": 1, "expected_id": 20, "returned_id": 30},
            {"position": 3, "expected_id": 40, "returned_id": 50},
        ],
        "normalized_text": "SENTINEL_RAW_TEXT",
        "response": "SENTINEL_RAW_RESPONSE",
    }

    written = lmstudio_lab.append_jsonl_record(target, payload)

    assert written["expected_count"] == 4
    assert written["returned_count"] == 4
    assert written["expected_ids"] == [10, 20, 30, 40]
    assert written["returned_ids"] == [10, 30, 30, 50]
    assert written["duplicate_ids"] == [30]
    assert written["missing_ids"] == [20, 40]
    assert written["extra_ids"] == [50]
    assert written["reordered_positions"] == [
        {"position": 1, "expected_id": 20, "returned_id": 30},
        {"position": 3, "expected_id": 40, "returned_id": 50},
    ]
    assert written["normalized_text"] == lmstudio_lab.REDACTED_VALUE
    assert written["response"] == lmstudio_lab.REDACTED_VALUE

    serialized = target.read_text(encoding="utf-8")
    assert "SENTINEL_RAW_TEXT" not in serialized
    assert "SENTINEL_RAW_RESPONSE" not in serialized


def test_jsonl_writer_redacts_forbidden_values_and_creates_parent_dir(tmp_path) -> None:
    target = tmp_path / "nested" / "metrics.jsonl"
    payload = {
        "run_id": "run-privacy",
        "prompt_tokens": 42,
        "response_format": {"kind": "json_schema"},
        "validation": {"non_empty_text_pass": True},
        "payload": {
            "apiKey": "SENTINEL_API_KEY",
            "filePath": "C:/secret/camel-case.txt",
            "messages": [{"content": "SENTINEL_MESSAGE_CONTENT"}],
            "prompt": "SENTINEL_PROMPT",
            "providerBody": "SENTINEL_PROVIDER_BODY",
            "rawBody": "SENTINEL_RAW_BODY",
            "transcript": "SENTINEL_TRANSCRIPT",
            "response": "SENTINEL_RESPONSE",
            "file_path": "C:/secret/transcript.txt",
        },
    }

    written = lmstudio_lab.append_jsonl_record(target, payload)

    assert target.exists()
    assert written["prompt_tokens"] == 42
    assert written["response_format"] == {"kind": "json_schema"}
    assert written["validation"]["non_empty_text_pass"] is True
    assert written["payload"]["apiKey"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["filePath"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["messages"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["prompt"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["providerBody"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["rawBody"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["transcript"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["response"] == lmstudio_lab.REDACTED_VALUE
    assert written["payload"]["file_path"] == lmstudio_lab.REDACTED_VALUE
    assert written["privacy_redaction_count"] == 9

    line = target.read_text(encoding="utf-8")
    assert "SENTINEL_API_KEY" not in line
    assert "SENTINEL_MESSAGE_CONTENT" not in line
    assert "SENTINEL_PROMPT" not in line
    assert "SENTINEL_PROVIDER_BODY" not in line
    assert "SENTINEL_RAW_BODY" not in line
    assert "SENTINEL_TRANSCRIPT" not in line
    assert "SENTINEL_RESPONSE" not in line
    assert "C:/secret/camel-case.txt" not in line
    assert "C:/secret/transcript.txt" not in line


def test_sanitize_metric_payload_keeps_payload_wrapper_and_redacts_nested_urls() -> None:
    raw_url = "https://private.example.test/v1/jobs/abc?token=secret"
    payload = {
        "run_id": "run-payload-wrapper",
        "payload": {
            "url": raw_url,
            "safe_note": f"url={raw_url}",
            "nested": {
                "instance_id": "raw-instance-123",
                "download_hint": raw_url,
                "keep": "ok",
            },
        },
    }

    sanitized, redaction_count = lmstudio_lab.sanitize_metric_payload(payload)

    assert isinstance(sanitized["payload"], dict)
    assert sanitized["payload"]["url"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["payload"]["safe_note"] == "url=[REDACTED]"
    assert sanitized["payload"]["nested"]["instance_id"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["payload"]["nested"]["download_hint"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["payload"]["nested"]["keep"] == "ok"
    assert redaction_count == 4


def test_find_privacy_violations_flags_raw_urls_without_changing_path_detection() -> None:
    raw_url = "https://private.example.test/v1/jobs/abc?token=secret"
    raw_path = r"C:\Users\Private\LM Studio\secret.txt"

    violations = lmstudio_lab.find_privacy_violations(
        {
            "payload": {
                "safe_note": f"url={raw_url}",
                "download_hint": raw_url,
                "attachment_hint": raw_path,
            }
        },
        context="",
    )

    assert "payload.safe_note contains a raw URL" in violations
    assert "payload.download_hint contains a raw URL" in violations
    assert "payload.attachment_hint contains an absolute path" in violations


def test_forbidden_key_detection_supports_camel_case_without_false_allowlist_hits() -> None:
    assert lmstudio_lab.is_forbidden_metric_key("apiKey") is True
    assert lmstudio_lab.is_forbidden_metric_key("filePath") is True
    assert lmstudio_lab.is_forbidden_metric_key("providerBody") is True
    assert lmstudio_lab.is_forbidden_metric_key("rawBody") is True
    assert lmstudio_lab.is_forbidden_metric_key("body") is True
    assert lmstudio_lab.is_forbidden_metric_key("API_KEY") is True
    assert lmstudio_lab.is_forbidden_metric_key("ApiToken") is True
    assert lmstudio_lab.is_forbidden_metric_key("authorization") is True
    assert lmstudio_lab.is_forbidden_metric_key("requestBody") is True
    assert lmstudio_lab.is_forbidden_metric_key("rawResponse") is True

    assert lmstudio_lab.is_forbidden_metric_key("prompt_tokens") is False
    assert lmstudio_lab.is_forbidden_metric_key("content_hash") is False
    assert lmstudio_lab.is_forbidden_metric_key("response_format") is False
    assert lmstudio_lab.is_forbidden_metric_key("total_output_tokens") is False
    assert lmstudio_lab.is_forbidden_metric_key("reasoning_output_tokens") is False
    assert lmstudio_lab.is_forbidden_metric_key("empty_text_count") is False
    assert lmstudio_lab.is_forbidden_metric_key("non_empty_text_pass") is False
    assert lmstudio_lab.is_forbidden_metric_key("prompt_hash") is False
    assert lmstudio_lab.is_forbidden_metric_key("prompt_chars") is False
    assert lmstudio_lab.is_forbidden_metric_key("response_hash") is False
    assert lmstudio_lab.is_forbidden_metric_key("response_chars") is False
    assert lmstudio_lab.is_forbidden_metric_key("raw_prompt_response_stored") is False
    assert lmstudio_lab.is_forbidden_metric_key("structured_prompt_variant") is False
    assert lmstudio_lab.is_forbidden_metric_key("structured_schema_variant") is False
    assert lmstudio_lab.is_forbidden_metric_key("structured_reasoning_control_variant") is False
    assert lmstudio_lab.is_forbidden_metric_key("text_length") is False
    assert lmstudio_lab.is_forbidden_metric_key("normalized_text_length") is False
    assert lmstudio_lab.is_forbidden_metric_key("total_prompt_tokens") is False


def test_sanitize_metric_payload_preserves_safe_metric_keys_with_text_prompt_response_words() -> (
    None
):
    payload = {
        "empty_text_count": 2,
        "prompt_hash": "sha256:prompt-placeholder",
        "prompt_chars": 128,
        "response_hash": "sha256:response-placeholder",
        "response_chars": 256,
        "raw_prompt_response_stored": False,
        "structured_prompt_variant": "anti_reasoning",
        "structured_schema_variant": "per_position_id_const",
        "structured_reasoning_control_variant": "chat_template_kwargs_enable_thinking_false",
        "text_length": 42,
        "normalized_text_length": 40,
        "total_prompt_tokens": 384,
        "text": "SENTINEL_RAW_TEXT",
        "prompt": "SENTINEL_RAW_PROMPT",
        "response": "SENTINEL_RAW_RESPONSE",
        "messages": [{"content": "SENTINEL_RAW_CONTENT"}],
    }

    sanitized, redaction_count = lmstudio_lab.sanitize_metric_payload(payload)

    assert sanitized["empty_text_count"] == 2
    assert sanitized["prompt_hash"] == "sha256:prompt-placeholder"
    assert sanitized["prompt_chars"] == 128
    assert sanitized["response_hash"] == "sha256:response-placeholder"
    assert sanitized["response_chars"] == 256
    assert sanitized["raw_prompt_response_stored"] is False
    assert sanitized["structured_prompt_variant"] == "anti_reasoning"
    assert sanitized["structured_schema_variant"] == "per_position_id_const"
    assert (
        sanitized["structured_reasoning_control_variant"]
        == "chat_template_kwargs_enable_thinking_false"
    )
    assert sanitized["text_length"] == 42
    assert sanitized["normalized_text_length"] == 40
    assert sanitized["total_prompt_tokens"] == 384
    assert sanitized["text"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["prompt"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["response"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["messages"] == lmstudio_lab.REDACTED_VALUE
    assert redaction_count == 4


def test_jsonl_writer_uses_sorted_deterministic_output(tmp_path) -> None:
    target = tmp_path / "metrics.jsonl"

    lmstudio_lab.append_jsonl_record(target, {"b": 2, "a": 1})

    assert target.read_text(encoding="utf-8") == '{"a": 1, "b": 2}\n'


def test_sanitize_metric_payload_redacts_nested_text_and_absolute_user_paths() -> None:
    payload = {
        "content_hash": "sha256:stable-placeholder",
        "model_id": "qwen/qwen3-4b-instruct",
        "notes": [
            {"content": "SENTINEL_CONTENT"},
            {
                "attachment": "C:\\Users\\Vladimir\\Videos\\lecture.mp4",
                "metadata": {
                    "location": "/Users/vladimir/Documents/lecture.mov",
                    "messageText": "SENTINEL_MESSAGE_TEXT",
                    "safe_model": "qwen/qwen3-4b-instruct",
                    "secondary": "/home/vladimir/lecture.wav",
                },
            },
        ],
    }

    sanitized, redaction_count = lmstudio_lab.sanitize_metric_payload(payload)

    assert sanitized["content_hash"] == "sha256:stable-placeholder"
    assert sanitized["model_id"] == "qwen/qwen3-4b-instruct"
    assert sanitized["notes"][0]["content"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["notes"][1]["attachment"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["notes"][1]["metadata"]["location"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["notes"][1]["metadata"]["messageText"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["notes"][1]["metadata"]["safe_model"] == "qwen/qwen3-4b-instruct"
    assert sanitized["notes"][1]["metadata"]["secondary"] == lmstudio_lab.REDACTED_VALUE
    assert redaction_count == 5


def test_sanitize_metric_payload_redacts_absolute_paths_with_spaces() -> None:
    payload = {
        "windows_drive": r"C:\Users\Vladimir\My Videos\lecture.mp4",
        "windows_slash": "C:/Users/Vladimir/My Videos/lecture.mp4",
        "mac_home": "/Users/vladimir/My Documents/lecture.mov",
        "linux_home": "/home/vladimir/My Lectures/lecture.wav",
        "network_share": r"\\SERVER\Share Name\lecture.mp4",
        "safe_model": "qwen/qwen3-4b-instruct",
    }

    sanitized, redaction_count = lmstudio_lab.sanitize_metric_payload(payload)

    assert sanitized["windows_drive"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["windows_slash"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["mac_home"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["linux_home"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["network_share"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["safe_model"] == "qwen/qwen3-4b-instruct"
    assert redaction_count == 5


def test_sanitize_metric_payload_redacts_secret_synonyms_and_error_surfaces() -> None:
    payload = {
        "request": {
            "API_KEY": "SENTINEL_API_KEY",
            "ApiToken": "SENTINEL_API_TOKEN",
            "authorization": "Bearer SENTINEL",
            "bearer": "SENTINEL_BEARER",
            "secret": "SENTINEL_SECRET",
            "requestBody": "SENTINEL_REQUEST_BODY",
            "rawResponse": "SENTINEL_RAW_RESPONSE",
            "error": {
                "message": "SENTINEL_ERROR_MESSAGE",
                "rawBody": "SENTINEL_ERROR_BODY",
            },
            "run_id": "run-123",
        }
    }

    sanitized, redaction_count = lmstudio_lab.sanitize_metric_payload(payload)

    assert sanitized["request"]["API_KEY"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["ApiToken"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["authorization"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["bearer"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["secret"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["requestBody"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["rawResponse"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["error"] == lmstudio_lab.REDACTED_VALUE
    assert sanitized["request"]["run_id"] == "run-123"
    assert redaction_count == 8


def test_lab_files_do_not_reference_forbidden_runtime_imports() -> None:
    project_root = Path(__file__).resolve().parents[2]
    files_to_scan = sorted((project_root / "tools" / "lmstudio_lab").glob("*.py"))
    files_to_scan.append(project_root / "tools" / "lmstudio_benchmark.py")
    forbidden_modules = (
        "src",
        "src.services",
        "src.ui",
        "src.infrastructure.storage",
        "src.application.services",
        "src.infrastructure.llm.prompt_loader",
        "src.core.event_bus",
        "PySide6",
        "peewee",
        "jsonschema",
        "pydantic",
        "fastjsonschema",
        "transformers",
        "tokenizers",
        "tiktoken",
    )

    def _is_forbidden(module_name: str) -> bool:
        return any(
            module_name == forbidden or module_name.startswith(f"{forbidden}.")
            for forbidden in forbidden_modules
        )

    for path in files_to_scan:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders: list[str] = []
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden(alias.name):
                        offenders.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if _is_forbidden(node.module):
                    offenders.append(node.module)

        assert not offenders, f"forbidden imports in {path}: {sorted(set(offenders))}"
