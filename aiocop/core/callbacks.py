"""Callback registry for aiocop events."""

from collections.abc import Callable
from typing import Any

from aiocop.types.events import SlowTaskEvent

SlowTaskCallback = Callable[[SlowTaskEvent], None]
ContextProvider = Callable[[], dict[str, Any]]

_slow_task_callbacks: list[SlowTaskCallback] = []
_context_providers: list[ContextProvider] = []


def register_slow_task_callback(callback: SlowTaskCallback) -> None:
    """Register a callback to be invoked when a slow task is detected."""
    if callback not in _slow_task_callbacks:
        _slow_task_callbacks.append(callback)


def unregister_slow_task_callback(callback: SlowTaskCallback) -> None:
    """Unregister a previously registered slow task callback."""
    if callback in _slow_task_callbacks:
        _slow_task_callbacks.remove(callback)


def clear_slow_task_callbacks() -> None:
    """Clear all registered slow task callbacks."""
    _slow_task_callbacks.clear()


def register_context_provider(provider: ContextProvider) -> None:
    """
    Register a context provider to capture context at the START of each task.

    Context providers are called before the task runs, allowing you to capture
    things like tracing spans that might not be available after the task completes.

    The provider should return a dict that will be merged into SlowTaskEvent.context.
    """
    if provider not in _context_providers:
        _context_providers.append(provider)


def unregister_context_provider(provider: ContextProvider) -> None:
    """Unregister a previously registered context provider."""
    if provider in _context_providers:
        _context_providers.remove(provider)


def clear_context_providers() -> None:
    """Clear all registered context providers."""
    _context_providers.clear()


def _capture_context() -> dict[str, Any]:
    """Capture context from all registered providers. Internal use only."""
    import logging

    logger = logging.getLogger(__name__)
    context: dict[str, Any] = {}

    for provider in _context_providers:
        try:
            provider_context = provider()
            if provider_context is not None:
                context.update(provider_context)
        except Exception as e:
            logger.warning("Error in context provider %s: %s", getattr(provider, "__name__", repr(provider)), e)

    return context


def _invoke_slow_task_callbacks(event: SlowTaskEvent) -> None:
    """Invoke all registered slow task callbacks. Internal use only."""
    import logging

    logger = logging.getLogger(__name__)

    for callback in _slow_task_callbacks:
        try:
            callback(event)
        except Exception as e:
            logger.warning("Error in slow task callback %s: %s", getattr(callback, "__name__", repr(callback)), e)
