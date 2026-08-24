"""
aiocop - Non-intrusive monitoring for Python asyncio.

Detects, pinpoints, and logs blocking IO and CPU calls that freeze your event loop.

Basic Usage:
    import aiocop

    # 1. Patch stdlib functions to emit audit events
    aiocop.patch_audit_functions()

    # 2. Register the audit hook to capture blocking IO
    aiocop.start_blocking_io_detection(trace_depth=20)

    # 3. Patch the event loop to detect slow tasks
    def my_callback(event: aiocop.SlowTaskEvent) -> None:
        if event.exceeded_threshold:
            print(f"Slow task: {event.elapsed_ms}ms, severity: {event.severity_level}")

    # Also starts CPU stack sampling (cpu_sampling=True by default), so
    # cpu_blocking events carry stack attribution like IO events do. To
    # customize sampling, call aiocop.start_cpu_sampling(...) BEFORE this;
    # to disable it, pass cpu_sampling=False.
    aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=my_callback)

    # 4. Activate monitoring when ready (e.g., after startup)
    aiocop.activate()

Dynamic Controls:
    # Pause/resume monitoring at runtime
    aiocop.deactivate()
    aiocop.activate()

    # Check if monitoring is active
    if aiocop.is_monitoring_active():
        ...

    # Raise exceptions on high severity blocking IO (useful for tests)
    aiocop.enable_raise_on_violations()
    aiocop.disable_raise_on_violations()

    # Or use context manager for scoped raise-on-violations:
    with aiocop.raise_on_violations():
        await some_operation()

Context Providers (Optional):
    Context providers allow you to capture external context (like tracing spans)
    that will be passed to your callbacks. The context is captured within the
    asyncio task's context, ensuring proper propagation of contextvars.

    Example with Datadog tracing:

        from ddtrace import tracer

        def datadog_context_provider() -> dict[str, Any]:
            return {"span": tracer.current_span()}

        aiocop.register_context_provider(datadog_context_provider)

        def my_callback(event: aiocop.SlowTaskEvent) -> None:
            span = event.context.get("span")
            if span is not None:
                span.set_tag("slow_task", True)
                span.set_metric("slow_task_ms", event.elapsed_ms)

    Context providers are completely optional. If none are registered,
    event.context will be an empty dict.

SlowTaskEvent Fields:
    - elapsed_ms: float - Time the task took in milliseconds
    - threshold_ms: float - Configured threshold for "slow" tasks
    - exceeded_threshold: bool - True if elapsed_ms >= threshold_ms
    - severity_score: int - Calculated severity score based on IO operations
    - severity_level: str - Human-readable severity ("low", "medium", "high")
    - reason: str - Why the task was flagged ("io_blocking" or "cpu_blocking")
    - blocking_events: list[BlockingEventInfo] - Details of each blocking operation
    - context: dict[str, Any] - Custom context from registered context providers
    - cpu_stack_samples: list[CpuStackSample] - Aggregated main-thread stack samples
      captured during the slice (empty unless start_cpu_sampling() was called)

Severity Levels:
    aiocop calculates severity based on the type and number of blocking operations:
    - WEIGHT_HEAVY (50): Network, DB, subprocess, time.sleep
    - WEIGHT_MODERATE (10): File I/O, mutations
    - WEIGHT_LIGHT (1): Stat, access checks
    - WEIGHT_TRIVIAL (0): Negligible operations

    Thresholds for severity levels:
    - THRESHOLD_LOW (1): "low" severity
    - THRESHOLD_MEDIUM (10): "medium" severity
    - THRESHOLD_HIGH (50): "high" severity (triggers exceptions if raise_on_violations)
"""

from importlib.metadata import metadata

_metadata = metadata("aiocop")
__version__ = _metadata["Version"]
__author__ = _metadata["Author-email"]

# ruff: noqa: E402 - imports must be after metadata loading
from aiocop.core.audit_patcher import get_patched_functions, patch_audit_functions
from aiocop.core.blocking_io import (
    format_blocking_event,
    get_blocking_events_dict,
    reset_blocking_events,
    start_blocking_io_detection,
)
from aiocop.core.callbacks import (
    ContextProvider,
    clear_context_providers,
    clear_slow_task_callbacks,
    register_context_provider,
    register_slow_task_callback,
    unregister_context_provider,
    unregister_slow_task_callback,
)
from aiocop.core.cpu_sampler import is_cpu_sampling_started, start_cpu_sampling
from aiocop.core.severity import calculate_io_severity_score, get_severity_level_from_score
from aiocop.core.slow_tasks import SlowTaskCallback, detect_slow_tasks, get_slow_task_threshold_ms
from aiocop.core.state import (
    activate,
    deactivate,
    disable_raise_on_violations,
    enable_raise_on_violations,
    is_monitoring_active,
    is_raise_on_violations_enabled,
)
from aiocop.core.state import (
    raise_on_violations_context as raise_on_violations,
)
from aiocop.exceptions import HighSeverityBlockingIoException
from aiocop.types.events import BlockingEventInfo, CpuStackSample, RawBlockingEvent, SlowTaskEvent
from aiocop.types.severity import (
    THRESHOLD_HIGH,
    THRESHOLD_LOW,
    THRESHOLD_MEDIUM,
    WEIGHT_HEAVY,
    WEIGHT_LIGHT,
    WEIGHT_MODERATE,
    WEIGHT_TRIVIAL,
    IoSeverityLevel,
)

__all__ = [
    # Setup functions
    "patch_audit_functions",
    "start_blocking_io_detection",
    "detect_slow_tasks",
    "start_cpu_sampling",
    "is_cpu_sampling_started",
    # Activation controls
    "activate",
    "deactivate",
    "is_monitoring_active",
    # Raise on violations controls
    "enable_raise_on_violations",
    "disable_raise_on_violations",
    "is_raise_on_violations_enabled",
    "raise_on_violations",
    # Callback management
    "register_slow_task_callback",
    "unregister_slow_task_callback",
    "clear_slow_task_callbacks",
    # Context provider management
    "register_context_provider",
    "unregister_context_provider",
    "clear_context_providers",
    "ContextProvider",
    # Utility functions
    "reset_blocking_events",
    "format_blocking_event",
    "get_patched_functions",
    "get_blocking_events_dict",
    "get_slow_task_threshold_ms",
    "calculate_io_severity_score",
    "get_severity_level_from_score",
    # Types
    "BlockingEventInfo",
    "CpuStackSample",
    "RawBlockingEvent",
    "SlowTaskEvent",
    "SlowTaskCallback",
    "IoSeverityLevel",
    # Exceptions
    "HighSeverityBlockingIoException",
    # Severity constants
    "WEIGHT_HEAVY",
    "WEIGHT_MODERATE",
    "WEIGHT_LIGHT",
    "WEIGHT_TRIVIAL",
    "THRESHOLD_HIGH",
    "THRESHOLD_MEDIUM",
    "THRESHOLD_LOW",
]
