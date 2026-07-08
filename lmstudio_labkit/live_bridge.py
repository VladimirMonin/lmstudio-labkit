from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .requests import RequestPlan, RequestResult


class LiveBridgeError(RuntimeError):
    """Raised when live execution guardrails reject a request."""


@dataclass(frozen=True, slots=True)
class LiveBridgeOptions:
    live: bool = False
    allow_model_load: bool = False
    allow_remote: bool = False
    allow_stress: bool = False
    base_url: str = "http://127.0.0.1:1234"
    profile: str = "offline-fake"
    max_requests: int = 1


@dataclass(frozen=True, slots=True)
class ManagedLiveBridge:
    """Guarded bridge from public request plans to an injected managed executor.

    The bridge performs no network I/O by itself. Tests and host applications inject
    a callable that owns the actual managed runner/lifecycle interaction.
    """

    executor: Callable[[RequestPlan], str]
    options: LiveBridgeOptions

    def execute(self, plan: RequestPlan) -> tuple[str, RequestResult]:
        validate_live_guardrails(self.options, request_count=1)
        if plan.envelope.modality == "image":
            raise NotImplementedError("image live bridge is intentionally not implemented yet")
        raw_response = self.executor(plan)
        return raw_response, RequestResult.from_raw_response(
            request_id=plan.envelope.request_id,
            model_id=plan.options.model_id,
            raw_response=raw_response,
            status="ok",
            latency_ms=0.0,
            token_counts={},
            finish_reason="stop",
        )


def validate_live_guardrails(options: LiveBridgeOptions, *, request_count: int) -> None:
    if not options.live:
        raise LiveBridgeError("live bridge requires explicit live=True")
    if options.profile in {"overnight", "stress"} and not options.allow_stress:
        raise LiveBridgeError("stress/overnight profiles require allow_stress=True")
    if request_count > options.max_requests:
        raise LiveBridgeError("request_count exceeds max_requests")
    parsed = urlparse(options.base_url)
    hostname = parsed.hostname or ""
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if hostname not in local_hosts and not options.allow_remote:
        raise LiveBridgeError("remote base_url requires allow_remote=True")


def managed_runner_bridge_factory(
    options: LiveBridgeOptions, executor: Callable[[RequestPlan], str]
) -> ManagedLiveBridge:
    validate_live_guardrails(options, request_count=1)
    return ManagedLiveBridge(executor=executor, options=options)


def safe_live_metadata(options: LiveBridgeOptions) -> dict[str, Any]:
    parsed = urlparse(options.base_url)
    return {
        "live": options.live,
        "allow_model_load": options.allow_model_load,
        "allow_remote": options.allow_remote,
        "allow_stress": options.allow_stress,
        "base_url_host": parsed.hostname,
        "base_url_scheme": parsed.scheme,
        "profile": options.profile,
        "max_requests": options.max_requests,
    }


__all__ = [
    "LiveBridgeError",
    "LiveBridgeOptions",
    "ManagedLiveBridge",
    "managed_runner_bridge_factory",
    "safe_live_metadata",
    "validate_live_guardrails",
]
