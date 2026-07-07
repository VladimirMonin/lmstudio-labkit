"""Pure generation contract DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GenerationPurpose(StrEnum):
    FACTUAL_BLOCKS = "factual_blocks"
    PLAIN_TEXT_ARTIFACTS = "plain_text_artifacts"


class ResponseFormatKind(StrEnum):
    JSON_SCHEMA = "json_schema"
    PLAIN_TEXT = "plain_text"


@dataclass(frozen=True, slots=True)
class GenerationProfile:
    profile_id: str
    model_key: str
    purpose: GenerationPurpose
    response_format: ResponseFormatKind
    load_parallel: int | None
    app_concurrency: int | None
    max_tokens: int | None = None
    production_default: bool = False

    @property
    def is_true_parallel_candidate(self) -> bool:
        if self.load_parallel is None or self.app_concurrency is None:
            return False
        return self.load_parallel == self.app_concurrency and self.load_parallel > 1
