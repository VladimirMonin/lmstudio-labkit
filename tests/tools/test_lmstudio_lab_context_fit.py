from __future__ import annotations

import pytest

from tools import lmstudio_lab


def test_context_fit_passes_when_required_within_budget() -> None:
    result = lmstudio_lab.evaluate_context_fit(
        estimated_input_tokens=1200,
        max_tokens=512,
        effective_context_length=4096,
    )

    assert result.required_tokens == 1712
    assert result.budget_tokens == 3481
    assert result.fits is True
    assert result.safety_ratio == 0.85
    assert result.effective_context_length == 4096


def test_context_fit_fails_when_required_exceeds_budget() -> None:
    result = lmstudio_lab.evaluate_context_fit(
        estimated_input_tokens=6700,
        max_tokens=7500,
        effective_context_length=8192,
        safety_ratio=0.85,
    )

    assert result.required_tokens == 14200
    assert result.budget_tokens == 6963
    assert result.fits is False


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("estimated_input_tokens", 0),
        ("estimated_input_tokens", -1),
        ("estimated_input_tokens", False),
        ("max_tokens", 0),
        ("max_tokens", -1),
        ("max_tokens", False),
        ("effective_context_length", 0),
        ("effective_context_length", -1),
        ("effective_context_length", False),
    ],
)
def test_context_fit_rejects_invalid_positive_int_inputs(
    field_name: str,
    value: int | bool,
) -> None:
    kwargs = {
        "estimated_input_tokens": 1200,
        "max_tokens": 512,
        "effective_context_length": 4096,
    }
    kwargs[field_name] = value

    with pytest.raises(ValueError):
        lmstudio_lab.evaluate_context_fit(**kwargs)


@pytest.mark.parametrize("safety_ratio", [0, -0.1, 1.01, False])
def test_context_fit_rejects_invalid_safety_ratio(safety_ratio: float | int | bool) -> None:
    with pytest.raises(ValueError):
        lmstudio_lab.evaluate_context_fit(
            estimated_input_tokens=1200,
            max_tokens=512,
            effective_context_length=4096,
            safety_ratio=safety_ratio,
        )
