from __future__ import annotations

import pytest

from tools import lmstudio_lab


def test_estimate_input_tokens_from_chars_uses_ceiling_contract() -> None:
    assert lmstudio_lab.estimate_input_tokens_from_chars(0) == 0
    assert lmstudio_lab.estimate_input_tokens_from_chars(1) == 1
    assert lmstudio_lab.estimate_input_tokens_from_chars(3) == 1
    assert lmstudio_lab.estimate_input_tokens_from_chars(4) == 2
    assert lmstudio_lab.estimate_input_tokens_from_chars(7) == 3


@pytest.mark.parametrize(
    ("chars", "chars_per_token", "message"),
    [
        (-1, 3.0, "chars must be >= 0"),
        (True, 3.0, "chars must be an integer"),
        (1, 0.0, "chars_per_token must be > 0"),
        (1, -1.0, "chars_per_token must be > 0"),
        (1, False, "chars_per_token must be > 0"),
    ],
)
def test_estimate_input_tokens_from_chars_validates_inputs(
    chars: object,
    chars_per_token: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        lmstudio_lab.estimate_input_tokens_from_chars(chars, chars_per_token=chars_per_token)


def test_calculate_estimate_error_ratio_supports_unknown_actual_tokens() -> None:
    assert lmstudio_lab.calculate_estimate_error_ratio(10, None) is None
    assert lmstudio_lab.calculate_estimate_error_ratio(12, 10) == pytest.approx(0.2)
    assert lmstudio_lab.calculate_estimate_error_ratio(8, 10) == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("estimated", "actual", "message"),
    [
        (-1, 10, "estimated_input_tokens must be >= 0"),
        (10, 0, "actual_input_tokens must be > 0"),
        (10, -1, "actual_input_tokens must be >= 0"),
        (10, True, "actual_input_tokens must be an integer"),
    ],
)
def test_calculate_estimate_error_ratio_validates_inputs(
    estimated: object,
    actual: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        lmstudio_lab.calculate_estimate_error_ratio(estimated, actual)
