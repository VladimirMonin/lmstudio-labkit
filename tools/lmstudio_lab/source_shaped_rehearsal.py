"""Prepare and execute the phase-1 long-transcript representation matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import lmstudio as lms

MODEL_IDS = (
    "google/gemma-4-e2b",
    "google/gemma-4-e4b",
    "google/gemma-4-12b-qat",
    "google/gemma-4-26b-a4b-qat",
    "qwen/qwen3.5-4b",
    "qwen/qwen3.5-9b",
)
REPRESENTATIONS = ("plain", "timestamped_paragraphs", "json_blocks")
CHUNK_LABELS = ("early", "middle", "late")
CURRENT_CHUNK_BEGIN = "<<<BEGIN_CURRENT_CHUNK>>>"
CURRENT_CHUNK_END = "<<<END_CURRENT_CHUNK>>>"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _validate_source(source: dict[str, Any]) -> tuple[list[dict[str, Any]], list[list[int]]]:
    if source.get("schema_version") != "sanitized-whisper-transcript-v1":
        raise ValueError("unsupported source schema")
    if source.get("owner_verified") is not True or source.get("sanitized") is not True:
        raise ValueError("source must be owner-verified and sanitized")
    blocks = source.get("blocks")
    ranges = source.get("representative_ranges")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("source blocks must be a non-empty list")
    if not isinstance(ranges, list) or len(ranges) != 3:
        raise ValueError("exactly three representative ranges are required")
    expected_ids = list(range(len(blocks)))
    if [block.get("id") for block in blocks] != expected_ids:
        raise ValueError("block ids must be stable, neutral, contiguous integers")
    for block in blocks:
        if set(block) != {"id", "start", "end", "text"}:
            raise ValueError("blocks must contain only id/start/end/text")
        if not isinstance(block["text"], str) or not block["text"].strip():
            raise ValueError("block text must be non-empty")
        if not isinstance(block["start"], (int, float)) or not isinstance(
            block["end"], (int, float)
        ):
            raise ValueError("block timestamps must be numeric")
        if block["start"] < 0 or block["end"] <= block["start"]:
            raise ValueError("block timestamps must be increasing within each block")
    if any(left["end"] > right["start"] for left, right in zip(blocks, blocks[1:], strict=False)):
        raise ValueError("source blocks overlap")
    normalized: list[list[int]] = []
    previous_end = -1
    for value in ranges:
        if not isinstance(value, list) or len(value) != 2 or not all(type(x) is int for x in value):
            raise ValueError("representative ranges must be [start, end] integer pairs")
        start, end = value
        if start < 0 or start >= end or end > len(blocks) or start < previous_end:
            raise ValueError("representative ranges must be ordered, valid, and non-overlapping")
        normalized.append([start, end])
        previous_end = end
    return blocks, normalized


def _plain(blocks: list[dict[str, Any]]) -> str:
    return " ".join(block["text"].strip() for block in blocks)


def _timestamp(value: int | float) -> str:
    millis = round(float(value) * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _represent(blocks: list[dict[str, Any]], representation: str) -> str:
    if representation == "plain":
        return _plain(blocks)
    if representation == "timestamped_paragraphs":
        return "\n\n".join(
            f"[{_timestamp(block['start'])} --> {_timestamp(block['end'])}]\n{block['text'].strip()}"
            for block in blocks
        )
    if representation == "json_blocks":
        return json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))
    raise ValueError(f"unknown representation: {representation}")


def _request_text(
    instruction: str, representation: str, context: str, chunk: dict[str, Any]
) -> str:
    return (
        f"{instruction.rstrip()}\n\n"
        f"Input representation: {representation}.\n"
        f"Process only representative chunk {chunk['number']} ({chunk['label']}).\n"
        f"Its source block range is [{chunk['range'][0]}, {chunk['range'][1]}).\n\n"
        f"FULL TRANSCRIPT REFERENCE CONTEXT (REFERENCE ONLY; NEVER OUTPUT ADJACENT TEXT)\n"
        f"{context}\n\n"
        f"CURRENT CHUNK (the only text permitted in the answer)\n"
        f"{CURRENT_CHUNK_BEGIN}\n{chunk['text']}\n{CURRENT_CHUNK_END}"
    )


def build_plan(manifest_path: str | Path, source_path: str | Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    source_path = Path(source_path)
    manifest = _read_object(manifest_path)
    source = _read_object(source_path)
    blocks, ranges = _validate_source(source)
    if manifest.get("schema_version") != "long-transcript-representation-v1":
        raise ValueError("unsupported manifest schema")
    if tuple(manifest.get("models", [])) != MODEL_IDS:
        raise ValueError("manifest must contain the exact six-model inventory")
    if tuple(manifest.get("representations", [])) != REPRESENTATIONS:
        raise ValueError("manifest must contain the exact three representations")
    if manifest.get("reasoning") not in {"off", "none"} or manifest.get("retries") != 0:
        raise ValueError("phase 1 requires reasoning off/none and zero retries")
    instruction = (manifest_path.parent / manifest["instruction_path"]).read_text(encoding="utf-8")
    source_digest = _sha(_canonical(source))
    chunks = []
    for number, (label, block_range) in enumerate(zip(CHUNK_LABELS, ranges, strict=True), start=1):
        start, end = block_range
        text = _plain(blocks[start:end])
        chunks.append(
            {
                "number": number,
                "label": label,
                "range": block_range,
                "text": text,
                "text_sha256": _sha(text.encode()),
            }
        )
    contexts = {name: _represent(blocks, name) for name in REPRESENTATIONS}
    requests = []
    ordinal = 0
    for model in MODEL_IDS:
        for representation in REPRESENTATIONS:
            for chunk in chunks:
                ordinal += 1
                request_text = _request_text(
                    instruction, representation, contexts[representation], chunk
                )
                requests.append(
                    {
                        "request_id": f"c{ordinal:02d}",
                        "model": model,
                        "representation": representation,
                        "chunk_number": chunk["number"],
                        "chunk_label": chunk["label"],
                        "chunk_range": chunk["range"],
                        "chunk_text": chunk["text"],
                        "chunk_text_sha256": chunk["text_sha256"],
                        "instruction": instruction,
                        "instruction_sha256": _sha(instruction.encode()),
                        "full_context": contexts[representation],
                        "full_context_sha256": _sha(contexts[representation].encode()),
                        "request_text": request_text,
                        "request_text_sha256": _sha(request_text.encode()),
                        "output_format": "plain_text",
                        "reasoning": manifest["reasoning"],
                        "temperature": 0,
                        "retries": 0,
                    }
                )
    if len(requests) != 54:
        raise ValueError("matrix must contain exactly 54 calls")
    return {
        "schema_version": "long-transcript-representation-plan-v1",
        "live": False,
        "source_sha256": source_digest,
        "source_block_count": len(blocks),
        "manifest_sha256": _sha(manifest_path.read_bytes()),
        "planned_calls": 54,
        "calls_per_model": 9,
        "execution_order": "models_strictly_serial; calls_serial_within_model",
        "token_fit": "exact_sdk_tokenize_each_formatted_request_then_fail_closed",
        "output_budget": "ceil(exact_current_chunk_tokens * 1.5) + 256; no fixed cap",
        "lifecycle": "zero_loaded -> load_one -> 9 calls -> unload -> zero_loaded",
        "requests": requests,
    }


def write_plan(
    manifest_path: str | Path, source_path: str | Path, output: str | Path
) -> dict[str, Any]:
    plan = build_plan(manifest_path, source_path)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical(plan) + b"\n"
    if output.exists() and output.read_bytes() != payload:
        raise FileExistsError(f"immutable plan differs: {output}")
    output.write_bytes(payload)
    return plan


def build_confirmation_plan(
    manifest_path: str | Path,
    source_path: str | Path,
    selector_path: str | Path,
) -> dict[str, Any]:
    """Materialize the frozen three-call 12B confirmation from the full matrix."""
    selector_path = Path(selector_path)
    selector = _read_object(selector_path)
    if selector.get("schema_version") != "long-transcript-confirmation-selector-v1":
        raise ValueError("unsupported confirmation selector schema")
    if selector.get("model") != "google/gemma-4-12b-qat":
        raise ValueError("confirmation is frozen to Gemma 4 12B QAT")
    if selector.get("reasoning") != "off" or selector.get("retries") != 0:
        raise ValueError("confirmation requires reasoning off and zero retries")
    if selector.get("request_timeout_seconds") != 900:
        raise ValueError("confirmation timeout must be exactly 900 seconds")
    expected = [
        {"representation": "plain", "chunk_label": "early"},
        {"representation": "timestamped_paragraphs", "chunk_label": "late"},
        {"representation": "json_blocks", "chunk_label": "middle"},
    ]
    if selector.get("calls") != expected:
        raise ValueError("confirmation lanes must be plain/early, timestamps/late, JSON/middle")
    matrix = build_plan(manifest_path, source_path)
    rows = [
        row
        for lane in expected
        for row in matrix["requests"]
        if row["model"] == selector["model"]
        and row["representation"] == lane["representation"]
        and row["chunk_label"] == lane["chunk_label"]
    ]
    if len(rows) != 3:
        raise ValueError("confirmation selector did not resolve exactly three calls")
    return {
        "schema_version": "long-transcript-confirmation-plan-v1",
        "live": False,
        "source_sha256": matrix["source_sha256"],
        "manifest_sha256": matrix["manifest_sha256"],
        "selector_sha256": _sha(selector_path.read_bytes()),
        "planned_calls": 3,
        "calls_per_model": 3,
        "execution_order": "calls_serial_within_single_model",
        "request_timeout_seconds": 900,
        "reasoning": "off",
        "retries": 0,
        "output_budget": matrix["output_budget"],
        "requests": rows,
    }


def write_confirmation_plan(
    manifest_path: str | Path,
    source_path: str | Path,
    selector_path: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    plan = build_confirmation_plan(manifest_path, source_path, selector_path)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical(plan) + b"\n"
    if output.exists() and output.read_bytes() != payload:
        raise FileExistsError(f"immutable plan differs: {output}")
    output.write_bytes(payload)
    return plan


def _outside_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[2]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("private artifacts must stay outside the repository")
    return resolved


def initialize_private_rubric(template: str | Path, output: str | Path) -> None:
    output = _outside_repo(Path(output))
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output.parent, 0o700)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(Path(template).read_bytes())


def derive_output_budget(model: lms.LLM, chunk_text: str) -> int:
    chunk_tokens = len(list(model.tokenize(chunk_text)))
    if chunk_tokens <= 0:
        raise RuntimeError("SDK returned no tokens for the current chunk")
    return math.ceil(chunk_tokens * 1.5) + 256


def validate_token_fit(model: lms.LLM, request_text: str, output_budget: int) -> int:
    chat = lms.Chat.from_history({"messages": [{"role": "user", "content": request_text}]})
    formatted = model.apply_prompt_template(chat)
    input_tokens = len(list(model.tokenize(formatted)))
    if input_tokens <= 0:
        raise RuntimeError("SDK returned no tokens for the formatted request")
    if input_tokens + output_budget > model.get_context_length():
        raise RuntimeError("formatted request plus derived output budget exceeds context")
    return input_tokens


def _loaded_inventory() -> dict[str, dict[str, Any]]:
    """Return unique loaded instances from the REST inventory.

    LM Studio may expose one loaded instance under multiple model records (for
    example, a canonical key and a local alias). Lifecycle gates care about
    physical instances, so identity is the instance ``id`` rather than the
    number of containing records.
    """
    host = os.environ.get("LMSTUDIO_API_HOST", "localhost:1234")
    if "://" not in host:
        host = f"http://{host}"
    request = urllib.request.Request(f"{host.rstrip('/')}/api/v1/models")
    with urllib.request.urlopen(request, timeout=10) as response:
        document = json.loads(response.read())
    inventory: dict[str, dict[str, Any]] = {}
    for model in document.get("models", []):
        for instance in model.get("loaded_instances", []):
            instance_id = instance.get("id")
            if not isinstance(instance_id, str) or not instance_id:
                raise RuntimeError("loaded instance has no stable id")
            inventory.setdefault(instance_id, instance)
    return inventory


def _loaded_total() -> int:
    return len(_loaded_inventory())


def _loaded_instance(model_id: str, instance_id: str) -> dict[str, Any] | None:
    """Find an instance in the REST inventory, including remote-device instances."""
    host = os.environ.get("LMSTUDIO_API_HOST", "localhost:1234")
    if "://" not in host:
        host = f"http://{host}"
    request = urllib.request.Request(f"{host.rstrip('/')}/api/v1/models")
    with urllib.request.urlopen(request, timeout=10) as response:
        document = json.loads(response.read())
    for model in document.get("models", []):
        if model.get("key") != model_id:
            continue
        for instance in model.get("loaded_instances", []):
            if instance.get("id") == instance_id:
                return instance
    return None


def _model_load_config(model_id: str, load_config: dict[str, Any]) -> dict[str, Any]:
    """Return only load options supported by the selected model family/runtime."""
    if model_id.startswith("qwen/"):
        return {"context_length": load_config["context_length"]}
    return dict(load_config)


def _load_or_attach(
    client: lms.Client,
    model_id: str,
    instance_id: str,
    load_config: dict[str, Any],
) -> lms.LLM:
    """Load a model, or attach when a remote load materialized despite an SDK error."""
    try:
        return client.llm.load_new_instance(
            model_id,
            instance_id,
            ttl=None,
            config=lms.LlmLoadModelConfig(**_model_load_config(model_id, load_config)),
        )
    except Exception:
        if _loaded_instance(model_id, instance_id) is None:
            raise
        return client.llm.model(instance_id, ttl=None)


def _request_parameters(reasoning: str) -> dict[str, Any]:
    if reasoning not in {"off", "none"}:
        raise ValueError("reasoning must be off/none")
    return {"temperature": 0, "reasoning": {"effort": "none"}}


def _generate(
    instance_id: str,
    request_text: str,
    output_budget: int,
    *,
    request_timeout: int = 3600,
) -> dict[str, Any]:
    """Call the same OpenAI-compatible transport shape used by the host application."""
    host = os.environ.get("LMSTUDIO_API_HOST", "localhost:1234")
    if "://" not in host:
        host = f"http://{host}"
    payload = {
        "model": instance_id,
        "messages": [{"role": "user", "content": request_text}],
        "max_tokens": output_budget,
        "temperature": 0,
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        f"{host.rstrip('/')}/v1/chat/completions",
        data=_canonical(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            value = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"LM Studio chat completion failed with HTTP {exc.code}: {body}"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError("generation response is not an object")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise RuntimeError("chat completion did not return exactly one choice")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise RuntimeError("chat completion has no final message text")
    value["_lab_final_text"] = message["content"]
    return value


def admit_plan(
    plan_path: str | Path,
    load_config_path: str | Path,
    evidence_path: str | Path,
) -> dict[str, Any]:
    """Tokenize all frozen requests with each live model without generating output."""
    plan_path = Path(plan_path)
    plan = _read_object(plan_path)
    if plan.get("planned_calls") != 54 or plan.get("live") is not False:
        raise ValueError("admission requires an offline-prepared 54-call plan")
    evidence_path = _outside_repo(Path(evidence_path))
    evidence_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(evidence_path.parent, 0o700)
    load_config = _read_object(Path(load_config_path))
    if _loaded_total() != 0:
        raise RuntimeError("admission requires loaded_total=0 at global preflight")
    api_host = os.environ.get("LMSTUDIO_API_HOST", "localhost:1234")
    request_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    for model_index, model_id in enumerate(MODEL_IDS, start=1):
        rows = [row for row in plan["requests"] if row["model"] == model_id]
        if len(rows) != 9:
            raise ValueError("each model must have exactly nine admission requests")
        instance_id = f"long-repr-admission-{model_index:02d}"
        loaded = None
        try:
            with lms.Client(api_host=api_host) as client:
                loaded = _load_or_attach(client, model_id, instance_id, load_config)
                instance = _loaded_instance(model_id, instance_id)
                if _loaded_total() != 1 or instance is None:
                    raise RuntimeError(
                        "model load did not materialize exactly one expected instance"
                    )
                context_length = loaded.get_context_length()
                counts = []
                for row in rows:
                    budget = derive_output_budget(loaded, row["chunk_text"])
                    input_tokens = validate_token_fit(loaded, row["request_text"], budget)
                    counts.append(input_tokens)
                    request_rows.append(
                        {
                            "request_id": row["request_id"],
                            "model": model_id,
                            "request_text_sha256": row["request_text_sha256"],
                            "input_tokens": input_tokens,
                            "max_output_tokens": budget,
                            "context_length": context_length,
                            "context_fit": True,
                            "request_parameters": _request_parameters(row["reasoning"]),
                        }
                    )
                model_rows.append(
                    {
                        "model": model_id,
                        "instance_id": instance_id,
                        "loaded_config": instance.get("config", {}),
                        "request_count": len(counts),
                        "min_input_tokens": min(counts),
                        "max_input_tokens": max(counts),
                        "context_length": context_length,
                    }
                )
        finally:
            if loaded is not None or _loaded_instance(model_id, instance_id) is not None:
                with lms.Client(api_host=api_host) as cleanup_client:
                    cleanup_client.llm.unload(instance_id)
            if _loaded_total() != 0:
                raise RuntimeError("post-model admission unload is not loaded_total=0")
    evidence = {
        "schema_version": "long-transcript-token-admission-v1",
        "generation_performed": False,
        "plan_sha256": _sha(plan_path.read_bytes()),
        "models": model_rows,
        "requests": request_rows,
        "admitted_requests": len(request_rows),
        "global_loaded_total_final": _loaded_total(),
    }
    if len(request_rows) != 54 or evidence["global_loaded_total_final"] != 0:
        raise RuntimeError("six-model admission did not close cleanly")
    payload = _canonical(evidence) + b"\n"
    fd = os.open(evidence_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
    return evidence


def run_plan(
    plan_path: str | Path,
    load_config_path: str | Path,
    private_root: str | Path,
    *,
    max_calls: int | None = None,
    model_ids: tuple[str, ...] | None = None,
    request_ids: tuple[str, ...] | None = None,
    request_timeout: int = 3600,
) -> int:
    """Execute the frozen matrix serially, optionally as a bounded canary."""
    if max_calls is not None and max_calls <= 0:
        raise ValueError("max_calls must be positive")
    if request_timeout <= 0 or request_timeout > 900:
        raise ValueError("request_timeout must be in the range 1..900 seconds")
    selected_models = model_ids or MODEL_IDS
    if not selected_models or any(model_id not in MODEL_IDS for model_id in selected_models):
        raise ValueError("model_ids must be a non-empty subset of the frozen model inventory")
    plan = _read_object(Path(plan_path))
    if plan.get("planned_calls") not in {3, 54} or plan.get("live") is not False:
        raise ValueError("execute requires an offline-prepared supported plan")
    if plan.get("planned_calls") == 3:
        if plan.get("schema_version") != "long-transcript-confirmation-plan-v1":
            raise ValueError("three-call execution requires a confirmation plan")
        if request_timeout != plan.get("request_timeout_seconds"):
            raise ValueError("confirmation execution must use its frozen timeout")
        selected_models = ("google/gemma-4-12b-qat",)
    root = _outside_repo(Path(private_root))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    load_config = _read_object(Path(load_config_path))
    if _loaded_total() != 0:
        raise RuntimeError("execution requires loaded_total=0 at global preflight")
    api_host = os.environ.get("LMSTUDIO_API_HOST", "localhost:1234")
    executed = 0
    stop = False
    for model_id in selected_models:
        model_index = MODEL_IDS.index(model_id) + 1
        rows = [row for row in plan["requests"] if row["model"] == model_id]
        if len(rows) != plan["calls_per_model"]:
            raise ValueError("model row count differs from the frozen plan")
        if request_ids is not None:
            rows = [row for row in rows if row["request_id"] in request_ids]
            if not rows:
                continue
        instance_id = f"long-repr-{model_index:02d}"
        loaded = None
        try:
            with lms.Client(api_host=api_host) as client:
                loaded = _load_or_attach(client, model_id, instance_id, load_config)
                if _loaded_total() != 1:
                    raise RuntimeError("model load did not produce exactly one loaded instance")
                for row in rows:
                    budget = derive_output_budget(loaded, row["chunk_text"])
                    input_tokens = validate_token_fit(loaded, row["request_text"], budget)
                    try:
                        response = _generate(
                            instance_id,
                            row["request_text"],
                            budget,
                            request_timeout=request_timeout,
                        )
                    except Exception as exc:
                        error_artifact = {
                            "request_id": row["request_id"],
                            "model": model_id,
                            "request_text_sha256": row["request_text_sha256"],
                            "input_tokens": input_tokens,
                            "max_output_tokens": budget,
                            "transport": "/v1/chat/completions",
                            "cache_prompt": False,
                            "thinking_enabled": False,
                            "status": "transport_error",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                        path = root / f"{row['request_id']}.error.json"
                        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(fd, "wb") as stream:
                            stream.write(_canonical(error_artifact) + b"\n")
                        raise
                    completion_details = response.get("usage", {}).get(
                        "completion_tokens_details", {}
                    )
                    reasoning_tokens = completion_details.get("reasoning_tokens")
                    if reasoning_tokens not in {None, 0}:
                        raise RuntimeError("response exposed non-zero reasoning tokens")
                    artifact = {
                        "request_id": row["request_id"],
                        "model": model_id,
                        "request_text_sha256": row["request_text_sha256"],
                        "input_tokens": input_tokens,
                        "max_output_tokens": budget,
                        "reasoning_tokens": reasoning_tokens,
                        "transport": "/v1/chat/completions",
                        "cache_prompt": False,
                        "thinking_enabled": False,
                        "final_text": response.pop("_lab_final_text"),
                        "response": response,
                    }
                    path = root / f"{row['request_id']}.json"
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(_canonical(artifact) + b"\n")
                    executed += 1
                    if max_calls is not None and executed >= max_calls:
                        stop = True
                        break
        finally:
            if _loaded_instance(model_id, instance_id) is not None:
                with lms.Client(api_host=api_host) as cleanup_client:
                    cleanup_client.llm.unload(instance_id)
            if _loaded_total() != 0:
                raise RuntimeError("post-model unload read-back is not loaded_total=0")
        if stop:
            break
    return executed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--manifest", required=True)
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--output", required=True)
    rubric = sub.add_parser("init-private-rubric")
    rubric.add_argument("--template", required=True)
    rubric.add_argument("--output", required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("--plan", required=True)
    execute.add_argument("--load-config", required=True)
    execute.add_argument("--private-root", required=True)
    execute.add_argument("--max-calls", type=int)
    execute.add_argument("--model", action="append", choices=MODEL_IDS)
    execute.add_argument("--request", action="append")
    execute.add_argument("--request-timeout", type=int, default=900)
    execute.add_argument("--live", action="store_true", required=True)
    admit = sub.add_parser("admit")
    admit.add_argument("--plan", required=True)
    admit.add_argument("--load-config", required=True)
    admit.add_argument("--evidence", required=True)
    admit.add_argument("--live", action="store_true", required=True)
    confirmation = sub.add_parser("prepare-confirmation")
    confirmation.add_argument("--manifest", required=True)
    confirmation.add_argument("--source", required=True)
    confirmation.add_argument("--selector", required=True)
    confirmation.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "prepare":
        plan = write_plan(args.manifest, args.source, args.output)
        print(json.dumps({"planned_calls": plan["planned_calls"], "output": args.output}))
    elif args.action == "init-private-rubric":
        initialize_private_rubric(args.template, args.output)
        print(json.dumps({"created": args.output, "mode": "0600"}))
    elif args.action == "prepare-confirmation":
        plan = write_confirmation_plan(args.manifest, args.source, args.selector, args.output)
        print(json.dumps({"planned_calls": plan["planned_calls"], "output": args.output}))
    elif args.action == "execute":
        executed = run_plan(
            args.plan,
            args.load_config,
            args.private_root,
            max_calls=args.max_calls,
            model_ids=tuple(args.model) if args.model else None,
            request_ids=tuple(args.request) if args.request else None,
            request_timeout=args.request_timeout,
        )
        print(json.dumps({"executed_calls": executed, "private_root": args.private_root}))
    else:
        evidence = admit_plan(args.plan, args.load_config, args.evidence)
        print(
            json.dumps(
                {
                    "admitted_requests": evidence["admitted_requests"],
                    "models": len(evidence["models"]),
                    "generation_performed": False,
                    "global_loaded_total_final": evidence["global_loaded_total_final"],
                    "evidence": args.evidence,
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
