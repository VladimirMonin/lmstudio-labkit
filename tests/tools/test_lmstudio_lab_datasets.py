from __future__ import annotations

import json
import re

import pytest
import yaml

from tools import lmstudio_lab

DATASETS_ROOT = lmstudio_lab.default_datasets_root()
MEDIUM_DATASET_DIR = DATASETS_ROOT / "blocks_json_medium"
MEDIUM_MANIFEST_PATH = MEDIUM_DATASET_DIR / "manifest.yaml"
MEDIUM_INPUT_BLOCKS_PATH = MEDIUM_DATASET_DIR / "input_blocks.json"
MEDIUM_EXPECTED_IDS_PATH = MEDIUM_DATASET_DIR / "expected_ids.json"
MEDIUM_CHUNKED_DATASET_DIR = DATASETS_ROOT / "blocks_json_medium_chunked"
MEDIUM_CHUNKED_MANIFEST_PATH = MEDIUM_CHUNKED_DATASET_DIR / "manifest.yaml"
MEDIUM_CHUNKED_INPUT_CHUNKS_PATH = MEDIUM_CHUNKED_DATASET_DIR / "input_chunks.json"
MEDIUM_CHUNKED_EXPECTED_IDS_PATH = MEDIUM_CHUNKED_DATASET_DIR / "expected_ids.json"
MEDIUM_CHUNKED_10_DATASET_DIR = DATASETS_ROOT / "blocks_json_medium_chunked_10"
MEDIUM_CHUNKED_10_MANIFEST_PATH = MEDIUM_CHUNKED_10_DATASET_DIR / "manifest.yaml"
MEDIUM_CHUNKED_10_INPUT_CHUNKS_PATH = MEDIUM_CHUNKED_10_DATASET_DIR / "input_chunks.json"
MEDIUM_CHUNKED_10_EXPECTED_IDS_PATH = MEDIUM_CHUNKED_10_DATASET_DIR / "expected_ids.json"
MEDIUM_CHUNKED_5_DATASET_DIR = DATASETS_ROOT / "blocks_json_medium_chunked_5"
MEDIUM_CHUNKED_5_MANIFEST_PATH = MEDIUM_CHUNKED_5_DATASET_DIR / "manifest.yaml"
MEDIUM_CHUNKED_5_INPUT_CHUNKS_PATH = MEDIUM_CHUNKED_5_DATASET_DIR / "input_chunks.json"
MEDIUM_CHUNKED_5_EXPECTED_IDS_PATH = MEDIUM_CHUNKED_5_DATASET_DIR / "expected_ids.json"


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_manifest(path, payload) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _build_source_blocks(count: int) -> list[dict[str, int | str]]:
    return [
        {
            "id": block_id,
            "text": f"Synthetic block {block_id:02d} keeps offline chunk tests safe.",
        }
        for block_id in range(count)
    ]


def _write_chunked_fixture(
    root,
    *,
    source_dataset_id: str = "source_small",
    view_dataset_id: str = "source_small_chunked",
    source_blocks: list[dict[str, int | str]] | None = None,
    source_expected_ids: list[int] | None = None,
    view_expected_ids: list[int] | None = None,
    chunks_payload: list[dict[str, object]] | None = None,
    chunk_size_blocks: int = 2,
    chunks_count: int = 2,
) -> None:
    source_blocks = source_blocks or _build_source_blocks(chunk_size_blocks * chunks_count)
    source_expected_ids = source_expected_ids or [block["id"] for block in source_blocks]
    view_expected_ids = view_expected_ids or list(source_expected_ids)
    if chunks_payload is None:
        chunks_payload = [
            {
                "chunk_id": chunk_id,
                "expected_ids": view_expected_ids[
                    chunk_id * chunk_size_blocks : (chunk_id + 1) * chunk_size_blocks
                ],
            }
            for chunk_id in range(chunks_count)
        ]

    source_dir = root / source_dataset_id
    source_dir.mkdir(parents=True)
    source_chars = sum(len(block["text"]) for block in source_blocks)
    source_estimated_tokens = lmstudio_lab.estimate_input_tokens_from_chars(source_chars)

    _write_manifest(
        source_dir / "manifest.yaml",
        {
            "dataset_id": source_dataset_id,
            "kind": "blocks_json",
            "privacy": "synthetic",
            "items_count": len(source_expected_ids),
            "chars": source_chars,
            "estimated_input_tokens": source_estimated_tokens,
            "actual_input_tokens": None,
            "estimate_error_ratio": None,
            "tokenizer": {
                "method": "heuristic",
                "family": "generic",
                "version": "1.0",
            },
            "content_hash": f"sha256:{source_dataset_id}",
        },
    )
    _write_json(source_dir / "input_blocks.json", source_blocks)
    _write_json(source_dir / "expected_ids.json", source_expected_ids)

    view_dir = root / view_dataset_id
    view_dir.mkdir(parents=True)
    view_expected_id_set = set(view_expected_ids)
    view_chars = sum(
        len(block["text"]) for block in source_blocks if block["id"] in view_expected_id_set
    )
    view_estimated_tokens = lmstudio_lab.estimate_input_tokens_from_chars(view_chars)
    _write_manifest(
        view_dir / "manifest.yaml",
        {
            "dataset_id": view_dataset_id,
            "kind": "blocks_json_chunked",
            "privacy": "synthetic",
            "source_dataset_id": source_dataset_id,
            "chunk_size_blocks": chunk_size_blocks,
            "chunks_count": chunks_count,
            "items_count": len(view_expected_ids),
            "chars": view_chars,
            "estimated_input_tokens": view_estimated_tokens,
            "actual_input_tokens": None,
            "estimate_error_ratio": None,
            "tokenizer": {
                "method": "heuristic",
                "family": "generic",
                "version": "1.0",
            },
            "content_hash": f"sha256:{view_dataset_id}",
        },
    )
    _write_json(view_dir / "expected_ids.json", view_expected_ids)
    _write_json(view_dir / "input_chunks.json", chunks_payload)


def test_load_dataset_manifest_reads_synthetic_manifest() -> None:
    manifest = lmstudio_lab.load_dataset_manifest("blocks_json_small")

    assert manifest.dataset_id == "blocks_json_small"
    assert manifest.kind == "blocks_json"
    assert manifest.privacy == "synthetic"
    assert manifest.items_count == 20
    assert manifest.chars == 3600
    assert manifest.estimated_input_tokens == 1200
    assert manifest.estimated_tokens == 1200
    assert manifest.actual_input_tokens is None
    assert manifest.estimate_error_ratio is None
    assert manifest.tokenizer == lmstudio_lab.DEFAULT_TOKENIZER_SPEC
    assert manifest.content_hash.startswith("sha256:")
    assert manifest.to_dict() == {
        "dataset_id": "blocks_json_small",
        "kind": "blocks_json",
        "privacy": "synthetic",
        "items_count": 20,
        "chars": 3600,
        "estimated_input_tokens": 1200,
        "actual_input_tokens": None,
        "estimate_error_ratio": None,
        "tokenizer": {
            "method": "heuristic",
            "family": "generic",
            "version": "1.0",
        },
        "content_hash": "sha256:blocks-json-small-v1",
    }


def test_load_dataset_manifest_rejects_dataset_id_mismatch(tmp_path) -> None:
    dataset_dir = tmp_path / "dataset-one"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "dataset_id": "other-dataset",
                "kind": "blocks_json",
                "privacy": "synthetic",
                "items_count": 1,
                "chars": 30,
                "estimated_input_tokens": 10,
                "actual_input_tokens": None,
                "estimate_error_ratio": None,
                "tokenizer": {
                    "method": "heuristic",
                    "family": "generic",
                    "version": "1.0",
                },
                "content_hash": "sha256:placeholder",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="dataset manifest id mismatch"):
        lmstudio_lab.load_dataset_manifest("dataset-one", datasets_root=tmp_path)


def test_load_dataset_manifest_estimates_tokens_when_field_missing(tmp_path) -> None:
    dataset_dir = tmp_path / "dataset-two"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "dataset_id": "dataset-two",
                "kind": "blocks_json",
                "privacy": "synthetic",
                "items_count": 2,
                "chars": 7,
                "actual_input_tokens": None,
                "estimate_error_ratio": None,
                "content_hash": "sha256:placeholder-two",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    manifest = lmstudio_lab.load_dataset_manifest("dataset-two", datasets_root=tmp_path)

    assert manifest.estimated_input_tokens == 3
    assert manifest.tokenizer == lmstudio_lab.DEFAULT_TOKENIZER_SPEC


def test_load_dataset_manifest_rejects_estimate_error_without_actual_tokens(tmp_path) -> None:
    dataset_dir = tmp_path / "dataset-three"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "dataset_id": "dataset-three",
                "kind": "blocks_json",
                "privacy": "synthetic",
                "items_count": 1,
                "chars": 10,
                "estimated_input_tokens": 4,
                "actual_input_tokens": None,
                "estimate_error_ratio": 0.2,
                "content_hash": "sha256:placeholder-three",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="estimate_error_ratio requires actual_input_tokens"):
        lmstudio_lab.load_dataset_manifest("dataset-three", datasets_root=tmp_path)


def test_load_dataset_manifest_reads_medium_manifest() -> None:
    manifest = lmstudio_lab.load_dataset_manifest("blocks_json_medium")
    blocks = _load_json(MEDIUM_INPUT_BLOCKS_PATH)
    chars = sum(len(block["text"]) for block in blocks)

    assert manifest.dataset_id == "blocks_json_medium"
    assert manifest.kind == "blocks_json"
    assert manifest.privacy == "synthetic"
    assert manifest.items_count == 100
    assert manifest.chars == chars == 20100
    assert manifest.estimated_input_tokens == 6700
    assert manifest.estimated_tokens == 6700
    assert manifest.actual_input_tokens is None
    assert manifest.estimate_error_ratio is None
    assert manifest.tokenizer == lmstudio_lab.DEFAULT_TOKENIZER_SPEC
    assert manifest.content_hash == "sha256:blocks-json-medium-v1"
    assert manifest.estimated_input_tokens > 0


def test_load_dataset_manifest_reads_medium_chunked_manifest() -> None:
    manifest = lmstudio_lab.load_dataset_manifest("blocks_json_medium_chunked")

    assert manifest.dataset_id == "blocks_json_medium_chunked"
    assert manifest.kind == "blocks_json_chunked"
    assert manifest.privacy == "synthetic"
    assert manifest.items_count == 100
    assert manifest.chars == 20100
    assert manifest.estimated_input_tokens == 6700
    assert manifest.actual_input_tokens is None
    assert manifest.estimate_error_ratio is None
    assert manifest.tokenizer == lmstudio_lab.DEFAULT_TOKENIZER_SPEC
    assert manifest.content_hash == "sha256:blocks-json-medium-chunked-v1"


def test_blocks_json_medium_input_has_100_unique_ordered_synthetic_blocks() -> None:
    blocks = _load_json(MEDIUM_INPUT_BLOCKS_PATH)

    assert len(blocks) == 100

    ids = [block["id"] for block in blocks]
    texts = [block["text"] for block in blocks]

    assert ids == list(range(100))
    assert len(set(ids)) == 100
    assert all(isinstance(text, str) and text.strip() for text in texts)


def test_blocks_json_medium_expected_ids_match_input_blocks() -> None:
    expected_ids = _load_json(MEDIUM_EXPECTED_IDS_PATH)
    blocks = _load_json(MEDIUM_INPUT_BLOCKS_PATH)

    assert expected_ids == list(range(100))
    assert expected_ids == [block["id"] for block in blocks]


def test_load_chunked_dataset_view_reads_four_ordered_chunks() -> None:
    view = lmstudio_lab.load_chunked_dataset_view("blocks_json_medium_chunked")

    assert view.dataset_id == "blocks_json_medium_chunked"
    assert view.source_dataset_id == "blocks_json_medium"
    assert view.chunk_size_blocks == 25
    assert view.chunks_count == 4
    assert list(view.expected_ids) == list(range(100))
    assert [chunk.chunk_id for chunk in view.chunks] == [0, 1, 2, 3]
    assert [list(chunk.expected_ids) for chunk in view.chunks] == [
        list(range(0, 25)),
        list(range(25, 50)),
        list(range(50, 75)),
        list(range(75, 100)),
    ]
    assert all(chunk.items_count == 25 for chunk in view.chunks)
    assert all(chunk.chars == 5025 for chunk in view.chunks)
    assert all(chunk.estimated_input_tokens == 1675 for chunk in view.chunks)


def test_blocks_json_medium_chunked_flattened_ids_cover_full_range_once() -> None:
    view = lmstudio_lab.load_chunked_dataset_view("blocks_json_medium_chunked")

    flattened_ids = [block_id for chunk in view.chunks for block_id in chunk.expected_ids]

    assert flattened_ids == list(range(100))
    assert len(flattened_ids) == 100
    assert len(set(flattened_ids)) == 100


def test_blocks_json_medium_chunked_context_fit_passes_per_chunk() -> None:
    view = lmstudio_lab.load_chunked_dataset_view("blocks_json_medium_chunked")

    fits = [
        lmstudio_lab.evaluate_context_fit(
            estimated_input_tokens=chunk.estimated_input_tokens,
            max_tokens=min(
                8192,
                max(512, chunk.estimated_input_tokens + chunk.items_count * 8),
            ),
            effective_context_length=8192,
            safety_ratio=0.85,
        )
        for chunk in view.chunks
    ]

    assert all(result.fits for result in fits)
    assert all(result.budget_tokens == 6963 for result in fits)
    assert all(result.required_tokens == 3550 for result in fits)


def test_l3_9_blocks_json_medium_chunked_dataset_contract_is_canonical() -> None:
    manifest = lmstudio_lab.load_dataset_manifest("blocks_json_medium_chunked")
    view = lmstudio_lab.load_chunked_dataset_view("blocks_json_medium_chunked")

    assert manifest.privacy == "synthetic"
    assert manifest.items_count == 100
    assert view.dataset_id == "blocks_json_medium_chunked"
    assert view.chunk_size_blocks == 25
    assert view.chunks_count == 4
    assert len(view.expected_ids) == 100
    assert list(view.expected_ids) == list(range(100))
    assert len(view.chunks) == 4
    assert all(chunk.items_count == 25 for chunk in view.chunks)
    assert [chunk.chunk_id for chunk in view.chunks] == [0, 1, 2, 3]


@pytest.mark.parametrize(
    ("dataset_id", "expected_hash"),
    [
        ("blocks_json_medium_chunked_10", "sha256:blocks-json-medium-chunked-10-v1"),
        ("blocks_json_medium_chunked_5", "sha256:blocks-json-medium-chunked-5-v1"),
    ],
)
def test_load_dataset_manifest_reads_l3_10e_medium_chunked_variants(
    dataset_id: str,
    expected_hash: str,
) -> None:
    manifest = lmstudio_lab.load_dataset_manifest(dataset_id)

    assert manifest.dataset_id == dataset_id
    assert manifest.kind == "blocks_json_chunked"
    assert manifest.privacy == "synthetic"
    assert manifest.items_count == 100
    assert manifest.chars == 20100
    assert manifest.estimated_input_tokens == 6700
    assert manifest.actual_input_tokens is None
    assert manifest.estimate_error_ratio is None
    assert manifest.tokenizer == lmstudio_lab.DEFAULT_TOKENIZER_SPEC
    assert manifest.content_hash == expected_hash


@pytest.mark.parametrize(
    ("dataset_id", "chunk_size_blocks", "chunks_count"),
    [
        ("blocks_json_medium_chunked_10", 10, 10),
        ("blocks_json_medium_chunked_5", 5, 20),
    ],
)
def test_load_chunked_dataset_view_reads_l3_10e_medium_chunked_variants(
    dataset_id: str,
    chunk_size_blocks: int,
    chunks_count: int,
) -> None:
    view = lmstudio_lab.load_chunked_dataset_view(dataset_id)

    flattened_ids = [block_id for chunk in view.chunks for block_id in chunk.expected_ids]

    assert view.dataset_id == dataset_id
    assert view.source_dataset_id == "blocks_json_medium"
    assert view.chunk_size_blocks == chunk_size_blocks
    assert view.chunks_count == chunks_count
    assert list(view.expected_ids) == list(range(100))
    assert [chunk.chunk_id for chunk in view.chunks] == list(range(chunks_count))
    assert flattened_ids == list(range(100))
    assert len(set(flattened_ids)) == 100
    assert sum(chunk.items_count for chunk in view.chunks) == 100
    assert sum(chunk.estimated_input_tokens for chunk in view.chunks) == 6700
    assert all(chunk.items_count == chunk_size_blocks for chunk in view.chunks)


def test_blocks_json_medium_has_no_paths_urls_or_private_markers() -> None:
    combined_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            MEDIUM_MANIFEST_PATH,
            MEDIUM_INPUT_BLOCKS_PATH,
            MEDIUM_EXPECTED_IDS_PATH,
        )
    )
    forbidden_patterns = [
        r"http://",
        r"https://",
        r"[A-Za-z]:\\",
        r"\\\\[^\s\\/]+\\",
        r"/Users/",
        r"/home/",
        r"password",
        r"secret",
        r"api[_-]?key",
        r"bearer\s+",
        r"@[A-Za-z0-9_.-]+",
    ]

    for pattern in forbidden_patterns:
        assert re.search(pattern, combined_text, flags=re.IGNORECASE) is None


def test_blocks_json_medium_chunked_has_no_paths_urls_or_private_markers() -> None:
    combined_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            MEDIUM_CHUNKED_MANIFEST_PATH,
            MEDIUM_CHUNKED_INPUT_CHUNKS_PATH,
            MEDIUM_CHUNKED_EXPECTED_IDS_PATH,
        )
    )
    forbidden_patterns = [
        r"http://",
        r"https://",
        r"[A-Za-z]:\\",
        r"\\\\[^\s\\/]+\\",
        r"/Users/",
        r"/home/",
        r"password",
        r"secret",
        r"api[_-]?key",
        r"bearer\s+",
        r"@[A-Za-z0-9_.-]+",
    ]

    for pattern in forbidden_patterns:
        assert re.search(pattern, combined_text, flags=re.IGNORECASE) is None


def test_blocks_json_medium_manifest_token_fields_are_pre_live_nulls() -> None:
    manifest = lmstudio_lab.load_dataset_manifest("blocks_json_medium")

    assert manifest.actual_input_tokens is None
    assert manifest.estimate_error_ratio is None


def test_load_chunked_dataset_view_rejects_overlapping_ids(tmp_path) -> None:
    _write_chunked_fixture(
        tmp_path,
        chunks_payload=[
            {"chunk_id": 0, "expected_ids": [0, 1]},
            {"chunk_id": 1, "expected_ids": [1, 3]},
        ],
    )

    with pytest.raises(ValueError, match="chunks overlap on ids"):
        lmstudio_lab.load_chunked_dataset_view("source_small_chunked", datasets_root=tmp_path)


def test_load_chunked_dataset_view_rejects_gap_against_source_dataset(tmp_path) -> None:
    _write_chunked_fixture(
        tmp_path,
        source_blocks=_build_source_blocks(5),
        source_expected_ids=[0, 1, 2, 3, 4],
        view_expected_ids=[0, 1, 3, 4],
        chunks_payload=[
            {"chunk_id": 0, "expected_ids": [0, 1]},
            {"chunk_id": 1, "expected_ids": [3, 4]},
        ],
    )

    with pytest.raises(ValueError, match="expected_ids must match source dataset"):
        lmstudio_lab.load_chunked_dataset_view("source_small_chunked", datasets_root=tmp_path)


def test_load_chunked_dataset_view_rejects_unknown_ids(tmp_path) -> None:
    _write_chunked_fixture(
        tmp_path,
        chunks_payload=[
            {"chunk_id": 0, "expected_ids": [0, 1]},
            {"chunk_id": 1, "expected_ids": [2, 9]},
        ],
    )

    with pytest.raises(ValueError, match="references unknown ids"):
        lmstudio_lab.load_chunked_dataset_view("source_small_chunked", datasets_root=tmp_path)
