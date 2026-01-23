"""Exceptions for aiocop."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiocop.types.events import BlockingEventInfo


class HighSeverityBlockingIoException(Exception):
    """Exception raised when high-severity blocking I/O is detected in async context."""

    def __init__(
        self,
        severity_score: int,
        severity_level: str,
        elapsed_ms: float,
        threshold_ms: float,
        events: "list[BlockingEventInfo]",
    ) -> None:
        self.severity_score = severity_score
        self.severity_level = severity_level
        self.elapsed_ms = elapsed_ms
        self.threshold_ms = threshold_ms
        self.events = events

        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format the exception message with clear visual structure."""
        events_str = ""
        if self.events is not None and len(self.events) > 0:
            events_list = [f"\n  - {evt['event']}\n    at {evt['trace']}" for evt in self.events]
            events_str = "".join(events_list)

        return (
            f"\n{'=' * 80}\n"
            f"HIGH SEVERITY BLOCKING I/O DETECTED\n"
            f"{'=' * 80}\n"
            f"Async task exceeded threshold:\n"
            f"  - Severity Score: {self.severity_score}\n"
            f"  - Severity Level: {self.severity_level}\n"
            f"  - Elapsed Time: {self.elapsed_ms:.2f}ms\n"
            f"  - Threshold: {self.threshold_ms:.2f}ms\n"
            f"\nBlocking I/O Events:{events_str}\n"
            f"{'=' * 80}\n"
        )
