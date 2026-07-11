"""Conservative JSON parsing with auditable single-fence normalization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

JsonNormalizationPolicy = Literal["strict", "single_complete_json_fence"]

_SINGLE_FENCE = re.compile(
    r"\A(?P<leading>\s*)```(?P<tag>[A-Za-z]*)[ \t]*\r?\n"
    r"(?P<body>[\s\S]*?)\r?\n```(?P<trailing>\s*)\Z"
)


@dataclass(frozen=True, slots=True)
class JsonParseStage:
    status: Literal["pass", "fail", "not_attempted"]
    error: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class JsonNormalizationResult:
    parsed: Any | None
    raw_text: str
    normalized_text: str | None
    transformation: Literal["none", "single_complete_json_fence", "not_applied"]
    raw_parse: JsonParseStage
    normalized_parse: JsonParseStage
    fence_eligible: bool
    fence_count: int
    semantic_repair: Literal[False] = False

    @property
    def parse_succeeded(self) -> bool:
        return self.parsed is not None

    @property
    def admission_depended_on_normalization(self) -> bool:
        return self.raw_parse.status == "fail" and self.normalized_parse.status == "pass"

    def safe_diagnostics(self) -> dict[str, object]:
        return {
            "raw": {
                "char_count": len(self.raw_text),
                "sha256": _hash_text(self.raw_text),
                "parse": _stage_dict(self.raw_parse),
            },
            "normalized": {
                "present": self.normalized_text is not None,
                "char_count": len(self.normalized_text or ""),
                "sha256": _hash_text(self.normalized_text or ""),
                "parse": _stage_dict(self.normalized_parse),
            },
            "transformation": self.transformation,
            "fence_eligible": self.fence_eligible,
            "fence_count": self.fence_count,
            "semantic_repair": False,
            "admission_depended_on_normalization": self.admission_depended_on_normalization,
        }


def parse_json_response(
    raw_text: str,
    *,
    policy: JsonNormalizationPolicy = "strict",
) -> JsonNormalizationResult:
    """Parse untouched JSON, optionally unwrapping one complete JSON fence.

    The normalization policy never edits the payload body. It rejects prose outside
    the fence, multiple/nested/four-backtick fences, unsupported language tags,
    same-line wrappers, and incomplete closing fences.
    """

    if policy not in {"strict", "single_complete_json_fence"}:
        raise ValueError(f"unsupported JSON normalization policy: {policy}")
    raw_stage, parsed = _parse(raw_text)
    if raw_stage.status == "pass":
        return JsonNormalizationResult(
            parsed=parsed,
            raw_text=raw_text,
            normalized_text=raw_text,
            transformation="none",
            raw_parse=raw_stage,
            normalized_parse=JsonParseStage("not_attempted"),
            fence_eligible=False,
            fence_count=0,
        )

    fence_count = raw_text.count("```")
    match = _SINGLE_FENCE.fullmatch(raw_text) if policy == "single_complete_json_fence" else None
    tag = match.group("tag").casefold() if match is not None else ""
    body = match.group("body") if match is not None else None
    eligible = (
        match is not None and tag in {"", "json"} and fence_count == 2 and "```" not in (body or "")
    )
    if not eligible or body is None:
        return JsonNormalizationResult(
            parsed=None,
            raw_text=raw_text,
            normalized_text=None,
            transformation="not_applied",
            raw_parse=raw_stage,
            normalized_parse=JsonParseStage("not_attempted"),
            fence_eligible=False,
            fence_count=fence_count,
        )

    normalized_stage, normalized_parsed = _parse(body)
    return JsonNormalizationResult(
        parsed=normalized_parsed,
        raw_text=raw_text,
        normalized_text=body,
        transformation="single_complete_json_fence",
        raw_parse=raw_stage,
        normalized_parse=normalized_stage,
        fence_eligible=True,
        fence_count=fence_count,
    )


def _parse(text: str) -> tuple[JsonParseStage, Any | None]:
    try:
        return JsonParseStage("pass"), json.loads(text)
    except json.JSONDecodeError as error:
        return (
            JsonParseStage(
                "fail",
                {
                    "category": "invalid_json",
                    "line": error.lineno,
                    "column": error.colno,
                    "offset": error.pos,
                    "message": error.msg,
                },
            ),
            None,
        )


def _hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _stage_dict(stage: JsonParseStage) -> dict[str, object]:
    error = stage.error
    safe_error = (
        {key: error[key] for key in ("category", "line", "column", "offset") if key in error}
        if error is not None
        else None
    )
    return {"status": stage.status, "error": safe_error}
