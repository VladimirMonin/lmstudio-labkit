"""Bounded OpenAI-compatible strict structured vision execution."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from .failure_forensics import ForensicsRecordHandle, LocalFailureForensics
from .validation import ValidationResult, validate_json_schema

OutcomeStatus = Literal["pass", "fail", "skip"]
STRICT_VISION_MODEL_IDS = (
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
)
STRICT_VISION_FIXTURE_IDS = (
    "ui_settings_ru_001",
    "document_table_products_ru_001",
    "chart_tasks_by_month_ru_001",
    "code_python_editor_001",
)


class StrictVisionRunnerError(RuntimeError):
    """Raised when strict vision execution cannot satisfy its safety contract."""


class StrictVisionHostRunner(Protocol):
    def model_metadata(self, *, model_id: str) -> Mapping[str, object] | None: ...

    def count_all_loaded_instances(self) -> int | None: ...

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object: ...

    def strict_chat_completion(
        self,
        *,
        endpoint_path: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> object: ...

    def cleanup_model(self, *, model_id: str) -> object: ...


class StrictVisionControllerHostRunner(StrictVisionHostRunner, Protocol):
    def native_chat_diagnostic(
        self,
        *,
        model_id: str,
        messages: Sequence[Mapping[str, str]],
        reasoning: str | None,
        max_output_tokens: int,
        timeout_s: float,
        stream: bool,
        request_id: str,
        attempt_index: int,
        context_length: int,
        image_data_url: str | None,
        capture_outbound_request: bool,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class StrictVisionRequest:
    request_id: str
    model_id: str
    preflight_prompt: str
    image_prompt: str
    image_data_url: str
    fixture_id: str
    fixture_sha256: str
    fixture_width: int
    fixture_height: int
    schema_name: str
    schema: dict[str, Any]
    image_ground_truth: dict[str, Any]
    context_length: int = 8192
    max_tokens: int = 1024
    timeout_s: float = 120.0


@dataclass(frozen=True, slots=True)
class StructuredCallOutcome:
    modality: Literal["text", "image"]
    transport_status: OutcomeStatus
    parse_status: OutcomeStatus
    schema_status: OutcomeStatus
    grounding_status: OutcomeStatus
    response_surface_status: OutcomeStatus = "pass"
    finish_reason: str | None = None
    reasoning_status: Literal["zero", "nonzero", "unobserved"] = "unobserved"
    reasoning_tokens: int | None = None
    reasoning_content_present: bool = False
    error_category: str | None = None
    raw_response: str = field(default="", repr=False)
    private_capture: dict[str, object] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        required = [
            self.transport_status,
            self.response_surface_status,
            self.parse_status,
            self.schema_status,
        ]
        if self.modality == "image":
            required.append(self.grounding_status)
        return (
            all(status == "pass" for status in required)
            and self.finish_reason == "stop"
            and self.reasoning_status == "zero"
        )

    def safe_metadata(self) -> dict[str, object]:
        return {
            "modality": self.modality,
            "transport_status": self.transport_status,
            "response_surface_status": self.response_surface_status,
            "parse_status": self.parse_status,
            "schema_status": self.schema_status,
            "grounding_status": self.grounding_status,
            "finish_reason": self.finish_reason,
            "reasoning_status": self.reasoning_status,
            "reasoning_tokens": self.reasoning_tokens,
            "reasoning_content_present": self.reasoning_content_present,
            "error_category": self.error_category,
            "private_capture": dict(self.private_capture),
            "api_bound_strict_json_schema": True,
        }


@dataclass(frozen=True, slots=True)
class StrictVisionRunResult:
    preflight: StructuredCallOutcome
    vision: StructuredCallOutcome | None
    image_call_status: Literal["executed", "blocked_by_text_preflight"]
    cleanup_verified: bool
    final_loaded_global_count: int

    def safe_metadata(self) -> dict[str, object]:
        return {
            "preflight": self.preflight.safe_metadata(),
            "vision": self.vision.safe_metadata() if self.vision is not None else None,
            "image_call_status": self.image_call_status,
            "cleanup_verified": self.cleanup_verified,
            "final_loaded_global_count": self.final_loaded_global_count,
        }


@dataclass(frozen=True, slots=True)
class StrictStructuredVisionRunner:
    """Offline seam for isolated request tests; live work must use the controller."""

    host_runner: StrictVisionHostRunner
    failure_forensics: LocalFailureForensics
    allow_model_loads: bool = False
    allow_unpinned_test_requests: bool = False
    endpoint_path: str = "/v1/chat/completions"

    def __post_init__(self) -> None:
        if self.endpoint_path != "/v1/chat/completions":
            raise StrictVisionRunnerError("strict vision runner supports only /v1/chat/completions")

    def run(self, request: StrictVisionRequest) -> StrictVisionRunResult:
        if not self.allow_unpinned_test_requests:
            raise StrictVisionRunnerError(
                "unpinned strict vision requests are test-only; use the manifest controller"
            )
        self._validate_request(request)
        if not self.allow_model_loads:
            raise StrictVisionRunnerError(
                "strict vision model loads require allow_model_loads=true"
            )
        if not self.failure_forensics.enabled:
            raise StrictVisionRunnerError("strict vision requires enabled owner-only capture")

        metadata = self.host_runner.model_metadata(model_id=request.model_id)
        _validate_exact_vlm_metadata(metadata, model_id=request.model_id)

        initial_loaded = self.host_runner.count_all_loaded_instances()
        if initial_loaded is None:
            raise StrictVisionRunnerError("global pre-load state was not verified")
        if initial_loaded != 0:
            raise StrictVisionRunnerError("strict vision refuses dirty global loaded state")

        handles: list[ForensicsRecordHandle] = []
        load_attempted = False
        cleanup_response: object = {"cleanup_verified": False}
        final_loaded: int | None = None
        preflight: StructuredCallOutcome | None = None
        vision: StructuredCallOutcome | None = None
        try:
            load_attempted = True
            load_response = self.host_runner.load_model(
                model_id=request.model_id,
                context_length=request.context_length,
                parallel=1,
            )
            if not _load_verified(load_response, context_length=request.context_length):
                raise StrictVisionRunnerError("strict vision model load was not verified")
            post_load = self.host_runner.count_all_loaded_instances()
            if post_load != 1:
                raise StrictVisionRunnerError(
                    "strict vision requires exactly one global loaded instance"
                )
            _validate_materialized_model_metadata(
                self.host_runner.model_metadata(model_id=request.model_id),
                model_id=request.model_id,
                context_length=request.context_length,
            )

            preflight_payload = _build_payload(
                request,
                content=request.preflight_prompt,
            )
            preflight, preflight_handle = self._execute_call(
                request=request,
                modality="text",
                attempt_index=1,
                payload=preflight_payload,
            )
            handles.append(preflight_handle)
            if preflight.accepted:
                image_payload = _build_payload(
                    request,
                    content=[
                        {"type": "text", "text": request.image_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": request.image_data_url},
                        },
                    ],
                )
                vision, vision_handle = self._execute_call(
                    request=request,
                    modality="image",
                    attempt_index=2,
                    payload=image_payload,
                )
                handles.append(vision_handle)
        finally:
            if load_attempted:
                cleanup_response = self.host_runner.cleanup_model(model_id=request.model_id)
                final_loaded = self.host_runner.count_all_loaded_instances()
                for handle in handles:
                    self.failure_forensics.finalize_attempt(
                        handle,
                        cleanup_result=cleanup_response,
                        final_loaded_instances=final_loaded,
                    )
                if not _cleanup_verified(cleanup_response):
                    raise StrictVisionRunnerError("strict vision cleanup was not verified")
                if final_loaded != 0:
                    raise StrictVisionRunnerError(
                        "strict vision final global loaded count must be zero"
                    )
        if preflight is None:
            raise StrictVisionRunnerError("strict vision preflight did not complete")
        return StrictVisionRunResult(
            preflight=preflight,
            vision=vision,
            image_call_status="executed" if vision is not None else "blocked_by_text_preflight",
            cleanup_verified=True,
            final_loaded_global_count=0,
        )

    def _execute_call(
        self,
        *,
        request: StrictVisionRequest,
        modality: Literal["text", "image"],
        attempt_index: int,
        payload: dict[str, object],
    ) -> tuple[StructuredCallOutcome, ForensicsRecordHandle]:
        started_at = datetime.now(UTC).isoformat()
        started = time.monotonic()
        raw_payload: object
        raw_response = ""
        response_surface_status: OutcomeStatus = "skip"
        finish_reason: str | None = None
        reasoning_status: Literal["zero", "nonzero", "unobserved"] = "unobserved"
        reasoning_tokens: int | None = None
        reasoning_content_present = False
        error_category: str | None = None
        transport_status: OutcomeStatus = "pass"
        try:
            raw_payload = self.host_runner.strict_chat_completion(
                endpoint_path=self.endpoint_path,
                payload=payload,
                timeout_s=request.timeout_s,
            )
            (
                raw_response,
                response_surface_status,
                finish_reason,
                reasoning_status,
                reasoning_tokens,
                reasoning_content_present,
            ) = _extract_compat_response(raw_payload)
            if response_surface_status == "fail":
                error_category = "malformed_response_surface"
        except Exception as error:
            error_category = type(error).__name__
            raw_payload = {"transport_error_category": error_category}
            transport_status = "fail"

        parse_status: OutcomeStatus = "skip"
        schema_status: OutcomeStatus = "skip"
        grounding_status: OutcomeStatus = "skip"
        parsed: object | None = None
        if transport_status == "pass" and response_surface_status == "pass":
            try:
                parsed = json.loads(raw_response)
            except (json.JSONDecodeError, TypeError):
                parse_status = "fail"
            else:
                parse_status = "pass"
                schema_status = _outcome_status(validate_json_schema(parsed, request.schema).status)
                if modality == "image" and schema_status == "pass":
                    grounding_status = _outcome_status(
                        validate_strict_vision_grounding(
                            parsed,
                            schema_name=request.schema_name,
                            ground_truth=request.image_ground_truth,
                        ).status
                    )

        handle = self.failure_forensics.capture_attempt(
            request_id=f"{request.request_id}:{modality}",
            attempt_index=attempt_index,
            context_length=request.context_length,
            output_cap=request.max_tokens,
            reasoning_mode="off",
            started_at=started_at,
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            http_status=200 if transport_status == "pass" else None,
            content_type="application/json" if transport_status == "pass" else None,
            raw_envelope=raw_payload,
            message_text=raw_response,
            finish_reason=finish_reason,
            boundary="terminal" if transport_status == "pass" else "transport_error",
            endpoint=self.endpoint_path,
            request_payload=payload,
            transport_error_category=error_category,
        )
        if handle is None:
            raise StrictVisionRunnerError("owner-only capture did not produce a record")
        return (
            StructuredCallOutcome(
                modality=modality,
                transport_status=transport_status,
                response_surface_status=response_surface_status,
                parse_status=parse_status,
                schema_status=schema_status,
                grounding_status=grounding_status,
                finish_reason=finish_reason,
                reasoning_status=reasoning_status,
                reasoning_tokens=reasoning_tokens,
                reasoning_content_present=reasoning_content_present,
                error_category=error_category,
                raw_response=raw_response,
                private_capture=self.failure_forensics.safe_manifest_entry(handle),
            ),
            handle,
        )

    @staticmethod
    def _validate_request(request: StrictVisionRequest) -> None:
        if not request.request_id or not request.model_id:
            raise StrictVisionRunnerError("strict vision request and model ids are required")
        if not request.preflight_prompt or not request.image_prompt:
            raise StrictVisionRunnerError("strict vision prompts must be non-empty")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request.schema_name):
            raise StrictVisionRunnerError("strict vision schema_name is invalid")
        if request.schema.get("type") != "object":
            raise StrictVisionRunnerError("strict vision requires an object JSON schema")
        if request.context_length not in {8192, 16384, 32768}:
            raise StrictVisionRunnerError("strict vision context length is unsupported")
        if request.max_tokens < 1:
            raise StrictVisionRunnerError("strict vision max_tokens must be positive")
        _validate_ground_truth_shape(
            schema_name=request.schema_name, ground_truth=request.image_ground_truth
        )
        _validate_image_data_url(
            request.image_data_url,
            fixture_id=request.fixture_id,
            expected_sha256=request.fixture_sha256,
            expected_width=request.fixture_width,
            expected_height=request.fixture_height,
        )


def _build_payload(
    request: StrictVisionRequest, *, content: str | list[dict[str, object]]
) -> dict[str, object]:
    return {
        "model": request.model_id,
        "messages": [{"role": "user", "content": content}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": request.schema_name,
                "strict": True,
                "schema": request.schema,
            },
        },
        "temperature": 0.0,
        "max_tokens": request.max_tokens,
        "stream": False,
        "reasoning_effort": "none",
        "enable_thinking": False,
    }


def _outcome_status(status: str) -> OutcomeStatus:
    if status == "pass":
        return "pass"
    if status == "skip":
        return "skip"
    return "fail"


def _extract_compat_response(
    payload: object,
) -> tuple[
    str,
    OutcomeStatus,
    str | None,
    Literal["zero", "nonzero", "unobserved"],
    int | None,
    bool,
]:
    if not isinstance(payload, Mapping):
        return "", "fail", None, "unobserved", None, False
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return "", "fail", None, "unobserved", None, False
    first = choices[0]
    message = first.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content:
        return "", "fail", None, "unobserved", None, False
    finish_reason = first.get("finish_reason")
    reasoning_content_present = _reasoning_content_present(message)
    reasoning_tokens = _reasoning_tokens(payload.get("usage"))
    if reasoning_content_present or (reasoning_tokens is not None and reasoning_tokens > 0):
        reasoning_status: Literal["zero", "nonzero", "unobserved"] = "nonzero"
    elif reasoning_tokens == 0:
        reasoning_status = "zero"
    else:
        reasoning_status = "unobserved"
    return (
        content,
        "pass",
        finish_reason if isinstance(finish_reason, str) else None,
        reasoning_status,
        reasoning_tokens,
        reasoning_content_present,
    )


def _reasoning_content_present(message: object) -> bool:
    if not isinstance(message, Mapping):
        return False
    for key in ("reasoning_content", "reasoning", "analysis"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, Mapping)) and value:
            return True
    return False


def _reasoning_tokens(usage: object) -> int | None:
    if not isinstance(usage, Mapping):
        return None
    candidates: list[object] = [usage.get("reasoning_tokens")]
    for key in ("completion_tokens_details", "output_tokens_details"):
        details = usage.get(key)
        if isinstance(details, Mapping):
            candidates.append(details.get("reasoning_tokens"))
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _validate_exact_vlm_metadata(metadata: object, *, model_id: str) -> None:
    if not isinstance(metadata, Mapping) or metadata.get("key") != model_id:
        raise StrictVisionRunnerError(
            f"strict vision exact model metadata not found for {model_id}"
        )
    if metadata.get("type") != "llm":
        raise StrictVisionRunnerError(f"strict vision exact model {model_id} is not a VLM")
    capabilities = metadata.get("capabilities")
    vision = capabilities.get("vision") if isinstance(capabilities, Mapping) else None
    if vision is not True:
        raise StrictVisionRunnerError(
            f"strict vision exact model {model_id} does not advertise vision capability"
        )


def _validate_materialized_model_metadata(
    metadata: object, *, model_id: str, context_length: int
) -> None:
    _validate_exact_vlm_metadata(metadata, model_id=model_id)
    assert isinstance(metadata, Mapping)
    loaded = metadata.get("loaded_instances", metadata.get("instances"))
    if not isinstance(loaded, Sequence) or isinstance(loaded, (str, bytes, bytearray)):
        raise StrictVisionRunnerError("strict vision materialized model state was not observed")
    if len(loaded) != 1 or not isinstance(loaded[0], Mapping):
        raise StrictVisionRunnerError("strict vision requires one observed materialized instance")
    instance = loaded[0]
    observed_model = instance.get("model_key", instance.get("model", instance.get("key", model_id)))
    if observed_model != model_id:
        raise StrictVisionRunnerError("strict vision materialized model identity mismatch")
    config = instance.get("load_config", instance.get("config", instance))
    if not isinstance(config, Mapping):
        raise StrictVisionRunnerError("strict vision materialized runtime config was not observed")
    observed_context = config.get("context_length", config.get("contextLength"))
    observed_parallel = config.get("parallel", config.get("n_parallel", config.get("nParallel")))
    if observed_context != context_length or observed_parallel != 1:
        raise StrictVisionRunnerError("strict vision materialized runtime shape mismatch")


def _load_verified(value: object, *, context_length: int) -> bool:
    if not isinstance(value, Mapping) or value.get("load_verified") is not True:
        return False
    applied = value.get("applied_load_config", value.get("load_config"))
    return (
        isinstance(applied, Mapping)
        and applied.get("context_length") == context_length
        and applied.get("parallel", applied.get("n_parallel")) == 1
    )


def _cleanup_verified(value: object) -> bool:
    return isinstance(value, Mapping) and value.get("cleanup_verified") is True


def _validate_image_data_url(
    data_url: str,
    *,
    fixture_id: str,
    expected_sha256: str,
    expected_width: int,
    expected_height: int,
) -> None:
    if not fixture_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fixture_id):
        raise StrictVisionRunnerError("strict vision fixture id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise StrictVisionRunnerError("strict vision fixture digest is invalid")
    if expected_width < 1 or expected_height < 1 or max(expected_width, expected_height) > 1024:
        raise StrictVisionRunnerError("strict vision fixture dimensions are invalid")
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise StrictVisionRunnerError("strict vision image must be a PNG data URL")
    encoded = data_url[len(prefix) :]
    if not encoded or any(character.isspace() for character in encoded):
        raise StrictVisionRunnerError("strict vision image base64 is invalid")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise StrictVisionRunnerError("strict vision image base64 is invalid") from error
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise StrictVisionRunnerError("strict vision image bytes are not PNG")
    if hashlib.sha256(decoded).hexdigest() != expected_sha256:
        raise StrictVisionRunnerError(
            "strict vision fixture digest does not match transmitted bytes"
        )
    width, height = _png_dimensions(decoded)
    if (width, height) != (expected_width, expected_height):
        raise StrictVisionRunnerError(
            "strict vision fixture dimensions do not match transmitted bytes"
        )


def _png_dimensions(value: bytes) -> tuple[int, int]:
    if len(value) < 24 or value[12:16] != b"IHDR":
        raise StrictVisionRunnerError("strict vision image has no valid PNG IHDR")
    width = int.from_bytes(value[16:20], "big")
    height = int.from_bytes(value[20:24], "big")
    if width < 1 or height < 1:
        raise StrictVisionRunnerError("strict vision image has invalid PNG dimensions")
    return width, height


@dataclass(frozen=True, slots=True)
class StrictVisionFixture:
    fixture_id: str
    path: Path
    sha256: str
    width: int
    height: int
    source_sha256: str
    ground_truth: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class StrictVisionSchema:
    name: str
    sha256: str
    body: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StrictVisionLaunchCall:
    ordinal: int
    call_id: str
    model_id: str
    fixture_id: str | None
    kind: Literal[
        "text_preflight",
        "native_plain",
        "simple_description",
        "medium_objects_text",
        "simple_repeat",
    ]
    schema_name: str | None
    condition: Literal[
        "always",
        "model_simple_schema_accepted",
        "first_three_model_simple_accepted",
    ]
    depends_on_call_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrictVisionLaunchManifest:
    manifest_sha256: str
    source_path: Path
    asset_root: Path
    serial: bool
    retry_policy: Literal["off"]
    max_calls: int
    models: tuple[str, ...]
    prompts: Mapping[str, str]
    request_controls: Mapping[str, object]
    fixtures: tuple[StrictVisionFixture, ...]
    schemas: tuple[StrictVisionSchema, ...]
    calls: tuple[StrictVisionLaunchCall, ...]


@dataclass(frozen=True, slots=True)
class StrictVisionContinuationManifest:
    """Frozen continuation that can execute only the uncalled tail of a prior run."""

    manifest_sha256: str
    source_path: Path
    asset_root: Path
    base_manifest_sha256: str
    prior_progress_sha256: str
    prior_review_sha256: str
    prior_host_call_count: int
    maximum_cumulative_host_calls: int
    prior_executed_call_ids: tuple[str, ...]
    accepted_simple_call_ids: tuple[str, ...]
    excluded_call_ids: tuple[str, ...]
    models: tuple[str, ...]
    prompts: Mapping[str, str]
    request_controls: Mapping[str, object]
    fixtures: tuple[StrictVisionFixture, ...]
    schemas: tuple[StrictVisionSchema, ...]
    calls: tuple[StrictVisionLaunchCall, ...]


def build_strict_vision_fixture(
    source_path: Path,
    *,
    output_dir: Path,
    fixture_id: str,
    max_side: int = 1024,
) -> StrictVisionFixture:
    """Create deterministic content-addressed PNG bytes from a committed image asset."""

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fixture_id):
        raise StrictVisionRunnerError("strict vision fixture id is invalid")
    if max_side < 1 or max_side > 1024:
        raise StrictVisionRunnerError("strict vision fixture max side must be in 1..1024")
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if (
        source_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        and max(_png_dimensions(source_bytes)) <= max_side
    ):
        output_bytes = source_bytes
    else:
        output_bytes = _render_png(source_bytes, max_side=max_side)
    width, height = _png_dimensions(output_bytes)
    if max(width, height) > max_side:
        raise StrictVisionRunnerError("strict vision fixture builder exceeded max side")
    digest = hashlib.sha256(output_bytes).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{digest}.png"
    if output_path.exists() and output_path.read_bytes() != output_bytes:
        raise StrictVisionRunnerError("strict vision content-addressed fixture collision")
    output_path.write_bytes(output_bytes)
    return StrictVisionFixture(
        fixture_id=fixture_id,
        path=output_path,
        sha256=digest,
        width=width,
        height=height,
        source_sha256=source_sha256,
    )


def _render_png(source_bytes: bytes, *, max_side: int) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(source_bytes)) as image:
        image.load()
        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        mode = "RGBA" if "A" in image.getbands() else "RGB"
        normalized = image.convert(mode)
        output = io.BytesIO()
        normalized.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def validate_strict_vision_grounding(
    value: object,
    *,
    schema_name: str,
    ground_truth: Mapping[str, object],
) -> ValidationResult:
    """Apply schema-specific visible-text, object, and forbidden-claim gates."""

    (
        expected_text,
        expected_objects,
        supported_text,
        supported_objects,
        forbidden_claims,
        text_threshold,
        object_threshold,
        text_precision_threshold,
        object_precision_threshold,
    ) = _validate_ground_truth_shape(schema_name=schema_name, ground_truth=ground_truth)
    manual_text_precision = ground_truth.get("visible_text_precision_policy") in {
        "complete_transcript_with_manual_phrase_adjudication",
        "manual_pixel_adjudication_open_world",
    }
    manual_object_precision = (
        ground_truth.get("object_precision_policy") == "manual_pixel_adjudication_open_world"
    )
    if not isinstance(value, Mapping):
        return ValidationResult("strict_vision_grounding", "fail", "grounding_output_not_object")
    all_text = _flatten_output_text(value)
    forbidden_matches = [
        claim for claim in forbidden_claims if _normalized_text(claim) in _normalized_text(all_text)
    ]
    actual_text = _string_list_or_empty(value.get("visible_text"))
    expected_text_matches = _match_count(expected_text, actual_text)
    text_recall = expected_text_matches / len(expected_text) if expected_text else 1.0
    text_precision = (
        _exact_match_count(actual_text, supported_text) / len(actual_text) if actual_text else 1.0
    )
    metrics: dict[str, Any] = {
        "expected_visible_text_count": len(expected_text),
        "visible_text_match_count": expected_text_matches,
        "visible_text_recall": round(text_recall, 4),
        "minimum_visible_text_recall": text_threshold,
        "visible_text_precision": round(text_precision, 4),
        "minimum_visible_text_precision": text_precision_threshold,
        "forbidden_claim_match_count": len(forbidden_matches),
    }
    if forbidden_matches:
        return ValidationResult("strict_vision_grounding", "fail", "forbidden_claim", metrics)
    if text_recall < text_threshold:
        return ValidationResult(
            "strict_vision_grounding", "fail", "visible_text_recall_below_threshold", metrics
        )
    if not manual_text_precision and text_precision < text_precision_threshold:
        return ValidationResult(
            "strict_vision_grounding",
            "fail",
            "visible_text_precision_below_threshold",
            metrics,
        )
    if schema_name == "medium_objects_text":
        actual_objects = _object_labels_or_empty(value.get("objects"))
        object_matches = _match_count(expected_objects, actual_objects)
        object_recall = object_matches / len(expected_objects)
        object_precision = (
            _exact_match_count(actual_objects, supported_objects) / len(actual_objects)
            if actual_objects
            else 1.0
        )
        metrics.update(
            {
                "expected_object_count": len(expected_objects),
                "object_match_count": object_matches,
                "object_recall": round(object_recall, 4),
                "minimum_object_recall": object_threshold,
                "object_precision": round(object_precision, 4),
                "minimum_object_precision": object_precision_threshold,
            }
        )
        if object_recall < object_threshold:
            return ValidationResult(
                "strict_vision_grounding", "fail", "object_recall_below_threshold", metrics
            )
        if not manual_object_precision and object_precision < object_precision_threshold:
            return ValidationResult(
                "strict_vision_grounding",
                "fail",
                "object_precision_below_threshold",
                metrics,
            )
    if manual_text_precision or (schema_name == "medium_objects_text" and manual_object_precision):
        metrics["manual_precision_review_required"] = True
        return ValidationResult(
            "strict_vision_grounding",
            "fail",
            "manual_precision_review_required",
            metrics,
        )
    return ValidationResult("strict_vision_grounding", "pass", metrics=metrics)


def _validate_ground_truth_shape(
    *, schema_name: str, ground_truth: Mapping[str, object]
) -> tuple[
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
    float,
    float,
    float,
    float,
]:
    if schema_name not in {"simple_description", "medium_objects_text"}:
        raise StrictVisionRunnerError("strict vision grounding schema is unsupported")
    expected_text = _required_string_list(ground_truth, "expected_visible_text")
    expected_objects = _required_string_list(ground_truth, "expected_objects")
    transcript = ground_truth.get("complete_visible_text")
    supported_text = (
        _required_string_list(ground_truth, "complete_visible_text")
        if transcript is not None
        else _optional_string_list(ground_truth, "supported_visible_text", fallback=expected_text)
    )
    supported_objects = _optional_string_list(
        ground_truth, "supported_objects", fallback=expected_objects
    )
    forbidden_claims = _required_string_list(ground_truth, "forbidden_claims")
    if not expected_text and not expected_objects:
        raise StrictVisionRunnerError("strict vision ground truth has no expected evidence")
    text_threshold = _grounding_threshold(ground_truth, "minimum_visible_text_recall")
    object_threshold = _grounding_threshold(ground_truth, "minimum_object_recall")
    text_precision_threshold = _grounding_threshold(ground_truth, "minimum_visible_text_precision")
    object_precision_threshold = _grounding_threshold(ground_truth, "minimum_object_precision")
    if schema_name == "medium_objects_text" and not expected_objects:
        raise StrictVisionRunnerError("strict vision medium ground truth has no expected objects")
    return (
        expected_text,
        expected_objects,
        supported_text,
        supported_objects,
        forbidden_claims,
        text_threshold,
        object_threshold,
        text_precision_threshold,
        object_precision_threshold,
    )


def _required_string_list(value: Mapping[str, object], key: str) -> list[str]:
    raw = value.get(key)
    if (
        not isinstance(raw, Sequence)
        or isinstance(raw, (str, bytes, bytearray))
        or any(not isinstance(item, str) or not item.strip() for item in raw)
    ):
        raise StrictVisionRunnerError("strict vision ground truth is malformed")
    return list(raw)


def _optional_string_list(
    value: Mapping[str, object], key: str, *, fallback: list[str]
) -> list[str]:
    if key not in value:
        return list(fallback)
    return _required_string_list(value, key)


def _grounding_threshold(value: Mapping[str, object], key: str) -> float:
    raw = value.get(key, 0.0)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0.0 <= raw <= 1.0:
        raise StrictVisionRunnerError("strict vision ground truth threshold is malformed")
    return float(raw)


def _string_list_or_empty(value: object) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or any(not isinstance(item, str) for item in value)
    ):
        return []
    return list(value)


def _object_labels_or_empty(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    labels: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            return []
        item_type = item.get("type")
        label = item.get("label")
        candidates = [candidate for candidate in (label, item_type) if isinstance(candidate, str)]
        if not candidates:
            return []
        labels.append(candidates[0])
    return labels


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _match_count(expected: list[str], actual: list[str]) -> int:
    normalized_actual = [_normalized_text(item) for item in actual]
    return sum(
        any(
            _normalized_text(item) in candidate or candidate in _normalized_text(item)
            for candidate in normalized_actual
        )
        for item in expected
    )


def _exact_match_count(expected: list[str], actual: list[str]) -> int:
    normalized_actual = {_normalized_text(item) for item in actual}
    return sum(_normalized_text(item) in normalized_actual for item in expected)


def _flatten_output_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(_flatten_output_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_output_text(item) for item in value)
    return ""


def load_strict_vision_launch_manifest(
    path: Path, *, expected_sha256: str, asset_root: Path | None = None
) -> StrictVisionLaunchManifest:
    """Load and fail closed on the frozen serial no-retry launch contract."""

    raw_bytes = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or actual_sha256 != expected_sha256:
        raise StrictVisionRunnerError("strict vision manifest digest pin mismatch")
    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as error:
        raise StrictVisionRunnerError("strict vision launch manifest is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise StrictVisionRunnerError("strict vision launch manifest must be an object")
    _validate_launch_controls(payload)
    raw_prompts = payload["prompts"]
    assert isinstance(raw_prompts, list)
    prompts = MappingProxyType(
        {str(item["name"]): str(item["text"]) for item in raw_prompts if isinstance(item, Mapping)}
    )
    request_controls = _freeze_mapping(payload["strict_request"])
    if payload.get("serial") is not True or payload.get("retry_policy") != "off":
        raise StrictVisionRunnerError("strict vision launch must be serial with retries off")
    max_calls = payload.get("max_calls")
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or not 1 <= max_calls <= 40:
        raise StrictVisionRunnerError("strict vision launch max_calls must be in 1..40")
    models = _manifest_string_tuple(payload.get("models"), "models")
    if models != STRICT_VISION_MODEL_IDS:
        raise StrictVisionRunnerError("strict vision launch exact model order is invalid")
    root = (asset_root if asset_root is not None else path.parent).resolve()
    fixtures = _load_manifest_fixtures(payload.get("fixtures"), root=root)
    schemas = _load_manifest_schemas(payload.get("schemas"))
    calls = _load_manifest_calls(payload.get("calls"))
    if len(calls) != 41:
        raise StrictVisionRunnerError(
            "strict vision launch candidate row count must be frozen at 41"
        )
    if [call.ordinal for call in calls] != list(range(1, len(calls) + 1)):
        raise StrictVisionRunnerError("strict vision launch serial call order is invalid")
    if len({call.call_id for call in calls}) != len(calls):
        raise StrictVisionRunnerError("strict vision launch call ids are not unique")
    calls_by_id = {call.call_id: call for call in calls}
    fixture_ids = {fixture.fixture_id for fixture in fixtures}
    schema_names = {schema.name for schema in schemas}
    for call in calls:
        if call.model_id not in models:
            raise StrictVisionRunnerError("strict vision launch call references are invalid")
        if call.kind == "text_preflight":
            if (
                call.fixture_id is not None
                or call.schema_name != "simple_description"
                or call.condition != "always"
                or call.depends_on_call_ids
            ):
                raise StrictVisionRunnerError("strict vision preflight launch call is invalid")
        elif call.fixture_id not in fixture_ids:
            raise StrictVisionRunnerError("strict vision launch fixture reference is invalid")
        elif call.kind == "native_plain":
            if (
                call.schema_name is not None
                or call.condition != "always"
                or call.depends_on_call_ids
            ):
                raise StrictVisionRunnerError("strict vision native launch call is invalid")
        elif call.schema_name not in schema_names:
            raise StrictVisionRunnerError("strict vision launch schema reference is invalid")
        if call.condition == "always" and call.depends_on_call_ids:
            raise StrictVisionRunnerError("strict vision unconditional call has dependencies")
        if call.condition in {
            "model_simple_schema_accepted",
            "first_three_model_simple_accepted",
        }:
            dependencies = [calls_by_id.get(call_id) for call_id in call.depends_on_call_ids]
            expected_dependency_ids = tuple(
                candidate.call_id
                for candidate in calls
                if candidate.model_id == call.model_id and candidate.kind == "simple_description"
            )
            if (
                call.depends_on_call_ids != expected_dependency_ids
                or len(dependencies) != 4
                or any(dependency is None for dependency in dependencies)
                or any(
                    dependency is not None
                    and (
                        dependency.model_id != call.model_id
                        or dependency.kind != "simple_description"
                        or dependency.ordinal >= call.ordinal
                    )
                    for dependency in dependencies
                )
            ):
                raise StrictVisionRunnerError("strict vision conditional dependencies are invalid")
            if (
                call.condition == "first_three_model_simple_accepted"
                and call.kind != "simple_repeat"
            ):
                raise StrictVisionRunnerError("strict vision repeat selection condition is invalid")
    _validate_launch_groups(
        calls, models=models, fixture_ids=tuple(item.fixture_id for item in fixtures)
    )
    return StrictVisionLaunchManifest(
        manifest_sha256=actual_sha256,
        source_path=path.resolve(),
        asset_root=root,
        serial=True,
        retry_policy="off",
        max_calls=max_calls,
        models=models,
        prompts=prompts,
        request_controls=request_controls,
        fixtures=fixtures,
        schemas=schemas,
        calls=calls,
    )


def load_strict_vision_continuation_manifest(
    path: Path, *, expected_sha256: str
) -> StrictVisionContinuationManifest:
    """Load the fixed 19-call tail without reopening any of the prior 21 calls."""

    raw_bytes = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or actual_sha256 != expected_sha256:
        raise StrictVisionRunnerError("strict vision continuation manifest digest pin mismatch")
    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as error:
        raise StrictVisionRunnerError(
            "strict vision continuation manifest is not valid JSON"
        ) from error
    if not isinstance(payload, Mapping) or payload.get("manifest_version") != 2:
        raise StrictVisionRunnerError("strict vision continuation manifest version is invalid")
    if payload.get("serial") is not True or payload.get("retry_policy") != "off":
        raise StrictVisionRunnerError("strict vision continuation must be serial with retries off")
    base_path_value = payload.get("base_manifest_path")
    base_sha256 = payload.get("base_manifest_sha256")
    if (
        not isinstance(base_path_value, str)
        or Path(base_path_value).is_absolute()
        or not isinstance(base_sha256, str)
    ):
        raise StrictVisionRunnerError("strict vision continuation base manifest binding is invalid")
    base_path = (path.parent / base_path_value).resolve()
    if not base_path.is_relative_to(path.parent.resolve()):
        raise StrictVisionRunnerError("strict vision continuation base manifest path escapes root")
    base = load_strict_vision_launch_manifest(
        base_path, expected_sha256=base_sha256, asset_root=path.parent
    )
    if payload.get("prior_host_call_count") != 21:
        raise StrictVisionRunnerError("strict vision continuation prior call count must be 21")
    if payload.get("maximum_cumulative_host_calls") != 40:
        raise StrictVisionRunnerError(
            "strict vision continuation cumulative call ceiling must be 40"
        )
    prior_progress_sha256 = payload.get("prior_progress_sha256")
    prior_review_sha256 = payload.get("prior_review_sha256")
    if not all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        for value in (prior_progress_sha256, prior_review_sha256)
    ):
        raise StrictVisionRunnerError(
            "strict vision continuation prior evidence digests are invalid"
        )

    prior_ids = _manifest_string_tuple(
        payload.get("prior_executed_call_ids"), "prior executed call ids"
    )
    accepted_ids = _manifest_string_tuple(
        payload.get("accepted_simple_call_ids"), "accepted simple call ids"
    )
    excluded_ids = _manifest_string_tuple(payload.get("excluded_call_ids"), "excluded call ids")
    continuation_ids = _manifest_string_tuple(payload.get("continuation_call_ids"), "call ids")
    base_calls = {call.call_id: call for call in base.calls}
    expected_prior = tuple(
        call.call_id
        for call in base.calls
        if call.kind in {"text_preflight", "native_plain", "simple_description"}
    )
    expected_accepted = (
        "sv-04-e2b-simple-document_table_products_ru_001",
        "sv-14-e4b-simple-document_table_products_ru_001",
        "sv-15-e4b-simple-chart_tasks_by_month_ru_001",
        "sv-34-26b-simple-document_table_products_ru_001",
    )
    accepted_models = tuple(
        model_id
        for model_id in base.models
        if any(base_calls[call_id].model_id == model_id for call_id in expected_accepted)
    )
    repeat_ids = {
        call.call_id
        for call in base.calls
        if call.kind == "simple_repeat" and call.model_id in accepted_models[:3]
    }
    expected_continuation = tuple(
        call.call_id
        for call in base.calls
        if call.kind == "medium_objects_text" or call.call_id in repeat_ids
    )
    if prior_ids != expected_prior or accepted_ids != expected_accepted:
        raise StrictVisionRunnerError("strict vision continuation prior adjudication is invalid")
    adjudication = payload.get("simple_adjudication")
    expected_simple_ids = tuple(
        call.call_id for call in base.calls if call.kind == "simple_description"
    )
    if not isinstance(adjudication, list) or len(adjudication) != 16:
        raise StrictVisionRunnerError(
            "strict vision continuation simple adjudication is incomplete"
        )
    adjudicated_ids: list[str] = []
    adjudicated_accepted: list[str] = []
    for item in adjudication:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("call_id"), str)
            or not isinstance(item.get("accepted"), bool)
            or not isinstance(item.get("findings"), list)
            or not item.get("findings")
            or any(not isinstance(finding, str) or not finding for finding in item["findings"])
        ):
            raise StrictVisionRunnerError(
                "strict vision continuation simple adjudication is invalid"
            )
        call_id = str(item["call_id"])
        adjudicated_ids.append(call_id)
        if item["accepted"] is True:
            adjudicated_accepted.append(call_id)
    if tuple(adjudicated_ids) != expected_simple_ids or tuple(adjudicated_accepted) != accepted_ids:
        raise StrictVisionRunnerError("strict vision continuation simple errors were substituted")
    if continuation_ids != expected_continuation or excluded_ids != ("sv-31-12b-repeat-ui",):
        raise StrictVisionRunnerError("strict vision continuation exact 19-call tail is invalid")
    if set(prior_ids) & set(continuation_ids) or len(continuation_ids) != 19:
        raise StrictVisionRunnerError("strict vision continuation repeats a prior call")
    if set(prior_ids) | set(continuation_ids) | set(excluded_ids) != set(base_calls):
        raise StrictVisionRunnerError("strict vision continuation does not reconcile base rows")

    raw_truth = payload.get("corrected_fixture_truth")
    if not isinstance(raw_truth, Mapping) or set(raw_truth) != set(STRICT_VISION_FIXTURE_IDS):
        raise StrictVisionRunnerError("strict vision continuation fixture truth is incomplete")
    fixtures: list[StrictVisionFixture] = []
    for fixture in base.fixtures:
        truth = raw_truth.get(fixture.fixture_id)
        if not isinstance(truth, Mapping):
            raise StrictVisionRunnerError("strict vision continuation fixture truth is invalid")
        _validate_continuation_truth_contract(truth)
        fixtures.append(replace(fixture, ground_truth=_freeze_mapping(truth)))
    calls = tuple(base_calls[call_id] for call_id in continuation_ids)
    return StrictVisionContinuationManifest(
        manifest_sha256=actual_sha256,
        source_path=path.resolve(),
        asset_root=path.parent.resolve(),
        base_manifest_sha256=base.manifest_sha256,
        prior_progress_sha256=str(prior_progress_sha256),
        prior_review_sha256=str(prior_review_sha256),
        prior_host_call_count=21,
        maximum_cumulative_host_calls=40,
        prior_executed_call_ids=prior_ids,
        accepted_simple_call_ids=accepted_ids,
        excluded_call_ids=excluded_ids,
        models=base.models,
        prompts=base.prompts,
        request_controls=base.request_controls,
        fixtures=tuple(fixtures),
        schemas=base.schemas,
        calls=calls,
    )


def _validate_continuation_truth_contract(ground_truth: Mapping[str, object]) -> None:
    _required_string_list(ground_truth, "expected_visible_text")
    _required_string_list(ground_truth, "expected_objects")
    _required_string_list(ground_truth, "forbidden_claims")
    policy = ground_truth.get("visible_text_precision_policy")
    if policy not in {
        "complete_transcript_with_manual_phrase_adjudication",
        "manual_pixel_adjudication_open_world",
    }:
        raise StrictVisionRunnerError("strict vision continuation text precision policy is invalid")
    if ground_truth.get("object_precision_policy") != "manual_pixel_adjudication_open_world":
        raise StrictVisionRunnerError(
            "strict vision continuation object precision policy is invalid"
        )
    transcript = ground_truth.get("complete_visible_text")
    if policy == "complete_transcript_with_manual_phrase_adjudication":
        if not isinstance(transcript, list) or not transcript:
            raise StrictVisionRunnerError("strict vision continuation transcript is incomplete")
        _required_string_list(ground_truth, "complete_visible_text")
    elif transcript is not None:
        raise StrictVisionRunnerError("open-world truth must not claim an exhaustive transcript")


def _validate_launch_controls(payload: Mapping[str, object]) -> None:
    if payload.get("manifest_version") != 1:
        raise StrictVisionRunnerError("strict vision launch manifest version is invalid")
    builder = payload.get("fixture_builder")
    expected_builder = {
        "implementation": "lmstudio_labkit.strict_vision.build_strict_vision_fixture",
        "pillow_version": "11.3.0",
        "max_side": 1024,
        "format": "PNG",
        "resample": "LANCZOS",
        "compress_level": 9,
    }
    if not isinstance(builder, Mapping) or dict(builder) != expected_builder:
        raise StrictVisionRunnerError("strict vision launch fixture builder is not frozen")
    request = payload.get("strict_request")
    expected_request = {
        "endpoint": "/v1/chat/completions",
        "context_length": 8192,
        "max_tokens": 1024,
        "temperature": 0.0,
        "stream": False,
        "reasoning_effort": "none",
        "enable_thinking": False,
    }
    if not isinstance(request, Mapping) or dict(request) != expected_request:
        raise StrictVisionRunnerError("strict vision launch request controls are not frozen")
    prompts = payload.get("prompts")
    if not isinstance(prompts, list) or len(prompts) != 4:
        raise StrictVisionRunnerError("strict vision launch prompts are invalid")
    prompt_names: set[str] = set()
    for item in prompts:
        if not isinstance(item, Mapping):
            raise StrictVisionRunnerError("strict vision launch prompt is invalid")
        name = item.get("name")
        text = item.get("text")
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or not isinstance(text, str)
            or not text
            or digest != hashlib.sha256(text.encode()).hexdigest()
        ):
            raise StrictVisionRunnerError("strict vision launch prompt digest mismatch")
        prompt_names.add(name)
    if prompt_names != {
        "native_plain",
        "simple_description",
        "medium_objects_text",
        "text_preflight",
    }:
        raise StrictVisionRunnerError("strict vision launch prompt names are invalid")
    gates = payload.get("conditional_gates")
    expected_gates = {
        "route_rejection": "stop_all_after_first_e2b_schema_image",
        "simple_hard_failure": "block_model_medium_and_repeat",
        "semantic_failure": "block_model_admission",
        "finish_reason": "require_stop",
        "reasoning": "require_observed_zero",
        "cleanup": "require_global_zero",
    }
    if not isinstance(gates, Mapping) or dict(gates) != expected_gates:
        raise StrictVisionRunnerError("strict vision launch conditional gates are not frozen")


def _manifest_string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise StrictVisionRunnerError(f"strict vision launch {label} are invalid")
    return tuple(value)


def _load_manifest_fixtures(value: object, *, root: Path) -> tuple[StrictVisionFixture, ...]:
    if not isinstance(value, list) or len(value) != 4:
        raise StrictVisionRunnerError("strict vision launch requires four fixtures")
    fixtures: list[StrictVisionFixture] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise StrictVisionRunnerError("strict vision launch fixture is invalid")
        fixture_id = item.get("fixture_id")
        relative_path = item.get("path")
        digest = item.get("sha256")
        source_digest = item.get("source_sha256")
        width = item.get("width")
        height = item.get("height")
        ground_truth = item.get("ground_truth")
        if (
            not isinstance(fixture_id, str)
            or not isinstance(relative_path, str)
            or Path(relative_path).is_absolute()
            or not isinstance(digest, str)
            or not isinstance(source_digest, str)
            or not isinstance(width, int)
            or isinstance(width, bool)
            or not isinstance(height, int)
            or isinstance(height, bool)
            or not isinstance(ground_truth, Mapping)
        ):
            raise StrictVisionRunnerError("strict vision launch fixture fields are invalid")
        fixture_path = root / relative_path
        if not fixture_path.resolve().is_relative_to(root.resolve()):
            raise StrictVisionRunnerError("strict vision launch fixture path escapes asset root")
        fixture_bytes = fixture_path.read_bytes()
        if hashlib.sha256(fixture_bytes).hexdigest() != digest:
            raise StrictVisionRunnerError("strict vision launch fixture digest mismatch")
        if fixture_path.name != f"{digest}.png" or _png_dimensions(fixture_bytes) != (
            width,
            height,
        ):
            raise StrictVisionRunnerError("strict vision launch fixture identity mismatch")
        if max(width, height) > 1024:
            raise StrictVisionRunnerError("strict vision launch fixture exceeds max side")
        _validate_ground_truth_contract(ground_truth)
        fixtures.append(
            StrictVisionFixture(
                fixture_id=fixture_id,
                path=fixture_path,
                sha256=digest,
                width=width,
                height=height,
                source_sha256=source_digest,
                ground_truth=_freeze_mapping(ground_truth),
            )
        )
    if tuple(item.fixture_id for item in fixtures) != STRICT_VISION_FIXTURE_IDS:
        raise StrictVisionRunnerError("strict vision launch exact fixture order is invalid")
    return tuple(fixtures)


def _validate_ground_truth_contract(ground_truth: Mapping[str, object]) -> None:
    expected_text = _required_string_list(ground_truth, "expected_visible_text")
    expected_objects = _required_string_list(ground_truth, "expected_objects")
    supported_text = _required_string_list(ground_truth, "supported_visible_text")
    supported_objects = _required_string_list(ground_truth, "supported_objects")
    _required_string_list(ground_truth, "forbidden_claims")
    _grounding_threshold(ground_truth, "minimum_visible_text_recall")
    _grounding_threshold(ground_truth, "minimum_object_recall")
    _grounding_threshold(ground_truth, "minimum_visible_text_precision")
    _grounding_threshold(ground_truth, "minimum_object_precision")
    if not expected_text or not expected_objects or not supported_text or not supported_objects:
        raise StrictVisionRunnerError("strict vision launch ground truth is incomplete")


def _load_manifest_schemas(value: object) -> tuple[StrictVisionSchema, ...]:
    if not isinstance(value, list) or len(value) != 2:
        raise StrictVisionRunnerError("strict vision launch requires two schemas")
    schemas: list[StrictVisionSchema] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise StrictVisionRunnerError("strict vision launch schema is invalid")
        name = item.get("name")
        digest = item.get("sha256")
        body = item.get("body")
        if (
            not isinstance(name, str)
            or not isinstance(digest, str)
            or not isinstance(body, Mapping)
        ):
            raise StrictVisionRunnerError("strict vision launch schema fields are invalid")
        canonical = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        if hashlib.sha256(canonical).hexdigest() != digest:
            raise StrictVisionRunnerError("strict vision launch schema digest mismatch")
        schemas.append(StrictVisionSchema(name=name, sha256=digest, body=_freeze_mapping(body)))
    if {schema.name for schema in schemas} != {"simple_description", "medium_objects_text"}:
        raise StrictVisionRunnerError("strict vision launch schema names are invalid")
    return tuple(schemas)


def _load_manifest_calls(value: object) -> tuple[StrictVisionLaunchCall, ...]:
    if not isinstance(value, list):
        raise StrictVisionRunnerError("strict vision launch calls are invalid")
    calls: list[StrictVisionLaunchCall] = []
    allowed_kinds = {
        "text_preflight",
        "native_plain",
        "simple_description",
        "medium_objects_text",
        "simple_repeat",
    }
    allowed_conditions = {
        "always",
        "model_simple_schema_accepted",
        "first_three_model_simple_accepted",
    }
    for item in value:
        if not isinstance(item, Mapping):
            raise StrictVisionRunnerError("strict vision launch call is invalid")
        ordinal = item.get("ordinal")
        call_id = item.get("call_id")
        model_id = item.get("model_id")
        fixture_id = item.get("fixture_id")
        kind = item.get("kind")
        schema_name = item.get("schema_name")
        condition = item.get("condition")
        dependencies = item.get("depends_on_call_ids")
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or not isinstance(call_id, str)
            or not isinstance(model_id, str)
            or (fixture_id is not None and not isinstance(fixture_id, str))
            or kind not in allowed_kinds
            or (schema_name is not None and not isinstance(schema_name, str))
            or condition not in allowed_conditions
            or not isinstance(dependencies, list)
            or any(not isinstance(dependency, str) for dependency in dependencies)
        ):
            raise StrictVisionRunnerError("strict vision launch call fields are invalid")
        calls.append(
            StrictVisionLaunchCall(
                ordinal=ordinal,
                call_id=call_id,
                model_id=model_id,
                fixture_id=fixture_id,
                kind=kind,
                schema_name=schema_name,
                condition=condition,
                depends_on_call_ids=tuple(dependencies),
            )
        )
    return tuple(calls)


def _validate_launch_groups(
    calls: tuple[StrictVisionLaunchCall, ...],
    *,
    models: tuple[str, ...],
    fixture_ids: tuple[str, ...],
) -> None:
    expected: list[tuple[str, str | None, str, str | None, str]] = [
        (models[0], None, "text_preflight", "simple_description", "always")
    ]
    ui_fixture = fixture_ids[0]
    for model_id in models:
        expected.append((model_id, ui_fixture, "native_plain", None, "always"))
        expected.extend(
            (model_id, fixture_id, "simple_description", "simple_description", "always")
            for fixture_id in fixture_ids
        )
        expected.extend(
            (
                model_id,
                fixture_id,
                "medium_objects_text",
                "medium_objects_text",
                "model_simple_schema_accepted",
            )
            for fixture_id in fixture_ids
        )
        expected.append(
            (
                model_id,
                ui_fixture,
                "simple_repeat",
                "simple_description",
                "first_three_model_simple_accepted",
            )
        )
    actual = [
        (call.model_id, call.fixture_id, call.kind, call.schema_name, call.condition)
        for call in calls
    ]
    if actual != expected:
        raise StrictVisionRunnerError("strict vision launch frozen model/cell order is invalid")


@dataclass(frozen=True, slots=True)
class StrictVisionLaunchRowResult:
    ordinal: int
    call_id: str
    model_id: str
    kind: str
    status: Literal["executed", "skipped"]
    accepted: bool | None
    host_call_index: int | None
    safe_binding: Mapping[str, object]
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StrictVisionLaunchResult:
    manifest_sha256: str
    rows: tuple[StrictVisionLaunchRowResult, ...]
    host_call_count: int
    stop_reason: str | None
    final_loaded_global_count: int


@dataclass(frozen=True, slots=True)
class StrictVisionContinuationResult:
    manifest_sha256: str
    rows: tuple[StrictVisionLaunchRowResult, ...]
    continuation_host_call_count: int
    cumulative_host_call_count: int
    final_loaded_global_count: int


@dataclass(slots=True)
class StrictVisionLaunchController:
    """Execute only the independently pinned manifest's serial host-call schedule."""

    manifest: StrictVisionLaunchManifest
    host_runner: StrictVisionControllerHostRunner
    failure_forensics: LocalFailureForensics
    allow_model_loads: bool = False
    timeout_s: float = 120.0

    def run(self) -> StrictVisionLaunchResult:
        verified_manifest = load_strict_vision_launch_manifest(
            self.manifest.source_path,
            expected_sha256=self.manifest.manifest_sha256,
            asset_root=self.manifest.asset_root,
        )
        if verified_manifest != self.manifest:
            raise StrictVisionRunnerError(
                "strict vision controller manifest snapshot was substituted"
            )
        if not self.allow_model_loads:
            raise StrictVisionRunnerError(
                "strict vision controller model loads require allow_model_loads=true"
            )
        if not self.failure_forensics.enabled:
            raise StrictVisionRunnerError("strict vision controller requires owner-only capture")
        if self.manifest.max_calls != 40 or len(self.manifest.calls) != 41:
            raise StrictVisionRunnerError(
                "strict vision controller requires 41 candidate rows and at most 40 host calls"
            )
        ledger_path = self.failure_forensics.root / "strict-vision-progress.jsonl"
        try:
            descriptor = os.open(
                ledger_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND,
                0o600,
            )
        except FileExistsError as error:
            raise StrictVisionRunnerError(
                "strict vision append-only progress already exists"
            ) from error
        os.close(descriptor)
        os.chmod(ledger_path, 0o600)

        rows: list[StrictVisionLaunchRowResult] = []
        accepted_by_call_id: dict[str, bool] = {}
        host_call_count = 0
        selected_repeat_count = 0
        stop_reason: str | None = None
        runner = StrictStructuredVisionRunner(
            host_runner=self.host_runner,
            failure_forensics=self.failure_forensics,
            allow_model_loads=True,
        )
        calls_by_model = {
            model_id: [call for call in self.manifest.calls if call.model_id == model_id]
            for model_id in self.manifest.models
        }
        for model_id in self.manifest.models:
            model_calls = calls_by_model[model_id]
            if stop_reason is not None:
                for call in model_calls:
                    row = self._skipped_row(call, stop_reason)
                    rows.append(row)
                    self._append_progress(ledger_path, row)
                continue
            metadata = self.host_runner.model_metadata(model_id=model_id)
            _validate_exact_vlm_metadata(metadata, model_id=model_id)
            initial_loaded = self.host_runner.count_all_loaded_instances()
            if initial_loaded is None or initial_loaded != 0:
                raise StrictVisionRunnerError(
                    "strict vision controller requires verified global zero before load"
                )
            handles: list[ForensicsRecordHandle] = []
            load_attempted = False
            cleanup_response: object = {"cleanup_verified": False}
            final_loaded: int | None = None
            try:
                load_attempted = True
                load_response = self.host_runner.load_model(
                    model_id=model_id,
                    context_length=int(self.manifest.request_controls["context_length"]),
                    parallel=1,
                )
                if not _load_verified(load_response, context_length=8192):
                    raise StrictVisionRunnerError("strict vision controller load was not verified")
                if self.host_runner.count_all_loaded_instances() != 1:
                    raise StrictVisionRunnerError(
                        "strict vision controller requires one global loaded instance"
                    )
                _validate_materialized_model_metadata(
                    self.host_runner.model_metadata(model_id=model_id),
                    model_id=model_id,
                    context_length=8192,
                )
                for call in model_calls:
                    if stop_reason is not None:
                        row = self._skipped_row(call, stop_reason)
                    elif call.condition != "always" and not all(
                        accepted_by_call_id.get(call_id) is True
                        for call_id in call.depends_on_call_ids
                    ):
                        row = self._skipped_row(call, "model_simple_schema_not_accepted")
                    elif (
                        call.condition == "first_three_model_simple_accepted"
                        and selected_repeat_count >= 3
                    ):
                        row = self._skipped_row(call, "first_three_accepted_models_selected")
                    else:
                        if host_call_count >= self.manifest.max_calls:
                            raise StrictVisionRunnerError(
                                "strict vision host call 41 is impossible"
                            )
                        host_call_count += 1
                        row, handle = self._execute_manifest_call(
                            runner=runner,
                            call=call,
                            host_call_index=host_call_count,
                        )
                        if call.condition == "first_three_model_simple_accepted":
                            selected_repeat_count += 1
                        if handle is not None:
                            handles.append(handle)
                        accepted_by_call_id[call.call_id] = row.accepted is True
                        if call.kind == "text_preflight" and row.accepted is not True:
                            stop_reason = "matrix_text_preflight_failed"
                        elif (
                            call.kind == "simple_description"
                            and call.model_id == self.manifest.models[0]
                            and call.fixture_id == self.manifest.fixtures[0].fixture_id
                            and row.accepted is not True
                            and row.safe_binding.get("route_surface_accepted") is not True
                        ):
                            stop_reason = "first_schema_image_route_rejected"
                    rows.append(row)
                    self._append_progress(ledger_path, row)
            finally:
                if load_attempted:
                    cleanup_response = self.host_runner.cleanup_model(model_id=model_id)
                    final_loaded = self.host_runner.count_all_loaded_instances()
                    for handle in handles:
                        self.failure_forensics.finalize_attempt(
                            handle,
                            cleanup_result=cleanup_response,
                            final_loaded_instances=final_loaded,
                        )
                    if not _cleanup_verified(cleanup_response):
                        raise StrictVisionRunnerError(
                            "strict vision controller cleanup was not verified"
                        )
                    if final_loaded != 0:
                        raise StrictVisionRunnerError(
                            "strict vision controller final global loaded count must be zero"
                        )
        final_global = self.host_runner.count_all_loaded_instances()
        if final_global != 0:
            raise StrictVisionRunnerError(
                "strict vision controller matrix-final global loaded count must be zero"
            )
        if [row.ordinal for row in rows] != list(range(1, len(self.manifest.calls) + 1)):
            raise StrictVisionRunnerError("strict vision controller did not reconcile all ordinals")
        return StrictVisionLaunchResult(
            manifest_sha256=self.manifest.manifest_sha256,
            rows=tuple(rows),
            host_call_count=host_call_count,
            stop_reason=stop_reason,
            final_loaded_global_count=0,
        )

    def _execute_manifest_call(
        self,
        *,
        runner: StrictStructuredVisionRunner,
        call: StrictVisionLaunchCall,
        host_call_index: int,
    ) -> tuple[StrictVisionLaunchRowResult, ForensicsRecordHandle | None]:
        binding = self._binding(call, host_call_index=host_call_index)
        request_id = f"{self.manifest.manifest_sha256}:{call.ordinal}:{call.call_id}"
        if call.kind == "native_plain":
            fixture = self._fixture(call.fixture_id)
            result = self.host_runner.native_chat_diagnostic(
                model_id=call.model_id,
                messages=[{"role": "user", "content": self.manifest.prompts["native_plain"]}],
                reasoning=None,
                max_output_tokens=int(self.manifest.request_controls["max_tokens"]),
                timeout_s=self.timeout_s,
                stream=False,
                request_id=request_id,
                attempt_index=call.ordinal,
                context_length=int(self.manifest.request_controls["context_length"]),
                image_data_url=_fixture_data_url(fixture),
                capture_outbound_request=True,
            )
            handle = getattr(result, "forensics_handle", None)
            if not isinstance(handle, ForensicsRecordHandle):
                raise StrictVisionRunnerError(
                    "strict vision native baseline did not produce owner-only capture"
                )
            accepted = (
                getattr(result, "http_status", None) == 200
                and bool(getattr(result, "message_text", ""))
                and getattr(result, "finish_reason", None) == "stop"
                and getattr(result, "boundary", None) == "terminal"
            )
            binding["route_surface_accepted"] = accepted
            binding["request_id_sha256"] = hashlib.sha256(request_id.encode()).hexdigest()
            private_capture = self.failure_forensics.safe_manifest_entry(handle)
            max_output_tokens = self.manifest.request_controls["max_tokens"]
            assert isinstance(max_output_tokens, int) and not isinstance(max_output_tokens, bool)
            expected_native_payload = _native_plain_payload(
                model_id=call.model_id,
                prompt=self.manifest.prompts["native_plain"],
                image_data_url=_fixture_data_url(fixture),
                max_output_tokens=max_output_tokens,
            )
            expected_payload_sha256 = _canonical_sha256(expected_native_payload)
            outbound = private_capture.get("outbound")
            if (
                not isinstance(outbound, Mapping)
                or outbound.get("captured") is not True
                or outbound.get("endpoint") != "/api/v1/chat"
                or outbound.get("payload_sha256") != expected_payload_sha256
            ):
                raise StrictVisionRunnerError(
                    "strict vision native outbound capture does not match production payload"
                )
            binding["native_payload_sha256"] = expected_payload_sha256
            binding["private_capture"] = private_capture
            return self._executed_row(call, accepted, host_call_index, binding), handle

        request = self._request_for_call(call, request_id=request_id)
        if call.kind == "text_preflight":
            payload = _build_payload(request, content=self.manifest.prompts["text_preflight"])
            modality: Literal["text", "image"] = "text"
        else:
            fixture = self._fixture(call.fixture_id)
            prompt_name = "simple_description" if call.kind == "simple_repeat" else call.kind
            payload = _build_payload(
                request,
                content=[
                    {"type": "text", "text": self.manifest.prompts[prompt_name]},
                    {"type": "image_url", "image_url": {"url": _fixture_data_url(fixture)}},
                ],
            )
            modality = "image"
        self._validate_exact_payload(payload, call=call)
        outcome, handle = runner._execute_call(
            request=request,
            modality=modality,
            attempt_index=call.ordinal,
            payload=payload,
        )
        binding["route_surface_accepted"] = (
            outcome.transport_status == "pass" and outcome.response_surface_status == "pass"
        )
        captured_request_id = f"{request_id}:{modality}"
        binding["request_id_sha256"] = hashlib.sha256(captured_request_id.encode()).hexdigest()
        binding["private_capture"] = outcome.private_capture
        return self._executed_row(call, outcome.accepted, host_call_index, binding), handle

    def _request_for_call(
        self, call: StrictVisionLaunchCall, *, request_id: str
    ) -> StrictVisionRequest:
        schema = self._schema(call.schema_name)
        fixture = (
            self._fixture(call.fixture_id)
            if call.fixture_id is not None
            else self.manifest.fixtures[0]
        )
        prompt_name = "simple_description" if call.kind == "simple_repeat" else call.kind
        if prompt_name == "text_preflight":
            prompt_name = "simple_description"
        return StrictVisionRequest(
            request_id=request_id,
            model_id=call.model_id,
            preflight_prompt=self.manifest.prompts["text_preflight"],
            image_prompt=self.manifest.prompts[prompt_name],
            image_data_url=_fixture_data_url(fixture),
            fixture_id=fixture.fixture_id,
            fixture_sha256=fixture.sha256,
            fixture_width=fixture.width,
            fixture_height=fixture.height,
            schema_name=schema.name,
            schema=_thaw_mapping(schema.body),
            image_ground_truth=_thaw_mapping(fixture.ground_truth),
            context_length=int(self.manifest.request_controls["context_length"]),
            max_tokens=int(self.manifest.request_controls["max_tokens"]),
            timeout_s=self.timeout_s,
        )

    def _validate_exact_payload(
        self, payload: Mapping[str, object], *, call: StrictVisionLaunchCall
    ) -> None:
        controls = self.manifest.request_controls
        for key in ("temperature", "stream", "reasoning_effort", "enable_thinking"):
            if payload.get(key) != controls[key]:
                raise StrictVisionRunnerError(
                    f"strict vision payload diverged from manifest control {key}"
                )
        if payload.get("max_tokens") != controls["max_tokens"]:
            raise StrictVisionRunnerError("strict vision payload diverged from manifest output cap")
        if payload.get("model") != call.model_id:
            raise StrictVisionRunnerError("strict vision payload model substitution detected")

    def _fixture(self, fixture_id: str | None) -> StrictVisionFixture:
        matches = [item for item in self.manifest.fixtures if item.fixture_id == fixture_id]
        if len(matches) != 1:
            raise StrictVisionRunnerError("strict vision manifest fixture binding failed")
        return matches[0]

    def _schema(self, schema_name: str | None) -> StrictVisionSchema:
        matches = [item for item in self.manifest.schemas if item.name == schema_name]
        if len(matches) != 1:
            raise StrictVisionRunnerError("strict vision manifest schema binding failed")
        return matches[0]

    def _binding(
        self, call: StrictVisionLaunchCall, *, host_call_index: int | None
    ) -> dict[str, object]:
        fixture = self._fixture(call.fixture_id) if call.fixture_id is not None else None
        schema = self._schema(call.schema_name) if call.schema_name is not None else None
        return {
            "manifest_sha256": self.manifest.manifest_sha256,
            "ordinal": call.ordinal,
            "call_id": call.call_id,
            "model_id": call.model_id,
            "kind": call.kind,
            "fixture_sha256": fixture.sha256 if fixture is not None else None,
            "schema_sha256": schema.sha256 if schema is not None else None,
            "request_controls_sha256": _canonical_sha256(self.manifest.request_controls),
            "host_call_index": host_call_index,
        }

    def _executed_row(
        self,
        call: StrictVisionLaunchCall,
        accepted: bool,
        host_call_index: int,
        binding: Mapping[str, object],
    ) -> StrictVisionLaunchRowResult:
        return StrictVisionLaunchRowResult(
            ordinal=call.ordinal,
            call_id=call.call_id,
            model_id=call.model_id,
            kind=call.kind,
            status="executed",
            accepted=accepted,
            host_call_index=host_call_index,
            safe_binding=_freeze_mapping(binding),
        )

    def _skipped_row(
        self, call: StrictVisionLaunchCall, reason: str
    ) -> StrictVisionLaunchRowResult:
        return StrictVisionLaunchRowResult(
            ordinal=call.ordinal,
            call_id=call.call_id,
            model_id=call.model_id,
            kind=call.kind,
            status="skipped",
            accepted=None,
            host_call_index=None,
            safe_binding=_freeze_mapping(self._binding(call, host_call_index=None)),
            skip_reason=reason,
        )

    @staticmethod
    def _append_progress(path: Path, row: StrictVisionLaunchRowResult) -> None:
        payload = {
            "record_type": "call",
            **_thaw_mapping(row.safe_binding),
            "status": row.status,
            "accepted": row.accepted,
            "skip_reason": row.skip_reason,
        }
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(slots=True)
class StrictVisionContinuationController:
    """Execute the reviewed 19-call tail after verifying immutable prior evidence."""

    manifest: StrictVisionContinuationManifest
    host_runner: StrictVisionControllerHostRunner
    failure_forensics: LocalFailureForensics
    prior_progress_path: Path
    prior_review_path: Path
    allow_model_loads: bool = False
    timeout_s: float = 120.0

    def run(self) -> StrictVisionContinuationResult:
        verified = load_strict_vision_continuation_manifest(
            self.manifest.source_path, expected_sha256=self.manifest.manifest_sha256
        )
        if verified != self.manifest:
            raise StrictVisionRunnerError(
                "strict vision continuation manifest snapshot was substituted"
            )
        if not self.allow_model_loads:
            raise StrictVisionRunnerError(
                "strict vision continuation model loads require allow_model_loads=true"
            )
        if not self.failure_forensics.enabled:
            raise StrictVisionRunnerError("strict vision continuation requires owner-only capture")
        self._validate_prior_evidence()
        if self.host_runner.count_all_loaded_instances() != 0:
            raise StrictVisionRunnerError(
                "strict vision continuation requires verified global zero before execution"
            )
        ledger_path = self.failure_forensics.root / "strict-vision-continuation-progress.jsonl"
        try:
            descriptor = os.open(
                ledger_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND,
                0o600,
            )
        except FileExistsError as error:
            raise StrictVisionRunnerError(
                "strict vision continuation append-only progress already exists"
            ) from error
        os.close(descriptor)
        os.chmod(ledger_path, 0o600)

        rows: list[StrictVisionLaunchRowResult] = []
        cumulative_call_count = self.manifest.prior_host_call_count
        executor = StrictVisionLaunchController(
            manifest=self.manifest,  # type: ignore[arg-type]
            host_runner=self.host_runner,
            failure_forensics=self.failure_forensics,
            allow_model_loads=True,
            timeout_s=self.timeout_s,
        )
        calls_by_model = {
            model_id: [call for call in self.manifest.calls if call.model_id == model_id]
            for model_id in self.manifest.models
        }
        for model_id in self.manifest.models:
            model_calls = calls_by_model[model_id]
            if not model_calls:
                continue
            metadata = self.host_runner.model_metadata(model_id=model_id)
            _validate_exact_vlm_metadata(metadata, model_id=model_id)
            if self.host_runner.count_all_loaded_instances() != 0:
                raise StrictVisionRunnerError(
                    "strict vision continuation requires global zero before each load"
                )
            handles: list[ForensicsRecordHandle] = []
            load_attempted = False
            try:
                load_attempted = True
                context_length = self.manifest.request_controls["context_length"]
                if not isinstance(context_length, int) or isinstance(context_length, bool):
                    raise StrictVisionRunnerError(
                        "strict vision continuation context length is invalid"
                    )
                load_response = self.host_runner.load_model(
                    model_id=model_id,
                    context_length=context_length,
                    parallel=1,
                )
                if not _load_verified(load_response, context_length=8192):
                    raise StrictVisionRunnerError(
                        "strict vision continuation load was not verified"
                    )
                if self.host_runner.count_all_loaded_instances() != 1:
                    raise StrictVisionRunnerError(
                        "strict vision continuation requires one global loaded instance"
                    )
                _validate_materialized_model_metadata(
                    self.host_runner.model_metadata(model_id=model_id),
                    model_id=model_id,
                    context_length=8192,
                )
                for call in model_calls:
                    if cumulative_call_count >= self.manifest.maximum_cumulative_host_calls:
                        raise StrictVisionRunnerError(
                            "strict vision cumulative host call 41 is impossible"
                        )
                    cumulative_call_count += 1
                    row, handle = executor._execute_manifest_call(
                        runner=StrictStructuredVisionRunner(
                            host_runner=self.host_runner,
                            failure_forensics=self.failure_forensics,
                            allow_model_loads=True,
                        ),
                        call=call,
                        host_call_index=cumulative_call_count,
                    )
                    if handle is not None:
                        handles.append(handle)
                    rows.append(row)
                    self._append_progress(ledger_path, row)
            finally:
                if load_attempted:
                    cleanup_response = self.host_runner.cleanup_model(model_id=model_id)
                    final_loaded = self.host_runner.count_all_loaded_instances()
                    for handle in handles:
                        self.failure_forensics.finalize_attempt(
                            handle,
                            cleanup_result=cleanup_response,
                            final_loaded_instances=final_loaded,
                        )
                    if not _cleanup_verified(cleanup_response) or final_loaded != 0:
                        raise StrictVisionRunnerError(
                            "strict vision continuation cleanup did not reach global zero"
                        )
        if len(rows) != 19 or cumulative_call_count != 40:
            raise StrictVisionRunnerError(
                "strict vision continuation did not execute the exact 19-call tail"
            )
        if tuple(row.call_id for row in rows) != tuple(
            call.call_id for call in self.manifest.calls
        ):
            raise StrictVisionRunnerError("strict vision continuation call order diverged")
        if self.host_runner.count_all_loaded_instances() != 0:
            raise StrictVisionRunnerError(
                "strict vision continuation matrix-final global count must be zero"
            )
        return StrictVisionContinuationResult(
            manifest_sha256=self.manifest.manifest_sha256,
            rows=tuple(rows),
            continuation_host_call_count=19,
            cumulative_host_call_count=40,
            final_loaded_global_count=0,
        )

    def _validate_prior_evidence(self) -> None:
        progress_bytes = self.prior_progress_path.read_bytes()
        review_bytes = self.prior_review_path.read_bytes()
        if hashlib.sha256(progress_bytes).hexdigest() != self.manifest.prior_progress_sha256:
            raise StrictVisionRunnerError("strict vision prior progress digest mismatch")
        if hashlib.sha256(review_bytes).hexdigest() != self.manifest.prior_review_sha256:
            raise StrictVisionRunnerError("strict vision prior review digest mismatch")
        try:
            progress = [json.loads(line) for line in progress_bytes.splitlines() if line]
            review = json.loads(review_bytes)
        except json.JSONDecodeError as error:
            raise StrictVisionRunnerError("strict vision prior evidence is malformed") from error
        if len(progress) != 41 or not isinstance(review, Mapping):
            raise StrictVisionRunnerError("strict vision prior evidence row count is invalid")
        executed = [row for row in progress if row.get("status") == "executed"]
        executed_ids = tuple(str(row.get("call_id")) for row in executed)
        host_indices = [row.get("host_call_index") for row in executed]
        if executed_ids != self.manifest.prior_executed_call_ids:
            raise StrictVisionRunnerError("strict vision prior executed calls were substituted")
        if host_indices != list(range(1, self.manifest.prior_host_call_count + 1)):
            raise StrictVisionRunnerError("strict vision prior host call indices are invalid")
        skipped_ids = {
            str(row.get("call_id")) for row in progress if row.get("status") == "skipped"
        }
        expected_skipped = {call.call_id for call in self.manifest.calls} | set(
            self.manifest.excluded_call_ids
        )
        if skipped_ids != expected_skipped:
            raise StrictVisionRunnerError("strict vision prior skipped rows are invalid")
        review_rows = review.get("rows")
        if not isinstance(review_rows, list):
            raise StrictVisionRunnerError("strict vision prior review rows are invalid")
        accepted: list[str] = []
        for row in review_rows:
            if not isinstance(row, Mapping) or row.get("kind") != "simple_description":
                continue
            manual = row.get("manual_review")
            if not isinstance(manual, Mapping):
                raise StrictVisionRunnerError("strict vision prior manual review is invalid")
            if (
                manual.get("grounded") is True
                and manual.get("visible_text_exact") is True
                and manual.get("warnings_supported_and_relevant") is True
                and manual.get("forbidden_claims_present") is False
            ):
                accepted.append(str(row.get("call_id")))
        if tuple(accepted) != self.manifest.accepted_simple_call_ids:
            raise StrictVisionRunnerError("strict vision accepted simple rows were substituted")

    @staticmethod
    def _append_progress(path: Path, row: StrictVisionLaunchRowResult) -> None:
        payload = {
            "record_type": "continuation_call",
            **_thaw_mapping(row.safe_binding),
            "status": row.status,
            "accepted": row.accepted,
        }
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _fixture_data_url(fixture: StrictVisionFixture) -> str:
    encoded = base64.b64encode(fixture.path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _native_plain_payload(
    *,
    model_id: str,
    prompt: str,
    image_data_url: str,
    max_output_tokens: int,
) -> dict[str, object]:
    return {
        "model": model_id,
        "input": [
            {"type": "text", "content": prompt},
            {"type": "image", "data_url": image_data_url},
        ],
        "max_output_tokens": max_output_tokens,
        "temperature": 0.0,
        "stream": False,
        "store": False,
    }


def _thaw_mapping(value: Mapping[str, object]) -> dict[str, Any]:
    return {key: _thaw_json(item) for key, item in value.items()}


def _thaw_json(value: object) -> Any:
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _thaw_mapping(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


__all__ = [
    "StrictVisionContinuationController",
    "StrictVisionContinuationManifest",
    "StrictVisionContinuationResult",
    "StrictVisionFixture",
    "StrictVisionLaunchController",
    "StrictVisionLaunchCall",
    "StrictVisionLaunchManifest",
    "StrictVisionLaunchResult",
    "StrictVisionLaunchRowResult",
    "StrictVisionSchema",
    "StrictVisionHostRunner",
    "StrictVisionRunnerError",
    "StructuredCallOutcome",
    "build_strict_vision_fixture",
    "load_strict_vision_continuation_manifest",
    "load_strict_vision_launch_manifest",
    "validate_strict_vision_grounding",
]
