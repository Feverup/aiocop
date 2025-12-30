"""Event type definitions for aiocop."""

from dataclasses import dataclass, field
from typing import Any, TypedDict


class RawBlockingEvent(TypedDict):
    """Raw blocking event captured by the audit hook before formatting."""

    event_name: str
    raw_args: tuple
    raw_stack: list[tuple[str, int, str]]
    timestamp: float
    severity: int | None


class BlockingEventInfo(TypedDict):
    """Formatted blocking event info for reporting."""

    event: str
    trace: str
    entry_point: str
    severity: int | None


@dataclass(frozen=True)
class SlowTaskEvent:
    """Event emitted when a slow task is detected."""

    elapsed_ms: float
    threshold_ms: float
    exceeded_threshold: bool
    severity_score: int
    severity_level: str
    reason: str
    blocking_events: list[BlockingEventInfo]
    context: dict[str, Any] = field(default_factory=dict)
