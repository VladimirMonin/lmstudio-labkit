from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .tokens import (
    DEFAULT_TOKENIZER_SPEC,
    TokenizerSpec,
    calculate_estimate_error_ratio,
    estimate_input_tokens_from_chars,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require_mapping(payload: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{context} must be a mapping")
    return payload


def _require_list(payload: Any, *, context: str) -> list[Any]:
    if not isinstance(payload, list):
        raise ValueError(f"{context} must be a list")
    return payload


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def _require_non_negative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _require_positive_int(value: Any, *, field_name: str) -> int:
    normalized = _require_non_negative_int(value, field_name=field_name)
    if normalized <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return normalized


def _require_optional_non_negative_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_non_negative_int(value, field_name=field_name)


def _require_optional_non_negative_float(
    value: Any,
    *,
    field_name: str,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number")
    normalized = float(value)
    if normalized < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return normalized


def _load_tokenizer_spec(payload: Any) -> TokenizerSpec:
    if payload is None:
        return DEFAULT_TOKENIZER_SPEC
    tokenizer_payload = _require_mapping(payload, context="tokenizer")
    return TokenizerSpec(
        method=_require_non_empty_string(
            tokenizer_payload.get("method"),
            field_name="tokenizer.method",
        ),
        family=_require_non_empty_string(
            tokenizer_payload.get("family"),
            field_name="tokenizer.family",
        ),
        version=_require_non_empty_string(
            tokenizer_payload.get("version"),
            field_name="tokenizer.version",
        ),
    )


def _load_yaml_mapping(path: Path, *, context: str) -> Mapping[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _require_mapping(payload, context=context)


def _load_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_expected_ids(path: Path, *, context: str) -> tuple[int, ...]:
    payload = _require_list(_load_json_payload(path), context=context)
    return tuple(
        _require_non_negative_int(item, field_name=f"{context}[{index}]")
        for index, item in enumerate(payload)
    )


def _load_source_blocks(path: Path, *, context: str) -> dict[int, str]:
    payload = _require_list(_load_json_payload(path), context=context)
    blocks_by_id: dict[int, str] = {}

    for index, item in enumerate(payload):
        block_payload = _require_mapping(item, context=f"{context}[{index}]")
        block_id = _require_non_negative_int(
            block_payload.get("id"),
            field_name=f"{context}[{index}].id",
        )
        block_text = _require_non_empty_string(
            block_payload.get("text"),
            field_name=f"{context}[{index}].text",
        )
        if block_id in blocks_by_id:
            raise ValueError(f"{context} has duplicate block id {block_id}")
        blocks_by_id[block_id] = block_text

    return blocks_by_id


def _validate_manifest_stats(
    manifest: DatasetManifest,
    *,
    expected_ids: tuple[int, ...],
    blocks_by_id: Mapping[int, str],
    context: str,
) -> None:
    actual_items_count = len(expected_ids)
    if manifest.items_count != actual_items_count:
        raise ValueError(
            f"{context} manifest items_count mismatch: manifest={manifest.items_count}, actual={actual_items_count}"
        )

    actual_chars = sum(len(blocks_by_id[block_id]) for block_id in expected_ids)
    if manifest.chars != actual_chars:
        raise ValueError(
            f"{context} manifest chars mismatch: manifest={manifest.chars}, actual={actual_chars}"
        )

    actual_estimated_tokens = estimate_input_tokens_from_chars(actual_chars)
    if manifest.estimated_input_tokens != actual_estimated_tokens:
        raise ValueError(
            f"{context} manifest estimated_input_tokens mismatch: "
            f"manifest={manifest.estimated_input_tokens}, actual={actual_estimated_tokens}"
        )


def default_datasets_root() -> Path:
    return _project_root() / "experiments" / "lmstudio" / "datasets"


@dataclass(slots=True, frozen=True)
class DatasetManifest:
    dataset_id: str
    kind: str
    privacy: str
    items_count: int
    chars: int
    estimated_input_tokens: int
    actual_input_tokens: int | None
    estimate_error_ratio: float | None
    tokenizer: TokenizerSpec
    content_hash: str

    @property
    def estimated_tokens(self) -> int:
        return self.estimated_input_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "kind": self.kind,
            "privacy": self.privacy,
            "items_count": self.items_count,
            "chars": self.chars,
            "estimated_input_tokens": self.estimated_input_tokens,
            "actual_input_tokens": self.actual_input_tokens,
            "estimate_error_ratio": self.estimate_error_ratio,
            "tokenizer": {
                "method": self.tokenizer.method,
                "family": self.tokenizer.family,
                "version": self.tokenizer.version,
            },
            "content_hash": self.content_hash,
        }


@dataclass(slots=True, frozen=True)
class DatasetChunk:
    chunk_id: int
    expected_ids: tuple[int, ...]
    items_count: int
    chars: int
    estimated_input_tokens: int


@dataclass(slots=True, frozen=True)
class ChunkedDatasetView:
    dataset_id: str
    source_dataset_id: str
    chunk_size_blocks: int
    chunks_count: int
    expected_ids: tuple[int, ...]
    chunks: tuple[DatasetChunk, ...]


def load_dataset_manifest(
    dataset_id: str,
    *,
    datasets_root: str | Path | None = None,
) -> DatasetManifest:
    requested_id = _require_non_empty_string(dataset_id, field_name="dataset_id")
    root = Path(datasets_root) if datasets_root is not None else default_datasets_root()
    manifest_path = root / requested_id / "manifest.yaml"
    raw_payload = _load_yaml_mapping(manifest_path, context="dataset manifest")

    manifest_dataset_id = _require_non_empty_string(
        raw_payload.get("dataset_id"),
        field_name="dataset_id",
    )
    if manifest_dataset_id != requested_id:
        raise ValueError(
            f"dataset manifest id mismatch: expected {requested_id!r}, got {manifest_dataset_id!r}"
        )

    chars = _require_non_negative_int(raw_payload.get("chars"), field_name="chars")
    estimated_input_tokens = _require_optional_non_negative_int(
        raw_payload.get("estimated_input_tokens"),
        field_name="estimated_input_tokens",
    )
    if estimated_input_tokens is None:
        estimated_input_tokens = estimate_input_tokens_from_chars(chars)

    actual_input_tokens = _require_optional_non_negative_int(
        raw_payload.get("actual_input_tokens"),
        field_name="actual_input_tokens",
    )
    estimate_error_ratio = _require_optional_non_negative_float(
        raw_payload.get("estimate_error_ratio"),
        field_name="estimate_error_ratio",
    )
    if actual_input_tokens is None and estimate_error_ratio is not None:
        raise ValueError("estimate_error_ratio requires actual_input_tokens")
    if estimate_error_ratio is not None:
        calculate_estimate_error_ratio(estimated_input_tokens, actual_input_tokens)

    return DatasetManifest(
        dataset_id=manifest_dataset_id,
        kind=_require_non_empty_string(raw_payload.get("kind"), field_name="kind"),
        privacy=_require_non_empty_string(
            raw_payload.get("privacy"),
            field_name="privacy",
        ),
        items_count=_require_non_negative_int(
            raw_payload.get("items_count"),
            field_name="items_count",
        ),
        chars=chars,
        estimated_input_tokens=estimated_input_tokens,
        actual_input_tokens=actual_input_tokens,
        estimate_error_ratio=estimate_error_ratio,
        tokenizer=_load_tokenizer_spec(raw_payload.get("tokenizer")),
        content_hash=_require_non_empty_string(
            raw_payload.get("content_hash"),
            field_name="content_hash",
        ),
    )


def load_chunked_dataset_view(
    dataset_id: str,
    *,
    datasets_root: str | Path | None = None,
) -> ChunkedDatasetView:
    requested_id = _require_non_empty_string(dataset_id, field_name="dataset_id")
    root = Path(datasets_root) if datasets_root is not None else default_datasets_root()
    dataset_dir = root / requested_id

    manifest = load_dataset_manifest(requested_id, datasets_root=root)
    if manifest.kind != "blocks_json_chunked":
        raise ValueError("dataset kind must be 'blocks_json_chunked'")
    if manifest.privacy != "synthetic":
        raise ValueError("dataset privacy must be 'synthetic'")

    raw_manifest = _load_yaml_mapping(dataset_dir / "manifest.yaml", context="dataset manifest")
    source_dataset_id = _require_non_empty_string(
        raw_manifest.get("source_dataset_id"),
        field_name="source_dataset_id",
    )
    chunk_size_blocks = _require_positive_int(
        raw_manifest.get("chunk_size_blocks"),
        field_name="chunk_size_blocks",
    )
    chunks_count = _require_positive_int(
        raw_manifest.get("chunks_count"),
        field_name="chunks_count",
    )

    source_manifest = load_dataset_manifest(source_dataset_id, datasets_root=root)
    if source_manifest.privacy != "synthetic":
        raise ValueError("source dataset privacy must be 'synthetic'")

    source_dir = root / source_dataset_id
    source_expected_ids = _load_expected_ids(
        source_dir / "expected_ids.json",
        context=f"{source_dataset_id} expected_ids",
    )
    source_blocks_by_id = _load_source_blocks(
        source_dir / "input_blocks.json",
        context=f"{source_dataset_id} input_blocks",
    )
    if tuple(source_blocks_by_id) != source_expected_ids:
        raise ValueError("source dataset input_blocks ids must match expected_ids")
    _validate_manifest_stats(
        source_manifest,
        expected_ids=source_expected_ids,
        blocks_by_id=source_blocks_by_id,
        context=source_dataset_id,
    )

    view_expected_ids = _load_expected_ids(
        dataset_dir / "expected_ids.json",
        context=f"{requested_id} expected_ids",
    )
    if len(view_expected_ids) != manifest.items_count:
        raise ValueError(f"{requested_id} expected_ids length must match manifest items_count")
    if view_expected_ids != source_expected_ids:
        raise ValueError(f"{requested_id} expected_ids must match source dataset")

    if manifest.items_count != source_manifest.items_count:
        raise ValueError(f"{requested_id} manifest items_count must match source dataset")
    if manifest.chars != source_manifest.chars:
        raise ValueError(f"{requested_id} manifest chars must match source dataset")
    if manifest.estimated_input_tokens != source_manifest.estimated_input_tokens:
        raise ValueError(
            f"{requested_id} manifest estimated_input_tokens must match source dataset"
        )
    if chunk_size_blocks * chunks_count != manifest.items_count:
        raise ValueError(
            f"{requested_id} manifest items_count must equal chunk_size_blocks * chunks_count"
        )

    chunks_payload = _require_list(
        _load_json_payload(dataset_dir / "input_chunks.json"),
        context=f"{requested_id} input_chunks",
    )
    if len(chunks_payload) != chunks_count:
        raise ValueError(f"{requested_id} input_chunks length must match chunks_count")

    seen_ids: set[int] = set()
    flattened_ids: list[int] = []
    chunks: list[DatasetChunk] = []

    for index, item in enumerate(chunks_payload):
        chunk_payload = _require_mapping(item, context=f"{requested_id} input_chunks[{index}]")
        chunk_id = _require_non_negative_int(
            chunk_payload.get("chunk_id"),
            field_name=f"{requested_id} input_chunks[{index}].chunk_id",
        )
        if chunk_id != index:
            raise ValueError(f"{requested_id} chunk ids must be sequential starting at 0")

        raw_chunk_expected_ids = _require_list(
            chunk_payload.get("expected_ids"),
            context=f"{requested_id} input_chunks[{index}].expected_ids",
        )
        chunk_expected_ids = tuple(
            _require_non_negative_int(
                block_id,
                field_name=f"{requested_id} input_chunks[{index}].expected_ids[{position}]",
            )
            for position, block_id in enumerate(raw_chunk_expected_ids)
        )
        if len(chunk_expected_ids) != chunk_size_blocks:
            raise ValueError(
                f"{requested_id} chunk {chunk_id} size mismatch: "
                f"expected {chunk_size_blocks}, got {len(chunk_expected_ids)}"
            )

        unknown_ids = [
            block_id for block_id in chunk_expected_ids if block_id not in source_blocks_by_id
        ]
        if unknown_ids:
            raise ValueError(
                f"{requested_id} chunk {chunk_id} references unknown ids: {unknown_ids}"
            )

        overlapping_ids: list[int] = []
        for block_id in chunk_expected_ids:
            if block_id in seen_ids:
                overlapping_ids.append(block_id)
                continue
            seen_ids.add(block_id)

        if overlapping_ids:
            raise ValueError(f"{requested_id} chunks overlap on ids: {overlapping_ids}")

        chunk_chars = sum(len(source_blocks_by_id[block_id]) for block_id in chunk_expected_ids)
        flattened_ids.extend(chunk_expected_ids)
        chunks.append(
            DatasetChunk(
                chunk_id=chunk_id,
                expected_ids=chunk_expected_ids,
                items_count=len(chunk_expected_ids),
                chars=chunk_chars,
                estimated_input_tokens=estimate_input_tokens_from_chars(chunk_chars),
            )
        )

    if tuple(flattened_ids) != view_expected_ids:
        missing_ids = [block_id for block_id in view_expected_ids if block_id not in seen_ids]
        unexpected_ids = [
            block_id for block_id in flattened_ids if block_id not in view_expected_ids
        ]
        if missing_ids or unexpected_ids:
            raise ValueError(
                f"{requested_id} chunk coverage mismatch: "
                f"missing ids {missing_ids}, unexpected ids {unexpected_ids}"
            )
        raise ValueError(f"{requested_id} chunk coverage order mismatch")

    derived_chars = sum(chunk.chars for chunk in chunks)
    if derived_chars != manifest.chars:
        raise ValueError(
            f"{requested_id} chunk chars mismatch: manifest={manifest.chars}, actual={derived_chars}"
        )

    derived_estimated_tokens = sum(chunk.estimated_input_tokens for chunk in chunks)
    if derived_estimated_tokens != manifest.estimated_input_tokens:
        raise ValueError(
            f"{requested_id} chunk estimated_input_tokens mismatch: "
            f"manifest={manifest.estimated_input_tokens}, actual={derived_estimated_tokens}"
        )

    return ChunkedDatasetView(
        dataset_id=manifest.dataset_id,
        source_dataset_id=source_dataset_id,
        chunk_size_blocks=chunk_size_blocks,
        chunks_count=chunks_count,
        expected_ids=view_expected_ids,
        chunks=tuple(chunks),
    )


__all__ = [
    "ChunkedDatasetView",
    "DatasetChunk",
    "DatasetManifest",
    "default_datasets_root",
    "load_chunked_dataset_view",
    "load_dataset_manifest",
]
