from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from pathlib import Path

import pytest

PACK_ROOT = (
    Path(__file__).resolve().parents[2]
    / "experiments"
    / "lmstudio"
    / "private_benchmark_pack"
    / "v1"
)

LOCALIZED_DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:январ[яе]|феврал[яе]|марта|апрел[яе]|ма[яе]|июн[яе]|"
    r"июл[яе]|август[ае]|сентябр[яе]|октябр[яе]|ноябр[яе]|декабр[яе])"
    r"(?:\s+(?:19|20)\d{2}(?:\s*г(?:ода|\.)?)?)?",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DOTTED_IDENTIFIER_RE = re.compile(r"(?<!\w)\d{1,4}(?:\.\d{1,4}){2,}(?!\w)")
PLACEHOLDER_RE = re.compile(
    r"\b(?:PERSON|CONTACT|ACCOUNT|LOCATION|ORG|PRODUCT|ENTITY|DATE|PATH|SECRET|RARE)_\d{3}\b"
)
PLACEHOLDER_TOKEN_RE = re.compile(
    r"(?:PERSON|CONTACT|ACCOUNT|LOCATION|ORG|PRODUCT|ENTITY|DATE|PATH|SECRET|RARE)_\d{3}"
)
PLACEHOLDER_LIKE_RE = re.compile(r"(?<!\w)[A-Z][A-Z0-9_]*_\d{3}(?!\w)")
RESIDUAL_PROTECTED_PATTERNS = {
    "email": re.compile(r"(?<!\w)[^\s@]+@[^\s@]+(?!\w)"),
    "http_locator": re.compile(r"https?://|www\.", re.IGNORECASE),
    "private_path": re.compile(r"(?:^|\s)(?:/home/|[A-Za-z]:\\\\)"),
}


def _public_text_fields() -> list[tuple[Path, str]]:
    fields: list[tuple[Path, str]] = []
    for view_dir in sorted((PACK_ROOT / "views").iterdir()):
        fixture_path = view_dir / "fixture.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fields.extend((fixture_path, unit["text"]) for unit in fixture["ordered_units"])

        blocks_path = view_dir / "blocks.json"
        blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
        for block in blocks["blocks"]:
            fields.append((blocks_path, block["raw_text"]))
            if block["reference_candidate_text"] is not None:
                fields.append((blocks_path, block["reference_candidate_text"]))

        reference_path = view_dir / "reference_candidate.json"
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        if reference["text"] is not None:
            fields.append((reference_path, reference["text"]))
    return fields


def _public_tree_sha256() -> str:
    payload = bytearray()
    for path in sorted(PACK_ROOT.rglob("*")):
        if not path.is_file() or path == PACK_ROOT / "pack.json":
            continue
        payload.extend(path.relative_to(PACK_ROOT).as_posix().encode())
        payload.append(0)
        payload.extend(path.read_bytes())
        payload.append(0)
    return hashlib.sha256(payload).hexdigest()


def _normalized_protected_entity(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _private_source_fields(snapshot: dict, redaction: dict) -> list[tuple[str, list[dict]]]:
    return [
        (snapshot["raw_text"], redaction["source_spans"]),
        *[
            (unit["text"], spans)
            for unit, spans in zip(
                snapshot["ordered_segments"], redaction["unit_spans"], strict=True
            )
        ],
        (snapshot["stored_postprocessed_text"], redaction["reference_spans"]),
        *[
            (block["text"], spans)
            for block, spans in zip(
                snapshot["raw_blocks"], redaction["block_raw_spans"], strict=True
            )
        ],
        *[
            (block.get("postprocessed_text") or "", spans)
            for block, spans in zip(
                snapshot["raw_blocks"], redaction["block_reference_spans"], strict=True
            )
        ],
    ]


def test_public_text_has_no_localized_dates_years_or_dotted_identifiers() -> None:
    findings: list[str] = []
    patterns = {
        "localized_date": LOCALIZED_DATE_RE,
        "year": YEAR_RE,
        "dotted_identifier": DOTTED_IDENTIFIER_RE,
    }
    for path, text in _public_text_fields():
        for name, pattern in patterns.items():
            if match := pattern.search(text):
                findings.append(f"{path.relative_to(PACK_ROOT)}: {name} at {match.span()}")
    assert findings == []


def test_contextual_fingerprints_are_replaced_by_view_scoped_placeholders() -> None:
    fixture = json.loads((PACK_ROOT / "views" / "M01" / "fixture.json").read_text(encoding="utf-8"))
    text = " ".join(unit["text"] for unit in fixture["ordered_units"])

    placeholders = PLACEHOLDER_RE.findall(text)
    assert any(value.startswith("ACCOUNT_") for value in placeholders)
    assert any(value.startswith("DATE_") for value in placeholders)
    assert DOTTED_IDENTIFIER_RE.search(text) is None
    assert LOCALIZED_DATE_RE.search(text) is None


def test_all_public_placeholders_are_atomic_known_tokens() -> None:
    findings: list[str] = []
    fields = _public_text_fields()
    assert len({path.parent.name for path, _ in fields}) == 16

    for path, text in fields:
        known = list(PLACEHOLDER_TOKEN_RE.finditer(text))
        placeholder_like = list(PLACEHOLDER_LIKE_RE.finditer(text))
        if [match.group() for match in known] != [match.group() for match in placeholder_like]:
            findings.append(f"{path.relative_to(PACK_ROOT)}: unknown placeholder-like token")
        for match in known:
            before = text[match.start() - 1 : match.start()] if match.start() else ""
            after = text[match.end() : match.end() + 1]
            if (before and (before.isalnum() or before == "_")) or (
                after and (after.isalnum() or after == "_")
            ):
                findings.append(
                    f"{path.relative_to(PACK_ROOT)}: non-atomic placeholder at {match.span()}"
                )
    assert findings == []


def test_all_public_source_derived_fields_have_zero_residual_protected_literals() -> None:
    findings: list[str] = []
    patterns = {
        "localized_date": LOCALIZED_DATE_RE,
        "year": YEAR_RE,
        "dotted_identifier": DOTTED_IDENTIFIER_RE,
        **RESIDUAL_PROTECTED_PATTERNS,
    }
    for path, text in _public_text_fields():
        for name, pattern in patterns.items():
            if match := pattern.search(text):
                findings.append(f"{path.relative_to(PACK_ROOT)}: {name} at {match.span()}")
    assert findings == []


def _private_root_from_owner_handoff() -> Path:
    configured = os.environ.get("PRIVATE_BENCHMARK_PACK_ROOT")
    handoff = Path.home() / ".config" / "lmstudio-labkit" / "private-benchmark-pack-root"
    if configured is None:
        if not handoff.is_file():
            pytest.fail("owner-only private replay handoff is unavailable")
        assert stat.S_IMODE(handoff.stat().st_mode) == 0o600
        configured = handoff.read_text(encoding="utf-8").strip()
    private_root = Path(configured)
    assert private_root.is_absolute()
    assert stat.S_IMODE(private_root.stat().st_mode) & 0o077 == 0
    return private_root


def test_private_full_pack_placeholder_mapping_is_a_view_class_bijection() -> None:
    private_root = _private_root_from_owner_handoff()
    manifest = json.loads((private_root / "manifest.json").read_text(encoding="utf-8"))
    redaction_map = json.loads((private_root / "redaction-map.json").read_text(encoding="utf-8"))
    registry = json.loads((private_root / "entity-registry.json").read_text(encoding="utf-8"))
    span_instances = 0

    for view in manifest["views"]:
        label = view["view_label"]
        snapshot = json.loads(
            (private_root / "source-snapshots" / f"{label}.json").read_text(encoding="utf-8")
        )
        entity_to_token: dict[tuple[str, str], str] = {}
        token_to_entity: dict[tuple[str, str], str] = {}
        for text, spans in _private_source_fields(snapshot, redaction_map[label]):
            for span in spans:
                span_instances += 1
                source = text[span["start"] : span["end"]]
                assert hashlib.sha256(source.encode()).hexdigest() == span["source_sha256"]
                entity = _normalized_protected_entity(source)
                entity_key = (span["placeholder_class"], entity)
                token_key = (span["placeholder_class"], span["placeholder"])
                assert (
                    entity_to_token.setdefault(entity_key, span["placeholder"])
                    == span["placeholder"]
                )
                assert token_to_entity.setdefault(token_key, entity) == entity

        expected_registry = {
            placeholder_class: {
                hashlib.sha256(entity.encode()).hexdigest(): token
                for (entity_class, entity), token in entity_to_token.items()
                if entity_class == placeholder_class
            }
            for placeholder_class in sorted({entity_class for entity_class, _ in entity_to_token})
        }
        assert registry[label] == expected_registry

    assert span_instances == 6366


def test_public_tree_digest_is_reproducible() -> None:
    pack = json.loads((PACK_ROOT / "pack.json").read_text(encoding="utf-8"))
    assert pack["public_tree_sha256"] == _public_tree_sha256()
