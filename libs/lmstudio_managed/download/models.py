"""Pure download DTOs with no transport ownership."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DownloadStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    ALREADY_DOWNLOADED = "already_downloaded"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    status: DownloadStatus
    ready_on_disk: bool
    downloaded_bytes: int | None
    total_bytes: int | None
    endpoint_kinds_used: tuple[str, ...] = ()

    @property
    def is_terminal_success(self) -> bool:
        return self.status in {
            DownloadStatus.ALREADY_DOWNLOADED,
            DownloadStatus.COMPLETED,
        }
