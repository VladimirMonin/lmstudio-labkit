from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from lmstudio_labkit.validation import validate_language

from lmstudio_labkit import BenchmarkConfig, plan_matrix

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = (
    PROJECT_ROOT
    / "experiments"
    / "lmstudio"
    / "structured_matrix"
    / "configs"
    / "matrix.l3_20_postprocessing_redesign.offline.yaml"
)
SUITE = (
    PROJECT_ROOT
    / "experiments"
    / "lmstudio"
    / "structured_matrix"
    / "suites"
    / "l3_20_postprocessing_redesign_offline.yaml"
)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_l3_20_postprocessing_config_separates_task_axes() -> None:
    payload = _load_yaml(CONFIG)
    config = BenchmarkConfig.from_file(CONFIG)
    plan = plan_matrix(config)

    assert payload["run_id"] == "matrix_l3_20_postprocessing_redesign_offline"
    assert payload["safety"] == {
        "live": False,
        "allow_model_downloads": False,
        "allow_model_loads": False,
        "allow_remote_base_url": False,
        "allow_raw_prompt_response_artifacts": False,
        "allow_image_live": False,
        "allow_stress": False,
        "max_requests": 20,
        "max_models": 2,
        "max_context_tier": 8192,
        "max_repeats": 1,
        "max_runtime_minutes": 10,
    }
    assert len(payload["tasks"]) == 5
    axes = payload["axes"]
    assert set(axes["task_intent"]) == {
        "fix_asr_terms_summary_actions",
        "punctuate",
        "remove_fillers_paragraphs",
        "summary_action_items",
        "translate_summary",
    }
    assert set(axes["input_profile"]) == {"asr_noise_ru", "asr_noise_ru_en_mixed", "clean_en"}
    assert axes["output_language_policy"] == ["preserve_input_language", "translate_to_ru"]
    assert set(axes["validation_policy"]) == {
        "auto_schema_language_manual_quality",
        "manual_quality_required",
    }
    assert plan.planner_summary()["cell_count"] == 20
    assert set(plan.planner_summary()["skip_reasons"]) >= {
        "task_intent_mismatch",
        "input_profile_mismatch",
        "output_language_policy_mismatch",
        "validation_policy_mismatch",
    }


def test_l3_20_suite_is_offline_only() -> None:
    suite = _load_yaml(SUITE)

    assert suite == {
        "suite_id": "l3_20_postprocessing_redesign_offline",
        "stop_on_failure": True,
        "configs": [
            {
                "id": "postprocessing_redesign_offline",
                "config": "../configs/matrix.l3_20_postprocessing_redesign.offline.yaml",
                "required": True,
            }
        ],
    }


def test_language_validator_preserve_policy_ignores_json_metadata_and_tech_terms() -> None:
    payload = {
        "id": 0,
        "language": "ru",
        "status": "accepted",
        "corrected_text": "Проверяем Embedding pipeline в Django и Qwen fallback.",
        "terms": ["Embedding", "Django", "Qwen"],
    }

    result = validate_language(payload, "ru_ru", policy="preserve_input_language")

    assert result.status == "pass"
    assert result.metrics["policy"] == "allow_code_terms"

    english_only = validate_language(
        {"corrected_text": "Embedding pipeline fallback only."},
        "ru_ru",
        policy="preserve_input_language",
    )
    assert english_only.status == "fail"
    assert english_only.category == "language_mismatch"


def test_language_validator_translation_policy_is_explicit() -> None:
    ru_result = validate_language(
        {"summary_ru": "Команда обсуждает Whisper postprocessing и JSON contract."},
        "en_en",
        policy="translate_to_ru",
    )
    en_result = validate_language(
        {"summary_en": "The team reviews Whisper postprocessing and JSON contract."},
        "ru_ru",
        policy="translate_to_en",
    )

    assert ru_result.status == "pass"
    assert ru_result.metrics["policy"] == "allow_code_terms"
    assert en_result.status == "pass"
    assert en_result.metrics["policy"] == "strict_en"
