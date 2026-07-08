from __future__ import annotations

from lmstudio_labkit.validation import validate_exact_ids


def test_integer_ids_are_collected_and_normalized() -> None:
    result = validate_exact_ids({"blocks": [{"id": 0}, {"id": 1}]}, (0, 1))

    assert result.status == "pass"
    assert result.metrics["seen_count"] == 2


def test_reordered_ids_report_first_mismatch_index() -> None:
    result = validate_exact_ids({"blocks": [{"id": 1}, {"id": 0}]}, (0, 1))

    assert result.status == "fail"
    assert result.category == "id_order_mismatch"
    assert result.metrics["first_mismatch_index"] == 0
    assert result.metrics["order_mismatch"] is True


def test_duplicate_missing_and_extra_are_counted_separately() -> None:
    result = validate_exact_ids({"blocks": [{"id": 0}, {"id": 0}, {"id": 2}]}, (0, 1))

    assert result.status == "fail"
    assert result.metrics["duplicate_count"] == 1
    assert result.metrics["missing_count"] == 1
    assert result.metrics["unexpected_count"] == 1
