"""Shared state management for aiocop monitoring."""

import threading
from contextvars import ContextVar

_thread_local = threading.local()

_monitoring_active: bool = False

raise_on_violations: ContextVar[bool] = ContextVar("raise_on_violations", default=False)

_exception_raised = False


def activate() -> None:
    """Activate monitoring. Call this after startup when you want to start detecting blocking IO."""
    global _monitoring_active
    _monitoring_active = True


def deactivate() -> None:
    """Deactivate monitoring. Pauses all detection without unregistering hooks."""
    global _monitoring_active
    _monitoring_active = False


def is_monitoring_active() -> bool:
    """Check if monitoring is currently active."""
    return _monitoring_active is True


def enable_raise_on_violations() -> None:
    """Enable raising exceptions on high severity blocking IO for the current context."""
    raise_on_violations.set(True)


def disable_raise_on_violations() -> None:
    """Disable raising exceptions on high severity blocking IO for the current context."""
    raise_on_violations.set(False)


def is_raise_on_violations_enabled() -> bool:
    """Check if raise on violations is enabled for the current context."""
    return raise_on_violations.get() is True


class raise_on_violations_context:
    """Context manager to temporarily enable raise_on_violations."""

    def __init__(self) -> None:
        self._token = None

    def __enter__(self) -> "raise_on_violations_context":
        self._token = raise_on_violations.set(True)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        if self._token is not None:
            raise_on_violations.reset(self._token)


def _reset_exception_flag() -> None:
    """Reset the exception raised flag. Internal use only."""
    global _exception_raised
    _exception_raised = False


def _mark_exception_raised() -> None:
    """Mark that an exception has been raised. Internal use only."""
    global _exception_raised
    _exception_raised = True


def _has_exception_been_raised() -> bool:
    """Check if an exception has been raised in the current handle. Internal use only."""
    return _exception_raised is True


def _get_thread_local() -> threading.local:
    """Get the thread local storage. Internal use only."""
    return _thread_local
