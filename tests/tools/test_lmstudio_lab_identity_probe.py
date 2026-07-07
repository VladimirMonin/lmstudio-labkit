from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib import error as urllib_error

import pytest

import tools.lmstudio_lab.identity_probe as identity_probe_module
from tools import lmstudio_benchmark, lmstudio_lab

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:[\\/][^\"\r\n]+"),
    re.compile(r"\\\\[^\"\r\n]+[\\/][^\"\r\n]+"),
    re.compile(r"/(?:Users|home|var|tmp|mnt)/[^\"\r\n]+"),
)
FORBIDDEN_OUTPUT_SNIPPETS = (
    "http://127.0.0.1:1234/v1/models",
    "http://127.0.0.1:1234/api/v1/models",
    "https://example.com:1234/v1/models",
    "https://example.com:1234/api/v1/models",
    "/v1/models",
    "/api/v1/models",
    "/v1/chat/completions",
    "/api/v1/models/load",
    "/api/v1/models/unload",
    "/api/v1/downloads",
    "endpoint_path",
    "https://private.example/native/models",
    "C:/Users/Private/weights.gguf",
    "/var/tmp/private.gguf",
    "secret-token-value-1234567890",
    "top secret message",
    "prompt should not leak",
    "response should not leak",
    "message should not leak",
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


def _assert_no_raw_endpoint_paths(*texts: str) -> None:
    forbidden_endpoint_paths = (
        "/v1/models",
        "/api/v1/models",
        "endpoint_path",
        "http://127.0.0.1:1234/v1/models",
        "http://127.0.0.1:1234/api/v1/models",
        "https://example.com:1234/v1/models",
        "https://example.com:1234/api/v1/models",
    )
    for text in texts:
        for endpoint_path in forbidden_endpoint_paths:
            assert endpoint_path not in text


def _build_payload(records: list[dict[str, object]], *, container_key: str = "data") -> bytes:
    return json.dumps({container_key: records}, ensure_ascii=False).encode("utf-8")


def _sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _success_payloads() -> dict[str, bytes]:
    compat = _build_payload(
        [
            {
                "id": "google/gemma-4-e2b",
                "context_length": 32768,
                "capabilities": {
                    "vision": True,
                    "tool_calling": True,
                    "provider_url": "https://private.example/native/models",
                    "message": "top secret message",
                },
            },
            {
                "id": "other/model",
                "capabilities": {"vision": False},
            },
        ]
    )
    native = _build_payload(
        [
            {
                "id": "google/gemma-4-e2b",
                "load_id": "google/gemma-4-e2b-native-load",
                "path": "C:/Users/Private/weights.gguf",
                "loaded_instances": [{"context_length": 32768}],
                "format": "gguf",
                "quantization": "Q4_K_M",
                "bits_per_weight": 4,
                "params": "4B",
                "size_bytes": 3383082464,
                "capabilities": {
                    "vision": True,
                    "max_batch_size": 8,
                    "secret_token": "secret-token-value-1234567890",
                    "response": "response should not leak",
                },
            }
        ],
        container_key="models",
    )
    return {
        "http://127.0.0.1:1234/v1/models": compat,
        "http://127.0.0.1:1234/api/v1/models": native,
    }


def _compat_only_payloads() -> dict[str, bytes]:
    compat = _build_payload(
        [
            {
                "id": "google/gemma-4-e2b",
                "capabilities": {"vision": True},
                "context_length": 8192,
            }
        ]
    )
    native = _build_payload(
        [
            {
                "id": "different/model",
                "load_id": "different/model-load",
                "context_length": 4096,
            }
        ]
    )
    return {
        "http://127.0.0.1:1234/v1/models": compat,
        "http://127.0.0.1:1234/api/v1/models": native,
    }


def test_probe_lmstudio_identity_uses_two_get_requests_and_no_payload() -> None:
    captured: list[tuple[str, str, bytes | None]] = []

    def fake_transport(request, timeout_s: float) -> bytes:
        captured.append((request.full_url, request.get_method(), request.data))
        assert timeout_s == 10.0
        return b"[]"

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234/api/v1",
        target_model_id="google/gemma-4-e2b",
        transport=fake_transport,
    )

    assert result.summary["status"] == "ok"
    assert result.summary["safe_record_count"] == 0
    assert isinstance(result.summary["safe_record_count"], int)
    assert captured == [
        ("http://127.0.0.1:1234/v1/models", "GET", None),
        ("http://127.0.0.1:1234/api/v1/models", "GET", None),
    ]
    serialized = json.dumps(captured)
    assert "/v1/chat/completions" not in serialized
    assert "/api/v1/models/load" not in serialized
    assert "/api/v1/models/unload" not in serialized


def test_probe_lmstudio_identity_marks_target_found_in_both_planes_without_raw_bodies() -> None:
    payloads = _success_payloads()

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["status"] == "ok"
    assert result.summary["resolution_status"] == "resolved"
    assert result.summary["raw_lookup_before_sanitization"] is True
    assert result.summary["target_model_id_safe"] is True
    assert result.summary["target_found_compat"] is True
    assert result.summary["target_found_native"] is True
    assert result.summary["compat_match_fields"] == ["id"]
    assert result.summary["native_match_fields"] == ["id"]
    assert result.summary["compat_model_id_verified"] is True
    assert result.summary["native_model_key_verified"] is True
    assert result.summary["target_hash_match"] is True
    assert result.summary["candidate_capability_keys"] == ["max_batch_size", "vision"]
    assert result.summary["native_load_id_resolved"] is True
    assert result.native_load_id == "google/gemma-4-e2b-native-load"
    assert result.summary["compat_record_count"] == 2
    assert result.summary["native_record_count"] == 1
    assert result.summary["safe_record_count"] == 3
    assert result.summary["compat_capability_keys"] == ["tool_calling", "vision"]
    assert result.summary["native_capability_keys"] == ["max_batch_size", "vision"]
    assert result.summary["compat_context_candidates"] == [32768]
    assert result.summary["native_context_candidates"] == [32768]
    assert result.summary["native_loaded_instances_count"] == 1
    assert result.summary["native_format"] == "gguf"
    assert result.summary["native_quantization"] == "Q4_K_M"
    assert result.summary["native_bits_per_weight"] == 4
    assert result.summary["native_params"] == "4B"
    assert result.summary["native_size_bytes"] == 3383082464

    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    assert "google/gemma-4-e2b" not in serialized
    assert "google/gemma-4-e2b-native-load" not in serialized
    assert "top secret message" not in serialized
    assert "secret-token-value-1234567890" not in serialized
    assert "C:/Users/Private/weights.gguf" not in serialized
    _assert_no_raw_endpoint_paths(serialized)


def test_probe_lmstudio_identity_marks_compat_only_target_without_native_hash_match() -> None:
    payloads = _compat_only_payloads()

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["status"] == "ok"
    assert result.summary["resolution_status"] == "native_missing"
    assert result.summary["raw_lookup_before_sanitization"] is True
    assert result.summary["target_found_compat"] is True
    assert result.summary["target_found_native"] is False
    assert result.summary["compat_match_fields"] == ["id"]
    assert result.summary["native_match_fields"] == []
    assert result.summary["compat_model_id_verified"] is True
    assert result.summary["native_model_key_verified"] is False
    assert result.summary["target_hash_match"] is False
    assert result.summary["native_load_id_resolved"] is False
    assert result.summary["native_loaded_instances_count"] is None
    assert result.summary["native_format"] is None
    assert result.summary["native_quantization"] is None
    assert result.summary["native_bits_per_weight"] is None
    assert result.summary["native_params"] is None
    assert result.summary["native_size_bytes"] is None


def test_probe_lmstudio_identity_rejects_unsafe_target_without_network_and_without_leak() -> None:
    captured: list[str] = []
    unsafe_target = "/var/tmp/private.gguf"

    def fake_transport(request, _timeout_s: float) -> bytes:
        captured.append(request.full_url)
        return b"[]"

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id=unsafe_target,
        transport=fake_transport,
    )

    assert result.summary["status"] == "invalid_target_model_id"
    assert result.summary["error_category"] == "validation"
    assert result.summary["resolution_status"] == "identity_error"
    assert result.summary["raw_lookup_before_sanitization"] is False
    assert result.summary["target_model_id_safe"] is False
    assert result.summary["target_found_compat"] is False
    assert result.summary["target_found_native"] is False
    assert result.summary["compat_model_id_verified"] is False
    assert result.summary["native_model_key_verified"] is False
    assert result.summary["safe_record_count"] == 0
    assert isinstance(result.summary["safe_record_count"], int)
    assert captured == []

    report = lmstudio_lab.render_identity_probe_report(run_id="unsafe", summary=result.summary)
    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True) + report
    assert unsafe_target not in serialized


def test_probe_lmstudio_identity_does_not_resolve_unsafe_native_load_id_or_leak_it() -> None:
    payloads = {
        "http://127.0.0.1:1234/v1/models": _build_payload(
            [{"id": "google/gemma-4-e2b", "context_length": 32768}]
        ),
        "http://127.0.0.1:1234/api/v1/models": _build_payload(
            [
                {
                    "id": "C:/Users/Private/weights.gguf",
                    "load_id": "C:/Users/Private/weights.gguf",
                    "model_id": "/var/tmp/private.gguf",
                    "model": "https://private.example/native/models",
                    "identifier": "/var/tmp/private.gguf",
                    "catalog_id": "https://private.example/native/models",
                    "path": "google/gemma-4-e2b",
                }
            ],
            container_key="models",
        ),
    }

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["status"] == "ok"
    assert result.summary["resolution_status"] == "unresolved"
    assert result.summary["target_found_native"] is True
    assert result.summary["native_match_fields"] == ["path"]
    assert result.summary["native_model_key_verified"] is False
    assert result.summary["native_load_id_resolved"] is False
    assert "native_load_id_hash" not in result.summary
    assert result.native_load_id is None

    report = lmstudio_lab.render_identity_probe_report(
        run_id="unsafe-load-id", summary=result.summary
    )
    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True) + report
    assert "C:/Users/Private/weights.gguf" not in serialized
    assert "/var/tmp/private.gguf" not in serialized


def test_probe_identity_cli_writes_safe_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    payloads = _success_payloads()

    def fake_probe(
        base_url: str,
        *,
        target_model_id: str,
        allow_remote: bool = False,
        timeout_s: float = 10.0,
    ) -> lmstudio_lab.IdentityProbeResult:
        return lmstudio_lab.probe_lmstudio_identity(
            base_url,
            target_model_id=target_model_id,
            allow_remote=allow_remote,
            timeout_s=timeout_s,
            transport=lambda request, _timeout_s: payloads[request.full_url],
        )

    monkeypatch.setattr(lmstudio_benchmark, "probe_lmstudio_identity", fake_probe)

    exit_code = lmstudio_benchmark.main(
        [
            "probe-identity",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "probe-identity-safe",
            "--model-id",
            "google/gemma-4-e2b",
        ]
    )

    assert exit_code == 0

    run_dir = tmp_path / "run_probe-identity-safe_identity_probe"
    assert run_dir.exists()
    assert {path.name for path in run_dir.iterdir() if path.is_file()} == {
        "environment.json",
        "identity_probe.json",
        "report.md",
    }

    environment_text = (run_dir / "environment.json").read_text(encoding="utf-8")
    probe_text = (run_dir / "identity_probe.json").read_text(encoding="utf-8")
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")

    for text in (environment_text, probe_text, report_text):
        _assert_safe_text(text, project_root=project_root)
    _assert_no_raw_endpoint_paths(environment_text, probe_text, report_text)

    environment_payload = json.loads(environment_text)
    assert environment_payload["command"] == "probe-identity"
    assert environment_payload["allow_remote"] is False
    assert environment_payload["run_id"] == "probe-identity-safe"
    assert "base_url" not in environment_payload
    assert "model_id" not in environment_payload

    probe_payload = json.loads(probe_text)
    assert probe_payload["status"] == "ok"
    assert probe_payload["resolution_status"] == "resolved"
    assert probe_payload["raw_lookup_before_sanitization"] is True
    assert probe_payload["target_found_compat"] is True
    assert probe_payload["target_found_native"] is True
    assert probe_payload["compat_model_id_verified"] is True
    assert probe_payload["native_model_key_verified"] is True
    assert probe_payload["target_hash_match"] is True
    assert "google/gemma-4-e2b-native-load" not in probe_text
    assert "google/gemma-4-e2b-native-load" not in report_text

    assert "# LM Studio Identity Probe Report" in report_text
    assert "compat_endpoint_kind: `compat_models`" in report_text
    assert "native_endpoint_kind: `native_models`" in report_text
    assert "resolution_status: `resolved`" in report_text
    assert "raw_lookup_before_sanitization: `True`" in report_text
    assert "chat/load/unload/download/generation endpoints: not used" in report_text


def test_probe_lmstudio_identity_rejects_remote_without_allow_remote() -> None:
    with pytest.raises(ValueError, match="allow_remote"):
        lmstudio_lab.probe_lmstudio_identity(
            "https://example.com:1234",
            target_model_id="google/gemma-4-e2b",
            transport=lambda _request, _timeout_s: b"[]",
        )


def test_probe_lmstudio_identity_allows_remote_with_flag() -> None:
    captured: list[str] = []

    def fake_transport(request, _timeout_s: float) -> bytes:
        captured.append(request.full_url)
        return b"[]"

    result = lmstudio_lab.probe_lmstudio_identity(
        "https://example.com:1234/api/v1",
        target_model_id="google/gemma-4-e2b",
        allow_remote=True,
        transport=fake_transport,
    )

    assert result.summary["status"] == "ok"
    assert result.summary["is_localhost"] is False
    assert captured == [
        "https://example.com:1234/v1/models",
        "https://example.com:1234/api/v1/models",
    ]


def test_probe_lmstudio_identity_maps_transport_decode_and_shape_errors_safely() -> None:
    compat_error_result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: (
            (_ for _ in ()).throw(urllib_error.URLError(TimeoutError("top secret message")))
            if request.full_url == "http://127.0.0.1:1234/v1/models"
            else b"[]"
        ),
    )
    assert compat_error_result.summary["status"] == "compat_transport_error"
    assert compat_error_result.summary["error_category"] == "timeout"
    compat_serialized = json.dumps(compat_error_result.summary, sort_keys=True)
    assert "127.0.0.1" not in compat_serialized
    assert "top secret message" not in compat_serialized

    decode_error_result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: (
            _build_payload([])
            if request.full_url == "http://127.0.0.1:1234/v1/models"
            else b"not-json prompt should not leak"
        ),
    )
    assert decode_error_result.summary["status"] == "native_decode_error"
    assert decode_error_result.summary["error_category"] == "json"
    decode_serialized = json.dumps(decode_error_result.summary, sort_keys=True)
    assert "127.0.0.1" not in decode_serialized
    assert "prompt should not leak" not in decode_serialized

    invalid_shape_result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda _request, _timeout_s: json.dumps(
            {"status": "message should not leak"}, ensure_ascii=False
        ).encode("utf-8"),
    )
    assert invalid_shape_result.summary["status"] == "multiple_errors"
    assert invalid_shape_result.summary["error_category"] == "multiple"
    invalid_shape_serialized = json.dumps(invalid_shape_result.summary, sort_keys=True)
    assert "message should not leak" not in invalid_shape_serialized


def test_probe_lmstudio_identity_collects_only_safe_capability_keys_and_context_values() -> None:
    compat = _build_payload(
        [
            {
                "id": "different/model",
                "context_length": 4096,
                "metadata": {"n_ctx": 8192},
                "capabilities": {
                    "vision": True,
                    "tool_calling": True,
                    "provider_url": "https://private.example/native/models",
                    "secret_token": "secret-token-value-1234567890",
                    "message": "message should not leak",
                },
            }
        ]
    )
    native = _build_payload(
        [
            {
                "id": "different/model",
                "loaded_instances": [{"context_length": 16384}],
                "capabilities": {
                    "vision": False,
                    "labels": ["local", "C:/Users/Private/weights.gguf"],
                    "path": "C:/Users/Private/weights.gguf",
                },
            }
        ]
    )
    payloads = {
        "http://127.0.0.1:1234/v1/models": compat,
        "http://127.0.0.1:1234/api/v1/models": native,
    }

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["compat_capability_keys"] == ["tool_calling", "vision"]
    assert result.summary["native_capability_keys"] == ["labels", "vision"]
    assert result.summary["candidate_capability_keys"] == ["labels", "vision"]
    assert result.summary["compat_context_candidates"] == [4096, 8192]
    assert result.summary["native_context_candidates"] == [16384]

    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    assert "provider_url" not in serialized
    assert "secret_token" not in serialized
    assert "message should not leak" not in serialized
    assert "C:/Users/Private/weights.gguf" not in serialized


def test_probe_lmstudio_identity_does_not_match_sanitized_placeholder_without_raw_candidate() -> (
    None
):
    payloads = {
        "http://127.0.0.1:1234/v1/models": _build_payload(
            [{"id": "different/model", "context_length": 4096}]
        ),
        "http://127.0.0.1:1234/api/v1/models": _build_payload(
            [
                {
                    "id": "/var/tmp/private.gguf",
                    "model": "C:/Users/Private/weights.gguf",
                    "path": "https://private.example/native/models",
                    "capabilities": {"vision": True},
                }
            ],
            container_key="models",
        ),
    }

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="model_0001",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["status"] == "ok"
    assert result.summary["resolution_status"] == "unresolved"
    assert result.summary["raw_lookup_before_sanitization"] is True
    assert result.summary["target_found_compat"] is False
    assert result.summary["target_found_native"] is False
    assert result.summary["compat_match_fields"] == []
    assert result.summary["native_match_fields"] == []
    assert result.summary["compat_model_id_verified"] is False
    assert result.summary["native_model_key_verified"] is False
    assert result.summary["native_load_id_resolved"] is False


def test_probe_lmstudio_identity_matches_raw_native_key_without_leaking_it() -> None:
    payloads = {
        "http://127.0.0.1:1234/v1/models": _build_payload(
            [{"id": "google/gemma-4-e2b", "context_length": 32768}]
        ),
        "http://127.0.0.1:1234/api/v1/models": _build_payload(
            [
                {
                    "key": "google/gemma-4-e2b",
                    "display_name": "top secret message",
                    "path": "C:/Users/Private/weights.gguf",
                    "capabilities": {"vision": True, "reasoning": True},
                }
            ],
            container_key="models",
        ),
    }

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["status"] == "ok"
    assert result.summary["resolution_status"] == "resolved"
    assert result.summary["target_found_native"] is True
    assert result.summary["native_match_fields"] == ["key"]
    assert result.summary["native_model_key_verified"] is True
    assert result.summary["native_load_id_resolved"] is True
    assert result.summary["native_load_id_hash"] == _sha256_text("google/gemma-4-e2b")
    assert result.summary["native_loaded_instances_count"] is None
    assert result.summary["native_format"] is None
    assert result.summary["native_quantization"] is None
    assert result.summary["native_bits_per_weight"] is None
    assert result.summary["native_params"] is None
    assert result.summary["native_size_bytes"] is None

    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    assert "google/gemma-4-e2b" not in serialized
    assert "C:/Users/Private/weights.gguf" not in serialized
    assert "top secret message" not in serialized


def test_probe_plane_resolves_raw_identity_before_sanitization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        identity_probe_module,
        "_extract_raw_candidate_pairs",
        lambda _payload: events.append("raw_candidates") or (("id", "google/gemma-4-e2b"),),
    )
    monkeypatch.setattr(
        identity_probe_module,
        "_collect_match_fields",
        lambda _pairs, *, target_model_id: (
            events.append(f"match:{target_model_id}") or True,
            True,
            ("id",),
        ),
    )
    monkeypatch.setattr(
        identity_probe_module,
        "_resolve_native_load_id",
        lambda _payload, *, target_model_id: (
            events.append(f"native_load_id:{target_model_id}") or target_model_id
        ),
    )
    monkeypatch.setattr(
        identity_probe_module,
        "_sanitize_external_mapping",
        lambda _payload: events.append("sanitize") or {"id": "model_0001"},
    )
    monkeypatch.setattr(
        identity_probe_module,
        "_collect_capability_keys",
        lambda _payload: events.append("capabilities") or ("vision",),
    )
    monkeypatch.setattr(
        identity_probe_module,
        "_collect_context_candidates",
        lambda _payload: events.append("context") or (32768,),
    )

    outcome = identity_probe_module._probe_plane(
        url="http://127.0.0.1:1234/api/v1/models",
        target_model_id="google/gemma-4-e2b",
        timeout_s=10.0,
        transport=lambda _request, _timeout_s: _build_payload(
            [{"id": "google/gemma-4-e2b"}],
            container_key="models",
        ),
        include_native_load_id=True,
    )

    assert outcome.raw_lookup_before_sanitization is True
    assert outcome.native_load_id_resolved is True
    assert events == [
        "raw_candidates",
        "match:google/gemma-4-e2b",
        "native_load_id:google/gemma-4-e2b",
        "sanitize",
        "capabilities",
        "context",
    ]


def test_probe_lmstudio_identity_projects_only_safe_native_capability_keys() -> None:
    payloads = {
        "http://127.0.0.1:1234/v1/models": _build_payload([]),
        "http://127.0.0.1:1234/api/v1/models": _build_payload(
            [
                {
                    "key": "different/model",
                    "capabilities": {
                        "vision": True,
                        "reasoning": True,
                        "trained_for_tool_use": True,
                        "secret_token": "secret-token-value-1234567890",
                        "provider_url": "https://private.example/native/models",
                        "message": "message should not leak",
                        "path": "C:/Users/Private/weights.gguf",
                    },
                }
            ],
            container_key="models",
        ),
    }

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["candidate_capability_keys"] == [
        "reasoning",
        "trained_for_tool_use",
        "vision",
    ]
    serialized = json.dumps(result.summary, ensure_ascii=False, sort_keys=True)
    assert "secret_token" not in serialized
    assert "provider_url" not in serialized
    assert "message" not in serialized
    assert "C:/Users/Private/weights.gguf" not in serialized


def test_probe_lmstudio_identity_reports_unresolved_state_without_native_resolution() -> None:
    payloads = {
        "http://127.0.0.1:1234/v1/models": _build_payload(
            [{"id": "different/model", "context_length": 4096}]
        ),
        "http://127.0.0.1:1234/api/v1/models": _build_payload(
            [{"key": "another/model", "capabilities": {"vision": True}}],
            container_key="models",
        ),
    }

    result = lmstudio_lab.probe_lmstudio_identity(
        "http://127.0.0.1:1234",
        target_model_id="google/gemma-4-e2b",
        transport=lambda request, _timeout_s: payloads[request.full_url],
    )

    assert result.summary["status"] == "ok"
    assert result.summary["resolution_status"] == "unresolved"
    assert result.summary["compat_model_id_verified"] is False
    assert result.summary["native_model_key_verified"] is False
    assert result.summary["native_load_id_resolved"] is False
    assert result.summary["compat_match_fields"] == []
    assert result.summary["native_match_fields"] == []


def test_identity_probe_exports_remain_importable() -> None:
    assert callable(lmstudio_lab.probe_lmstudio_identity)
    assert callable(lmstudio_lab.render_identity_probe_report)
    assert lmstudio_lab.IDENTITY_PROBE_RESULT_FILE_NAMES == (
        "environment.json",
        "identity_probe.json",
        "report.md",
    )
