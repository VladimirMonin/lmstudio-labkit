from __future__ import annotations

from lmstudio_labkit.validation import validate_language


def test_language_validation_include_paths_ignores_metadata() -> None:
    payload = {
        "id": 0,
        "language": "ru",
        "warnings": [{"type": "EN_ENUM"}],
        "clean_text": "Проверяем Django.",
    }
    result = validate_language(
        payload, "ru_ru", policy="preserve_input_language", include_paths=("clean_text",)
    )
    assert result.status == "pass"


def test_language_validation_blocks_value_path() -> None:
    payload = {"blocks": [{"id": 0, "text": "Настраиваем Django."}], "language": "ru"}
    result = validate_language(
        payload, "ru_ru", policy="preserve_input_language", include_paths=("blocks[*].text",)
    )
    assert result.status == "pass"
