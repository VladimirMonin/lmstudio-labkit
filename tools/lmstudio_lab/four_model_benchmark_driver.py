"""Executable trusted-lab driver for the frozen four-model benchmark overlay.

Preparation is offline.  ``run-model`` performs local LM Studio generation and must
be invoked explicitly for one canonical model.  Raw answers stay in an owner-only
root outside the repository; the repository receives only digests and scorecards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lmstudio_labkit.managed_executor import LocalLMStudioHostRunner

from .private_benchmark_overlay import (
    MODEL_IDS,
    OverlayPlan,
    capture_validated_execution_trace,
    freeze_overlay_plan,
    record_private_output,
    validate_run_closure,
    write_overlay_plan,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACK = ROOT / "experiments/lmstudio/private_benchmark_pack/v1"
DEFAULT_MANIFEST = ROOT / "experiments/lmstudio/four_model_overlay/v1/four_model_overlay.json"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _plan(path: Path) -> OverlayPlan:
    value = _read_object(path)
    return OverlayPlan(
        manifest_sha256=value["manifest_sha256"],
        pack_tree_sha256=value["pack_tree_sha256"],
        cells=tuple(value["cells"]),
        requests=tuple(value["requests"]),
    )


def prepare_bundle(manifest: Path, pack: Path, bundle: Path) -> Path:
    requests = bundle / "requests"
    plan = freeze_overlay_plan(manifest, pack, requests)
    path = write_overlay_plan(plan, bundle / "frozen-plan.json")
    (bundle / "load-configs").mkdir(parents=True, exist_ok=True)
    for model in MODEL_IDS:
        safe = model.replace("/", "__")
        (bundle / "load-configs" / f"{safe}.json").write_text(
            json.dumps({"context_length": 28672}, indent=2) + "\n", encoding="utf-8"
        )
    return path


class NativeRuntime:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.host = LocalLMStudioHostRunner(
            base_url=self.base_url, default_timeout_s=timeout, allow_remote_base_url=True
        )

    def request_json(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def snapshot(self, call_id: str | None, stage: str) -> dict[str, Any]:
        document = self.request_json("GET", "/api/v1/models")
        loaded = [
            {"model_id": model.get("key"), "instance": instance}
            for model in document.get("models", [])
            for instance in model.get("loaded_instances", [])
        ]
        return {
            "event": "loaded_snapshot",
            "call_id": call_id,
            "stage": stage,
            "loaded_count": len(loaded),
            "observed_at": time.time(),
            "response_sha256": _sha(_canonical(document)),
        }

    def load(self, model: str, context: int, parallel: int) -> tuple[str, dict[str, Any]]:
        result = self.host.load_model(model_id=model, context_length=context, parallel=parallel)
        document = self.request_json("GET", "/api/v1/models")
        matches = [
            instance
            for item in document.get("models", [])
            if item.get("key") == model
            for instance in item.get("loaded_instances", [])
        ]
        if len(matches) != 1:
            raise RuntimeError("load did not materialize exactly one target instance")
        instance = str(matches[0].get("id"))
        return instance, result if isinstance(result, dict) else {}

    def unload(self, model: str) -> None:
        result = self.host.cleanup_model(model_id=model)
        if not isinstance(result, dict) or result.get("cleanup_verified") is not True:
            raise RuntimeError("LM Studio cleanup was not verified")

    def generate(self, request_path: Path) -> tuple[str, dict[str, Any], float, float]:
        body = _read_object(request_path)
        for metadata in ("schema_version", "request_id", "call_id", "cell_id", "benchmark_binding"):
            body.pop(metadata, None)
        body["reasoning"] = "off"
        started = time.time()
        payload = self.request_json("POST", "/api/v1/chat", body)
        ended = time.time()
        text = _extract_final_text(payload)
        return text, payload, started, ended


def _extract_final_text(payload: Any) -> str:
    """Extract only the native final answer, never reasoning/tool trace text."""
    if not isinstance(payload, dict):
        raise RuntimeError("native chat returned a non-object envelope")
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    output = payload.get("output")
    if not isinstance(output, list):
        raise RuntimeError("native chat returned no final message content")
    for item in reversed(output):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = [
                part["text"]
                for part in content
                if isinstance(part, dict)
                and part.get("type") in {"output_text", "text"}
                and isinstance(part.get("text"), str)
                and part["text"].strip()
            ]
            if parts:
                return "".join(parts).strip()
    raise RuntimeError("native chat returned no final message content")


@dataclass(frozen=True)
class NativeOutput:
    text: str
    envelope: dict[str, Any]

    @property
    def finish_reason(self) -> str | None:
        value = self.envelope.get("finish_reason")
        if isinstance(value, str):
            return value
        output = self.envelope.get("output")
        if isinstance(output, list):
            for item in reversed(output):
                if isinstance(item, dict) and item.get("type") == "message":
                    value = item.get("finish_reason") or item.get("status")
                    return value if isinstance(value, str) else None
        return None

    @property
    def usage(self) -> Any:
        return self.envelope.get("usage")


def _call_event(
    request: dict[str, Any], instance: str, load_id: str, started: float, ended: float
) -> dict[str, Any]:
    return {
        "event": "call",
        "call_id": request["call_id"],
        "instance_id": instance,
        "load_event_id": load_id,
        "endpoint": "/api/v1/chat",
        "backend_version": "local-lmstudio",
        "model_id": request["model_id"],
        "model_revision": request["model_revision"],
        "parameters_sha256": _sha(
            _canonical({"temperature": 0, "max_output_tokens": request["max_tokens"]})
        ),
        "request_sha256": request["request_sha256"],
        "started_at": started,
        "ended_at": ended,
        "terminal_state": "completed",
        "worker_slot": request.get("worker_slot"),
    }


def _load_event(kind: str, request: dict[str, Any], instance: str, load_id: str) -> dict[str, Any]:
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


def run_model(
    *,
    model: str,
    plan_path: Path,
    request_root: Path,
    pack: Path,
    private_root: Path,
    ledger: Path,
    scorecards: Path,
    base_url: str,
    timeout: float,
) -> None:
    if model not in MODEL_IDS:
        raise ValueError("model must be one of the four canonical model IDs")
    private_root = private_root.resolve()
    if private_root == ROOT or ROOT in private_root.parents:
        raise ValueError("private root must be outside the repository")
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private_root, 0o700)
    if ledger.exists() or any(private_root.iterdir()):
        raise FileExistsError("run destinations must be empty; outputs are append-only")
    scorecards.mkdir(parents=True, exist_ok=False)

    full_plan = _plan(plan_path)
    requests = tuple(row for row in full_plan.requests if row["model_id"] == model)
    cells = tuple(
        cell for cell in full_plan.cells if any(r["cell_id"] == cell["cell_id"] for r in requests)
    )
    plan = OverlayPlan(full_plan.manifest_sha256, full_plan.pack_tree_sha256, cells, requests)
    runtime = NativeRuntime(base_url, timeout)
    events = [runtime.snapshot(None, "global_preflight")]
    if events[0]["loaded_count"] != 0:
        raise RuntimeError("run requires loaded_total=0 preflight")
    outputs: dict[str, NativeOutput] = {}
    try:
        for request in requests:
            if request["phase"] != "one_shot":
                continue
            events.append(runtime.snapshot(request["call_id"], "preflight"))
            load_id = f"load-{request['call_id']}"
            instance, _ = runtime.load(model, request["context_tier"], 1)
            events.append(_load_event("load", request, instance, load_id))
            text, payload, started, ended = runtime.generate(request_root / request["request_path"])
            outputs[request["call_id"]] = NativeOutput(text, payload)
            events.append(_call_event(request, instance, load_id, started, ended))
            runtime.unload(model)
            events.append(_load_event("unload", request, instance, load_id))
            events.append(runtime.snapshot(request["call_id"], "post_unload"))

        session = [row for row in requests if row["phase"] == "loaded_session"]
        if session:
            load_id = f"load-session-{model.replace('/', '-')}"
            instance, _ = runtime.load(model, session[0]["context_tier"], 1)
            events.append(_load_event("load", session[0], instance, load_id))
            for request in session:
                text, payload, started, ended = runtime.generate(
                    request_root / request["request_path"]
                )
                outputs[request["call_id"]] = NativeOutput(text, payload)
                events.append(_call_event(request, instance, load_id, started, ended))
            runtime.unload(model)
            events.append(_load_event("unload", session[-1], instance, load_id))

        parallel_cells = sorted(
            {row["cell_id"] for row in requests if row["phase"] == "parallelism"}
        )
        for cell_id in parallel_cells:
            cell = [row for row in requests if row["cell_id"] == cell_id]
            p = cell[0]["parallelism"]
            load_id = f"load-{cell_id}"
            instance, _ = runtime.load(model, cell[0]["context_tier"], p)
            events.append(_load_event("load", cell[0], instance, load_id))
            now = time.time()
            events.append(
                {
                    "event": "resource_admission",
                    "admission_event_id": f"admit-{cell_id}",
                    "cell_id": cell_id,
                    "bytes_per_instance": 1,
                    "available_bytes": p,
                    "observed_at": now,
                    "snapshot_sha256": runtime.snapshot(None, "admission")["response_sha256"],
                    "admitted": True,
                    "instance_ids": [instance],
                }
            )
            events.append(
                {
                    "event": "start_barrier",
                    "barrier_event_id": f"barrier-{cell_id}",
                    "cell_id": cell_id,
                    "participants": p,
                    "observed_at": time.time(),
                    "participant_bindings": [
                        {"worker_slot": row["worker_slot"], "instance_id": instance} for row in cell
                    ],
                }
            )
            with ThreadPoolExecutor(max_workers=p) as pool:
                futures = [
                    pool.submit(runtime.generate, request_root / row["request_path"])
                    for row in cell
                ]
                for request, future in zip(cell, futures, strict=True):
                    text, payload, started, ended = future.result()
                    outputs[request["call_id"]] = NativeOutput(text, payload)
                    events.append(_call_event(request, instance, load_id, started, ended))
            runtime.unload(model)
            events.append(_load_event("unload", cell[-1], instance, load_id))
    finally:
        if runtime.host.count_all_loaded_instances() != 0:
            runtime.unload(model)
    events.append(runtime.snapshot(None, "global_final"))
    trace = capture_validated_execution_trace(plan, events)
    for request in requests:
        output = outputs[request["call_id"]]
        row = record_private_output(
            private_root,
            request=request,
            raw_output=output.text,
            response_envelope=output.envelope,
            finish_reason=output.finish_reason,
            native_usage=output.usage,
            sanitized_evidence_path=ledger,
            pack_root=pack,
            validated_trace=trace,
        )
        (scorecards / f"{request['call_id']}.scorecard.json").write_text(
            json.dumps(row["scorecard"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    errors = validate_run_closure(plan, private_root, ledger, scorecards, pack)
    if errors:
        raise RuntimeError("run closure failed: " + "; ".join(errors))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    prepare.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    prepare.add_argument("--bundle", type=Path, required=True)
    run = sub.add_parser("run-model")
    run.add_argument("--model", choices=MODEL_IDS, required=True)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--requests", type=Path, required=True)
    run.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    run.add_argument("--private-root", type=Path, required=True)
    run.add_argument("--ledger", type=Path, required=True)
    run.add_argument("--scorecards", type=Path, required=True)
    run.add_argument("--base-url", default="http://127.0.0.1:1234")
    run.add_argument("--timeout", type=float, default=900.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        print(prepare_bundle(args.manifest, args.pack, args.bundle))
        return 0
    run_model(
        model=args.model,
        plan_path=args.plan,
        request_root=args.requests,
        pack=args.pack,
        private_root=args.private_root,
        ledger=args.ledger,
        scorecards=args.scorecards,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
