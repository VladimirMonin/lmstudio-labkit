from __future__ import annotations

from lmstudio_labkit.requests import ResponseContract, stable_hash


def test_response_contract_carries_postprocessing_metadata_safely() -> None:
    contract = ResponseContract(
        source_text="сырой приватный текст",
        expected_terms=({"source_variants": ["джанго"], "normalized": "Django"},),
        filler_terms=("ну", "как бы"),
        punctuation_policy="diagnostic",
        paragraphing_policy="hard",
        paragraph_count_min=2,
        paragraph_count_max=4,
        filler_cleanup_policy="warning",
        term_normalization_policy="hard",
        manual_review_policy="sampled",
    )

    metadata = contract.safe_metadata()

    assert metadata["source_text_hash"] == stable_hash("сырой приватный текст")
    assert metadata["source_text_char_count"] == len("сырой приватный текст")
    assert "сырой приватный текст" not in str(metadata)
    assert metadata["expected_terms_count"] == 1
    assert metadata["expected_terms_hash"] is not None
    assert metadata["filler_terms_count"] == 2
    assert metadata["filler_terms_hash"] is not None
    assert metadata["manual_review_policy"] == "sampled"
