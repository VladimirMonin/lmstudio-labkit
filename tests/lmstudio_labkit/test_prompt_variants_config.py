from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "experiments/lmstudio/structured_matrix/prompts"


def test_prompt_variant_files_exist() -> None:
    expected = {
        "baseline.md",
        "strict_same_language.md",
        "strict_no_new_facts.md",
        "strict_no_new_facts_v2.md",
        "term_glossary.md",
        "paragraphing_focused.md",
        "translation_focused.md",
    }
    assert expected <= {path.name for path in PROMPTS.glob("*.md")}
    for name in expected:
        assert PROMPTS.joinpath(name).read_text().strip()
