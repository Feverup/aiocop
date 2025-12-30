"""Tests for aiocop package."""

import pytest

import aiocop
from aiocop.types.events import SlowTaskEvent


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
