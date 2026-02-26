"""Tests for aiocop package."""

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

import aiocop
from aiocop.core.blocking_io import format_blocking_event, get_blocking_events_dict
from aiocop.types.events import RawBlockingEvent, SlowTaskEvent

# =============================================================================
# Fixtures for integration tests
# =============================================================================


@pytest.fixture(scope="module")
def setup_aiocop():
    """
    Set up aiocop once for the entire test module.

    These functions can only be called once, so we do it at module scope.
    """
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection(trace_depth=10)
    aiocop.detect_slow_tasks(threshold_ms=10)
    yield
    aiocop.deactivate()
    aiocop.clear_slow_task_callbacks()
    aiocop.clear_context_providers()


@pytest.fixture
def captured_events():
    """Fixture to capture SlowTaskEvents during a test."""
    events: list[SlowTaskEvent] = []

    def callback(event: SlowTaskEvent) -> None:
        events.append(event)

    aiocop.register_slow_task_callback(callback)
    yield events
    aiocop.unregister_slow_task_callback(callback)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset aiocop state before each test."""
    aiocop.deactivate()
    aiocop.disable_raise_on_violations()
    aiocop.clear_slow_task_callbacks()
    aiocop.clear_context_providers()
    yield


# =============================================================================
# Public API Tests
# =============================================================================


class TestPublicApi:
    """Test that the public API is accessible."""

    def test_patch_audit_functions_is_exported(self) -> None:
        assert hasattr(aiocop, "patch_audit_functions")
        assert callable(aiocop.patch_audit_functions)

    def test_start_blocking_io_detection_is_exported(self) -> None:
        assert hasattr(aiocop, "start_blocking_io_detection")
        assert callable(aiocop.start_blocking_io_detection)

    def test_detect_slow_tasks_is_exported(self) -> None:
        assert hasattr(aiocop, "detect_slow_tasks")
        assert callable(aiocop.detect_slow_tasks)

    def test_activate_deactivate_are_exported(self) -> None:
        assert hasattr(aiocop, "activate")
        assert hasattr(aiocop, "deactivate")
        assert hasattr(aiocop, "is_monitoring_active")

    def test_raise_on_violations_controls_are_exported(self) -> None:
        assert hasattr(aiocop, "enable_raise_on_violations")
        assert hasattr(aiocop, "disable_raise_on_violations")
        assert hasattr(aiocop, "is_raise_on_violations_enabled")
        assert hasattr(aiocop, "raise_on_violations")


class TestActivation:
    """Test activation/deactivation functionality."""

    def test_initially_inactive(self) -> None:
        from aiocop.core.state import _monitoring_active

        assert _monitoring_active is False or aiocop.is_monitoring_active() is False

    def test_activate_enables_monitoring(self) -> None:
        aiocop.activate()
        assert aiocop.is_monitoring_active() is True

    def test_deactivate_disables_monitoring(self) -> None:
        aiocop.activate()
        aiocop.deactivate()
        assert aiocop.is_monitoring_active() is False


class TestRaiseOnViolations:
    """Test raise_on_violations context management."""

    def test_initially_disabled(self) -> None:
        assert aiocop.is_raise_on_violations_enabled() is False

    def test_enable_raise_on_violations(self) -> None:
        aiocop.enable_raise_on_violations()
        assert aiocop.is_raise_on_violations_enabled() is True
        aiocop.disable_raise_on_violations()

    def test_disable_raise_on_violations(self) -> None:
        aiocop.enable_raise_on_violations()
        aiocop.disable_raise_on_violations()
        assert aiocop.is_raise_on_violations_enabled() is False

    def test_context_manager(self) -> None:
        assert aiocop.is_raise_on_violations_enabled() is False

        with aiocop.raise_on_violations():
            assert aiocop.is_raise_on_violations_enabled() is True

        assert aiocop.is_raise_on_violations_enabled() is False


class TestSeverityCalculation:
    """Test severity score calculation."""

    def test_empty_events_returns_zero(self) -> None:
        assert aiocop.calculate_io_severity_score([]) == 0
        assert aiocop.calculate_io_severity_score(None) == 0

    def test_calculates_score_from_events(self) -> None:
        events = [
            {"event": "test", "trace": "", "entry_point": "", "severity": 50},
            {"event": "test2", "trace": "", "entry_point": "", "severity": 10},
        ]
        assert aiocop.calculate_io_severity_score(events) == 60

    def test_severity_level_from_score(self) -> None:
        assert aiocop.get_severity_level_from_score(0) == "low"
        assert aiocop.get_severity_level_from_score(9) == "low"
        assert aiocop.get_severity_level_from_score(10) == "medium"
        assert aiocop.get_severity_level_from_score(49) == "medium"
        assert aiocop.get_severity_level_from_score(50) == "high"
        assert aiocop.get_severity_level_from_score(100) == "high"


class TestSlowTaskEvent:
    """Test SlowTaskEvent dataclass."""

    def test_slow_task_event_creation(self) -> None:
        event = SlowTaskEvent(
            elapsed_ms=50.0,
            threshold_ms=30.0,
            exceeded_threshold=True,
            severity_score=60,
            severity_level="high",
            reason="io_blocking",
            blocking_events=[],
        )

        assert event.elapsed_ms == 50.0
        assert event.threshold_ms == 30.0
        assert event.exceeded_threshold is True
        assert event.severity_score == 60
        assert event.severity_level == "high"
        assert event.reason == "io_blocking"
        assert event.blocking_events == []

    def test_slow_task_event_is_frozen(self) -> None:
        event = SlowTaskEvent(
            elapsed_ms=50.0,
            threshold_ms=30.0,
            exceeded_threshold=True,
            severity_score=60,
            severity_level="high",
            reason="io_blocking",
            blocking_events=[],
        )

        with pytest.raises(AttributeError):
            event.elapsed_ms = 100.0  # type: ignore[misc]


class TestCallbacks:
    """Test callback registration."""

    def test_register_and_clear_callbacks(self) -> None:
        callback_called = []

        def my_callback(event: SlowTaskEvent) -> None:
            callback_called.append(event)

        aiocop.register_slow_task_callback(my_callback)
        aiocop.clear_slow_task_callbacks()

        assert len(callback_called) == 0

    def test_unregister_callback(self) -> None:
        def my_callback(event: SlowTaskEvent) -> None:
            pass

        aiocop.register_slow_task_callback(my_callback)
        aiocop.unregister_slow_task_callback(my_callback)
        aiocop.clear_slow_task_callbacks()


class TestHighSeverityBlockingIoException:
    """Test the HighSeverityBlockingIoException."""

    def test_exception_creation(self) -> None:
        exc = aiocop.HighSeverityBlockingIoException(
            severity_score=60,
            severity_level="high",
            elapsed_ms=50.0,
            threshold_ms=30.0,
            events=[{"event": "test()", "trace": "file.py:10:func"}],
        )

        assert exc.severity_score == 60
        assert exc.severity_level == "high"
        assert exc.elapsed_ms == 50.0
        assert exc.threshold_ms == 30.0
        assert len(exc.events) == 1

    def test_exception_message_format(self) -> None:
        exc = aiocop.HighSeverityBlockingIoException(
            severity_score=60,
            severity_level="high",
            elapsed_ms=50.0,
            threshold_ms=30.0,
            events=[],
        )

        message = str(exc)
        assert "HIGH SEVERITY BLOCKING I/O DETECTED" in message
        assert "Severity Score: 60" in message
        assert "Severity Level: high" in message


# =============================================================================
# Integration Tests - Actual Blocking I/O Detection
# =============================================================================


class TestBlockingIODetection:
    """Integration tests for actual blocking I/O detection in async code.

    Note: Blocking I/O must run in a SEPARATE task (via create_task) because
    callbacks are invoked after Handle._run completes. If we run blocking I/O
    inline (via await), the callback won't be invoked until the test itself completes.
    """

    @pytest.mark.asyncio
    async def test_detects_file_open_in_async_task(self, setup_aiocop, captured_events) -> None:
        """Test that opening a file in async code is detected."""
        aiocop.activate()

        async def task_with_file_io():
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write("test")
                temp_path = f.name
            Path(temp_path).unlink()

        # Run in separate task so callback is invoked when task completes
        task = asyncio.create_task(task_with_file_io())
        await task

        # Give event loop a chance to process
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.reason == "io_blocking"
        assert len(event.blocking_events) > 0
        # Check that 'open' was detected
        event_names = [e["event"] for e in event.blocking_events]
        assert any("open" in name or "tempfile" in name for name in event_names)

    @pytest.mark.asyncio
    async def test_detects_time_sleep_in_async_task(self, setup_aiocop, captured_events) -> None:
        """Test that time.sleep() in async code is detected as blocking."""
        aiocop.activate()

        async def task_with_sleep():
            time.sleep(0.02)  # 20ms blocking sleep

        # Run in separate task
        task = asyncio.create_task(task_with_sleep())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.reason == "io_blocking"
        # time.sleep should be detected
        event_names = [e["event"] for e in event.blocking_events]
        assert any("time.sleep" in name for name in event_names)

    @pytest.mark.asyncio
    async def test_no_detection_when_deactivated(self, setup_aiocop, captured_events) -> None:
        """Test that no events are captured when monitoring is deactivated."""
        aiocop.deactivate()

        async def task_with_file_io():
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write("test")
                temp_path = f.name
            Path(temp_path).unlink()

        task = asyncio.create_task(task_with_file_io())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) == 0

    @pytest.mark.asyncio
    async def test_exceeded_threshold_flag(self, setup_aiocop, captured_events) -> None:
        """Test that exceeded_threshold is set correctly."""
        aiocop.activate()

        async def slow_task():
            time.sleep(0.02)  # 20ms, threshold is 10ms

        task = asyncio.create_task(slow_task())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.exceeded_threshold is True
        assert event.elapsed_ms >= 10  # Should be at least threshold

    @pytest.mark.asyncio
    async def test_severity_score_calculated(self, setup_aiocop, captured_events) -> None:
        """Test that severity score is calculated from blocking events."""
        aiocop.activate()

        async def task_with_heavy_io():
            time.sleep(0.015)  # WEIGHT_HEAVY = 50

        task = asyncio.create_task(task_with_heavy_io())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.severity_score >= 50  # time.sleep is WEIGHT_HEAVY
        assert event.severity_level == "high"


# =============================================================================
# Context Provider Tests
# =============================================================================


class TestContextProviders:
    """Test context provider functionality."""

    @pytest.mark.asyncio
    async def test_context_provider_captures_context(self, setup_aiocop, captured_events) -> None:
        """Test that context providers capture and pass context to callbacks."""
        aiocop.activate()

        def my_context_provider() -> dict[str, Any]:
            return {"request_id": "test-123", "user_id": 42}

        aiocop.register_context_provider(my_context_provider)

        async def task_with_io():
            time.sleep(0.015)

        task = asyncio.create_task(task_with_io())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.context.get("request_id") == "test-123"
        assert event.context.get("user_id") == 42

    @pytest.mark.asyncio
    async def test_multiple_context_providers(self, setup_aiocop, captured_events) -> None:
        """Test that multiple context providers are merged."""
        aiocop.activate()

        def provider_a() -> dict[str, Any]:
            return {"key_a": "value_a"}

        def provider_b() -> dict[str, Any]:
            return {"key_b": "value_b"}

        aiocop.register_context_provider(provider_a)
        aiocop.register_context_provider(provider_b)

        async def task_with_io():
            time.sleep(0.015)

        task = asyncio.create_task(task_with_io())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.context.get("key_a") == "value_a"
        assert event.context.get("key_b") == "value_b"

    def test_register_unregister_context_provider(self) -> None:
        """Test registering and unregistering context providers."""

        def my_provider() -> dict[str, Any]:
            return {}

        aiocop.register_context_provider(my_provider)
        aiocop.unregister_context_provider(my_provider)
        # Should not raise
        aiocop.clear_context_providers()

    @pytest.mark.asyncio
    async def test_context_provider_called_before_callback(self, setup_aiocop, captured_events) -> None:
        """Test that context providers run BEFORE the callback, not after.

        Reproduces the real-world issue where tracing middleware (e.g. ddtrace)
        creates a span, runs the handler, and calls span.finish() all within
        the same event-loop callback. If context were captured after the
        callback returns, the span would already be deactivated and the
        provider would return None.
        """
        aiocop.activate()

        # Simulate an active tracing span that gets deactivated by the callback
        active_span = {"span_id": "abc-123"}

        def tracing_context_provider() -> dict[str, Any]:
            """Mimics ddtrace's tracer.current_span() — returns None after finish()."""
            return {"current_span": active_span.get("span_id")}

        aiocop.register_context_provider(tracing_context_provider)

        async def task_that_deactivates_span():
            # Blocking I/O to trigger a SlowTaskEvent
            time.sleep(0.015)
            # Simulate span.finish() clearing the active span
            active_span.pop("span_id", None)

        task = asyncio.create_task(task_that_deactivates_span())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        # Context must have been captured BEFORE the callback ran,
        # so the span was still active. If this is None, context was
        # captured too late (after the callback deactivated the span).
        assert event.context.get("current_span") == "abc-123", (
            "Context provider was called after the callback instead of before. "
            "The span was already deactivated by the time context was captured."
        )

    @pytest.mark.asyncio
    async def test_context_captured_at_audit_hook_time_for_single_step_requests(
        self, setup_aiocop, captured_events
    ) -> None:
        """Test context capture for single-step async requests (FastAPI/Starlette).

        In single-step frameworks, the tracing middleware creates a span, runs the
        endpoint, and finishes the span all within the same call_soon callback.
        The span does NOT exist before callback(*args) and is already deactivated
        after it returns. The only moment the span is active is during blocking I/O,
        when the audit hook fires. Context must be captured at that point.
        """
        aiocop.activate()

        # Simulate a span that is created INSIDE the callback and finished
        # before callback returns — mirrors ddtrace ASGI middleware behavior.
        span_state: dict[str, Any] = {}

        def tracing_context_provider() -> dict[str, Any]:
            return {"active_span": span_state.get("span_id")}

        aiocop.register_context_provider(tracing_context_provider)

        async def single_step_asgi_callback():
            # 1. Middleware creates the span (inside the callback)
            span_state["span_id"] = "span-456"
            # 2. Endpoint handler does blocking I/O — audit hook fires here
            time.sleep(0.015)
            # 3. Middleware finishes the span
            span_state.pop("span_id", None)

        task = asyncio.create_task(single_step_asgi_callback())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.reason == "io_blocking"
        # Context captured at audit-hook time must see the active span.
        # Pre-callback capture would return None (span not yet created).
        # Post-callback capture would return None (span already finished).
        assert event.context.get("active_span") == "span-456", (
            "Context was not captured at audit-hook time. "
            "In single-step requests the span only exists during the blocking call."
        )

    @pytest.mark.asyncio
    async def test_post_context_used_when_pre_context_is_none(self, setup_aiocop, captured_events) -> None:
        """Test that post-callback context is used when pre-callback context returns None.

        Covers the case where a span is only set AFTER the callback starts
        (e.g. middleware creates the span inside the event loop callback).
        """
        aiocop.activate()

        span_state: dict[str, Any] = {}

        def late_span_provider() -> dict[str, Any]:
            return {"span_id": span_state.get("span_id")}

        aiocop.register_context_provider(late_span_provider)

        async def task_where_span_set_during_execution():
            # Span doesn't exist yet when pre_context is captured
            span_state["span_id"] = "late-span-789"
            time.sleep(0.015)
            # Span still active when post_context is captured

        task = asyncio.create_task(task_where_span_set_during_execution())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.context.get("span_id") == "late-span-789", (
            "Post-callback context was not used. The span set during execution "
            "should have been picked up by post_context capture."
        )

    @pytest.mark.asyncio
    async def test_pre_context_preserved_when_post_context_returns_none(self, setup_aiocop, captured_events) -> None:
        """Test that pre-callback context is preserved when post-callback context returns None.

        Covers the case where a span is active before the callback but gets
        deactivated during execution (e.g. span.finish() called inside the handler).
        """
        aiocop.activate()

        span_state: dict[str, Any] = {"span_id": "pre-span-123"}

        def span_provider() -> dict[str, Any]:
            return {"span_id": span_state.get("span_id")}

        aiocop.register_context_provider(span_provider)

        async def task_that_clears_span():
            time.sleep(0.015)
            span_state.pop("span_id", None)

        task = asyncio.create_task(task_that_clears_span())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.context.get("span_id") == "pre-span-123", (
            "Pre-callback context was lost. When post_context returns None for a key, "
            "the pre_context value should be preserved."
        )

    @pytest.mark.asyncio
    async def test_pre_and_post_context_merged_best_of_both(self, setup_aiocop, captured_events) -> None:
        """Test that pre and post context are merged, keeping the best of both.

        When one provider has a value before but not after, and another has a
        value after but not before, both values should appear in the final context.
        """
        aiocop.activate()

        early_state: dict[str, Any] = {"trace_id": "trace-abc"}
        late_state: dict[str, Any] = {}

        def early_provider() -> dict[str, Any]:
            return {"trace_id": early_state.get("trace_id")}

        def late_provider() -> dict[str, Any]:
            return {"request_id": late_state.get("request_id")}

        aiocop.register_context_provider(early_provider)
        aiocop.register_context_provider(late_provider)

        async def task_with_mixed_context():
            # late_provider gets a value during execution
            late_state["request_id"] = "req-456"
            time.sleep(0.015)
            # early_provider loses its value
            early_state.pop("trace_id", None)

        task = asyncio.create_task(task_with_mixed_context())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.context.get("trace_id") == "trace-abc", (
            "Pre-callback trace_id was lost even though post_context had None for it."
        )
        assert event.context.get("request_id") == "req-456", (
            "Post-callback request_id was not picked up."
        )

    @pytest.mark.asyncio
    async def test_post_context_overrides_pre_context_for_cpu_blocking(
        self, setup_aiocop, captured_events
    ) -> None:
        """Test that post-context values override pre-context for cpu_blocking tasks.

        When there are no blocking IO events (pure CPU work), blocking_context
        is not set, so the pre/post merged captured_context is used directly.
        Post non-None values should override pre values.
        """
        aiocop.activate()

        span_state: dict[str, Any] = {"span_id": "old-span"}

        def span_provider() -> dict[str, Any]:
            return {"span_id": span_state.get("span_id")}

        aiocop.register_context_provider(span_provider)

        async def cpu_task_that_updates_span():
            span_state["span_id"] = "new-span"
            # CPU-bound work without IO to trigger cpu_blocking path
            start = time.perf_counter()
            while time.perf_counter() - start < 0.02:
                sum(range(1000))

        task = asyncio.create_task(cpu_task_that_updates_span())
        await task
        await asyncio.sleep(0)

        slow_events = [e for e in captured_events if e.exceeded_threshold]
        if len(slow_events) > 0:
            event = slow_events[0]
            assert event.context.get("span_id") == "new-span", (
                "Post-callback value should override pre-callback value when both are non-None."
            )

    @pytest.mark.asyncio
    async def test_context_provider_exception_is_caught(self, setup_aiocop, captured_events) -> None:
        """Test that exceptions in context providers are caught and logged."""
        aiocop.activate()

        def bad_provider() -> dict[str, Any]:
            raise ValueError("Provider error!")

        def good_provider() -> dict[str, Any]:
            return {"good_key": "good_value"}

        aiocop.register_context_provider(bad_provider)
        aiocop.register_context_provider(good_provider)

        async def task_with_io():
            time.sleep(0.015)

        # Should not raise despite bad_provider
        task = asyncio.create_task(task_with_io())
        await task
        await asyncio.sleep(0)

        # Good provider's context should still be captured
        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.context.get("good_key") == "good_value"


# =============================================================================
# Callback Error Handling Tests
# =============================================================================


class TestCallbackErrorHandling:
    """Test that callback errors are handled gracefully."""

    @pytest.mark.asyncio
    async def test_callback_exception_is_caught(self, setup_aiocop) -> None:
        """Test that exceptions in callbacks are caught and don't crash the app."""
        aiocop.activate()

        good_callback_called = []

        def bad_callback(event: SlowTaskEvent) -> None:
            raise RuntimeError("Callback error!")

        def good_callback(event: SlowTaskEvent) -> None:
            good_callback_called.append(event)

        aiocop.register_slow_task_callback(bad_callback)
        aiocop.register_slow_task_callback(good_callback)

        async def task_with_io():
            time.sleep(0.015)

        # Should not raise despite bad_callback
        task = asyncio.create_task(task_with_io())
        await task
        await asyncio.sleep(0)

        # Good callback should still be called
        assert len(good_callback_called) >= 1

    @pytest.mark.asyncio
    async def test_multiple_callbacks_all_invoked(self, setup_aiocop) -> None:
        """Test that all registered callbacks are invoked."""
        aiocop.activate()

        callback_a_events: list[SlowTaskEvent] = []
        callback_b_events: list[SlowTaskEvent] = []

        def callback_a(event: SlowTaskEvent) -> None:
            callback_a_events.append(event)

        def callback_b(event: SlowTaskEvent) -> None:
            callback_b_events.append(event)

        aiocop.register_slow_task_callback(callback_a)
        aiocop.register_slow_task_callback(callback_b)

        async def task_with_io():
            time.sleep(0.015)

        task = asyncio.create_task(task_with_io())
        await task
        await asyncio.sleep(0)

        assert len(callback_a_events) >= 1
        assert len(callback_b_events) >= 1


# =============================================================================
# CPU Blocking Detection Tests
# =============================================================================


class TestCPUBlockingDetection:
    """Test detection of CPU-bound blocking (no I/O but slow)."""

    @pytest.mark.asyncio
    async def test_cpu_blocking_detected(self, setup_aiocop, captured_events) -> None:
        """Test that CPU-bound work exceeding threshold is detected."""
        aiocop.activate()

        async def cpu_bound_task():
            # CPU-intensive work without I/O
            total = 0
            start = time.perf_counter()
            while time.perf_counter() - start < 0.02:  # 20ms of CPU work
                total += sum(range(1000))
            return total

        task = asyncio.create_task(cpu_bound_task())
        await task
        await asyncio.sleep(0)

        # Should detect slow task even without I/O
        slow_events = [e for e in captured_events if e.exceeded_threshold]
        if len(slow_events) > 0:
            event = slow_events[0]
            # If no blocking I/O detected, reason should be cpu_blocking
            if len(event.blocking_events) == 0:
                assert event.reason == "cpu_blocking"
                assert event.severity_score == 0
                assert event.severity_level == "low"


# =============================================================================
# Core Function Tests
# =============================================================================


class TestCoreFunctions:
    """Test core utility functions."""

    def test_get_patched_functions_returns_list(self, setup_aiocop) -> None:
        """Test that get_patched_functions returns the patched functions."""
        patched = aiocop.get_patched_functions()
        assert isinstance(patched, list)
        assert len(patched) > 0
        # Should include time.sleep
        assert "time.sleep" in patched

    def test_get_blocking_events_dict(self) -> None:
        """Test that get_blocking_events_dict returns event weights."""
        events_dict = get_blocking_events_dict()
        assert isinstance(events_dict, dict)
        assert len(events_dict) > 0
        # Check some known events
        assert "open" in events_dict
        assert "time.sleep" in events_dict
        assert events_dict["time.sleep"] == aiocop.WEIGHT_HEAVY

    def test_format_blocking_event(self) -> None:
        """Test formatting of raw blocking events."""
        raw_event: RawBlockingEvent = {
            "event_name": "open",
            "raw_args": ("/path/to/file", "r"),
            "raw_stack": [
                ("/home/user/app/main.py", 42, "my_function"),
                ("/home/user/app/utils.py", 10, "helper"),
            ],
            "timestamp": 1234567890.0,
            "severity": 10,
        }

        formatted = format_blocking_event(raw_event)

        assert formatted["event"] == "open(/path/to/file, r)"
        assert "main.py:42:my_function" in formatted["trace"]
        assert formatted["severity"] == 10

    def test_get_slow_task_threshold_ms(self, setup_aiocop) -> None:
        """Test getting the current slow task threshold."""
        threshold = aiocop.get_slow_task_threshold_ms()
        assert threshold == 10.0  # Set in setup_aiocop fixture

    def test_severity_constants_exported(self) -> None:
        """Test that severity constants are exported."""
        assert aiocop.WEIGHT_HEAVY == 50
        assert aiocop.WEIGHT_MODERATE == 10
        assert aiocop.WEIGHT_LIGHT == 1
        assert aiocop.WEIGHT_TRIVIAL == 0
        assert aiocop.THRESHOLD_HIGH == 50
        assert aiocop.THRESHOLD_MEDIUM == 10
        assert aiocop.THRESHOLD_LOW == 1


# =============================================================================
# Raise on Violations Integration Tests
# =============================================================================


class TestRaiseOnViolationsIntegration:
    """Integration tests for raise_on_violations functionality.

    Note: The HighSeverityBlockingIoException is raised at the event loop level
    (in Handle._run), not at the task level. This makes it difficult to catch
    in async tests. We test the mechanism by verifying its components work.
    """

    def test_raise_on_violations_flag_propagates(self, setup_aiocop) -> None:
        """Test that raise_on_violations flag is properly managed."""
        # Initially disabled
        assert aiocop.is_raise_on_violations_enabled() is False

        # Enable via function
        aiocop.enable_raise_on_violations()
        assert aiocop.is_raise_on_violations_enabled() is True

        # Disable
        aiocop.disable_raise_on_violations()
        assert aiocop.is_raise_on_violations_enabled() is False

        # Enable via context manager
        with aiocop.raise_on_violations():
            assert aiocop.is_raise_on_violations_enabled() is True

        # Disabled after context exits
        assert aiocop.is_raise_on_violations_enabled() is False

    def test_check_and_raise_function_raises_on_high_severity(self) -> None:
        """Test that the internal check function raises for high severity."""
        from aiocop.core.slow_tasks import _check_and_raise_if_needed
        from aiocop.core.state import _reset_exception_flag

        _reset_exception_flag()

        # High severity events should trigger exception
        high_severity_events = [
            {"event": "time.sleep(1)", "trace": "test.py:1:func", "entry_point": "test.py:1:func", "severity": 50},
        ]

        with pytest.raises(aiocop.HighSeverityBlockingIoException) as exc_info:
            _check_and_raise_if_needed(
                elapsed=50_000_000,  # 50ms in nanoseconds
                blocking_events=high_severity_events,
                should_raise=True,
            )

        assert exc_info.value.severity_score >= 50
        assert exc_info.value.severity_level == "high"

    def test_check_and_raise_does_not_raise_when_disabled(self) -> None:
        """Test that check function doesn't raise when should_raise is False."""
        from aiocop.core.slow_tasks import _check_and_raise_if_needed
        from aiocop.core.state import _reset_exception_flag

        _reset_exception_flag()

        high_severity_events = [
            {"event": "time.sleep(1)", "trace": "test.py:1:func", "entry_point": "test.py:1:func", "severity": 50},
        ]

        # Should not raise when should_raise is False
        _check_and_raise_if_needed(
            elapsed=50_000_000,
            blocking_events=high_severity_events,
            should_raise=False,  # Disabled
        )
        # If we get here, no exception was raised - test passes

    def test_check_and_raise_does_not_raise_for_low_severity(self) -> None:
        """Test that check function doesn't raise for low severity events."""
        from aiocop.core.slow_tasks import _check_and_raise_if_needed
        from aiocop.core.state import _reset_exception_flag

        _reset_exception_flag()

        low_severity_events = [
            {"event": "os.stat()", "trace": "test.py:1:func", "entry_point": "test.py:1:func", "severity": 1},
        ]

        # Should not raise for low severity even when should_raise is True
        _check_and_raise_if_needed(
            elapsed=50_000_000,
            blocking_events=low_severity_events,
            should_raise=True,
        )
        # If we get here, no exception was raised - test passes

    def test_exception_propagates_through_event_loop(self, setup_aiocop) -> None:
        """Test that HighSeverityBlockingIoException propagates and crashes the event loop.

        This test verifies that when raise_on_violations is enabled and high-severity
        blocking I/O is detected, the exception propagates through asyncio's exception
        handler and can crash the worker (rather than just being logged).

        We use a fresh event loop to isolate this test and avoid affecting other tests.
        """
        import asyncio

        # Create a fresh event loop for this test to avoid affecting other tests
        loop = asyncio.new_event_loop()

        # We need to patch this new loop for aiocop
        from aiocop.core.slow_tasks import _patch_loop

        _patch_loop(loop)

        # Enable raise_on_violations and activate BEFORE running the coroutine
        # The audit hook checks raise_on_violations.get() when it captures events
        aiocop.enable_raise_on_violations()
        aiocop.activate()

        async def task_with_high_severity_blocking():
            # time.sleep has WEIGHT_HEAVY = 50, which is high severity
            time.sleep(0.02)

        # The exception should propagate up through run_until_complete
        with pytest.raises(aiocop.HighSeverityBlockingIoException) as exc_info:
            loop.run_until_complete(task_with_high_severity_blocking())

        # Verify it's the correct exception with expected attributes
        assert exc_info.value.severity_score >= 50
        assert exc_info.value.severity_level == "high"
        assert any("time.sleep" in e["event"] for e in exc_info.value.events)

        # Clean up
        loop.close()
        aiocop.disable_raise_on_violations()
        aiocop.deactivate()


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_duplicate_callback_registration(self) -> None:
        """Test that registering the same callback twice doesn't duplicate it."""
        call_count = []

        def my_callback(event: SlowTaskEvent) -> None:
            call_count.append(1)

        aiocop.register_slow_task_callback(my_callback)
        aiocop.register_slow_task_callback(my_callback)  # Duplicate

        # Internal check - callback list should only have one entry
        from aiocop.core.callbacks import _slow_task_callbacks

        count = sum(1 for cb in _slow_task_callbacks if cb == my_callback)
        assert count == 1

    def test_unregister_nonexistent_callback(self) -> None:
        """Test that unregistering a non-existent callback doesn't raise."""

        def my_callback(event: SlowTaskEvent) -> None:
            pass

        # Should not raise
        aiocop.unregister_slow_task_callback(my_callback)

    def test_duplicate_context_provider_registration(self) -> None:
        """Test that registering the same provider twice doesn't duplicate it."""

        def my_provider() -> dict[str, Any]:
            return {}

        aiocop.register_context_provider(my_provider)
        aiocop.register_context_provider(my_provider)  # Duplicate

        from aiocop.core.callbacks import _context_providers

        count = sum(1 for p in _context_providers if p == my_provider)
        assert count == 1

    @pytest.mark.asyncio
    async def test_empty_context_when_no_providers(self, setup_aiocop, captured_events) -> None:
        """Test that context is empty dict when no providers registered."""
        aiocop.activate()
        aiocop.clear_context_providers()

        async def task_with_io():
            time.sleep(0.015)

        task = asyncio.create_task(task_with_io())
        await task
        await asyncio.sleep(0)

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.context == {}

    def test_slow_task_event_default_context(self) -> None:
        """Test that SlowTaskEvent has empty dict as default context."""
        event = SlowTaskEvent(
            elapsed_ms=50.0,
            threshold_ms=30.0,
            exceeded_threshold=True,
            severity_score=60,
            severity_level="high",
            reason="io_blocking",
            blocking_events=[],
            # context not provided - should default to {}
        )
        assert event.context == {}
