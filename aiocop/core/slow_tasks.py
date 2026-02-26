"""Slow task detection by patching event loop scheduling methods.

This module patches the event loop's call_soon, call_later, call_at, and
call_soon_threadsafe methods to wrap callbacks with monitoring logic.

This approach works with both standard asyncio and uvloop, since it patches
at the loop level rather than relying on asyncio's Handle._run which uvloop
replaces with its own Cython implementation.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from time import perf_counter_ns
from typing import Any

from aiocop.core.blocking_io import format_blocking_event
from aiocop.core.callbacks import _capture_context, _invoke_slow_task_callbacks
from aiocop.core.severity import calculate_io_severity_score, get_severity_level_from_score
from aiocop.core.state import (
    _get_thread_local,
    _has_exception_been_raised,
    _mark_exception_raised,
    _reset_exception_flag,
    is_monitoring_active,
    raise_on_violations,
    register_on_activate_hook,
)
from aiocop.exceptions import HighSeverityBlockingIoException
from aiocop.types.events import BlockingEventInfo, SlowTaskEvent
from aiocop.types.severity import THRESHOLD_HIGH

logger = logging.getLogger(__name__)

_detect_slow_tasks_configured = False
_slow_task_threshold_ns: int = 30 * 1_000_000

SlowTaskCallback = Callable[[SlowTaskEvent], None]


def detect_slow_tasks(
    threshold_ms: int = 30,
    on_slow_task: SlowTaskCallback | None = None,
) -> None:
    """
    Configure slow task detection for the asyncio event loop.

    This patches the event loop's scheduling methods (call_soon, call_later, etc.)
    to measure execution time and capture blocking IO events. Works with both
    standard asyncio and uvloop.

    The loop is patched either immediately (if called from an async context) or
    when activate() is called.

    Callbacks are invoked for every task that has blocking events detected, with
    the exceeded_threshold flag indicating if the task exceeded the threshold.

    Args:
        threshold_ms: Threshold in milliseconds for considering a task "slow" (default: 30)
        on_slow_task: Optional callback invoked when blocking IO is detected in a task.
                      The callback receives a SlowTaskEvent with exceeded_threshold indicating
                      if the threshold was exceeded.

    Should be called after start_blocking_io_detection().
    """
    global _detect_slow_tasks_configured, _slow_task_threshold_ns

    if _detect_slow_tasks_configured is True:
        logger.warning("detect_slow_tasks called more than once, ignoring")
        return

    _slow_task_threshold_ns = threshold_ms * 1_000_000

    if on_slow_task is not None:
        from aiocop.core.callbacks import register_slow_task_callback

        register_slow_task_callback(on_slow_task)

    if raise_on_violations.get() is True:
        logger.info("Exceptions raising on high severity IO blocking tasks enabled")

    _detect_slow_tasks_configured = True

    register_on_activate_hook(_ensure_loop_patched)

    _ensure_loop_patched()


def _ensure_loop_patched() -> bool:
    """
    Ensure the current event loop is patched for slow task detection.
    """
    if not _detect_slow_tasks_configured:
        return False

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    if getattr(loop, "_aiocop_patched", False):
        return True

    _patch_loop(loop)
    loop._aiocop_patched = True  # type: ignore[attr-defined]
    logger.info("Event loop patched for slow task detection")
    return True


def _patch_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Patch the event loop's scheduling methods to monitor callback execution."""

    # Re-raise HighSeverityBlockingIoException
    original_exception_handler = loop.call_exception_handler

    def patched_exception_handler(context: dict[str, Any]) -> None:
        exception = context.get("exception")
        if isinstance(exception, HighSeverityBlockingIoException):
            raise exception
        return original_exception_handler(context)

    loop.call_exception_handler = patched_exception_handler  # type: ignore[method-assign]

    original_call_soon = loop.call_soon

    def patched_call_soon(callback: Callable[..., Any], *args: Any, context: Any = None) -> Any:
        wrapped = _make_monitored_callback(callback, args)
        return original_call_soon(wrapped, context=context)

    loop.call_soon = patched_call_soon  # type: ignore[method-assign]

    original_call_later = loop.call_later

    def patched_call_later(delay: float, callback: Callable[..., Any], *args: Any, context: Any = None) -> Any:
        wrapped = _make_monitored_callback(callback, args)
        return original_call_later(delay, wrapped, context=context)

    loop.call_later = patched_call_later  # type: ignore[method-assign]

    original_call_at = loop.call_at

    def patched_call_at(when: float, callback: Callable[..., Any], *args: Any, context: Any = None) -> Any:
        wrapped = _make_monitored_callback(callback, args)
        return original_call_at(when, wrapped, context=context)

    loop.call_at = patched_call_at  # type: ignore[method-assign]

    original_call_soon_threadsafe = loop.call_soon_threadsafe

    def patched_call_soon_threadsafe(callback: Callable[..., Any], *args: Any, context: Any = None) -> Any:
        wrapped = _make_monitored_callback(callback, args)
        return original_call_soon_threadsafe(wrapped, context=context)

    loop.call_soon_threadsafe = patched_call_soon_threadsafe  # type: ignore[method-assign]


def _make_monitored_callback(callback: Callable[..., Any], args: tuple[Any, ...]) -> Callable[[], Any]:
    """
    Create a wrapper that monitors callback execution time and blocking events.

    The wrapper is called with no arguments - the original args are captured
    in the closure and passed to the callback.
    """

    def monitored_wrapper() -> Any:
        if not is_monitoring_active():
            if args:
                return callback(*args)
            return callback()

        thread_local = _get_thread_local()
        captured_events: list[Any] = []

        previous_events = getattr(thread_local, "blocking_events", None)
        thread_local.blocking_events = captured_events
        thread_local.blocking_context = None
        thread_local.should_raise_for_this_handle = False

        _reset_exception_flag()

        pre_context = _capture_context()

        t0 = perf_counter_ns()

        try:
            if args:
                return_value = callback(*args)
            else:
                return_value = callback()
        finally:
            thread_local.blocking_events = previous_events

        post_context = _capture_context()
        captured_context = {**pre_context, **{k: v for k, v in post_context.items() if v is not None}}

        should_raise = getattr(thread_local, "should_raise_for_this_handle", False)

        try:
            elapsed = perf_counter_ns() - t0
            elapsed_ms = elapsed / 1_000_000
            threshold_ms = _slow_task_threshold_ns / 1_000_000
            exceeded_threshold = elapsed >= _slow_task_threshold_ns

            has_events = len(captured_events) > 0

            blocking_context = getattr(thread_local, "blocking_context", None)

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

                _invoke_callbacks_with_context(
                    slow_task_event, blocking_context if blocking_context is not None else captured_context
                )

                if exceeded_threshold is True:
                    _check_and_raise_if_needed(elapsed, formatted_events, should_raise)

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

                _invoke_callbacks_with_context(slow_task_event, captured_context)

        except HighSeverityBlockingIoException:
            raise
        except Exception as ex:
            logger.error("Error while checking async task execution time: %s", ex)

        return return_value

    return monitored_wrapper


def _invoke_callbacks_with_context(event: SlowTaskEvent, captured_context: dict[str, Any]) -> None:
    """
    Attach pre-captured context to the event and invoke callbacks.
    """
    event_with_context = replace(event, context=captured_context)
    _invoke_slow_task_callbacks(event_with_context)


def _check_and_raise_if_needed(
    elapsed: int, blocking_events: list[BlockingEventInfo] | None, should_raise: bool
) -> None:
    """Check if high severity blocking IO should raise an exception."""
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
