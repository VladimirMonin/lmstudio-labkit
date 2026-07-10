from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal

Modality = Literal["text", "image"]
ResponseMode = Literal["json", "text"]
EndpointFamily = Literal["openai_compat", "native"]
LanguagePolicy = Literal[
    "strict_ru",
    "strict_en",
    "mixed_ru_en",
    "allow_code_terms",
    "preserve_input_language",
    "preserve_mixed_language",
    "translate_to_ru",
    "translate_to_en",
    "labels_only",
    "skip",
]
LengthRatioPolicy = Literal["off", "warning", "hard"]
ValidationPolicyMode = Literal["off", "warning", "hard", "diagnostic"]


def stable_hash(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class TextInput:
    """In-memory text input. Safe metadata stores only hashes and counts."""

    text: str
    label: str = "prompt"

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "kind": "text",
            "label": self.label,
            "text_hash": stable_hash(self.text),
            "char_count": len(self.text),
        }


@dataclass(frozen=True, slots=True)
class ImageInput:
    """Image input reference. Keep public artifacts path-free by default."""

    content_hash: str
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    label: str = "image"

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "kind": "image",
            "label": self.label,
            "content_hash": self.content_hash,
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content_hash": stable_hash(self.content),
            "char_count": len(self.content),
        }


@dataclass(frozen=True, slots=True)
class ResponseContract:
    mode: ResponseMode = "json"
    schema: dict[str, Any] | None = None
    expected_ids: tuple[Any, ...] = ()
    id_paths: tuple[str, ...] = ()
    id_field_names: tuple[str, ...] = ("id",)
    preserve_order: bool = True
    language: str | None = None
    language_policy: LanguagePolicy | str | None = None
    min_length_ratio: float | None = None
    max_length_ratio: float | None = None
    length_ratio_policy: LengthRatioPolicy | str | dict[str, Any] = "hard"
    expected_output: Any | None = None
    image_ground_truth: dict[str, Any] | None = None
    source_text: str | None = None
    language_include_paths: tuple[str, ...] = ()
    language_ignore_paths: tuple[str, ...] = ()
    task_intent: str | None = None
    validation_policy: str | None = None
    expected_terms: tuple[dict[str, Any], ...] = ()
    punctuation_policy: str | None = "diagnostic"
    paragraphing_policy: str | None = None
    paragraph_count_min: int | None = None
    paragraph_count_max: int | None = None
    filler_terms: tuple[str, ...] = ()
    filler_cleanup_policy: str | None = None
    term_normalization_policy: str | None = None
    near_identity_policy: str | None = None
    language_drift_policy: str | None = None
    term_language_preservation_policy: str | None = None
    manual_review_policy: str | None = None
    schema_family: str | None = None
    response_schema_complexity: str | None = None

    def safe_metadata(self) -> dict[str, Any]:
        schema_hash = stable_hash(_stable_repr(self.schema)) if self.schema is not None else None
        expected_hash = (
            stable_hash(_stable_repr(self.expected_output))
            if self.expected_output is not None
            else None
        )
        return {
            "mode": self.mode,
            "schema_hash": schema_hash,
            "expected_ids": list(self.expected_ids),
            "id_paths": list(self.id_paths),
            "id_field_names": list(self.id_field_names),
            "preserve_order": self.preserve_order,
            "language": self.language,
            "language_policy": self.language_policy,
            "min_length_ratio": self.min_length_ratio,
            "max_length_ratio": self.max_length_ratio,
            "length_ratio_policy": self.length_ratio_policy,
            "expected_output_hash": expected_hash,
            "image_ground_truth_hash": stable_hash(_stable_repr(self.image_ground_truth))
            if self.image_ground_truth is not None
            else None,
            "source_text_hash": stable_hash(self.source_text)
            if self.source_text is not None
            else None,
            "source_text_char_count": len(self.source_text)
            if self.source_text is not None
            else None,
            "language_include_paths": list(self.language_include_paths),
            "language_ignore_paths": list(self.language_ignore_paths),
            "task_intent": self.task_intent,
            "validation_policy": self.validation_policy,
            "expected_terms_hash": stable_hash(_stable_repr(self.expected_terms))
            if self.expected_terms
            else None,
            "expected_terms_count": len(self.expected_terms),
            "punctuation_policy": self.punctuation_policy,
            "paragraphing_policy": self.paragraphing_policy,
            "paragraph_count_min": self.paragraph_count_min,
            "paragraph_count_max": self.paragraph_count_max,
            "filler_terms_hash": stable_hash(_stable_repr(self.filler_terms))
            if self.filler_terms
            else None,
            "filler_terms_count": len(self.filler_terms),
            "filler_cleanup_policy": self.filler_cleanup_policy,
            "term_normalization_policy": self.term_normalization_policy,
            "near_identity_policy": self.near_identity_policy,
            "language_drift_policy": self.language_drift_policy,
            "term_language_preservation_policy": self.term_language_preservation_policy,
            "manual_review_policy": self.manual_review_policy,
            "schema_family": self.schema_family,
            "response_schema_complexity": self.response_schema_complexity,
        }


@dataclass(frozen=True, slots=True)
class ExecutionOptions:
    model_id: str
    endpoint_family: str = "openai_compat"
    context_tier: str = "8192"
    max_tokens: int | None = None
    temperature: float = 0.0
    timeout_s: float = 30.0
    retry_policy: Literal["off", "retry1"] = "off"
    live: bool = False

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "endpoint_family": self.endpoint_family,
            "context_tier": self.context_tier,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout_s": self.timeout_s,
            "retry_policy": self.retry_policy,
            "live": self.live,
        }


@dataclass(frozen=True, slots=True)
class RequestEnvelope:
    request_id: str
    modality: Modality
    text_inputs: tuple[TextInput, ...] = ()
    image_inputs: tuple[ImageInput, ...] = ()
    chat_messages: tuple[ChatMessage, ...] = ()
    response_contract: ResponseContract = field(default_factory=ResponseContract)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.modality == "text" and self.image_inputs:
            raise ValueError("text modality cannot include image_inputs")
        if self.modality == "image" and not self.image_inputs:
            raise ValueError("image modality requires at least one image input")
        if not self.text_inputs and not self.image_inputs and not self.chat_messages:
            raise ValueError("request envelope requires text, image, or chat input")

    @classmethod
    def text(cls, request_id: str, prompt: str, **metadata: Any) -> RequestEnvelope:
        return cls(
            request_id=request_id,
            modality="text",
            text_inputs=(TextInput(prompt),),
            metadata=metadata,
        )

    @classmethod
    def chat(
        cls,
        request_id: str,
        messages: tuple[ChatMessage, ...],
        **metadata: Any,
    ) -> RequestEnvelope:
        return cls(
            request_id=request_id,
            modality="text",
            chat_messages=messages,
            metadata=metadata,
        )

    @classmethod
    def image(
        cls,
        request_id: str,
        image: ImageInput,
        *,
        prompt: str | None = None,
        **metadata: Any,
    ) -> RequestEnvelope:
        return cls(
            request_id=request_id,
            modality="image",
            text_inputs=(TextInput(prompt),) if prompt is not None else (),
            image_inputs=(image,),
            metadata=metadata,
        )

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "modality": self.modality,
            "text_inputs": [item.safe_metadata() for item in self.text_inputs],
            "image_inputs": [item.safe_metadata() for item in self.image_inputs],
            "chat_messages": [item.safe_metadata() for item in self.chat_messages],
            "response_contract": self.response_contract.safe_metadata(),
            "metadata": _safe_metadata_items(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RequestPlan:
    cell_id: str
    envelope: RequestEnvelope
    options: ExecutionOptions

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "request": self.envelope.safe_metadata(),
            "options": self.options.safe_metadata(),
        }


@dataclass(frozen=True, slots=True)
class RequestResult:
    request_id: str
    model_id: str
    raw_response_hash: str
    raw_response_char_count: int
    status: Literal["ok", "error"]
    latency_ms: float
    token_counts: dict[str, int] = field(default_factory=dict)
    error_category: str | None = None
    finish_reason: str | None = None
    lifecycle_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw_response(
        cls,
        *,
        request_id: str,
        model_id: str,
        raw_response: str,
        status: Literal["ok", "error"] = "ok",
        latency_ms: float = 0.0,
        token_counts: dict[str, int] | None = None,
        error_category: str | None = None,
        finish_reason: str | None = None,
        lifecycle_metadata: dict[str, Any] | None = None,
    ) -> RequestResult:
        return cls(
            request_id=request_id,
            model_id=model_id,
            raw_response_hash=stable_hash(raw_response),
            raw_response_char_count=len(raw_response),
            status=status,
            latency_ms=latency_ms,
            token_counts=token_counts or {},
            error_category=error_category,
            finish_reason=finish_reason,
            lifecycle_metadata=lifecycle_metadata or {},
        )

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model_id": self.model_id,
            "response_hash": self.raw_response_hash,
            "response_char_count": self.raw_response_char_count,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "token_counts": dict(self.token_counts),
            "error_category": self.error_category,
            "finish_reason": self.finish_reason,
            "lifecycle_metadata": dict(self.lifecycle_metadata),
        }


def _stable_repr(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_metadata_items(metadata: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _safe_metadata_value(value) for key, value in sorted(metadata.items())}


def _safe_metadata_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return {"value_hash": stable_hash(value), "char_count": len(value)}
    if isinstance(value, bytes):
        return {"value_hash": stable_hash(value), "byte_count": len(value)}
    if isinstance(value, tuple | list):
        return [_safe_metadata_value(item) for item in value]
    if isinstance(value, dict):
        return _safe_metadata_items(value)
    text = str(value)
    return {"value_hash": stable_hash(text), "char_count": len(text)}


__all__ = [
    "ChatMessage",
    "EndpointFamily",
    "ExecutionOptions",
    "ImageInput",
    "LanguagePolicy",
    "Modality",
    "RequestEnvelope",
    "RequestPlan",
    "RequestResult",
    "ResponseContract",
    "ResponseMode",
    "TextInput",
    "stable_hash",
]
