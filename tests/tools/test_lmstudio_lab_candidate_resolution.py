from __future__ import annotations

import json
import re
from pathlib import Path
from urllib import error as urllib_error

import pytest
import yaml

from tools import lmstudio_benchmark, lmstudio_lab

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home|var|tmp|mnt)/[^\"\r\n]+"),
)
FORBIDDEN_OUTPUT_SNIPPETS = (
    "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf",
    "C:/Users/Private/private.gguf",
    "/var/tmp/private.gguf",
    "https://private.example/v1/models",
    "secret-token-value-1234567890",
    "prompt should not leak",
    "message should not leak",
    "content should not leak",
    "raw response body should not be stored",
)


def _assert_safe_text(text: str, *, project_root: Path) -> None:
    for forbidden in FORBIDDEN_OUTPUT_SNIPPETS:
        assert forbidden not in text
    known_private_values = {
        str(project_root),
        project_root.as_posix(),
        str(Path.home()),
        Path.home().as_posix(),
    }
    for value in known_private_values:
        if value:
            assert value not in text
    for pattern in ABSOLUTE_PATH_PATTERNS:
        assert pattern.search(text) is None


def _write_registry(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "registry_kind": "lmstudio_lab_candidates",
        "candidates": [
            {
                "lab_key": "gemma4_e2b_q4km",
                "family": "gemma",
                "size_class": "small",
                "source_id": "lmstudio-community/gemma-4-E2B-it-GGUF/gemma-4-E2B-it-Q4_K_M.gguf",
                "compat_model_id": "google/gemma-4-e2b",
                "compat_model_id_status": "measured_baseline",
            },
            {
                "lab_key": "qwen35_4b_q4km",
                "family": "qwen",
                "size_class": "small",
                "source_id": "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf",
                "compat_model_id": None,
                "compat_model_id_status": "pending_safe_resolution",
            },
        ],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_resolve_candidate_models_uses_get_v1_models_without_payload(tmp_path: Path) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)
    captured: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append((request.full_url, request.get_method(), request.data))
        assert timeout_s == 10.0
        return b'{"data": [{"id": "google/gemma-4-e2b"}]}'

    result = lmstudio_lab.resolve_candidate_models(
        "http://127.0.0.1:1234/api/v1",
        registry_path=registry_path,
        transport=fake_transport,
    )

    assert result.summary["status"] == "ok"
    assert captured == [("http://127.0.0.1:1234/v1/models", "GET", None)]


def test_resolve_candidate_models_confirms_exact_existing_compat_id() -> None:
    registry_path = (
        Path(__file__).resolve().parents[2]
        / "experiments"
        / "lmstudio"
        / "models"
        / "candidates.yaml"
    )

    result = lmstudio_lab.resolve_candidate_models(
        "http://127.0.0.1:1234",
        registry_path=registry_path,
        transport=lambda _request, _timeout_s: b'{"data": [{"id": "google/gemma-4-e2b"}]}',
    )

    candidate = next(
        record for record in result.candidate_records if record["lab_key"] == "gemma4_e2b_q4km"
    )
    assert candidate["existing_compat_exact_match"] is True
    assert candidate["status"] == "confirmed"
    assert candidate["suggestions"] == []
    assert result.summary["exact_confirmed_count"] == 1


def test_resolve_candidate_models_keeps_fuzzy_matches_unconfirmed_with_confirmation_flag(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)

    result = lmstudio_lab.resolve_candidate_models(
        "http://127.0.0.1:1234",
        registry_path=registry_path,
        transport=lambda _request, _timeout_s: json.dumps(
            {
                "data": [
                    {"id": "Qwen/Qwen3.5-4B-Instruct"},
                    {"id": "google/gemma-4-e2b"},
                ]
            }
        ).encode("utf-8"),
    )

    candidate = next(
        record for record in result.candidate_records if record["lab_key"] == "qwen35_4b_q4km"
    )
    assert candidate["existing_compat_exact_match"] is False
    assert candidate["status"] == "suggested"
    assert candidate["suggestions"]
    assert all(item["requires_user_confirmation"] is True for item in candidate["suggestions"])
    assert result.summary["exact_confirmed_count"] == 1
    assert result.summary["unresolved_count"] == 1


def test_resolve_candidates_cli_writes_safe_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)

    def fake_resolve(
        base_url: str,
        *,
        registry_path: Path,
        allow_remote: bool = False,
        timeout_s: float = 10.0,
    ) -> lmstudio_lab.CandidateResolutionResult:
        assert base_url == "http://127.0.0.1:1234"
        assert allow_remote is False
        assert timeout_s == 10.0
        return lmstudio_lab.resolve_candidate_models(
            base_url,
            registry_path=registry_path,
            allow_remote=allow_remote,
            timeout_s=timeout_s,
            transport=lambda _request, _timeout_s: json.dumps(
                {
                    "data": [
                        {"id": "Qwen/Qwen3.5-4B-Instruct"},
                        {"id": "google/gemma-4-e2b"},
                        {"id": "C:/Users/Private/private.gguf"},
                        {"id": "secret-token-value-1234567890"},
                        {
                            "id": "message should not leak",
                            "prompt": "prompt should not leak",
                            "content": "content should not leak",
                            "response": "raw response body should not be stored",
                        },
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )

    monkeypatch.setattr(lmstudio_benchmark, "resolve_candidate_models", fake_resolve)

    exit_code = lmstudio_benchmark.main(
        [
            "resolve-candidates",
            "--registry-path",
            str(registry_path),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "candidate-safe",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_candidate-safe_candidate_resolution"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "candidate_resolution.json",
        "candidate_suggestions.jsonl",
        "report.md",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    resolution_text = (run_dir / "candidate_resolution.json").read_text(encoding="utf-8")
    suggestions_text = (run_dir / "candidate_suggestions.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, resolution_text, suggestions_text, report_text):
        _assert_safe_text(text, project_root=project_root)

    assert str(registry_path) not in environment_text
    assert "http://127.0.0.1:1234" not in resolution_text
    assert "raw response body should not be stored" not in report_text

    environment_payload = json.loads(environment_text)
    assert environment_payload["command"] == "resolve-candidates"
    assert "registry_path" not in environment_payload
    assert "base_url" not in environment_payload

    resolution_payload = json.loads(resolution_text)
    assert resolution_payload["summary"]["probe_kind"] == "candidate_model_resolution"
    assert resolution_payload["summary"]["endpoint_path"] == "/v1/models"
    assert resolution_payload["summary"]["registry_written"] is False
    assert resolution_payload["summary"]["raw_response_body_stored"] is False

    suggestion_rows = _read_jsonl(run_dir / "candidate_suggestions.jsonl")
    assert suggestion_rows
    assert suggestion_rows[0]["run_id"] == "candidate-safe"
    assert suggestion_rows[0]["requires_user_confirmation"] is True

    assert "GET `/v1/models` only" in report_text
    assert "no generation/load/unload/download endpoints used" in report_text
    assert "registry not written" in report_text
    assert "fuzzy suggestions require user confirmation" in report_text


def test_resolve_candidates_cli_rejects_remote_without_allow_remote(tmp_path: Path) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)

    with pytest.raises(ValueError, match="allow-remote"):
        lmstudio_benchmark.main(
            [
                "resolve-candidates",
                "--base-url",
                "https://example.com:1234",
                "--registry-path",
                str(registry_path),
                "--output-root",
                str(tmp_path),
            ]
        )


@pytest.mark.parametrize(
    ("transport", "expected_status", "expected_category"),
    [
        (
            lambda _request, _timeout_s: (_ for _ in ()).throw(
                urllib_error.URLError(TimeoutError("secret-token-value-1234567890"))
            ),
            "transport_error",
            "timeout",
        ),
        (lambda _request, _timeout_s: b"not-json", "decode_error", "json"),
        (lambda _request, _timeout_s: b'{"unexpected": []}', "invalid_shape", "shape"),
    ],
)
def test_resolve_candidate_models_maps_safe_error_statuses(
    tmp_path: Path,
    transport,
    expected_status: str,
    expected_category: str,
) -> None:
    registry_path = tmp_path / "candidates.yaml"
    _write_registry(registry_path)

    result = lmstudio_lab.resolve_candidate_models(
        "http://127.0.0.1:1234",
        registry_path=registry_path,
        transport=transport,
    )

    assert result.summary["status"] == expected_status
    assert result.summary["error_category"] == expected_category
    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    report_text = lmstudio_lab.render_candidate_resolution_report(
        run_id="errors",
        summary=result.summary,
        candidate_records=result.candidate_records,
    )
    assert "secret-token-value-1234567890" not in serialized
    assert "secret-token-value-1234567890" not in report_text
    assert "127.0.0.1" not in serialized
