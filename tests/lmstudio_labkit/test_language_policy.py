from __future__ import annotations

import json

from lmstudio_labkit.benchmarks import BenchmarkConfig, plan_matrix
from lmstudio_labkit.requests import ResponseContract
from lmstudio_labkit.validation import validate_language, validate_response


def test_ru_ru_defaults_to_strict_cyrillic_ratio() -> None:
    result = validate_language("Короткий русский ответ with Latin terms", "ru_ru")

    assert result.status == "pass"
    assert result.metrics["policy"] == "strict_ru"
    assert result.metrics["cyrillic_ratio"] >= 0.5


def test_strict_ru_fails_when_cyrillic_ratio_is_too_low() -> None:
    result = validate_language("English text with немного", "ru_ru")

    assert result.status == "fail"
    assert result.category == "language_mismatch"
    assert result.metrics["policy"] == "strict_ru"


def test_allow_code_terms_accepts_lower_cyrillic_ratio_with_cyrillic_present() -> None:
    result = validate_language(
        "Use JSON schema and API fields: ошибка, код, ответ.",
        "ru_ru",
        policy="allow_code_terms",
    )

    assert result.status == "pass"
    assert result.metrics["policy"] == "allow_code_terms"
    assert result.metrics["cyrillic_ratio"] >= 0.25


def test_allow_code_terms_still_requires_some_cyrillic() -> None:
    result = validate_language(
        "Use JSON schema and API fields.",
        "ru_ru",
        policy="allow_code_terms",
    )

    assert result.status == "fail"
    assert result.category == "language_mismatch"


def test_ru_en_mixed_requires_cyrillic_or_explicit_expected_hint() -> None:
    cyrillic_only = validate_language("Только русский ответ", "ru_en_mixed")
    latin_only_without_hint = validate_language("English only answer", "ru_en_mixed")
    latin_only_with_hint = validate_language(
        "English label value",
        "ru_en_mixed",
        expected_hints={"language_policy": "mixed_ru_en"},
    )

    assert cyrillic_only.status == "pass"
    assert latin_only_without_hint.status == "fail"
    assert latin_only_without_hint.category == "language_mismatch"
    assert latin_only_with_hint.status == "pass"


def test_en_en_defaults_to_strict_latin_ratio() -> None:
    result = validate_language("English response with слово", "en_en")

    assert result.status == "pass"
    assert result.metrics["policy"] == "strict_en"
    assert result.metrics["latin_ratio"] >= 0.5


def test_skip_policy_disables_language_validation() -> None:
    result = validate_language("Any output", "ru_ru", policy="skip")

    assert result.status == "skip"


def test_labels_only_validates_expected_labels_instead_of_global_ratio() -> None:
    raw_response = json.dumps({"labels": ["cat", "table"]})
    contract = ResponseContract(
        mode="json",
        language="ru_ru",
        language_policy="labels_only",
        image_ground_truth={"labels": ["cat", "table"]},
    )

    summary = validate_response(raw_response, contract)
    language_result = next(item for item in summary.results if item.name == "language_compliance")
    image_result = next(item for item in summary.results if item.name == "image_ground_truth")

    assert language_result.status == "pass"
    assert language_result.metrics["policy"] == "labels_only"
    assert language_result.metrics["missing_label_count"] == 0
    assert image_result.status == "pass"
    assert summary.status == "pass"


def test_labels_only_reports_missing_expected_labels() -> None:
    result = validate_language(
        {"labels": ["cat"]},
        "ru_ru",
        policy="labels_only",
        image_ground_truth={"labels": ["cat", "table"]},
    )

    assert result.status == "fail"
    assert result.category == "language_label_mismatch"
    assert result.metrics["missing_label_count"] == 1


def test_task_language_policy_is_transferred_to_response_contract() -> None:
    config = BenchmarkConfig.from_dict(
        {
            "run_id": "language_policy_transfer",
            "models": [{"model_key": "fake", "model_id": "fake/model"}],
            "tasks": [
                {
                    "task_id": "ru_code_terms",
                    "family": "simple_flat",
                    "language": "ru_ru",
                    "language_policy": "allow_code_terms",
                    "prompt": "Synthetic fixture prompt.",
                    "expected_output": {"id": "item_0", "text": "API ответ"},
                }
            ],
            "axes": {"language": ["ru_ru"]},
        }
    )

    plan = config.tasks[0]
    request_plan = next(iter(plan_matrix(config).cells)).to_request_plan()

    assert plan.language_policy == "allow_code_terms"
    assert request_plan.envelope.response_contract.language == "ru_ru"
    assert request_plan.envelope.response_contract.language_policy == "allow_code_terms"
    assert (
        request_plan.envelope.response_contract.safe_metadata()["language_policy"]
        == "allow_code_terms"
    )
