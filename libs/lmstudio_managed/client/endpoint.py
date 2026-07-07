"""Safe endpoint identity contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EndpointKind(StrEnum):
    COMPAT_MODELS = "compat_models"
    NATIVE_MODELS = "native_models"
    NATIVE_DOWNLOAD = "native_download"
    NATIVE_DOWNLOAD_PROGRESS = "native_download_progress"
    NATIVE_LOAD = "native_load"
    NATIVE_UNLOAD = "native_unload"
    COMPAT_CHAT = "compat_chat"
    OPENAI_RESPONSES = "openai_responses"


class LMStudioEndpointFamily(StrEnum):
    NATIVE_CHAT = "native_chat"
    OPENAI_RESPONSES = "openai_responses"
    CHAT_COMPLETIONS = "chat_completions"
    MODEL_LIFECYCLE = "model_lifecycle"


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    kind: EndpointKind
    method: HttpMethod
    privacy_label: str
