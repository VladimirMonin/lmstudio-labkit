from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

import pytest
from lmstudio_labkit.strict_vision import (
    StrictStructuredVisionRunner,
    StrictVisionRequest,
    StrictVisionRunnerError,
)

from lmstudio_labkit import LocalFailureForensics, LocalLMStudioHostRunner

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_DATA_URL = f"data:image/png;base64,{PNG_BASE64}"
PNG_DIGEST = hashlib.sha256(base64.b64decode(PNG_BASE64)).hexdigest()
SCHEMA = {
    "type": "object",
    "required": ["description", "visible_text", "warnings"],
    "additionalProperties": False,
    "properties": {
        "description": {"type": "string", "minLength": 1},
        "visible_text": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


class CapturingStrictVisionHost:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.loaded_instances = 0

    def count_all_loaded_instances(self) -> int | None:
        self.calls.append(("count_all_loaded_instances", {}))
        return self.loaded_instances

    def model_metadata(self, *, model_id: str) -> Mapping[str, object] | None:
        self.calls.append(("model_metadata", {"model_id": model_id}))
        return {
            "type": "llm",
            "key": model_id,
            "capabilities": {"vision": True},
            "loaded_instances": (
                [
                    {
                        "model_key": model_id,
                        "context_length": 8192,
                        "parallel": 1,
                    }
                ]
                if self.loaded_instances
                else []
            ),
        }

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append(
            (
                "load_model",
                {"model_id": model_id, "context_length": context_length, "parallel": parallel},
            )
        )
        self.loaded_instances = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def strict_chat_completion(
        self, *, endpoint_path: str, payload: dict[str, object], timeout_s: float
    ) -> object:
        self.calls.append(
            (
                "strict_chat_completion",
                {"endpoint_path": endpoint_path, "payload": payload, "timeout_s": timeout_s},
            )
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append(("cleanup_model", {"model_id": model_id}))
        self.loaded_instances = 0
        return {"cleanup_verified": True}


class UnverifiedCleanupHost(CapturingStrictVisionHost):
    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append(("cleanup_model", {"model_id": model_id}))
        return {"cleanup_verified": False}


class VerifiedNonzeroCleanupHost(CapturingStrictVisionHost):
    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append(("cleanup_model", {"model_id": model_id}))
        return {"cleanup_verified": True}


class RecordingLocalStrictHost(LocalLMStudioHostRunner):
    calls: ClassVar[list[tuple[str, object, float]]] = []
    native_payloads: ClassVar[list[Mapping[str, object]]] = []

    def _request_json(
        self, path: str, payload: Mapping[str, object] | None, timeout_s: float
    ) -> dict[str, object]:
        type(self).calls.append((path, payload, timeout_s))
        return {"choices": []}

    def _request_native_chat(
        self,
        *,
        payload: Mapping[str, object],
        timeout_s: float,
        stream: bool,
    ) -> tuple[bytes, str, int]:
        type(self).native_payloads.append(payload)
        response = {
            "output": [{"type": "message", "content": "Visible fixture"}],
            "finish_reason": "stop",
        }
        return json.dumps(response).encode(), "application/json", 200


def _response(content: str, *, finish_reason: str = "stop") -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 6,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _request() -> StrictVisionRequest:
    return StrictVisionRequest(
        request_id="vision-cell",
        model_id="mock/vision",
        preflight_prompt="Return a synthetic schema-conforming object.",
        image_prompt="Describe the image without inventing text.",
        image_data_url=PNG_DATA_URL,
        fixture_id="fixture-1",
        fixture_sha256=PNG_DIGEST,
        fixture_width=1,
        fixture_height=1,
        schema_name="simple_description",
        schema=SCHEMA,
        image_ground_truth={
            "expected_visible_text": ["Settings"],
            "expected_objects": [],
            "forbidden_claims": ["private customer"],
            "minimum_visible_text_recall": 1.0,
        },
        max_tokens=512,
    )


def _runner(
    tmp_path: Path, host: CapturingStrictVisionHost
) -> tuple[StrictStructuredVisionRunner, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    private_root = tmp_path / "owner-only"
    forensics = LocalFailureForensics(private_root, repo_root=repo, enabled=True)
    return (
        StrictStructuredVisionRunner(
            host_runner=host,
            failure_forensics=forensics,
            allow_model_loads=True,
            allow_unpinned_test_requests=True,
        ),
        private_root,
    )


def test_strict_vision_runner_sends_text_preflight_then_exact_schema_bound_image_payload(
    tmp_path: Path,
) -> None:
    preflight_value = {"description": "Synthetic", "visible_text": [], "warnings": []}
    image_value = {
        "description": "Settings panel",
        "visible_text": ["Settings"],
        "warnings": [],
    }
    host = CapturingStrictVisionHost(
        [_response(json.dumps(preflight_value)), _response(json.dumps(image_value))]
    )
    runner, private_root = _runner(tmp_path, host)

    result = runner.run(_request())

    chat_calls = [payload for name, payload in host.calls if name == "strict_chat_completion"]
    assert len(chat_calls) == 2
    text_payload = chat_calls[0]["payload"]
    image_payload = chat_calls[1]["payload"]
    assert (
        text_payload["response_format"]
        == image_payload["response_format"]
        == {
            "type": "json_schema",
            "json_schema": {"name": "simple_description", "strict": True, "schema": SCHEMA},
        }
    )
    assert text_payload["messages"] == [
        {"role": "user", "content": "Return a synthetic schema-conforming object."}
    ]
    assert image_payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe the image without inventing text."},
                {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
            ],
        }
    ]
    for payload in (text_payload, image_payload):
        assert payload["reasoning_effort"] == "none"
        assert payload["enable_thinking"] is False
        assert payload["temperature"] == 0.0
        assert payload["max_tokens"] == 512

    assert result.preflight.transport_status == "pass"
    assert result.preflight.parse_status == "pass"
    assert result.preflight.schema_status == "pass"
    assert result.preflight.grounding_status == "skip"
    assert result.vision is not None
    assert result.vision.transport_status == "pass"
    assert result.vision.parse_status == "pass"
    assert result.vision.schema_status == "pass"
    assert result.vision.grounding_status == "pass"
    assert result.cleanup_verified is True
    assert result.final_loaded_global_count == 0

    private_files = sorted(private_root.glob("*.json"))
    assert len(private_files) == 2
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in private_files)
    captured = [json.loads(path.read_text(encoding="utf-8")) for path in private_files]
    assert {item["outbound"]["endpoint"] for item in captured} == {"/v1/chat/completions"}
    assert any(
        item["outbound"]["payload"]["messages"] == image_payload["messages"]
        and item["outbound"]["payload"]["response_format"] == image_payload["response_format"]
        for item in captured
    )


def test_local_host_forwards_strict_payload_without_reshaping() -> None:
    host = RecordingLocalStrictHost()
    type(host).calls = []
    payload = {
        "model": "mock/vision",
        "messages": [{"role": "user", "content": "Synthetic"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "simple", "strict": True, "schema": SCHEMA},
        },
    }

    response = host.strict_chat_completion(
        endpoint_path="/v1/chat/completions",
        payload=payload,
        timeout_s=12.0,
    )

    assert response == {"choices": []}
    assert host.calls == [("/v1/chat/completions", payload, 12.0)]


def test_local_native_host_opt_in_captures_exact_outbound_payload_and_safe_digest(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    private_root = tmp_path / "owner-only"
    forensics = LocalFailureForensics(private_root, repo_root=repo, enabled=True)
    host = RecordingLocalStrictHost(
        allow_native_diagnostics=True,
        failure_forensics=forensics,
    )
    type(host).native_payloads = []

    result = host.native_chat_diagnostic(
        model_id="mock/vision",
        messages=[{"role": "user", "content": "Describe visible content."}],
        reasoning=None,
        max_output_tokens=1024,
        timeout_s=12.0,
        stream=False,
        request_id="native-controller-row",
        attempt_index=2,
        context_length=8192,
        image_data_url=PNG_DATA_URL,
        capture_outbound_request=True,
    )

    assert len(type(host).native_payloads) == 1
    exact_payload = dict(type(host).native_payloads[0])
    assert result.forensics_handle is not None
    capture = json.loads(result.forensics_handle.path.read_text(encoding="utf-8"))
    assert capture["outbound"] == {"endpoint": "/api/v1/chat", "payload": exact_payload}
    safe = forensics.safe_manifest_entry(result.forensics_handle)["outbound"]
    assert isinstance(safe, dict)
    serialized = json.dumps(
        exact_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert safe["payload_sha256"] == hashlib.sha256(serialized.encode()).hexdigest()
    assert safe["image_data_url_present"] is True


def test_strict_vision_runner_blocks_image_when_text_preflight_is_not_schema_valid(
    tmp_path: Path,
) -> None:
    host = CapturingStrictVisionHost([_response('{"description":"missing fields"}')])
    runner, _private_root = _runner(tmp_path, host)

    result = runner.run(_request())

    assert result.preflight.transport_status == "pass"
    assert result.preflight.parse_status == "pass"
    assert result.preflight.schema_status == "fail"
    assert result.vision is None
    assert result.image_call_status == "blocked_by_text_preflight"
    assert [name for name, _payload in host.calls].count("strict_chat_completion") == 1
    assert result.cleanup_verified is True
    assert result.final_loaded_global_count == 0


def test_strict_vision_runner_keeps_schema_and_grounding_outcomes_separate(
    tmp_path: Path,
) -> None:
    value = {"description": "Synthetic", "visible_text": [], "warnings": []}
    host = CapturingStrictVisionHost([_response(json.dumps(value)), _response(json.dumps(value))])
    runner, _private_root = _runner(tmp_path, host)

    result = runner.run(_request())

    assert result.vision is not None
    assert result.vision.parse_status == "pass"
    assert result.vision.schema_status == "pass"
    assert result.vision.grounding_status == "fail"
    assert result.vision.accepted is False


def test_strict_vision_runner_records_transport_failure_and_still_cleans_up(tmp_path: Path) -> None:
    host = CapturingStrictVisionHost([RuntimeError("synthetic transport failure")])
    runner, private_root = _runner(tmp_path, host)

    result = runner.run(_request())

    assert result.preflight.transport_status == "fail"
    assert result.preflight.parse_status == "skip"
    assert result.preflight.schema_status == "skip"
    assert result.vision is None
    assert result.image_call_status == "blocked_by_text_preflight"
    assert result.cleanup_verified is True
    assert result.final_loaded_global_count == 0
    capture = json.loads(next(private_root.glob("*.json")).read_text(encoding="utf-8"))
    assert capture["transport"]["error_category"] == "RuntimeError"
    assert "synthetic transport failure" not in json.dumps(capture)


def test_strict_vision_runner_requires_enabled_owner_only_capture_before_loading(
    tmp_path: Path,
) -> None:
    host = CapturingStrictVisionHost([])
    repo = tmp_path / "repo"
    repo.mkdir()
    disabled = LocalFailureForensics(tmp_path / "private", repo_root=repo, enabled=False)
    runner = StrictStructuredVisionRunner(
        host_runner=host,
        failure_forensics=disabled,
        allow_model_loads=True,
        allow_unpinned_test_requests=True,
    )

    with pytest.raises(StrictVisionRunnerError, match="owner-only capture"):
        runner.run(_request())

    assert host.calls == []


def test_strict_vision_runner_fails_closed_when_cleanup_does_not_reach_global_zero(
    tmp_path: Path,
) -> None:
    value = {"description": "Synthetic", "visible_text": [], "warnings": []}
    host = UnverifiedCleanupHost([_response(json.dumps(value))])
    runner, _private_root = _runner(tmp_path, host)

    with pytest.raises(StrictVisionRunnerError, match="cleanup was not verified"):
        runner.run(_request())

    assert host.loaded_instances == 1
    assert [name for name, _payload in host.calls][-2:] == [
        "cleanup_model",
        "count_all_loaded_instances",
    ]


def test_strict_vision_runner_fails_closed_on_verified_cleanup_with_nonzero_global_count(
    tmp_path: Path,
) -> None:
    value = {"description": "Synthetic", "visible_text": [], "warnings": []}
    host = VerifiedNonzeroCleanupHost([_response(json.dumps(value))])
    runner, _private_root = _runner(tmp_path, host)

    with pytest.raises(StrictVisionRunnerError, match="final global loaded count"):
        runner.run(_request())

    assert host.loaded_instances == 1
