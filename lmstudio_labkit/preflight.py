from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from .benchmarks import BenchmarkConfig, plan_matrix


@dataclass(frozen=True, slots=True)
class PreflightResult:
    status: str
    config_path: str
    run_id: str | None
    config_hash: str | None
    planned_request_count: int
    checks: dict[str, Any]
    lmstudio: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def preflight_config(config_path: str | Path, *, base_url: str | None = None) -> PreflightResult:
    path = Path(config_path)
    checks: dict[str, Any] = {
        "config_parse": "pending",
        "plan_build": "pending",
        "budget": "pending",
        "privacy_defaults": "pending",
        "chunk_count_axis_absent": "pending",
    }
    try:
        config = BenchmarkConfig.from_file(path)
        checks["config_parse"] = "pass"
        if "chunk_count" in config.axes:
            checks["chunk_count_axis_absent"] = "fail"
            raise ValueError("chunk_count must not be a top-level axis")
        checks["chunk_count_axis_absent"] = "pass"
        plan = plan_matrix(config)
        checks["plan_build"] = "pass"
        checks["budget"] = "pass"
        _validate_privacy_defaults(config)
        checks["privacy_defaults"] = "pass"
        lmstudio = preflight_lmstudio_readonly(base_url) if base_url else None
        status = "pass" if lmstudio is None or lmstudio.get("status") == "pass" else "fail"
        return PreflightResult(
            status=status,
            config_path=str(path),
            run_id=config.run_id,
            config_hash=config.safe_hash(),
            planned_request_count=len(plan.cells),
            checks=checks,
            lmstudio=lmstudio,
        )
    except Exception as error:
        checks.setdefault("error", str(error))
        checks["error"] = str(error)
        return PreflightResult(
            status="fail",
            config_path=str(path),
            run_id=None,
            config_hash=None,
            planned_request_count=0,
            checks=checks,
            lmstudio=None,
        )


def preflight_lmstudio_readonly(base_url: str) -> dict[str, Any]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        return {"status": "fail", "error": "base_url scheme must be http or https"}
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base_url_kind = "local" if host in {"127.0.0.1", "localhost", "::1"} else "remote"
    tcp_open = _tcp_probe(host, port)
    probes = {
        "/v1/models": _get_json_models(base_url, "/v1/models"),
        "/api/v1/models": _get_json_models(base_url, "/api/v1/models"),
    }
    return {
        "status": "pass"
        if tcp_open and any(item.get("ok") for item in probes.values())
        else "fail",
        "base_url_kind": base_url_kind,
        "base_url_scheme": parsed.scheme,
        "tcp_open": tcp_open,
        "model_counts": {path: item.get("model_count") for path, item in probes.items()},
        "probes": probes,
    }


def _validate_privacy_defaults(config: BenchmarkConfig) -> None:
    safety = config.safety
    if safety.allow_raw_prompt_response_artifacts:
        raise ValueError("raw prompt/response artifacts must be disabled")
    if safety.allow_model_downloads:
        raise ValueError("model downloads must be disabled")
    if safety.allow_image_live:
        raise ValueError("image live must be disabled")


def _tcp_probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _get_json_models(base_url: str, path: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    try:
        req = urllib_request.Request(url, method="GET")
        with urllib_request.urlopen(req, timeout=3.0) as response:  # noqa: S310 - explicit operator local/read-only preflight
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {"ok": False, "error_type": type(error).__name__}
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list) and isinstance(payload, dict):
        models = payload.get("models")
    return {
        "ok": isinstance(models, list),
        "model_count": len(models) if isinstance(models, list) else None,
    }
