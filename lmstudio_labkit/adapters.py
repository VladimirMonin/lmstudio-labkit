from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .requests import RequestPlan


class HostApplicationAdapter(Protocol):
    """Boundary for host-owned orchestration outside the public benchmark core."""

    def select_model_key(self, request_plan: RequestPlan) -> str: ...

    def consume_report(self, run_id: str, report_markdown: str) -> None: ...


@dataclass(frozen=True, slots=True)
class NullHostApplicationAdapter:
    """No-op adapter for standalone/offline use."""

    model_key: str = "default"

    def select_model_key(self, request_plan: RequestPlan) -> str:
        return self.model_key

    def consume_report(self, run_id: str, report_markdown: str) -> None:
        return None
