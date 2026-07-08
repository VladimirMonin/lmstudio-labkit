from __future__ import annotations

from lmstudio_labkit.validation import extract_user_text_for_validation


def test_extract_simple_user_text_paths() -> None:
    text = extract_user_text_for_validation(
        {"language": "ru", "clean_text": "Текст.", "summary": "Итог.", "id": 1},
        response_schema_complexity="simple",
    )
    assert "Текст." in text
    assert "Итог." in text
    assert "ru" not in text


def test_extract_blocks_user_text_paths() -> None:
    text = extract_user_text_for_validation(
        {"blocks": [{"id": 0, "text": "Первый."}, {"id": 1, "text": "Второй."}]},
        response_schema_complexity="blocks",
    )
    assert text == "Первый. Второй."


def test_extract_complex_user_text_paths() -> None:
    payload = {
        "document": {
            "title": "Документ",
            "sections": [
                {
                    "heading": "Раздел",
                    "blocks": [
                        {
                            "id": 0,
                            "text": "Текст блока.",
                            "terms": [{"source": "джанго", "normalized": "Django"}],
                        }
                    ],
                }
            ],
        }
    }
    text = extract_user_text_for_validation(payload, response_schema_complexity="complex")
    assert "Документ" in text
    assert "Раздел" in text
    assert "Текст блока." in text
    assert "Django" in text
    assert "джанго" not in text
