from __future__ import annotations

import base64
import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from lmstudio_labkit.strict_vision import (
    StrictStructuredVisionRunner,
    StrictVisionContinuationController,
    StrictVisionLaunchController,
    StrictVisionRequest,
    StrictVisionRunnerError,
    StructuredCallOutcome,
    build_strict_vision_fixture,
    load_strict_vision_continuation_manifest,
    load_strict_vision_launch_manifest,
    validate_strict_vision_grounding,
)

from lmstudio_labkit import LocalFailureForensics, LocalLMStudioHostRunner

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_BYTES = base64.b64decode(PNG_BASE64)
PNG_DIGEST = hashlib.sha256(PNG_BYTES).hexdigest()
CONTINUATION_MANIFEST_SHA256 = "4354fe01b23f3be5c1c43654ff5215604d99c980019f88d1d7630ce27ad06fc2"
SIMPLE_SCHEMA = {
    "type": "object",
    "required": ["description", "visible_text", "warnings"],
    "additionalProperties": False,
    "properties": {
        "description": {"type": "string", "minLength": 1},
        "visible_text": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


class GateHost:
    def __init__(self, responses: list[object], *, metadata: object | None = None) -> None:
        self.responses = list(responses)
        self.metadata = (
            {
                "type": "llm",
                "key": "mock/vision",
                "capabilities": {"vision": True},
                "loaded_instances": [],
            }
            if metadata is None
            else metadata
        )
        self.calls: list[str] = []
        self.loaded = 0

    def model_metadata(self, *, model_id: str) -> object | None:
        self.calls.append("model_metadata")
        if not self.loaded or not isinstance(self.metadata, dict):
            return self.metadata
        materialized = dict(self.metadata)
        materialized["loaded_instances"] = [
            {
                "model_key": model_id,
                "context_length": 8192,
                "parallel": 1,
            }
        ]
        return materialized

    def count_all_loaded_instances(self) -> int | None:
        self.calls.append("count_all_loaded_instances")
        return self.loaded

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append("load_model")
        self.loaded = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def strict_chat_completion(
        self, *, endpoint_path: str, payload: dict[str, object], timeout_s: float
    ) -> object:
        self.calls.append("strict_chat_completion")
        return self.responses.pop(0)

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append("cleanup_model")
        self.loaded = 0
        return {"cleanup_verified": True}


def _response(
    content: str,
    *,
    finish_reason: str = "stop",
    reasoning_tokens: int | None = 0,
    reasoning_content: str | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {"content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    usage: dict[str, object] = {"prompt_tokens": 8, "completion_tokens": 6}
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }


def _request() -> StrictVisionRequest:
    return StrictVisionRequest(
        request_id="vision-cell",
        model_id="mock/vision",
        preflight_prompt="Return a synthetic schema-conforming object.",
        image_prompt="Describe the image without inventing text.",
        image_data_url=f"data:image/png;base64,{PNG_BASE64}",
        fixture_id="fixture-1",
        fixture_sha256=PNG_DIGEST,
        fixture_width=1,
        fixture_height=1,
        schema_name="simple_description",
        schema=SIMPLE_SCHEMA,
        image_ground_truth={
            "expected_visible_text": ["Settings"],
            "expected_objects": [],
            "forbidden_claims": ["private customer"],
            "minimum_visible_text_recall": 1.0,
        },
        max_tokens=512,
    )


def _runner(tmp_path: Path, host: GateHost) -> StrictStructuredVisionRunner:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return StrictStructuredVisionRunner(
        host_runner=host,
        failure_forensics=LocalFailureForensics(
            tmp_path / "owner-only", repo_root=repo, enabled=True
        ),
        allow_model_loads=True,
        allow_unpinned_test_requests=True,
    )


def test_outcome_rejects_truncation_nonzero_reasoning_and_unobserved_reasoning() -> None:
    common: dict[str, Any] = {
        "modality": "image",
        "transport_status": "pass",
        "parse_status": "pass",
        "schema_status": "pass",
        "grounding_status": "pass",
    }
    assert (
        StructuredCallOutcome(**common, finish_reason="length", reasoning_status="zero").accepted
        is False
    )
    assert (
        StructuredCallOutcome(
            **common, finish_reason="stop", reasoning_status="nonzero", reasoning_tokens=2
        ).accepted
        is False
    )
    assert (
        StructuredCallOutcome(
            **common, finish_reason="stop", reasoning_status="unobserved"
        ).accepted
        is False
    )
    assert (
        StructuredCallOutcome(
            **common, finish_reason="stop", reasoning_status="zero", reasoning_tokens=0
        ).accepted
        is True
    )


def test_unpinned_single_request_runner_is_not_a_live_entry_point(tmp_path: Path) -> None:
    host = GateHost([])
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = StrictStructuredVisionRunner(
        host_runner=host,
        failure_forensics=LocalFailureForensics(
            tmp_path / "owner-only", repo_root=repo, enabled=True
        ),
        allow_model_loads=True,
    )

    with pytest.raises(StrictVisionRunnerError, match="manifest controller"):
        runner.run(_request())

    assert host.calls == []


@pytest.mark.parametrize(
    ("metadata", "match"),
    [
        ({"type": "llm", "key": "other", "capabilities": {"vision": True}}, "exact model"),
        ({"type": "llm", "key": "mock/vision", "capabilities": {"vision": False}}, "vision"),
        ({"type": "embedding", "key": "mock/vision", "capabilities": {"vision": True}}, "VLM"),
    ],
)
def test_model_metadata_preflight_fails_before_load(
    tmp_path: Path, metadata: dict[str, object], match: str
) -> None:
    host = GateHost([], metadata=metadata)

    with pytest.raises(StrictVisionRunnerError, match=match):
        _runner(tmp_path, host).run(_request())

    assert host.calls == ["model_metadata"]


def test_runner_extracts_and_hard_gates_reasoning_and_finish_reason(tmp_path: Path) -> None:
    value = json.dumps({"description": "Synthetic", "visible_text": [], "warnings": []})
    host = GateHost([_response(value, finish_reason="length", reasoning_tokens=0)])
    result = _runner(tmp_path, host).run(_request())
    assert result.preflight.finish_reason == "length"
    assert result.preflight.reasoning_status == "zero"
    assert result.preflight.accepted is False
    assert result.vision is None

    host = GateHost([_response(value, reasoning_tokens=1, reasoning_content="hidden")])
    result = _runner(tmp_path, host).run(_request())
    assert result.preflight.reasoning_status == "nonzero"
    assert result.preflight.reasoning_tokens == 1
    assert result.preflight.reasoning_content_present is True
    assert result.preflight.accepted is False


def test_request_rejects_fixture_digest_or_dimension_mismatch_before_metadata(
    tmp_path: Path,
) -> None:
    host = GateHost([])
    bad_digest = replace(_request(), fixture_sha256="0" * 64)
    with pytest.raises(StrictVisionRunnerError, match="fixture digest"):
        _runner(tmp_path, host).run(bad_digest)
    assert host.calls == []

    bad_dimensions = replace(_request(), fixture_width=2)
    with pytest.raises(StrictVisionRunnerError, match="fixture dimensions"):
        _runner(tmp_path, host).run(bad_dimensions)
    assert host.calls == []


def test_schema_specific_grounding_enforces_text_objects_and_forbidden_claims() -> None:
    truth = {
        "expected_visible_text": ["Настройки модели", "Сохранить"],
        "expected_objects": ["settings_window", "save_button"],
        "forbidden_claims": ["real customer"],
        "minimum_visible_text_recall": 0.5,
        "minimum_object_recall": 1.0,
    }
    simple = validate_strict_vision_grounding(
        {
            "description": "A settings window",
            "visible_text": ["Настройки модели"],
            "warnings": [],
        },
        schema_name="simple_description",
        ground_truth=truth,
    )
    assert simple.status == "pass"
    assert simple.metrics["visible_text_recall"] == 0.5

    medium = validate_strict_vision_grounding(
        {
            "description": "A settings window with a save button",
            "visible_text": ["Настройки модели"],
            "objects": ["settings_window"],
            "warnings": [],
        },
        schema_name="medium_objects_text",
        ground_truth=truth,
    )
    assert medium.status == "fail"
    assert medium.category == "object_recall_below_threshold"

    forbidden = validate_strict_vision_grounding(
        {
            "description": "Real customer settings",
            "visible_text": ["Настройки модели", "Сохранить"],
            "warnings": [],
        },
        schema_name="simple_description",
        ground_truth=truth,
    )
    assert forbidden.status == "fail"
    assert forbidden.category == "forbidden_claim"


@pytest.mark.parametrize(
    "ground_truth",
    [
        {},
        {"expected_visible_text": [], "expected_objects": [], "forbidden_claims": []},
        {
            "expected_visible_text": ["x"],
            "expected_objects": [],
            "forbidden_claims": [],
            "minimum_visible_text_recall": 1.5,
        },
    ],
)
def test_grounding_rejects_empty_or_malformed_truth(ground_truth: dict[str, object]) -> None:
    with pytest.raises(StrictVisionRunnerError, match="ground truth"):
        validate_strict_vision_grounding(
            {"description": "x", "visible_text": ["x"], "warnings": []},
            schema_name="simple_description",
            ground_truth=ground_truth,
        )


def test_content_addressed_fixture_builder_is_deterministic_and_bounded(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(PNG_BYTES)
    first = build_strict_vision_fixture(
        source, output_dir=tmp_path / "built", fixture_id="fixture-1", max_side=1024
    )
    second = build_strict_vision_fixture(
        source, output_dir=tmp_path / "built", fixture_id="fixture-1", max_side=1024
    )
    assert first == second
    assert first.sha256 == PNG_DIGEST
    assert first.width == first.height == 1
    assert first.path.name == f"{PNG_DIGEST}.png"
    assert first.path.read_bytes() == PNG_BYTES


def test_frozen_launch_manifest_is_serial_retry_off_bounded_and_content_addressed() -> None:
    root = Path("experiments/lmstudio/strict_vision")
    manifest_path = root / "launch_manifest.json"
    launch = load_strict_vision_launch_manifest(
        manifest_path,
        expected_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    assert (
        launch.manifest_sha256
        == hashlib.sha256((root / "launch_manifest.json").read_bytes()).hexdigest()
    )
    assert launch.serial is True
    assert launch.retry_policy == "off"
    assert launch.max_calls == 40
    assert len(launch.calls) == 41
    assert [call.ordinal for call in launch.calls] == list(range(1, 42))
    assert len({call.call_id for call in launch.calls}) == 41
    assert len(launch.models) == 4
    assert len(launch.fixtures) == 4
    assert {call.condition for call in launch.calls} == {
        "always",
        "model_simple_schema_accepted",
        "first_three_model_simple_accepted",
    }
    assert all(
        not call.depends_on_call_ids
        if call.condition == "always"
        else len(call.depends_on_call_ids) == 4
        for call in launch.calls
    )
    assert all(fixture.path.name == f"{fixture.sha256}.png" for fixture in launch.fixtures)
    assert all(max(fixture.width, fixture.height) <= 1024 for fixture in launch.fixtures)
    canonical = yaml.safe_load(
        Path(
            "experiments/lmstudio/structured_matrix/schemas/vision/vision_schema_contracts.yaml"
        ).read_text(encoding="utf-8")
    )["schemas"]
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {item["name"]: item["body"] for item in raw_manifest["schemas"]} == {
        "simple_description": canonical["simple_description"],
        "medium_objects_text": canonical["medium_objects_text"],
    }


def test_launch_manifest_loader_rejects_mutated_call_order(tmp_path: Path) -> None:
    source = Path("experiments/lmstudio/strict_vision/launch_manifest.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["calls"][1]["ordinal"] = 1
    mutated = tmp_path / "launch_manifest.json"
    mutated.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StrictVisionRunnerError, match="serial call order"):
        load_strict_vision_launch_manifest(
            mutated,
            expected_sha256=hashlib.sha256(mutated.read_bytes()).hexdigest(),
            asset_root=source.parent,
        )


def test_launch_manifest_loader_rejects_substituted_skipped_duplicated_or_appended_rows(
    tmp_path: Path,
) -> None:
    source = Path("experiments/lmstudio/strict_vision/launch_manifest.json")
    for case in ("substituted", "skipped", "duplicated", "appended"):
        payload = json.loads(source.read_text(encoding="utf-8"))
        calls = payload["calls"]
        if case == "substituted":
            calls[2]["fixture_id"] = payload["fixtures"][1]["fixture_id"]
        elif case == "skipped":
            calls.pop()
        elif case == "duplicated":
            calls[2] = {**calls[1], "ordinal": 3}
        else:
            calls.append({**calls[-1], "ordinal": 41, "call_id": "sv-41-forbidden"})
        mutated = tmp_path / f"{case}.json"
        mutated.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(StrictVisionRunnerError):
            load_strict_vision_launch_manifest(
                mutated,
                expected_sha256=hashlib.sha256(mutated.read_bytes()).hexdigest(),
                asset_root=source.parent,
            )


def _manifest_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManifestHost:
    def __init__(
        self,
        *,
        forensics: LocalFailureForensics,
        materialized_model: str | None = None,
        reject_first_image_surface: bool = False,
        fail_simple_grounding: bool = False,
        fail_simple_models: frozenset[str] = frozenset(),
        cleanup_leaves_loaded: bool = False,
    ):
        self.forensics = forensics
        self.materialized_model = materialized_model
        self.loaded_model: str | None = None
        self.loaded = 0
        self.host_calls: list[tuple[str, dict[str, object]]] = []
        self.lifecycle_calls: list[str] = []
        self.expected_by_digest: dict[str, dict[str, object]] = {}
        self.reject_first_image_surface = reject_first_image_surface
        self.fail_simple_grounding = fail_simple_grounding
        self.fail_simple_models = fail_simple_models
        self.cleanup_leaves_loaded = cleanup_leaves_loaded
        self.image_calls = 0

    def model_metadata(self, *, model_id: str) -> Mapping[str, object] | None:
        self.lifecycle_calls.append("model_metadata")
        loaded_instances: list[dict[str, object]] = []
        if self.loaded:
            loaded_instances.append(
                {
                    "id": "instance-1",
                    "model_key": self.materialized_model or self.loaded_model,
                    "context_length": 8192,
                    "parallel": 1,
                }
            )
        return {
            "type": "llm",
            "key": model_id,
            "capabilities": {"vision": True},
            "loaded_instances": loaded_instances,
        }

    def count_all_loaded_instances(self) -> int | None:
        self.lifecycle_calls.append("count_all_loaded_instances")
        return self.loaded

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.lifecycle_calls.append("load_model")
        self.loaded_model = model_id
        self.loaded = 1
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def strict_chat_completion(
        self, *, endpoint_path: str, payload: dict[str, object], timeout_s: float
    ) -> object:
        self.host_calls.append((endpoint_path, payload))
        messages = payload["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        response_format = payload["response_format"]
        assert isinstance(response_format, dict)
        schema = response_format["json_schema"]["schema"]
        if isinstance(content, str):
            value: dict[str, object] = {
                "description": "Synthetic",
                "visible_text": [],
                "warnings": [],
            }
        else:
            self.image_calls += 1
            if self.reject_first_image_surface and self.image_calls == 1:
                return {"choices": []}
            data_url = content[1]["image_url"]["url"]
            digest = hashlib.sha256(base64.b64decode(data_url.split(",", 1)[1])).hexdigest()
            fixture_truth = self.expected_by_digest[digest]
            if "image_type" in schema["properties"]:
                value = {
                    "image_type": "ui_screenshot",
                    "summary": "Visible fixture",
                    "visible_text": fixture_truth["expected_visible_text"],
                    "objects": [
                        {"type": item, "label": item} for item in fixture_truth["expected_objects"]
                    ],
                    "warnings": [],
                }
            else:
                value = {
                    "description": "Visible fixture",
                    "visible_text": (
                        []
                        if self.fail_simple_grounding
                        or self.loaded_model in self.fail_simple_models
                        else fixture_truth["expected_visible_text"]
                    ),
                    "warnings": [],
                }
        return _response(json.dumps(value, ensure_ascii=False))

    def native_chat_diagnostic(self, **kwargs: object) -> object:
        payload = {
            "model": kwargs["model_id"],
            "input": [
                {
                    "type": "text",
                    "content": kwargs["messages"][0]["content"],
                },
                {"type": "image", "data_url": kwargs["image_data_url"]},
            ],
            "max_output_tokens": kwargs["max_output_tokens"],
            "temperature": 0.0,
            "stream": kwargs["stream"],
            "store": False,
        }
        self.host_calls.append(("/api/v1/chat", payload))
        handle = self.forensics.capture_attempt(
            request_id=str(kwargs["request_id"]),
            attempt_index=int(kwargs["attempt_index"]),
            context_length=int(kwargs["context_length"]),
            output_cap=int(kwargs["max_output_tokens"]),
            reasoning_mode=None,
            started_at="2026-07-13T00:00:00+00:00",
            latency_ms=1.0,
            http_status=200,
            content_type="application/json",
            raw_envelope={"message": "visible fixture"},
            message_text="visible fixture",
            finish_reason="stop",
            boundary="terminal",
            endpoint="/api/v1/chat",
            request_payload=payload,
        )
        return SimpleNamespace(
            http_status=200,
            message_text="visible fixture",
            finish_reason="stop",
            boundary="terminal",
            forensics_handle=handle,
        )

    def cleanup_model(self, *, model_id: str) -> object:
        self.lifecycle_calls.append("cleanup_model")
        if not self.cleanup_leaves_loaded:
            self.loaded = 0
            self.loaded_model = None
        return {"cleanup_verified": True}


class ProductionPathControllerHost(LocalLMStudioHostRunner):
    loaded_model: str | None
    loaded: int
    strict_call_count: int
    native_payload: dict[str, object] | None

    def __init__(self, forensics: LocalFailureForensics) -> None:
        super().__init__(
            allow_native_diagnostics=True,
            failure_forensics=forensics,
        )
        object.__setattr__(self, "loaded_model", None)
        object.__setattr__(self, "loaded", 0)
        object.__setattr__(self, "strict_call_count", 0)
        object.__setattr__(self, "native_payload", None)

    def model_metadata(self, *, model_id: str) -> Mapping[str, object] | None:
        loaded_instances = []
        if self.loaded:
            loaded_instances = [
                {
                    "model_key": model_id,
                    "context_length": 8192,
                    "parallel": 1,
                }
            ]
        return {
            "type": "llm",
            "key": model_id,
            "capabilities": {"vision": True},
            "loaded_instances": loaded_instances,
        }

    def count_all_loaded_instances(self) -> int | None:
        return self.loaded

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        object.__setattr__(self, "loaded_model", model_id)
        object.__setattr__(self, "loaded", 1)
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def strict_chat_completion(
        self,
        *,
        endpoint_path: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> object:
        object.__setattr__(self, "strict_call_count", self.strict_call_count + 1)
        if self.strict_call_count == 1:
            value = {"description": "Synthetic", "visible_text": [], "warnings": []}
            return _response(json.dumps(value))
        return {"choices": []}

    def _request_native_chat(
        self,
        *,
        payload: Mapping[str, object],
        timeout_s: float,
        stream: bool,
    ) -> tuple[bytes, str, int]:
        object.__setattr__(self, "native_payload", dict(payload))
        response = {
            "output": [{"type": "message", "content": "Visible fixture"}],
            "finish_reason": "stop",
        }
        return json.dumps(response).encode(), "application/json", 200

    def cleanup_model(self, *, model_id: str) -> object:
        object.__setattr__(self, "loaded_model", None)
        object.__setattr__(self, "loaded", 0)
        return {"cleanup_verified": True}


def _controller(
    tmp_path: Path,
    *,
    materialized_model: str | None = None,
    reject_first_image_surface: bool = False,
    fail_simple_grounding: bool = False,
    fail_simple_models: frozenset[str] = frozenset(),
    cleanup_leaves_loaded: bool = False,
):
    manifest_path = Path("experiments/lmstudio/strict_vision/launch_manifest.json")
    repo = tmp_path / "repo"
    repo.mkdir()
    forensics = LocalFailureForensics(tmp_path / "owner-only", repo_root=repo, enabled=True)
    launch = load_strict_vision_launch_manifest(
        manifest_path, expected_sha256=_manifest_digest(manifest_path)
    )
    host = ManifestHost(
        forensics=forensics,
        materialized_model=materialized_model,
        reject_first_image_surface=reject_first_image_surface,
        fail_simple_grounding=fail_simple_grounding,
        fail_simple_models=fail_simple_models,
        cleanup_leaves_loaded=cleanup_leaves_loaded,
    )
    host.expected_by_digest = {
        fixture.sha256: dict(fixture.ground_truth) for fixture in launch.fixtures
    }
    controller = StrictVisionLaunchController(
        manifest=launch,
        host_runner=host,
        failure_forensics=forensics,
        allow_model_loads=True,
    )
    return controller, host, launch, tmp_path / "owner-only"


def test_manifest_requires_independent_digest_pin() -> None:
    path = Path("experiments/lmstudio/strict_vision/launch_manifest.json")
    with pytest.raises(StrictVisionRunnerError, match="manifest digest pin"):
        load_strict_vision_launch_manifest(path, expected_sha256="0" * 64)


def test_controller_revalidates_loaded_manifest_snapshot_before_any_host_action(
    tmp_path: Path,
) -> None:
    controller, host, launch, _private_root = _controller(tmp_path)
    controller.manifest = replace(launch, calls=tuple(reversed(launch.calls)))

    with pytest.raises(StrictVisionRunnerError, match="manifest snapshot was substituted"):
        controller.run()

    assert host.lifecycle_calls == []
    assert host.host_calls == []


def test_manifest_controller_executes_exact_40_call_schedule_and_append_only_bindings(
    tmp_path: Path,
) -> None:
    controller, host, launch, private_root = _controller(tmp_path)

    result = controller.run()

    assert result.host_call_count == 40
    assert len(host.host_calls) == 40
    assert [row.ordinal for row in result.rows] == list(range(1, 42))
    assert [
        row.model_id
        for row in result.rows
        if row.kind == "simple_repeat" and row.status == "executed"
    ] == list(launch.models[:3])
    assert [
        row.model_id
        for row in result.rows
        if row.kind == "simple_repeat" and row.status == "skipped"
    ] == [launch.models[3]]
    assert result.final_loaded_global_count == 0
    assert host.lifecycle_calls.count("load_model") == 4
    strict_payloads = [
        payload for endpoint, payload in host.host_calls if endpoint == "/v1/chat/completions"
    ]
    assert strict_payloads
    assert all(payload["stream"] is False for payload in strict_payloads)
    assert all(payload["temperature"] == 0.0 for payload in strict_payloads)
    assert all(payload["max_tokens"] == 1024 for payload in strict_payloads)
    raw_manifest = json.loads(
        Path("experiments/lmstudio/strict_vision/launch_manifest.json").read_text(encoding="utf-8")
    )
    controls = raw_manifest["strict_request"]
    simple_schema = raw_manifest["schemas"][0]["body"]
    assert strict_payloads[0] == {
        "model": raw_manifest["models"][0],
        "messages": [{"role": "user", "content": raw_manifest["prompts"][3]["text"]}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "simple_description",
                "strict": True,
                "schema": simple_schema,
            },
        },
        "temperature": controls["temperature"],
        "max_tokens": controls["max_tokens"],
        "stream": controls["stream"],
        "reasoning_effort": controls["reasoning_effort"],
        "enable_thinking": controls["enable_thinking"],
    }
    first_fixture = launch.fixtures[0]
    expected_data_url = "data:image/png;base64," + base64.b64encode(
        first_fixture.path.read_bytes()
    ).decode("ascii")
    assert strict_payloads[1]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": raw_manifest["prompts"][1]["text"]},
                {"type": "image_url", "image_url": {"url": expected_data_url}},
            ],
        }
    ]
    ledger_rows = [
        json.loads(line)
        for line in (private_root / "strict-vision-progress.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    call_rows = [row for row in ledger_rows if row["record_type"] == "call"]
    executed_rows = [row for row in call_rows if row["status"] == "executed"]
    assert len(call_rows) == 41
    assert len(executed_rows) == 40
    assert all(row["manifest_sha256"] == launch.manifest_sha256 for row in call_rows)
    assert [row["ordinal"] for row in call_rows] == list(range(1, 42))
    assert max(row["host_call_index"] for row in executed_rows) == 40
    assert all(
        {
            "model_id",
            "fixture_sha256",
            "schema_sha256",
            "request_controls_sha256",
            "request_id_sha256",
        }
        <= row.keys()
        for row in executed_rows
    )
    native_rows = [row for row in executed_rows if row["kind"] == "native_plain"]
    assert len(native_rows) == 4
    assert all(
        row["native_payload_sha256"] == row["private_capture"]["outbound"]["payload_sha256"]
        for row in native_rows
    )
    capture_hashes = {
        json.loads(path.read_text(encoding="utf-8"))["request"]["request_id_hash"]
        for path in private_root.glob("attempt-*.json")
    }
    assert capture_hashes == {row["request_id_sha256"] for row in executed_rows}


def test_controller_rejects_wrong_post_load_runtime_identity_before_chat(tmp_path: Path) -> None:
    controller, host, _launch, _private_root = _controller(
        tmp_path, materialized_model="other/model"
    )

    with pytest.raises(StrictVisionRunnerError, match="materialized model identity"):
        controller.run()

    assert host.host_calls == []
    assert host.loaded == 0


def test_controller_rejects_verified_cleanup_with_nonzero_final_global_count(
    tmp_path: Path,
) -> None:
    controller, host, _launch, _private_root = _controller(tmp_path, cleanup_leaves_loaded=True)

    with pytest.raises(StrictVisionRunnerError, match="final global loaded count"):
        controller.run()

    assert host.loaded == 1


def test_controller_route_canary_stops_remaining_schedule_and_cleans_up(tmp_path: Path) -> None:
    controller, host, _launch, _private_root = _controller(
        tmp_path, reject_first_image_surface=True
    )

    result = controller.run()

    assert result.host_call_count == 3
    assert result.stop_reason == "first_schema_image_route_rejected"
    assert [row.status for row in result.rows[:3]] == ["executed", "executed", "executed"]
    assert all(row.status == "skipped" for row in result.rows[3:])
    assert result.final_loaded_global_count == 0
    assert host.loaded == 0


def test_controller_simple_failures_block_only_model_medium_and_repeat_rows(
    tmp_path: Path,
) -> None:
    controller, _host, _launch, _private_root = _controller(tmp_path, fail_simple_grounding=True)

    result = controller.run()

    assert result.stop_reason is None
    assert result.host_call_count == 21
    assert all(
        row.status == "skipped"
        for row in result.rows
        if row.kind in {"medium_objects_text", "simple_repeat"}
    )
    assert result.final_loaded_global_count == 0


def test_controller_repeats_first_three_semantically_accepted_models_in_execution_order(
    tmp_path: Path,
) -> None:
    rejected_model = "google/gemma-4-e2b"
    controller, _host, launch, _private_root = _controller(
        tmp_path,
        fail_simple_models=frozenset({rejected_model}),
    )

    result = controller.run()

    repeat_rows = [row for row in result.rows if row.kind == "simple_repeat"]
    assert [row.model_id for row in repeat_rows if row.status == "executed"] == list(
        launch.models[1:]
    )
    assert [row.model_id for row in repeat_rows if row.status == "skipped"] == [rejected_model]
    assert result.host_call_count <= 40


def test_controller_production_native_path_has_ledger_request_hash_bijection(
    tmp_path: Path,
) -> None:
    manifest_path = Path("experiments/lmstudio/strict_vision/launch_manifest.json")
    repo = tmp_path / "repo"
    repo.mkdir()
    private_root = tmp_path / "owner-only"
    forensics = LocalFailureForensics(private_root, repo_root=repo, enabled=True)
    launch = load_strict_vision_launch_manifest(
        manifest_path,
        expected_sha256=_manifest_digest(manifest_path),
    )
    host = ProductionPathControllerHost(forensics)
    controller = StrictVisionLaunchController(
        manifest=launch,
        host_runner=host,
        failure_forensics=forensics,
        allow_model_loads=True,
    )

    result = controller.run()

    assert result.stop_reason == "first_schema_image_route_rejected"
    native_row = next(row for row in result.rows if row.kind == "native_plain")
    assert native_row.status == "executed"
    assert host.native_payload is not None
    private_records = [
        json.loads(path.read_text(encoding="utf-8")) for path in private_root.glob("attempt-*.json")
    ]
    native_capture = next(
        record
        for record in private_records
        if record["outbound"] is not None and record["outbound"]["endpoint"] == "/api/v1/chat"
    )
    assert native_capture["outbound"] == {
        "endpoint": "/api/v1/chat",
        "payload": host.native_payload,
    }
    assert (
        native_capture["request"]["request_id_hash"] == native_row.safe_binding["request_id_sha256"]
    )
    private_capture = native_row.safe_binding["private_capture"]
    assert isinstance(private_capture, Mapping)
    outbound = private_capture["outbound"]
    assert isinstance(outbound, Mapping)
    assert native_row.safe_binding["native_payload_sha256"] == outbound["payload_sha256"]


def test_response_surface_failure_is_distinct_and_blocks_parse(tmp_path: Path) -> None:
    host = GateHost([{"choices": []}])
    result = _runner(tmp_path, host).run(_request())

    assert result.preflight.response_surface_status == "fail"
    assert result.preflight.parse_status == "skip"
    assert result.preflight.error_category == "malformed_response_surface"


def test_grounding_rejects_unsupported_visible_text_and_objects() -> None:
    truth = {
        "expected_visible_text": ["Настройки"],
        "supported_visible_text": ["Настройки"],
        "expected_objects": ["save_button"],
        "supported_objects": ["save_button"],
        "forbidden_claims": [],
        "minimum_visible_text_recall": 1.0,
        "minimum_visible_text_precision": 1.0,
        "minimum_object_recall": 1.0,
        "minimum_object_precision": 1.0,
    }
    result = validate_strict_vision_grounding(
        {
            "image_type": "ui_screenshot",
            "summary": "Settings",
            "visible_text": ["Настройки", "invented secret text"],
            "objects": [
                {"type": "button", "label": "save_button"},
                {"type": "spaceship", "label": "identified_person"},
            ],
            "warnings": [],
        },
        schema_name="medium_objects_text",
        ground_truth=truth,
    )
    assert result.status == "fail"
    assert result.category == "visible_text_precision_below_threshold"

    object_result = validate_strict_vision_grounding(
        {
            "image_type": "ui_screenshot",
            "summary": "Settings",
            "visible_text": ["Настройки"],
            "objects": [
                {"type": "button", "label": "save_button"},
                {"type": "spaceship", "label": "identified_person"},
            ],
            "warnings": [],
        },
        schema_name="medium_objects_text",
        ground_truth=truth,
    )
    assert object_result.status == "fail"
    assert object_result.category == "object_precision_below_threshold"


def _continuation_controller(tmp_path: Path):
    source_root = Path("experiments/lmstudio/strict_vision")
    asset_root = tmp_path / "assets"
    shutil.copytree(source_root, asset_root)
    continuation_path = asset_root / "continuation_manifest.json"
    payload = json.loads(continuation_path.read_text(encoding="utf-8"))
    base_payload = json.loads((asset_root / "launch_manifest.json").read_text(encoding="utf-8"))
    prior_ids = payload["prior_executed_call_ids"]
    continuation_ids = set(payload["continuation_call_ids"])
    excluded_ids = set(payload["excluded_call_ids"])
    progress: list[dict[str, object]] = []
    host_index = 0
    for call in base_payload["calls"]:
        call_id = call["call_id"]
        if call_id in prior_ids:
            host_index += 1
            progress.append(
                {"call_id": call_id, "status": "executed", "host_call_index": host_index}
            )
        else:
            assert call_id in continuation_ids | excluded_ids
            progress.append({"call_id": call_id, "status": "skipped", "host_call_index": None})
    assert host_index == 21
    progress_path = tmp_path / "prior-progress.jsonl"
    progress_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in progress),
        encoding="utf-8",
    )
    accepted_ids = set(payload["accepted_simple_call_ids"])
    review = {
        "rows": [
            {
                "call_id": call["call_id"],
                "kind": "simple_description",
                "manual_review": {
                    "grounded": call["call_id"] in accepted_ids,
                    "visible_text_exact": call["call_id"] in accepted_ids,
                    "warnings_supported_and_relevant": call["call_id"] in accepted_ids,
                    "forbidden_claims_present": False,
                },
            }
            for call in base_payload["calls"]
            if call["kind"] == "simple_description"
        ]
    }
    review_path = tmp_path / "prior-review.json"
    review_path.write_text(json.dumps(review, sort_keys=True), encoding="utf-8")
    payload["prior_progress_sha256"] = hashlib.sha256(progress_path.read_bytes()).hexdigest()
    payload["prior_review_sha256"] = hashlib.sha256(review_path.read_bytes()).hexdigest()
    continuation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    launch = load_strict_vision_continuation_manifest(
        continuation_path,
        expected_sha256=hashlib.sha256(continuation_path.read_bytes()).hexdigest(),
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    forensics = LocalFailureForensics(tmp_path / "owner-only", repo_root=repo, enabled=True)
    host = ManifestHost(forensics=forensics)
    host.expected_by_digest = {
        fixture.sha256: dict(fixture.ground_truth) for fixture in launch.fixtures
    }
    controller = StrictVisionContinuationController(
        manifest=launch,
        host_runner=host,
        failure_forensics=forensics,
        prior_progress_path=progress_path,
        prior_review_path=review_path,
        allow_model_loads=True,
    )
    return controller, host, launch, progress_path, review_path


def test_continuation_manifest_replaces_partial_allow_lists_with_manual_precision_policy() -> None:
    path = Path("experiments/lmstudio/strict_vision/continuation_manifest.json")
    launch = load_strict_vision_continuation_manifest(
        path, expected_sha256=CONTINUATION_MANIFEST_SHA256
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == CONTINUATION_MANIFEST_SHA256
    assert len(launch.calls) == 19
    assert len(launch.prior_executed_call_ids) == 21
    assert launch.accepted_simple_call_ids == (
        "sv-04-e2b-simple-document_table_products_ru_001",
        "sv-14-e4b-simple-document_table_products_ru_001",
        "sv-15-e4b-simple-chart_tasks_by_month_ru_001",
        "sv-34-26b-simple-document_table_products_ru_001",
    )
    assert not set(launch.prior_executed_call_ids) & {call.call_id for call in launch.calls}
    assert [call.kind for call in launch.calls].count("medium_objects_text") == 16
    assert [call.kind for call in launch.calls].count("simple_repeat") == 3
    assert [call.call_id for call in launch.calls if call.kind == "simple_repeat"] == [
        "sv-11-e2b-repeat-ui",
        "sv-21-e4b-repeat-ui",
        "sv-41-26b-repeat-ui",
    ]
    assert launch.prior_host_call_count + len(launch.calls) == 40
    payload = json.loads(path.read_text(encoding="utf-8"))
    sv_33 = next(
        row
        for row in payload["simple_adjudication"]
        if row["call_id"] == "sv-33-26b-simple-ui_settings_ru_001"
    )
    assert sv_33 == {
        "call_id": "sv-33-26b-simple-ui_settings_ru_001",
        "accepted": False,
        "findings": [
            "The transcription is grounded, but repeating and translating the visible warning "
            "banner is not an uncertainty report."
        ],
    }
    for fixture in launch.fixtures:
        truth = fixture.ground_truth
        assert "supported_visible_text" not in truth
        assert "supported_objects" not in truth
        assert truth["object_precision_policy"] == "manual_pixel_adjudication_open_world"
        if fixture.fixture_id == "code_python_editor_001":
            assert truth["visible_text_precision_policy"] == "manual_pixel_adjudication_open_world"
            assert "complete_visible_text" not in truth
        else:
            assert truth["visible_text_precision_policy"] == (
                "complete_transcript_with_manual_phrase_adjudication"
            )
            complete_text = truth["complete_visible_text"]
            expected_text = truth["expected_visible_text"]
            assert isinstance(complete_text, tuple)
            assert isinstance(expected_text, tuple)
            assert len(complete_text) > len(expected_text)


def test_continuation_executes_only_remaining_19_calls_and_never_repeats_prior_21(
    tmp_path: Path,
) -> None:
    controller, host, launch, _progress_path, _review_path = _continuation_controller(tmp_path)
    result = controller.run()
    assert result.continuation_host_call_count == 19
    assert result.cumulative_host_call_count == 40
    assert len(host.host_calls) == 19
    assert [row.host_call_index for row in result.rows] == list(range(22, 41))
    assert tuple(row.call_id for row in result.rows) == tuple(call.call_id for call in launch.calls)
    assert not set(launch.prior_executed_call_ids) & {row.call_id for row in result.rows}
    assert all(row.kind in {"medium_objects_text", "simple_repeat"} for row in result.rows)
    assert all(row.accepted is False for row in result.rows)
    assert result.final_loaded_global_count == 0
    assert host.loaded == 0


def test_continuation_fails_before_host_action_when_prior_evidence_is_changed(
    tmp_path: Path,
) -> None:
    controller, host, _launch, progress_path, _review_path = _continuation_controller(tmp_path)
    progress_path.write_text(progress_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(StrictVisionRunnerError, match="prior progress digest"):
        controller.run()
    assert host.lifecycle_calls == []
    assert host.host_calls == []


def test_continuation_loader_rejects_reintroducing_a_prior_call(tmp_path: Path) -> None:
    source_root = Path("experiments/lmstudio/strict_vision")
    asset_root = tmp_path / "assets"
    shutil.copytree(source_root, asset_root)
    path = asset_root / "continuation_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["continuation_call_ids"][0] = payload["prior_executed_call_ids"][0]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StrictVisionRunnerError, match="exact 19-call tail|repeats a prior call"):
        load_strict_vision_continuation_manifest(
            path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )
