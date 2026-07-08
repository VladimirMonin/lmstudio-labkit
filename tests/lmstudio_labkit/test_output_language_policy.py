from __future__ import annotations

from lmstudio_labkit.validation import validate_language


def test_preserve_mixed_language_accepts_ru_with_english_terms() -> None:
    result = validate_language(
        {"clean_text": "Проверяем Django и Qwen embedding."},
        "ru_en_mixed",
        policy="preserve_mixed_language",
    )
    assert result.status == "pass"
    assert result.metrics["policy"] == "mixed_ru_en"


def test_translation_policy_is_not_global_russian_requirement() -> None:
    en = validate_language(
        {"clean_text": "Django migrations are ready."}, "en_en", policy="preserve_input_language"
    )
    ru = validate_language(
        {"clean_text": "Миграции Django готовы."}, "en_en", policy="translate_to_ru"
    )
    assert en.status == "pass"
    assert en.metrics["policy"] == "strict_en"
    assert ru.status == "pass"
    assert ru.metrics["policy"] == "allow_code_terms"
