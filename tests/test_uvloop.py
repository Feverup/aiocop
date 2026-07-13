"""Tests for uvloop compatibility.

These tests verify that aiocop works correctly with uvloop.
They are skipped on Windows or if uvloop is not installed.

Note: pytest-asyncio manages its own event loops, so we use uvloop.run()
for tests that need to verify uvloop-specific behavior.
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

# Skip entire module on Windows or if uvloop not available
uvloop = pytest.importorskip("uvloop", reason="uvloop not available")

if sys.platform == "win32":
    pytest.skip("uvloop not supported on Windows", allow_module_level=True)

import aiocop  # noqa: E402
from aiocop.core import slow_tasks, state  # noqa: E402
from aiocop.types.events import SlowTaskEvent  # noqa: E402

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_aiocop_state():
    """Reset aiocop state before and after each test.

    This is critical for uvloop tests since we need fresh state
    for each test to properly test loop patching.

    Note: _detect_slow_tasks_configured is reset since it gates a fresh event
    loop object created every test. _patch_audit_functions_configured and
    _start_blocking_io_detection_configured are NOT reset - they guard
    permanent, process-wide state with no teardown, so resetting them would
    re-wrap functions and re-register the audit hook each test.
    """
    # Reset before test
    state._monitoring_active = False
    state._on_activate_hooks.clear()
    slow_tasks._detect_slow_tasks_configured = False
    aiocop.clear_slow_task_callbacks()
    aiocop.clear_context_providers()

    yield

    # Reset after test
    state._monitoring_active = False
    state._on_activate_hooks.clear()
    slow_tasks._detect_slow_tasks_configured = False
    aiocop.clear_slow_task_callbacks()
    aiocop.clear_context_providers()


# =============================================================================
# Helper to run async code with uvloop
# =============================================================================


def run_with_uvloop(coro):
    """Run a coroutine using uvloop.run() to ensure uvloop is used."""
    return uvloop.run(coro)


# =============================================================================
# Tests using uvloop.run() directly
# =============================================================================


class TestUvloopWithRun:
    """Tests that use uvloop.run() to ensure uvloop is actually used."""

    def test_uvloop_run_uses_uvloop(self):
        """Verify that uvloop.run() actually uses uvloop."""

        async def check_loop():
            loop = asyncio.get_running_loop()
            return type(loop).__name__

        loop_type = run_with_uvloop(check_loop())
        assert loop_type == "Loop", f"Expected uvloop.Loop, got {loop_type}"

    def test_detects_blocking_io_with_uvloop_run(self, reset_aiocop_state):
        """Test blocking IO detection using uvloop.run()."""
        captured_events: list[SlowTaskEvent] = []

        def callback(event: SlowTaskEvent) -> None:
            captured_events.append(event)

        async def main():
            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=10)
            aiocop.detect_slow_tasks(threshold_ms=10)
            aiocop.register_slow_task_callback(callback)
            aiocop.activate()

            # Verify we're on uvloop
            loop = asyncio.get_running_loop()
            assert type(loop).__name__ == "Loop", "Not running on uvloop!"

            async def task_with_sleep():
                time.sleep(0.02)

            task = asyncio.create_task(task_with_sleep())
            await task
            await asyncio.sleep(0)

        run_with_uvloop(main())

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.reason == "io_blocking"
        event_names = [e["event"] for e in event.blocking_events]
        assert any("time.sleep" in name for name in event_names)

    def test_loop_is_patched_with_uvloop_run(self, reset_aiocop_state):
        """Test that uvloop loop gets patched correctly."""

        async def main():
            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=10)
            aiocop.detect_slow_tasks(threshold_ms=10)
            aiocop.activate()

            loop = asyncio.get_running_loop()
            assert type(loop).__name__ == "Loop", "Not running on uvloop!"
            assert hasattr(loop, "_aiocop_patched")
            assert loop._aiocop_patched is True

        run_with_uvloop(main())

    def test_context_providers_with_uvloop_run(self, reset_aiocop_state):
        """Test context providers work with uvloop."""
        captured_events: list[SlowTaskEvent] = []

        def callback(event: SlowTaskEvent) -> None:
            captured_events.append(event)

        def my_context_provider() -> dict[str, Any]:
            return {"uvloop_test": True}

        async def main():
            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=10)
            aiocop.detect_slow_tasks(threshold_ms=10)
            aiocop.register_slow_task_callback(callback)
            aiocop.register_context_provider(my_context_provider)
            aiocop.activate()

            async def task_with_io():
                time.sleep(0.015)

            task = asyncio.create_task(task_with_io())
            await task
            await asyncio.sleep(0)

        run_with_uvloop(main())

        assert len(captured_events) >= 1
        assert captured_events[0].context.get("uvloop_test") is True

    def test_severity_calculation_with_uvloop_run(self, reset_aiocop_state):
        """Test severity is calculated correctly with uvloop."""
        captured_events: list[SlowTaskEvent] = []

        def callback(event: SlowTaskEvent) -> None:
            captured_events.append(event)

        async def main():
            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=10)
            aiocop.detect_slow_tasks(threshold_ms=10)
            aiocop.register_slow_task_callback(callback)
            aiocop.activate()

            async def task_with_heavy_io():
                time.sleep(0.015)  # WEIGHT_HEAVY = 50

            task = asyncio.create_task(task_with_heavy_io())
            await task
            await asyncio.sleep(0)

        run_with_uvloop(main())

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.severity_score >= 50
        assert event.severity_level == "high"

    def test_file_io_detection_with_uvloop_run(self, reset_aiocop_state):
        """Test file IO is detected with uvloop."""
        captured_events: list[SlowTaskEvent] = []

        def callback(event: SlowTaskEvent) -> None:
            captured_events.append(event)

        async def main():
            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=10)
            aiocop.detect_slow_tasks(threshold_ms=10)
            aiocop.register_slow_task_callback(callback)
            aiocop.activate()

            async def task_with_file_io():
                with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                    f.write("test")
                    temp_path = f.name
                Path(temp_path).unlink()

            task = asyncio.create_task(task_with_file_io())
            await task
            await asyncio.sleep(0)

        run_with_uvloop(main())

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.reason == "io_blocking"
        event_names = [e["event"] for e in event.blocking_events]
        assert any("open" in name or "tempfile" in name for name in event_names)

    def test_deactivated_no_detection_with_uvloop_run(self, reset_aiocop_state):
        """Test no detection when deactivated with uvloop."""
        captured_events: list[SlowTaskEvent] = []

        def callback(event: SlowTaskEvent) -> None:
            captured_events.append(event)

        async def main():
            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=10)
            aiocop.detect_slow_tasks(threshold_ms=10)
            aiocop.register_slow_task_callback(callback)
            # Note: NOT calling aiocop.activate()

            async def task_with_io():
                time.sleep(0.015)

            task = asyncio.create_task(task_with_io())
            await task
            await asyncio.sleep(0)

        run_with_uvloop(main())

        assert len(captured_events) == 0

    def test_exceeded_threshold_flag_with_uvloop_run(self, reset_aiocop_state):
        """Test exceeded_threshold flag is set correctly with uvloop."""
        captured_events: list[SlowTaskEvent] = []

        def callback(event: SlowTaskEvent) -> None:
            captured_events.append(event)

        async def main():
            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=10)
            aiocop.detect_slow_tasks(threshold_ms=10)
            aiocop.register_slow_task_callback(callback)
            aiocop.activate()

            async def slow_task():
                time.sleep(0.02)  # 20ms, threshold is 10ms

            task = asyncio.create_task(slow_task())
            await task
            await asyncio.sleep(0)

        run_with_uvloop(main())

        assert len(captured_events) >= 1
        event = captured_events[0]
        assert event.exceeded_threshold is True
        assert event.elapsed_ms >= 10
