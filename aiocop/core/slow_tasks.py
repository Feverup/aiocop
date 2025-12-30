"""Slow task detection by patching asyncio Handle._run."""




import logging
from asyncio.events import Handle
from time import perf_counter_ns
from typing import Any, Callable

from aiocop.core.blocking_io import format_blocking_event
from aiocop.core.callbacks import _capture_context, _invoke_slow_task_callbacks
from aiocop.core.severity import calculate_io_severity_score, get_severity_level_from_score
from dataclasses import replace
from aiocop.core.state import (
    _get_thread_local,
    _has_exception_been_raised,
    _mark_exception_raised,
    _reset_exception_flag,
    is_monitoring_active,
    raise_on_violations,
)
from aiocop.exceptions import HighSeverityBlockingIoException
from aiocop.types.events import BlockingEventInfo, SlowTaskEvent
from aiocop.types.severity import THRESHOLD_HIGH

logger = logging.getLogger(__name__)

_detect_slow_tasks_already_applied = False
_slow_task_threshold_ns: int = 30 * 1_000_000

SlowTaskCallback = Callable[[SlowTaskEvent], None]


def _invoke_callbacks_with_context(event: SlowTaskEvent) -> None:
    """
    Capture context and invoke callbacks within the Handle's context.

    This function is called via self._context.run() to ensure that context
    providers (like ddtrace span) are captured from the correct contextvars.
    """
    captured_context = _capture_context()
    event_with_context = replace(event, context=captured_context)
    _invoke_slow_task_callbacks(event_with_context)


def detect_slow_tasks(
    threshold_ms: int = 30,
    on_slow_task: SlowTaskCallback | None = None,
) -> None:
    """
    Patch the asyncio event loop to detect slow tasks.

    This patches Handle._run to measure execution time and capture blocking IO events.
    Callbacks are invoked for every task that has blocking events detected, with
    the exceeded_threshold flag indicating if the task exceeded the threshold.

    Args:
        threshold_ms: Threshold in milliseconds for considering a task "slow" (default: 30)
        on_slow_task: Optional callback invoked when blocking IO is detected in a task.
                      The callback receives a SlowTaskEvent with exceeded_threshold indicating
                      if the threshold was exceeded.

    Should be called after start_blocking_io_detection().
    """
    global _detect_slow_tasks_already_applied, _slow_task_threshold_ns

    if _detect_slow_tasks_already_applied is True:
        logger.warning("detect_slow_tasks called more than once, ignoring")
        return

    _slow_task_threshold_ns = threshold_ms * 1_000_000

    if on_slow_task is not None:
        from aiocop.core.callbacks import register_slow_task_callback

        register_slow_task_callback(on_slow_task)

    if raise_on_violations.get() is True:
        logger.info("Exceptions raising on high severity IO blocking tasks enabled")

    old_run = Handle._run  # noqa

    __class__ = Handle  # noqa

    def new_run(self) -> Any:
        if not is_monitoring_active():
            return old_run(self)

        thread_local = _get_thread_local()
        captured_events: list = []

        previous_events = getattr(thread_local, "blocking_events", None)

        thread_local.blocking_events = captured_events
        thread_local.should_raise_for_this_handle = False

        _reset_exception_flag()
        t0 = perf_counter_ns()

        try:
            return_value = old_run(self)  # noqa
        finally:
            thread_local.blocking_events = previous_events

        should_raise = getattr(thread_local, "should_raise_for_this_handle", False)

        try:
            elapsed = perf_counter_ns() - t0
            elapsed_ms = elapsed / 1_000_000
            threshold_ms = _slow_task_threshold_ns / 1_000_000
            exceeded_threshold = elapsed >= _slow_task_threshold_ns

            has_events = len(captured_events) > 0

            if has_events is True:
                formatted_events = [format_blocking_event(evt) for evt in captured_events]
                io_severity = calculate_io_severity_score(formatted_events)
                severity_level = get_severity_level_from_score(io_severity)

                slow_task_event = SlowTaskEvent(
                    elapsed_ms=elapsed_ms,
                    threshold_ms=threshold_ms,
                    exceeded_threshold=exceeded_threshold,
                    severity_score=io_severity,
                    severity_level=severity_level,
                    reason="io_blocking",
                    blocking_events=formatted_events,
                )

                self._context.run(_invoke_callbacks_with_context, slow_task_event)

                if exceeded_threshold is True:
                    self._context.run(_check_and_raise_if_needed, elapsed, formatted_events, should_raise)

            elif exceeded_threshold is True:
                slow_task_event = SlowTaskEvent(
                    elapsed_ms=elapsed_ms,
                    threshold_ms=threshold_ms,
                    exceeded_threshold=exceeded_threshold,
                    severity_score=0,
                    severity_level="low",
                    reason="cpu_blocking",
                    blocking_events=[],
                )

                self._context.run(_invoke_callbacks_with_context, slow_task_event)

        except HighSeverityBlockingIoException:
            raise
        except Exception as ex:
            logger.error("Error while checking async task execution time: %s", ex)

        return return_value

    Handle._run = new_run  # noqa # type: ignore[method-assign]
    _detect_slow_tasks_already_applied = True


def _check_and_raise_if_needed(
    elapsed: int, blocking_events: list[BlockingEventInfo] | None, should_raise: bool
) -> None:
    """Check if high severity blocking IO should raise an exception within the Handle's context."""
    if should_raise is True and _has_exception_been_raised() is False:
        io_severity = calculate_io_severity_score(blocking_events)

        if io_severity >= THRESHOLD_HIGH:
            _mark_exception_raised()

            raise HighSeverityBlockingIoException(
                severity_score=io_severity,
                severity_level=get_severity_level_from_score(io_severity),
                elapsed_ms=elapsed / 1_000_000,
                threshold_ms=_slow_task_threshold_ns / 1_000_000,
                events=blocking_events or [],
            )


def get_slow_task_threshold_ms() -> float:
    """Get the current slow task threshold in milliseconds."""
    return _slow_task_threshold_ns / 1_000_000
