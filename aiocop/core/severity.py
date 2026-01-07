"""Severity calculation for blocking IO events."""

from aiocop.types.events import BlockingEventInfo
from aiocop.types.severity import (
    THRESHOLD_HIGH,
    THRESHOLD_MEDIUM,
    WEIGHT_MODERATE,
    IoSeverityLevel,
)


def calculate_io_severity_score(blocking_events: list[BlockingEventInfo] | None) -> int:
    """
    Calculate aggregate I/O severity score by summing event weights.

    Each blocking event has a severity weight:
    - WEIGHT_HEAVY (50): Network, DB, subprocess operations
    - WEIGHT_MODERATE (10): File I/O, mutations
    - WEIGHT_LIGHT (1): Stat, access checks
    - WEIGHT_TRIVIAL (0): Negligible operations

    Returns:
        Total severity score (sum of all event weights)
    """
    if blocking_events is None or len(blocking_events) == 0:
        return 0

    total_score = 0
    for evt in blocking_events:
        severity = evt.get("severity")
        if severity is None:
            severity = WEIGHT_MODERATE
        total_score += severity

    return total_score


def get_severity_level_from_score(score: int) -> IoSeverityLevel:
    """Convert a numeric severity score to a severity level string."""
    if score >= THRESHOLD_HIGH:
        return "high"
    elif score >= THRESHOLD_MEDIUM:
        return "medium"
    else:
        return "low"
