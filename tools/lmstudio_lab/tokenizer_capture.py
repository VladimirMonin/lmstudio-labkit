"""Isolated LM Studio SDK authority for exact runtime tokenizer evidence.

This module is intentionally executable as a subprocess.  It accepts immutable plan
and request artifacts plus one canonical model key, one unique instance identifier,
and one frozen load configuration.  It does not accept tokenizer implementations,
trust records, model aliases, or precomputed token evidence.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.request
from datetime import UTC, datetime
from fcntl import LOCK_EX, LOCK_UN, flock
from importlib.metadata import version
from pathlib import Path
from typing import Any

import lmstudio as lms
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MODEL_KEYS = (
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
)
SAFETY_MARGIN = 256
_AUTHORITY_STORE = Path.home() / ".local/share/lmstudio-labkit/tokenizer-authority"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: Any) -> str:
    return _sha(_canonical(value))


def _authority_key(path: Path, public_key_path: Path) -> Ed25519PrivateKey:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise PermissionError("tokenizer authority key must be owner-only")
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("tokenizer authority key is not Ed25519")
    else:
        key = Ed25519PrivateKey.generate()
        payload = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
    public_payload = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if public_key_path.exists():
        if public_key_path.read_bytes() != public_payload:
            raise ValueError("pinned tokenizer authority public key mismatch")
    else:
        public_key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(public_key_path.parent, 0o700)
        fd = os.open(public_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(public_payload)
    return key


def create_capture_authority_generation(
    plan_path: Path, private_evidence_root: Path
) -> dict[str, Any]:
    """Create one explicit owner-only authority generation for a frozen plan."""
    plan_sha256 = capture_plan_digest(_read_object(plan_path))
    store = _AUTHORITY_STORE
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(store, 0o700)
    key_path = store / "authority.key"
    public_path = store / "authority.pub"
    ledger_path = store / "ledgers" / f"{plan_sha256}.jsonl"
    private_root = private_evidence_root.resolve()
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private_root, 0o700)
    key = _authority_key(key_path, public_path)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    generation = {
        "schema_version": "lmstudio-sdk-capture-authority-generation-v1",
        "plan_sha256": plan_sha256,
        "authority_identity_sha256": _sha(public_der),
        "authority_public_key_pem": public_pem.decode("ascii"),
        "authority_ledger_path": str(ledger_path),
        "private_evidence_root": str(private_root),
    }
    generation_path = store / "generations" / f"{plan_sha256}.json"
    generation_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(generation_path.parent, 0o700)
    payload = _canonical(generation) + b"\n"
    if generation_path.exists():
        if generation_path.read_bytes() != payload:
            raise FileExistsError("capture authority generation already exists; rotate explicitly")
    else:
        fd = os.open(generation_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
    return generation


def _capture_authority_generation(plan_sha256: str) -> dict[str, Any]:
    path = _AUTHORITY_STORE / "generations" / f"{plan_sha256}.json"
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("owner-sealed capture authority generation is unavailable")
    generation = _read_object(path)
    if generation.get("plan_sha256") != plan_sha256:
        raise ValueError("capture authority generation plan binding mismatch")
    return generation


def _issue_capture(ledger_path: Path, binding: dict[str, Any]) -> dict[str, Any]:
    """Allocate a monotonic, nonce-bearing capture identity in an owner-only ledger."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ledger_path.parent, 0o700)
    fd = os.open(ledger_path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "r+b", closefd=True) as stream:
        flock(stream.fileno(), LOCK_EX)
        stream.seek(0)
        records = [json.loads(line) for line in stream if line.strip()]
        capture_id = max((row.get("capture_id", 0) for row in records), default=0) + 1
        issuance = {
            "event": "issued",
            "capture_id": capture_id,
            "nonce": secrets.token_hex(32),
            "issued_at": datetime.now(UTC).isoformat(),
            "session_id": secrets.token_hex(16),
            **binding,
        }
        stream.seek(0, os.SEEK_END)
        stream.write(_canonical(issuance) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
        flock(stream.fileno(), LOCK_UN)
    return issuance


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def capture_plan_digest(plan: dict[str, Any]) -> str:
    """Bind capture to immutable plan identity and every planned request."""
    requests = plan.get("requests")
    if not isinstance(requests, list):
        raise ValueError("plan requests must be a list")
    bindings = [
        {
            "request_id": row.get("request_id"),
            "model_id": row.get("model_id"),
            "request_path": row.get("request_path"),
            "request_sha256": row.get("request_sha256"),
            "context_tier": row.get("context_tier"),
            "task_axis": row.get("task_axis"),
            "max_tokens": row.get("max_tokens"),
        }
        for row in requests
    ]
    return _digest(
        {
            "schema_version": plan.get("schema_version"),
            "manifest_sha256": plan.get("manifest_sha256"),
            "pack_tree_sha256": plan.get("pack_tree_sha256"),
            "requests": bindings,
        }
    )


def _api_base() -> str:
    host = os.environ.get("LMSTUDIO_API_HOST", "localhost:1234")
    if "://" not in host:
        host = f"http://{host}"
    return host.rstrip("/")


def _headers() -> dict[str, str]:
    token = os.environ.get("LM_API_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _rest_models() -> dict[str, Any]:
    request = urllib.request.Request(f"{_api_base()}/api/v1/models", headers=_headers())
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read()
    value = json.loads(body)
    if not isinstance(value, dict) or not isinstance(value.get("models"), list):
        raise ValueError("/api/v1/models returned an invalid document")
    return value


def _loaded_instances(document: dict[str, Any]) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for model in document["models"]:
        if not isinstance(model, dict):
            raise ValueError("/api/v1/models model entry is not an object")
        model_key = model.get("key")
        for instance in model.get("loaded_instances", []):
            if not isinstance(instance, dict):
                raise ValueError("/api/v1/models loaded instance is not an object")
            instances.append({"model_key": model_key, **instance})
    return instances


def _snapshot(document: dict[str, Any]) -> dict[str, Any]:
    instances = _loaded_instances(document)
    return {
        "loaded_count": len(instances),
        "instance_bindings_sha256": _digest(instances),
        "response_sha256": _digest(document),
    }


def _load_config(raw: dict[str, Any]) -> lms.LlmLoadModelConfig:
    allowed = {
        "context_length",
        "eval_batch_size",
        "flash_attention",
        "offload_kv_cache_to_gpu",
        "num_experts",
        "keep_model_in_memory",
        "try_mmap",
    }
    if set(raw) - allowed:
        raise ValueError("load config contains unsupported fields")
    if not isinstance(raw.get("context_length"), int) or isinstance(raw["context_length"], bool):
        raise ValueError("load config requires integer context_length")
    return lms.LlmLoadModelConfig(**raw)


def _validate_inputs(
    model_key: str,
    instance_id: str,
    load_config: dict[str, Any],
    plan: dict[str, Any],
    expected_plan_sha256: str,
) -> list[dict[str, Any]]:
    if model_key not in MODEL_KEYS:
        raise ValueError("model key must be an exact canonical key; aliases are forbidden")
    if not instance_id or instance_id == model_key or "/" in instance_id:
        raise ValueError("instance identifier must be unique and distinct from the model key")
    actual_plan_sha256 = capture_plan_digest(plan)
    if expected_plan_sha256 != actual_plan_sha256:
        raise ValueError("plan digest mismatch")
    requests = plan.get("requests")
    if not isinstance(requests, list):
        raise ValueError("plan requests must be a list")
    selected = [row for row in requests if row.get("model_id") == model_key]
    if not selected or len(selected) != len({row.get("request_id") for row in selected}):
        raise ValueError("plan has missing or duplicate model request bindings")
    if any(row.get("model_id") not in MODEL_KEYS for row in requests):
        raise ValueError("plan contains a model alias")
    context_length = load_config.get("context_length")
    if context_length != max(row.get("context_tier", 0) for row in selected):
        raise ValueError("load config context_length must equal the model's maximum planned tier")
    return selected


def capture_runtime_tokenizer(
    *,
    model_key: str,
    instance_id: str,
    load_config_path: Path,
    plan_path: Path,
    artifact_root: Path,
    expected_plan_sha256: str,
) -> dict[str, Any]:
    """Perform one strict zero→load→capture→unload→zero SDK lifecycle."""
    load_config = _read_object(load_config_path)
    plan = _read_object(plan_path)
    requests = _validate_inputs(model_key, instance_id, load_config, plan, expected_plan_sha256)
    generation = _capture_authority_generation(expected_plan_sha256)
    authority_key_path = _AUTHORITY_STORE / "authority.key"
    authority_public_key_path = _AUTHORITY_STORE / "authority.pub"
    authority_ledger_path = Path(generation["authority_ledger_path"])
    private_evidence_root = Path(generation["private_evidence_root"])
    sdk_config = _load_config(load_config)
    pre_document = _rest_models()
    pre_snapshot = _snapshot(pre_document)
    if pre_snapshot["loaded_count"] != 0:
        raise RuntimeError("capture requires a zero-loaded global preflight")

    rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    loaded = None
    capture_error: BaseException | None = None
    api_host = os.environ.get("LMSTUDIO_API_HOST", "localhost:1234")
    try:
        with lms.Client(api_host=api_host) as client:
            loaded = client.llm.load_new_instance(
                model_key, instance_id, ttl=None, config=sdk_config
            )
            sdk_loaded = list(client.list_loaded_models(namespace="llm"))
            rest_loaded = _rest_models()
            instances = _loaded_instances(rest_loaded)
            matches = [
                row
                for row in instances
                if row.get("model_key") == model_key and row.get("id") == instance_id
            ]
            if len(sdk_loaded) != 1 or sdk_loaded[0].identifier != instance_id:
                raise RuntimeError("SDK loaded-model inventory does not uniquely bind the instance")
            if len(instances) != 1 or len(matches) != 1:
                raise RuntimeError(
                    "REST loaded-model inventory does not uniquely bind the instance"
                )
            observed_config = matches[0].get("config")
            if not isinstance(observed_config, dict) or any(
                observed_config.get(field) != value for field, value in load_config.items()
            ):
                raise RuntimeError("REST loaded instance config does not match frozen load config")
            info = loaded.get_info()
            info_model_key = getattr(info, "model_key", None)
            info_instance = getattr(info, "identifier", None)
            info_reference = getattr(info, "instance_reference", None)
            if info_instance != instance_id or info_model_key != model_key or not info_reference:
                raise RuntimeError(
                    "SDK model info does not bind exact model key and loaded instance"
                )
            context_length = loaded.get_context_length()
            if context_length != load_config["context_length"]:
                raise RuntimeError("SDK context length does not match frozen load config")

            for request in requests:
                request_path = artifact_root / request["request_path"]
                request_bytes = request_path.read_bytes()
                if _sha(request_bytes) != request["request_sha256"]:
                    raise ValueError(f"request artifact digest mismatch: {request['request_id']}")
                history = {
                    "messages": [
                        {
                            "role": "user",
                            "content": request_bytes.decode("utf-8"),
                        }
                    ]
                }
                chat = lms.Chat.from_history(history)
                formatted = loaded.apply_prompt_template(chat)
                token_ids = list(loaded.tokenize(formatted))
                if not token_ids or any(type(token) is not int for token in token_ids):
                    raise RuntimeError("SDK tokenize returned invalid token IDs")
                count = len(token_ids)
                rows.append(
                    {
                        "request_id": request["request_id"],
                        "model_id": model_key,
                        "request_sha256": request["request_sha256"],
                        "byte_length": len(request_bytes),
                        "chat_sha256": _digest(history),
                        "formatted_prompt_sha256": _sha(formatted.encode()),
                        "token_ids_sha256": _digest(token_ids),
                        "exact_token_count": count,
                        "output_token_reserve": request["max_tokens"],
                        "safety_margin": SAFETY_MARGIN,
                        "effective_context": request["context_tier"],
                        "admitted": count + request["max_tokens"] <= request["context_tier"],
                    }
                )
                private_rows.append(
                    {
                        "request_id": request["request_id"],
                        "model_id": model_key,
                        "request_sha256": request["request_sha256"],
                        "formatted_prompt_base64": base64.b64encode(
                            formatted.encode("utf-8")
                        ).decode("ascii"),
                        "token_ids": token_ids,
                    }
                )
    except BaseException as exc:
        capture_error = exc
    finally:
        if loaded is not None:
            try:
                # The first client context may already be closing because capture failed.
                # Use a fresh SDK session so cleanup is not coupled to that websocket.
                with lms.Client(api_host=api_host) as cleanup_client:
                    cleanup_client.llm.unload(instance_id)
            except BaseException as unload_exc:
                if capture_error is None:
                    capture_error = unload_exc
        post_document = _rest_models()
        post_snapshot = _snapshot(post_document)
        if post_snapshot["loaded_count"] != 0 and capture_error is None:
            capture_error = RuntimeError("capture final read-back is not zero-loaded")
    if capture_error is not None:
        raise capture_error

    key = _authority_key(authority_key_path, authority_public_key_path)
    public_der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    authority = {
        "package": "lmstudio",
        "version": version("lmstudio"),
        "identity_sha256": _sha(public_der),
        "signature_algorithm": "ed25519-v1",
    }
    issuance = _issue_capture(
        authority_ledger_path,
        {
            "authority_identity_sha256": authority["identity_sha256"],
            "plan_sha256": expected_plan_sha256,
            "model_key": model_key,
            "instance_id": instance_id,
            "instance_config_sha256": _digest(load_config),
            "request_ids_sha256": _digest([row["request_id"] for row in rows]),
        },
    )
    capture_id = issuance["capture_id"]
    private_document = {
        "schema_version": "lmstudio-sdk-tokenizer-private-evidence-v1",
        "capture_id": capture_id,
        "nonce": issuance["nonce"],
        "issued_at": issuance["issued_at"],
        "session_id": issuance["session_id"],
        "authority_identity_sha256": authority["identity_sha256"],
        "plan_sha256": expected_plan_sha256,
        "model_key": model_key,
        "instance_id": instance_id,
        "instance_config": load_config,
        "rows": private_rows,
    }
    private_payload = _canonical(private_document)
    private_root = private_evidence_root.resolve()
    repo = Path(__file__).resolve().parents[2]
    if private_root == repo or repo in private_root.parents:
        raise ValueError("private tokenizer evidence must be written outside the repository")
    private_path = private_root / "captures" / f"{capture_id}.json"
    private_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private_root, 0o700)
    os.chmod(private_path.parent, 0o700)
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(private_payload + b"\n")

    evidence = {
        "schema_version": "lmstudio-sdk-tokenizer-capture-v2",
        "authority": authority,
        "capture_id": capture_id,
        "nonce": issuance["nonce"],
        "issued_at": issuance["issued_at"],
        "session_id": issuance["session_id"],
        "model_key": model_key,
        "instance_id": instance_id,
        "instance_config": load_config,
        "instance_config_sha256": _digest(load_config),
        "plan_sha256": expected_plan_sha256,
        "preflight": pre_snapshot,
        "post_unload": post_snapshot,
        "private_evidence_relative_path": f"captures/{capture_id}.json",
        "private_evidence_sha256": _sha(private_payload),
        "rows": rows,
    }
    evidence["evidence_sha256"] = _digest(evidence)
    evidence["authority_signature"] = base64.b64encode(key.sign(_canonical(evidence))).decode(
        "ascii"
    )
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-key", required=True, choices=MODEL_KEYS)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--load-config", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--plan-sha256", required=True)

    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output.resolve()
    repo = Path(__file__).resolve().parents[2]
    if output == repo or repo in output.parents:
        raise ValueError("tokenizer capture evidence must be written outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output.parent, 0o700)
    evidence = capture_runtime_tokenizer(
        model_key=args.model_key,
        instance_id=args.instance_id,
        load_config_path=args.load_config,
        plan_path=args.plan,
        artifact_root=args.artifact_root,
        expected_plan_sha256=args.plan_sha256,
    )
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
