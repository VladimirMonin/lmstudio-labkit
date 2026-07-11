from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
import shutil
import stat
from copy import deepcopy
from pathlib import Path

import pytest
import tools.lmstudio_lab.private_benchmark_overlay as overlay
import tools.lmstudio_lab.tokenizer_capture as tokenizer_capture
from cryptography.hazmat.primitives import serialization
from tools.lmstudio_lab.private_benchmark_overlay import (
    MODEL_IDS,
    OverlayPlan,
    build_overlay_plan,
    capture_plan_digest,
    capture_validated_execution_trace,
    compute_bound_scorecard,
    context_fits,
    freeze_overlay_plan,
    materialize_request_artifacts,
    record_private_output,
    scan_contamination,
    validate_execution_trace,
    validate_overlay_manifest,
    validate_resource_admission,
    validate_run_closure,
)
from tools.lmstudio_lab.private_benchmark_overlay import (
    validate_token_map as _validate_token_map,
)

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "experiments/lmstudio/private_benchmark_pack/v1"
OVERLAY = ROOT / "experiments/lmstudio/four_model_overlay/v1"
MANIFEST = OVERLAY / "four_model_overlay.json"
ZERO = "0" * 64


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.fixture(autouse=True)
def _isolated_owner_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "owner-sealed-authority"
    monkeypatch.setattr(overlay, "_AUTHORITY_STORE", store)
    monkeypatch.setattr(tokenizer_capture, "_AUTHORITY_STORE", store)


def _token_auth_paths(artifact_root: Path) -> tuple[Path, Path, Path, Path]:
    authority = overlay._AUTHORITY_STORE
    return (
        artifact_root.parent / "token-private",
        authority / "authority.key",
        authority / "authority.pub",
        authority / "ledgers" / "issuance.jsonl",
    )


def validate_token_map(token_map: dict, requests, artifact_root: Path) -> list[str]:
    return _validate_token_map(
        token_map,
        requests,
        artifact_root,
        consume=False,
    )


def _token_map(requests: tuple[dict, ...], artifact_root: Path, plan_sha256: str = ZERO) -> dict:
    private_root, key_path, public_path, ledger_path = _token_auth_paths(artifact_root)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private_root, 0o700)
    key = tokenizer_capture._authority_key(key_path, public_path)
    public_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    identity = hashlib.sha256(public_der).hexdigest()
    ledger_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ledger_path.parent, 0o700)
    generation_path = overlay._AUTHORITY_STORE / "generations" / f"{plan_sha256}.json"
    generation_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(generation_path.parent, 0o700)
    generation = {
        "schema_version": "lmstudio-sdk-capture-authority-generation-v1",
        "plan_sha256": plan_sha256,
        "authority_identity_sha256": identity,
        "authority_public_key_pem": public_path.read_text(),
        "authority_ledger_path": str(ledger_path.resolve()),
        "private_evidence_root": str(private_root.resolve()),
    }
    generation_path.write_text(json.dumps(generation), encoding="utf-8")
    os.chmod(generation_path, 0o600)
    captures = []
    for model_index, model_id in enumerate(MODEL_IDS):
        model_requests = [request for request in requests if request["model_id"] == model_id]
        rows = []
        private_rows = []
        for request in model_requests:
            data = (artifact_root / request["request_path"]).read_bytes()
            history = {"messages": [{"role": "user", "content": data.decode("utf-8")}]}
            formatted = b"template:" + data
            token_ids = [1, 2, 3]
            rows.append(
                {
                    "request_id": request["request_id"],
                    "model_id": model_id,
                    "request_sha256": hashlib.sha256(data).hexdigest(),
                    "byte_length": len(data),
                    "chat_sha256": _digest(history),
                    "formatted_prompt_sha256": hashlib.sha256(formatted).hexdigest(),
                    "token_ids_sha256": _digest(token_ids),
                    "exact_token_count": len(token_ids),
                    "output_token_reserve": request["max_tokens"],
                    "safety_margin": 256,
                    "effective_context": request["context_tier"],
                    "admitted": True,
                }
            )
            private_rows.append(
                {
                    "request_id": request["request_id"],
                    "model_id": model_id,
                    "request_sha256": request["request_sha256"],
                    "formatted_prompt_base64": base64.b64encode(formatted).decode(),
                    "token_ids": token_ids,
                }
            )
        config = {"context_length": 28672}
        instance_id = f"capture-instance-{model_index}"
        issuance = tokenizer_capture._issue_capture(
            ledger_path,
            {
                "authority_identity_sha256": identity,
                "plan_sha256": plan_sha256,
                "model_key": model_id,
                "instance_id": instance_id,
                "instance_config_sha256": _digest(config),
                "request_ids_sha256": _digest([row["request_id"] for row in rows]),
            },
        )
        capture_id = issuance["capture_id"]
        private = {
            "schema_version": "lmstudio-sdk-tokenizer-private-evidence-v1",
            "capture_id": capture_id,
            "nonce": issuance["nonce"],
            "issued_at": issuance["issued_at"],
            "session_id": issuance["session_id"],
            "authority_identity_sha256": identity,
            "plan_sha256": plan_sha256,
            "model_key": model_id,
            "instance_id": instance_id,
            "instance_config": config,
            "rows": private_rows,
        }
        private_payload = json.dumps(
            private, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        private_path = private_root / "captures" / f"{capture_id}.json"
        private_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(private_path.parent, 0o700)
        private_path.write_bytes(private_payload + b"\n")
        os.chmod(private_path, 0o600)
        capture = {
            "schema_version": "lmstudio-sdk-tokenizer-capture-v2",
            "authority": {
                "package": "lmstudio",
                "version": "1.5.0",
                "identity_sha256": identity,
                "signature_algorithm": "ed25519-v1",
            },
            "capture_id": capture_id,
            "nonce": issuance["nonce"],
            "issued_at": issuance["issued_at"],
            "session_id": issuance["session_id"],
            "model_key": model_id,
            "instance_id": instance_id,
            "instance_config": config,
            "instance_config_sha256": _digest(config),
            "plan_sha256": plan_sha256,
            "preflight": {
                "loaded_count": 0,
                "instance_bindings_sha256": ZERO,
                "response_sha256": ZERO,
            },
            "post_unload": {
                "loaded_count": 0,
                "instance_bindings_sha256": ZERO,
                "response_sha256": ZERO,
            },
            "private_evidence_relative_path": f"captures/{capture_id}.json",
            "private_evidence_sha256": hashlib.sha256(private_payload).hexdigest(),
            "rows": rows,
        }
        capture["evidence_sha256"] = _digest(capture)
        capture["authority_signature"] = base64.b64encode(
            key.sign(
                json.dumps(
                    capture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            )
        ).decode()
        captures.append(capture)
    return {"schema_version": "lmstudio-sdk-tokenizer-capture-set-v1", "captures": captures}


def _plan(tmp_path: Path) -> OverlayPlan:
    artifact_root = tmp_path / "requests"
    requests = materialize_request_artifacts(MANIFEST, PACK, artifact_root)
    grouped: dict[str, list[dict]] = {}
    for request in requests:
        grouped.setdefault(request["cell_id"], []).append(request)
    cells = tuple(
        {
            "cell_id": cell_id,
            "request_count": len(rows),
            "call_ids": [row["call_id"] for row in rows],
            "cell_sha256": _digest(rows),
        }
        for cell_id, rows in grouped.items()
    )
    return OverlayPlan(ZERO, ZERO, cells, requests)


def _call(
    request: dict, instance: str, load_id: str, start: float = 10.0, end: float = 20.0
) -> dict:
    return {
        "event": "call",
        "call_id": request["call_id"],
        "instance_id": instance,
        "load_event_id": load_id,
        "endpoint": "/api/v1/chat",
        "backend_version": "test",
        "model_id": request["model_id"],
        "model_revision": request["model_revision"],
        "parameters_sha256": ZERO,
        "request_sha256": request["request_sha256"],
        "started_at": start,
        "ended_at": end,
        "terminal_state": "completed",
        "worker_slot": request.get("worker_slot"),
    }


def _load(kind: str, request: dict, instance: str, load_id: str) -> dict:
    row = {
        "event": kind,
        "load_event_id": load_id,
        "instance_id": instance,
        "model_id": request["model_id"],
        "model_revision": request["model_revision"],
    }
    if kind == "unload":
        row["unload_event_id"] = f"unload-{load_id}"
    return row


def _snapshot(call_id: str | None, stage: str, observed_at: float) -> dict:
    return {
        "event": "loaded_snapshot",
        "call_id": call_id,
        "stage": stage,
        "loaded_count": 0,
        "observed_at": observed_at,
        "response_sha256": ZERO,
    }


def _events(plan: OverlayPlan) -> list[dict]:
    events = [_snapshot(None, "global_preflight", 0)]
    session_load_ids: dict[str, str] = {}
    parallel_initialized: set[str] = set()
    for request in plan.requests:
        if request["phase"] == "one_shot":
            instance = f"cold-{request['call_id']}"
            load_id = f"load-{request['call_id']}"
            events += [
                _snapshot(request["call_id"], "preflight", 1),
                _load("load", request, instance, load_id),
                _call(request, instance, load_id),
                _load("unload", request, instance, load_id),
                _snapshot(request["call_id"], "post_unload", 21),
            ]
            continue
        if request["phase"] == "loaded_session":
            instance = f"session-{request['model_id']}"
            load_id = session_load_ids.setdefault(
                request["model_id"], f"load-session-{request['model_id']}"
            )
            if request["ordinal"] == 0:
                events.append(_load("load", request, instance, load_id))
            events.append(_call(request, instance, load_id))
            if request["ordinal"] == 6:
                events.append(_load("unload", request, instance, load_id))
            continue
        instance = f"parallel-{request['cell_id']}"
        load_id = f"load-{request['cell_id']}"
        if request["cell_id"] not in parallel_initialized:
            instances = [instance]
            events += [
                {
                    "event": "resource_admission",
                    "admission_event_id": f"admit-{request['cell_id']}",
                    "cell_id": request["cell_id"],
                    "bytes_per_instance": 10,
                    "available_bytes": 100,
                    "observed_at": 1,
                    "snapshot_sha256": ZERO,
                    "admitted": True,
                    "instance_ids": instances,
                },
                {
                    "event": "start_barrier",
                    "barrier_event_id": f"barrier-{request['cell_id']}",
                    "cell_id": request["cell_id"],
                    "participants": request["parallelism"],
                    "observed_at": 2,
                    "participant_bindings": [
                        {"worker_slot": slot, "instance_id": instance}
                        for slot in range(request["parallelism"])
                    ],
                },
            ]
            parallel_initialized.add(request["cell_id"])
        if request["worker_slot"] == 0:
            events.append(_load("load", request, instance, load_id))
        events.append(
            _call(
                request, instance, load_id, 10 + request["worker_slot"], 20 + request["worker_slot"]
            )
        )
        if request["worker_slot"] == request["parallelism"] - 1:
            events.append(_load("unload", request, instance, load_id))
    events.append(_snapshot(None, "global_final", 99))
    return events


def _provenance(request: dict) -> dict:
    row = _call(request, "instance", "load-instance")
    row.pop("event")
    return row


def _small_plan(plan: OverlayPlan, count: int = 1) -> OverlayPlan:
    requests = plan.requests[:count]
    cell_ids = {request["cell_id"] for request in requests}
    cells = tuple(cell for cell in plan.cells if cell["cell_id"] in cell_ids)
    return OverlayPlan(plan.manifest_sha256, plan.pack_tree_sha256, cells, requests)


def _validated_trace(tmp_path: Path):
    plan = _plan(tmp_path)
    return capture_validated_execution_trace(plan, _events(plan))


def _record_small(plan: OverlayPlan, tmp_path: Path) -> tuple[Path, Path, Path]:
    private = tmp_path / "private"
    ledger = tmp_path / "ledger.jsonl"
    scores = tmp_path / "scores"
    scores.mkdir()
    trace = _validated_trace(tmp_path / "trace")
    for request in plan.requests:
        row = record_private_output(
            private,
            request=request,
            raw_output="answer",
            sanitized_evidence_path=ledger,
            pack_root=PACK,
            validated_trace=trace,
        )
        (scores / f"{request['call_id']}.scorecard.json").write_text(
            json.dumps(row["scorecard"]), encoding="utf-8"
        )

    return private, ledger, scores


def test_manifest_and_materialized_plan_close_exactly(tmp_path: Path) -> None:
    assert validate_overlay_manifest(json.loads(MANIFEST.read_text()), PACK) == []
    plan = _plan(tmp_path)
    assert len(plan.cells) == 64
    assert len(plan.requests) == 80
    assert all(sum(r["model_id"] == model for r in plan.requests) == 20 for model in MODEL_IDS)
    p4_cells = [cell for cell in plan.cells if len(cell["call_ids"]) == 4]
    assert len(p4_cells) == 4
    assert all(r["model_revision"] is None for r in plan.requests)
    request = json.loads((tmp_path / "requests" / plan.requests[0]["request_path"]).read_text())
    assert request["model"] == MODEL_IDS[0]
    assert request["max_output_tokens"] == plan.requests[0]["max_tokens"] == 512
    assert {(row["task_axis"], row["max_tokens"]) for row in plan.requests} == {
        ("short_semantic_normalization", 512),
        ("long_whisper_normalization", 2048),
        ("structural_retention", 512),
    }
    expected_axes = {
        (row["view_label"], row["mode"], row["task_axis"], row["max_tokens"])
        for row in plan.requests
        if row["model_id"] == MODEL_IDS[0]
    }
    assert all(
        {
            (row["view_label"], row["mode"], row["task_axis"], row["max_tokens"])
            for row in plan.requests
            if row["model_id"] == model
        }
        == expected_axes
        for model in MODEL_IDS
    )
    content = request["input"][0]["content"]
    assert "task_prompt" in content
    assert "sanitized_input" in content
    assert "output_schema" in content
    assert request["benchmark_binding"]["view_label"] == plan.requests[0]["view_label"]

    artifact_root = tmp_path / "blocked-requests"
    frozen = freeze_overlay_plan(MANIFEST, PACK, artifact_root)
    requests = frozen.requests
    frozen_path = tmp_path / "frozen-plan.json"
    overlay.write_overlay_plan(frozen, frozen_path)
    plan_sha256 = capture_plan_digest(json.loads(frozen_path.read_text()))
    assert len(requests) == 80
    assert capture_plan_digest(json.loads(frozen_path.read_text())) == plan_sha256


def test_context_fit_accepts_exact_boundary_and_rejects_overflow() -> None:
    assert context_fits(6144, 2048, 8192)
    assert not context_fits(6145, 2048, 8192)


def test_build_consumes_exact_frozen_plan_bundle(tmp_path: Path) -> None:
    artifact_root = tmp_path / "requests"
    plan = freeze_overlay_plan(MANIFEST, PACK, artifact_root)
    frozen_path = tmp_path / "plan.json"
    overlay.write_overlay_plan(plan, frozen_path)
    plan_sha256 = capture_plan_digest(json.loads(frozen_path.read_text()))
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        json.dumps(_token_map(plan.requests, artifact_root, plan_sha256)), encoding="utf-8"
    )
    built = build_overlay_plan(
        MANIFEST,
        token_path,
        PACK,
        artifact_root,
        frozen_path,
    )
    assert len(built.requests) == 80


def test_r01_tokenizer_verification_is_mandatory_and_authenticated(tmp_path: Path) -> None:
    artifact_root = tmp_path / "requests"
    requests = materialize_request_artifacts(MANIFEST, PACK, artifact_root)
    token_map = _token_map(requests, artifact_root)
    errors = validate_token_map(token_map, requests, artifact_root)
    assert errors == []
    assert not hasattr(overlay, "TRUSTED_TOKENIZERS")
    assert not hasattr(overlay, "_load_production_tokenizer")


def test_capture_plan_digest_is_reproducible_and_rejects_stale_plan(tmp_path: Path) -> None:
    artifact_root = tmp_path / "requests"
    plan = freeze_overlay_plan(MANIFEST, PACK, artifact_root)
    plan_path = tmp_path / "frozen-plan.json"
    overlay.write_overlay_plan(plan, plan_path)
    document = json.loads(plan_path.read_text())
    expected = capture_plan_digest(document)
    assert tokenizer_capture.capture_plan_digest(document) == expected
    assert document["planned_cells"] == 64
    assert document["planned_model_calls"] == 80

    stale = deepcopy(document)
    stale["requests"][0]["request_sha256"] = ZERO
    assert capture_plan_digest(stale) != expected
    with pytest.raises(ValueError, match="plan digest mismatch"):
        tokenizer_capture._validate_inputs(
            MODEL_IDS[0], "fresh-instance", {"context_length": 28672}, stale, expected
        )


def test_authenticated_capture_set_is_single_use_for_same_plan(tmp_path: Path) -> None:
    artifact_root = tmp_path / "requests"
    requests = materialize_request_artifacts(MANIFEST, PACK, artifact_root)
    token_map = _token_map(requests, artifact_root)
    assert _validate_token_map(token_map, requests, artifact_root) == []
    assert any(
        "replay" in error for error in _validate_token_map(token_map, requests, artifact_root)
    )


def test_caller_signed_bundle_from_alternate_authority_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted_root = tmp_path / "trusted" / "requests"
    trusted_requests = materialize_request_artifacts(MANIFEST, PACK, trusted_root)
    trusted = _token_map(trusted_requests, trusted_root)
    trusted_store = overlay._AUTHORITY_STORE
    alternate_root = tmp_path / "alternate" / "requests"
    alternate_requests = materialize_request_artifacts(MANIFEST, PACK, alternate_root)
    alternate_store = tmp_path / "caller-controlled-authority"
    monkeypatch.setattr(overlay, "_AUTHORITY_STORE", alternate_store)
    monkeypatch.setattr(tokenizer_capture, "_AUTHORITY_STORE", alternate_store)
    synthetic = _token_map(alternate_requests, alternate_root)
    monkeypatch.setattr(overlay, "_AUTHORITY_STORE", trusted_store)
    monkeypatch.setattr(tokenizer_capture, "_AUTHORITY_STORE", trusted_store)
    assert trusted["captures"][0]["authority"] != synthetic["captures"][0]["authority"]
    monkeypatch.setenv("LMSTUDIO_CAPTURE_AUTHORITY_ROOT", str(alternate_store))
    monkeypatch.setenv(
        "LMSTUDIO_CAPTURE_AUTHORITY_PUBLIC_KEY", str(alternate_store / "authority.pub")
    )
    errors = _validate_token_map(synthetic, alternate_requests, alternate_root, consume=False)
    assert any("authentication failed" in error for error in errors)
    assert _validate_token_map(trusted, trusted_requests, trusted_root, consume=False) == []

    for api in (_validate_token_map, build_overlay_plan):
        parameters = inspect.signature(api).parameters
        assert "private_evidence_root" not in parameters
        assert "authority_public_key_path" not in parameters
        assert "authority_ledger_path" not in parameters
        assert "expected_authority_identity_sha256" not in parameters
        assert "verifier" not in parameters


def test_token_map_rejects_unsigned_forged_replayed_and_private_evidence_attacks(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "requests"
    requests = materialize_request_artifacts(MANIFEST, PACK, artifact_root)
    token_map = _token_map(requests, artifact_root)
    private_root, _key_path, _public_path, _ledger_path = _token_auth_paths(artifact_root)

    unsigned = deepcopy(token_map)
    unsigned["captures"][0].pop("authority_signature")
    assert any(
        "schema is not closed" in error
        for error in validate_token_map(unsigned, requests, artifact_root)
    )

    validation_parameters = inspect.signature(_validate_token_map).parameters
    assert "authority_public_key_path" not in validation_parameters
    assert "authority_ledger_path" not in validation_parameters
    assert "expected_authority_identity_sha256" not in validation_parameters
    assert any(
        "generation is unavailable" in error
        for error in _validate_token_map(
            deepcopy(token_map)
            | {
                "captures": [
                    capture | {"plan_sha256": "f" * 64} for capture in token_map["captures"]
                ]
            },
            requests,
            artifact_root,
            consume=False,
        )
    )

    private_path = private_root / token_map["captures"][0]["private_evidence_relative_path"]
    saved = private_path.read_bytes()
    private_path.unlink()
    assert any(
        "private evidence missing" in error
        for error in validate_token_map(token_map, requests, artifact_root)
    )
    private_path.write_bytes(saved + b" ")
    os.chmod(private_path, 0o600)
    assert any(
        "private evidence digest mismatch" in error
        for error in validate_token_map(token_map, requests, artifact_root)
    )

    substituted = deepcopy(token_map)
    substituted["captures"][0]["instance_id"] = "substituted-instance"
    assert any(
        "authentication failed" in error or "capture identity binding" in error
        for error in validate_token_map(substituted, requests, artifact_root)
    )


def test_token_map_rejects_duplicates_missing_and_count_forgery(tmp_path: Path) -> None:
    artifact_root = tmp_path / "requests"
    requests = materialize_request_artifacts(MANIFEST, PACK, artifact_root)
    token_map = _token_map(requests, artifact_root)
    rows = token_map["captures"][0]["rows"]
    rows[0].update(request_sha256=ZERO, byte_length=999999, exact_token_count=0, admitted=False)
    rows[1]["request_id"] = rows[0]["request_id"]
    rows.pop()
    errors = validate_token_map(token_map, requests, artifact_root)
    assert any("digest/length" in error for error in errors)
    assert any("duplicate" in error for error in errors)
    assert any("missing" in error for error in errors)
    assert any("context admission" in error for error in errors)


def test_r01_rejects_alias_and_coordinated_artifact_substitution(tmp_path: Path) -> None:
    artifact_root = tmp_path / "requests"
    request = deepcopy(materialize_request_artifacts(MANIFEST, PACK, artifact_root)[0])
    request["model_revision"] = "attacker-revision"
    fake_record = {
        "status": "available",
        "model_revision": "attacker-revision",
        "model_artifact_path": str(tmp_path / "model.gguf"),
        "model_artifact_sha256": hashlib.sha256(b"fake-model").hexdigest(),
        "tokenizer_artifact_path": str(tmp_path / "tokenizer.json"),
        "tokenizer_artifact_sha256": hashlib.sha256(b"fake-tokenizer").hexdigest(),
        "tokenizer_version": "attacker-version",
        "tokenize": lambda _path, payload: list(payload),
    }
    Path(fake_record["model_artifact_path"]).write_bytes(b"fake-model")
    Path(fake_record["tokenizer_artifact_path"]).write_bytes(b"fake-tokenizer")
    token_map = _token_map((request,), artifact_root)
    token_map["captures"][0]["rows"][0]["token_ids_sha256"] = ZERO
    errors = validate_token_map(token_map, (request,), artifact_root)
    assert any("evidence digest mismatch" in error for error in errors)
    with pytest.raises(TypeError):
        validate_token_map(  # type: ignore[call-arg]
            token_map,
            (request,),
            artifact_root,
            trusted_tokenizers={request["model_id"]: fake_record},
        )

    request["model_id"] = "google/gemma-4-e2b-alias"
    assert any(
        "chat/model binding mismatch" in error
        for error in validate_token_map(token_map, (request,), artifact_root)
    )


def test_r02_trace_requires_ordered_unique_cold_cycles(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    events = _events(plan)
    assert validate_execution_trace(plan, events) == []
    forged = deepcopy(events)
    cleanup = next(e for e in forged if e.get("stage") == "post_unload")
    forged.remove(cleanup)
    forged.insert(1, cleanup)
    assert any("cold lifecycle" in error for error in validate_execution_trace(plan, forged))


def test_r03_parallel_bijection_barrier_and_overlap(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    events = _events(plan)
    p4 = next(r for r in plan.requests if r["parallelism"] == 4)
    cell_calls = [
        e
        for e in events
        if e.get("event") == "call"
        and e.get("call_id")
        in {r["call_id"] for r in plan.requests if r["cell_id"] == p4["cell_id"]}
    ]
    assert len(cell_calls) == 4
    cell_calls[1]["worker_slot"] = 0
    cell_calls[2]["started_at"] = 30
    barrier = next(
        e for e in events if e.get("cell_id") == p4["cell_id"] and e.get("event") == "start_barrier"
    )
    events.remove(barrier)
    events.append(barrier)
    errors = validate_execution_trace(plan, events)
    assert any("start barrier" in error for error in errors)
    assert any("bijection/overlap" in error for error in errors)


def test_resource_admission_proves_one_loaded_instance(tmp_path: Path) -> None:
    request = next(r for r in _plan(tmp_path).requests if r["parallelism"] == 4)
    admission = {
        "bytes_per_instance": 10,
        "available_bytes": 40,
        "observed_at": 1,
        "snapshot_sha256": ZERO,
        "admitted": True,
        "instance_ids": ["one-instance"],
    }
    assert validate_resource_admission(request, admission) == []
    admission["instance_ids"] = ["first", "second"]
    assert "one loaded" in validate_resource_admission(request, admission)[0]


def test_r04_recorder_computes_contamination_and_requires_provenance(tmp_path: Path) -> None:
    request = _plan(tmp_path).requests[0] | {"expected_absent_sentinels": ["LEAK"]}
    with pytest.raises(ValueError, match="authenticated validated trace handle"):
        record_private_output(
            tmp_path / "private",
            request=request,
            raw_output="LEAK",
            sanitized_evidence_path=tmp_path / "ledger",
            pack_root=PACK,
            validated_trace={},
        )
    row = record_private_output(
        tmp_path / "private",
        request=request,
        raw_output="LEAK",
        sanitized_evidence_path=tmp_path / "ledger",
        pack_root=PACK,
        validated_trace=_validated_trace(tmp_path / "valid-trace"),
    )
    assert row["contamination"] == scan_contamination("LEAK", request, {})
    assert row["contamination"]["passed"] is False


def test_r05_trace_rejects_duplicate_events_and_revision_swap(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    events = _events(plan)
    call = next(e for e in events if e.get("event") == "call")
    events.append(deepcopy(call))
    errors = validate_execution_trace(plan, events)
    assert any("duplicate or missing call" in error for error in errors)
    events = _events(plan)
    next(e for e in events if e.get("event") == "call")["model_revision"] = "forged"
    errors = validate_execution_trace(plan, events)
    assert any("provenance incomplete or mismatched" in error for error in errors)


def test_r04_r05_sealed_trace_rejects_mutation_replay_and_caller_pairs(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "plan")
    events = _events(plan)
    trace = capture_validated_execution_trace(plan, events)
    request = plan.requests[0]
    call = next(
        event
        for event in events
        if event.get("event") == "call" and event.get("call_id") == request["call_id"]
    )
    original_instance = call["instance_id"]
    call["instance_id"] = "coordinated-substitute-after-capture"
    row = record_private_output(
        tmp_path / "private",
        request=request,
        raw_output="answer",
        sanitized_evidence_path=tmp_path / "ledger",
        pack_root=PACK,
        validated_trace=trace,
    )
    assert row["call_provenance"]["instance_id"] == original_instance
    assert row["validated_trace_sha256"] == trace.trace_sha256
    with pytest.raises(ValueError, match="already consumed"):
        record_private_output(
            tmp_path / "private-replay",
            request=request,
            raw_output="answer",
            sanitized_evidence_path=tmp_path / "ledger-replay",
            pack_root=PACK,
            validated_trace=trace,
        )
    with pytest.raises(ValueError, match="authenticated validated trace handle"):
        record_private_output(
            tmp_path / "private-forged",
            request=request,
            raw_output="answer",
            sanitized_evidence_path=tmp_path / "ledger-forged",
            pack_root=PACK,
            validated_trace={"provenance": deepcopy(call)},  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("relative_path", "field"),
    [
        ("prompts/normalization-v1.txt", "prompt_sha256"),
        ("schemas/normalization_output_v1.schema.json", "output_schema_sha256"),
        ("views/M01/semantic_gold.json", "target_sha256"),
        ("views/M01/rubric.json", "rubric_sha256"),
    ],
)
def test_r06_scorer_recomputes_all_bound_artifacts(
    tmp_path: Path, relative_path: str, field: str
) -> None:
    plan = _plan(tmp_path)
    request = next(r for r in plan.requests if r["view_label"] == "M01")
    copied_pack = tmp_path / "pack"
    shutil.copytree(PACK, copied_pack)
    (copied_pack / relative_path).write_bytes((copied_pack / relative_path).read_bytes() + b"\n")
    with pytest.raises(ValueError, match=field):
        compute_bound_scorecard("{}", request, copied_pack)


def test_r06_scorer_rejects_view_task_family_swap(tmp_path: Path) -> None:
    request = deepcopy(_plan(tmp_path).requests[0])
    request["scorer_binding"]["task_family"] = "structural_context_retention"
    with pytest.raises(ValueError, match="view/task family"):
        compute_bound_scorecard("{}", request, PACK)


def test_r07_closure_rejects_swaps_extras_malformed_and_caller_evidence(tmp_path: Path) -> None:
    plan = _small_plan(_plan(tmp_path), 2)
    private, ledger, scores = _record_small(plan, tmp_path)
    assert validate_run_closure(plan, private, ledger, scores, PACK) == []
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    rows[0]["request_id"], rows[1]["request_id"] = rows[1]["request_id"], rows[0]["request_id"]
    rows[0]["extra"] = "forged"
    rows[1]["contamination"]["passed"] = False
    rows[1]["scorecard"] = {"accepted": True}
    ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    errors = validate_run_closure(plan, private, ledger, scores, PACK)
    assert any("schema is not closed" in error for error in errors)
    assert any("plan-to-ledger" in error for error in errors)
    assert any("contamination evidence" in error for error in errors)
    assert any("scorecard binding" in error for error in errors)


def test_private_record_is_immutable_and_outside_repository(tmp_path: Path) -> None:
    request = _plan(tmp_path).requests[0]
    private = tmp_path / "private"
    kwargs = {
        "request": request,
        "raw_output": "answer",
        "sanitized_evidence_path": tmp_path / "ledger",
        "pack_root": PACK,
    }
    row = record_private_output(
        private, validated_trace=_validated_trace(tmp_path / "trace"), **kwargs
    )
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert stat.S_IMODE((private / row["raw_relative_path"]).stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        record_private_output(
            private, validated_trace=_validated_trace(tmp_path / "trace-2"), **kwargs
        )
    with pytest.raises(ValueError, match="outside the repository"):
        record_private_output(
            ROOT / "raw", validated_trace=_validated_trace(tmp_path / "trace-3"), **kwargs
        )


def test_coordinated_forgery_regressions(tmp_path: Path) -> None:
    artifact_root = tmp_path / "requests"
    requests = list(materialize_request_artifacts(MANIFEST, PACK, artifact_root))
    token_map = _token_map(tuple(requests), artifact_root)
    token_map["captures"][0]["rows"][0].update(output_token_reserve=0, safety_margin=0)
    assert any(
        "context admission" in error
        for error in validate_token_map(token_map, requests, artifact_root)
    )

    token_map = _token_map(tuple(requests), artifact_root)
    requests[0]["model_revision"] = "coordinated-forgery"
    token_map["captures"][0]["model_key"] = "google/gemma-4-e2b-alias"
    assert any(
        "aliases are forbidden" in error
        for error in validate_token_map(token_map, requests, artifact_root)
    )

    plan = _plan(tmp_path / "trace")
    events = _events(plan)
    unload = next(e for e in events if e.get("event") == "unload")
    events.append(deepcopy(unload) | {"unload_event_id": "duplicate-binding"})
    assert any("one-to-one" in error for error in validate_execution_trace(plan, events))

    events = _events(plan)
    events.insert(-1, _snapshot("unknown-call", "post_unload", 98))
    assert any("exactly and uniquely" in error for error in validate_execution_trace(plan, events))

    events = _events(plan)
    barrier = next(
        e for e in events if e.get("event") == "start_barrier" and e["participants"] == 4
    )
    barrier["participant_bindings"] = barrier["participant_bindings"][:-1]
    barrier["observed_at"] = 99
    assert any("start barrier" in error for error in validate_execution_trace(plan, events))

    request = plan.requests[0]
    with pytest.raises(ValueError, match="authenticated validated trace handle"):
        record_private_output(
            tmp_path / "private-forged",
            request=request,
            raw_output="answer",
            sanitized_evidence_path=tmp_path / "ledger-forged",
            pack_root=PACK,
            validated_trace={"caller": "forged"},
        )


@pytest.mark.parametrize("payload", ["[]", "null", "not-json"])
def test_r07_malformed_scorecard_is_deterministic_rejection(tmp_path: Path, payload: str) -> None:
    plan = _small_plan(_plan(tmp_path))
    private, ledger, scores = _record_small(plan, tmp_path)
    (scores / f"{plan.requests[0]['call_id']}.scorecard.json").write_text(payload)
    errors = validate_run_closure(plan, private, ledger, scores, PACK)
    assert any("scorecard binding mismatch" in error for error in errors)


def test_sdk_capture_binds_exact_instance_template_tokens_and_zero_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path / "materialized")
    artifact_root = tmp_path / "requests"
    materialize_request_artifacts(MANIFEST, PACK, artifact_root)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan.as_dict()), encoding="utf-8")
    config = {"context_length": 28672}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    model_key = MODEL_IDS[0]
    instance_id = "tokenizer-canary-e2b-unique"
    lifecycle: list[str] = []

    class Info:
        identifier = instance_id
        instance_reference = "opaque-instance-reference"

        def __init__(self):
            self.model_key = model_key

    class Handle:
        identifier = instance_id

        def get_info(self):
            return Info()

        def get_context_length(self):
            return 28672

        def apply_prompt_template(self, chat):
            lifecycle.append("template")
            return "formatted"

        def tokenize(self, formatted):
            assert formatted == "formatted"
            lifecycle.append("tokenize")
            return [1, 2, 3]

        def unload(self):
            lifecycle.append("unload")

    handle = Handle()

    class Llm:
        def load_new_instance(self, key, identifier, *, ttl, config):
            assert (key, identifier, ttl) == (model_key, instance_id, None)
            lifecycle.append("load")
            return handle

        def unload(self, identifier):
            assert identifier == instance_id
            lifecycle.append("unload")

    class Client:
        llm = Llm()

        def __init__(self, api_host):
            assert api_host == "localhost:1234"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_loaded_models(self, namespace):
            assert namespace == "llm"
            return [handle]

    zero = {"models": [{"key": model_key, "loaded_instances": []}]}
    loaded = {
        "models": [
            {
                "key": model_key,
                "loaded_instances": [{"id": instance_id, "config": config}],
            }
        ]
    }
    snapshots = iter((zero, loaded, zero))
    monkeypatch.setattr(tokenizer_capture.lms, "Client", Client)
    monkeypatch.setattr(tokenizer_capture, "_rest_models", lambda: next(snapshots))
    plan_sha256 = tokenizer_capture.capture_plan_digest(plan.as_dict())
    generation = tokenizer_capture.create_capture_authority_generation(
        plan_path, tmp_path / "private-tokenizer"
    )
    evidence = tokenizer_capture.capture_runtime_tokenizer(
        model_key=model_key,
        instance_id=instance_id,
        load_config_path=config_path,
        plan_path=plan_path,
        artifact_root=artifact_root,
        expected_plan_sha256=plan_sha256,
    )
    assert lifecycle[0] == "load"
    assert lifecycle[-1] == "unload"
    assert len(evidence["rows"]) == 20
    assert all(row["exact_token_count"] == 3 for row in evidence["rows"])
    assert evidence["preflight"]["loaded_count"] == 0
    assert evidence["post_unload"]["loaded_count"] == 0
    assert isinstance(evidence["capture_id"], int)
    assert len(evidence["nonce"]) == 64
    assert len(evidence["session_id"]) == 32
    assert evidence["authority"]["signature_algorithm"] == "ed25519-v1"
    assert stat.S_IMODE(Path(generation["authority_ledger_path"]).stat().st_mode) == 0o600
    private_path = tmp_path / "private-tokenizer" / evidence["private_evidence_relative_path"]
    private = json.loads(private_path.read_text())
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(private_path.parent.stat().st_mode) == 0o700
    assert base64.b64decode(private["rows"][0]["formatted_prompt_base64"]) == b"formatted"
    assert private["rows"][0]["token_ids"] == [1, 2, 3]


@pytest.mark.parametrize(
    ("model_key", "instance_id", "plan_digest", "message"),
    [
        ("google/gemma-4-e2b-alias", "unique", ZERO, "exact canonical"),
        (MODEL_IDS[0], MODEL_IDS[0], ZERO, "unique and distinct"),
        (MODEL_IDS[0], "unique", "f" * 64, "plan digest mismatch"),
    ],
)
def test_sdk_capture_rejects_alias_instance_reuse_and_plan_substitution(
    tmp_path: Path, model_key: str, instance_id: str, plan_digest: str, message: str
) -> None:
    plan = _plan(tmp_path / "materialized")
    config = {"context_length": 28672}
    with pytest.raises(ValueError, match=message):
        tokenizer_capture._validate_inputs(
            model_key,
            instance_id,
            config,
            plan.as_dict(),
            plan_digest,
        )
