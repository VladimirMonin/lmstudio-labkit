from __future__ import annotations

from lmstudio_labkit.benchmarks import render_postprocessing_prompt


def test_render_postprocessing_prompt_includes_required_rules_and_glossary() -> None:
    rendered = render_postprocessing_prompt(
        template_text="Normalize terms.",
        source_text="сегодня используем джанго",
        task_intent="term_normalization",
        response_schema_complexity="blocks",
        expected_terms=({"source_variants": ["джанго"], "normalized": "Django"},),
    )

    assert "Return JSON only" in rendered
    assert "Do not use Markdown" in rendered
    assert "Do not add new facts" in rendered
    assert "Preserve the input language" in rendered
    assert "джанго -> Django" in rendered
    assert "сегодня используем джанго" in rendered
