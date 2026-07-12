from __future__ import annotations

import json
import stat
from collections import Counter
from pathlib import Path

import pytest
from tools.lmstudio_lab.source_shaped_rehearsal import (
    MODEL_IDS,
    REPRESENTATIONS,
    _generate,
    _load_or_attach,
    _loaded_inventory,
    _model_load_config,
    _request_parameters,
    build_confirmation_plan,
    build_plan,
    derive_output_budget,
    initialize_private_rubric,
    validate_token_fit,
    write_plan,
)

ROOT = Path(__file__).resolve().parents[2]
REHEARSAL = ROOT / "experiments/lmstudio/source_shaped_rehearsal/v1"
MANIFEST = REHEARSAL / "manifest.json"
SELECTOR = REHEARSAL / "confirmation_selector.json"


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "sanitized-whisper-transcript-v1",
                "owner_verified": True,
                "sanitized": True,
                "representative_ranges": [[0, 2], [3, 5], [7, 9]],
                "blocks": [
                    {
                        "id": index,
                        "start": index * 2.0,
                        "end": index * 2.0 + 1.5,
                        "text": f"Фраза {index}.",
                    }
                    for index in range(9)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_plan_is_exact_54_call_matrix(tmp_path: Path) -> None:
    plan = build_plan(MANIFEST, _source(tmp_path))
    rows = plan["requests"]
    assert plan["planned_calls"] == 54
    assert plan["calls_per_model"] == 9
    assert Counter(row["model"] for row in rows) == Counter(dict.fromkeys(MODEL_IDS, 9))
    assert Counter(row["representation"] for row in rows) == Counter(
        dict.fromkeys(REPRESENTATIONS, 18)
    )
    assert {row["chunk_number"] for row in rows} == {1, 2, 3}
    assert {row["reasoning"] for row in rows} == {"off"}
    assert {row["retries"] for row in rows} == {0}
    assert {row["output_format"] for row in rows} == {"plain_text"}


def test_request_marks_chunk_and_forbids_adjacent_output(tmp_path: Path) -> None:
    row = build_plan(MANIFEST, _source(tmp_path))["requests"][0]
    request = row["request_text"]
    assert request.count("<<<BEGIN_CURRENT_CHUNK>>>") == 1
    assert request.count("<<<END_CURRENT_CHUNK>>>") == 1
    assert "REFERENCE ONLY; NEVER OUTPUT ADJACENT TEXT" in request
    marked = request.split("<<<BEGIN_CURRENT_CHUNK>>>\n", 1)[1].split(
        "\n<<<END_CURRENT_CHUNK>>>", 1
    )[0]
    assert marked == row["chunk_text"]


def test_prompt_and_rubric_freeze_repair_contract() -> None:
    prompt = (REHEARSAL / "prompts/cleanup.txt").read_text(encoding="utf-8")
    for term in (
        "EXACT_PROTECTED",
        "character-for-character",
        "SEMANTIC_PROTECTED",
        "allowlist",
        "uncertain",
        "do not summarize",
        "topic paragraphs",
    ):
        assert term in prompt
    rubric = json.loads((REHEARSAL / "manual_rubric.template.json").read_text(encoding="utf-8"))
    required = rubric["required_per_call"]
    assert {
        "finish_ok",
        "current_chunk_complete",
        "chunk_only",
        "outside_chunk_span_count",
        "exact_protected",
        "semantic_protected",
        "beneficial_corrections",
        "harmful_corrections",
    } <= required.keys()


def test_confirmation_plan_is_frozen_to_three_12b_lanes(tmp_path: Path) -> None:
    plan = build_confirmation_plan(MANIFEST, _source(tmp_path), SELECTOR)
    assert plan["planned_calls"] == plan["calls_per_model"] == 3
    assert plan["request_timeout_seconds"] == 900
    assert plan["reasoning"] == "off"
    assert plan["retries"] == 0
    assert [(row["representation"], row["chunk_label"]) for row in plan["requests"]] == [
        ("plain", "early"),
        ("timestamped_paragraphs", "late"),
        ("json_blocks", "middle"),
    ]
    assert {row["model"] for row in plan["requests"]} == {"google/gemma-4-12b-qat"}
    assert [row["request_id"] for row in plan["requests"]] == ["c19", "c24", "c26"]


def test_confirmation_selector_fails_closed_on_timeout_change(tmp_path: Path) -> None:
    selector = json.loads(SELECTOR.read_text(encoding="utf-8"))
    selector["request_timeout_seconds"] = 901
    changed = tmp_path / "selector.json"
    changed.write_text(json.dumps(selector), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly 900"):
        build_confirmation_plan(MANIFEST, _source(tmp_path), changed)


def test_qwen_load_config_omits_gemma_specific_overrides() -> None:
    config = {
        "context_length": 32768,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": False,
    }
    assert _model_load_config("qwen/qwen3.5-4b", config) == {"context_length": 32768}
    assert _model_load_config("google/gemma-4-e4b", config) == config


def test_only_input_representation_changes_between_matched_lanes(tmp_path: Path) -> None:
    rows = build_plan(MANIFEST, _source(tmp_path))["requests"]
    for model in MODEL_IDS:
        model_rows = [row for row in rows if row["model"] == model]
        for chunk_number in (1, 2, 3):
            matched = [row for row in model_rows if row["chunk_number"] == chunk_number]
            assert len(matched) == 3
            assert len({row["chunk_text"] for row in matched}) == 1
            assert len({row["chunk_text_sha256"] for row in matched}) == 1
            assert len({row["instruction"] for row in matched}) == 1
            assert len({row["instruction_sha256"] for row in matched}) == 1
            assert {row["representation"] for row in matched} == set(REPRESENTATIONS)


def test_full_context_representations_are_complete_and_distinct(tmp_path: Path) -> None:
    rows = build_plan(MANIFEST, _source(tmp_path))["requests"][:9]
    contexts = {row["representation"]: row["full_context"] for row in rows}
    assert len(contexts) == 3
    assert all(f"Фраза {index}." in value for value in contexts.values() for index in range(9))
    assert "00:00:00.000 --> 00:00:01.500" in contexts["timestamped_paragraphs"]
    blocks = json.loads(contexts["json_blocks"])
    assert all(set(block) == {"id", "start", "end", "text"} for block in blocks)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(owner_verified=False),
        lambda value: value.update(sanitized=False),
        lambda value: value.update(representative_ranges=[[0, 3], [2, 5], [7, 9]]),
        lambda value: value["blocks"][0].update(extra="forbidden"),
        lambda value: value["blocks"][1].update(id=9),
        lambda value: value["blocks"][1].update(start=1.0),
    ],
)
def test_source_contract_fails_closed(tmp_path: Path, mutation) -> None:
    source = _source(tmp_path)
    value = json.loads(source.read_text(encoding="utf-8"))
    mutation(value)
    source.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        build_plan(MANIFEST, source)


def test_plan_write_is_deterministic_and_rubric_is_private(tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_plan(MANIFEST, source, first)
    write_plan(MANIFEST, source, second)
    assert first.read_bytes() == second.read_bytes()
    private = tmp_path / "owner" / "rubric.json"
    initialize_private_rubric(REHEARSAL / "manual_rubric.template.json", private)
    assert stat.S_IMODE(private.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        initialize_private_rubric(REHEARSAL / "manual_rubric.template.json", private)


class _FakeModel:
    def __init__(self, context_length: int = 1000) -> None:
        self.context_length = context_length

    def tokenize(self, text: str):
        return list(range(len(text.split())))

    def apply_prompt_template(self, _chat) -> str:
        return "one two three four"

    def get_context_length(self) -> int:
        return self.context_length


def test_budget_comes_from_chunk_tokens_without_fixed_cap() -> None:
    model = _FakeModel()
    assert derive_output_budget(model, " ".join(["слово"] * 2000)) == 3256


def test_token_fit_uses_formatted_sdk_request_and_fails_closed() -> None:
    assert validate_token_fit(_FakeModel(), "ignored", 995) == 4
    with pytest.raises(RuntimeError, match="exceeds context"):
        validate_token_fit(_FakeModel(), "ignored", 997)


def test_request_parameters_disable_reasoning_for_both_manifest_spellings() -> None:
    assert _request_parameters("off") == {
        "temperature": 0,
        "reasoning": {"effort": "none"},
    }
    assert _request_parameters("none") == _request_parameters("off")
    with pytest.raises(ValueError, match="off/none"):
        _request_parameters("on")


def test_load_or_attach_recovers_materialized_remote_instance(monkeypatch) -> None:
    class _Llm:
        def load_new_instance(self, *_args, **_kwargs):
            raise RuntimeError("device response was lost")

        def model(self, identifier, *, ttl):
            assert identifier == "instance"
            assert ttl is None
            return "attached"

    class _Client:
        llm = _Llm()

    monkeypatch.setattr(
        "tools.lmstudio_lab.source_shaped_rehearsal._loaded_instance",
        lambda model_id, instance_id: {"id": instance_id, "model": model_id},
    )
    assert _load_or_attach(_Client(), "model", "instance", {}) == "attached"


def test_loaded_inventory_deduplicates_alias_records(monkeypatch) -> None:
    document = {
        "models": [
            {"key": "canonical/model", "loaded_instances": [{"id": "instance-1"}]},
            {"key": "local-alias", "loaded_instances": [{"id": "instance-1"}]},
        ]
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(document).encode()

    monkeypatch.setattr(
        "tools.lmstudio_lab.source_shaped_rehearsal.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(),
    )
    assert _loaded_inventory() == {"instance-1": {"id": "instance-1"}}


def test_generate_uses_product_shaped_chat_transport(monkeypatch) -> None:
    captured = {}
    response = {
        "choices": [{"message": {"role": "assistant", "content": "Исправленный текст"}}],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 0}},
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(response, ensure_ascii=False).encode()

    def _urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(
        "tools.lmstudio_lab.source_shaped_rehearsal.urllib.request.urlopen", _urlopen
    )
    result = _generate("instance", "Обработай часть", 2048)
    assert captured == {
        "url": "http://localhost:1234/v1/chat/completions",
        "payload": {
            "model": "instance",
            "messages": [{"role": "user", "content": "Обработай часть"}],
            "max_tokens": 2048,
            "temperature": 0,
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        },
        "timeout": 3600,
    }
    assert result["_lab_final_text"] == "Исправленный текст"
