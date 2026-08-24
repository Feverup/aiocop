"""Tests for CPU stack sampling of slow event-loop slices."""

import asyncio
import os
import subprocess
import sys
import textwrap
import time

import pytest

import aiocop
from aiocop.core import cpu_sampler
from aiocop.types.events import SlowTaskEvent


@pytest.fixture(scope="module")
def setup_aiocop_with_sampler():
    """Set up aiocop with CPU sampling once for the module.

    These functions can only be called once per process, so module scope.
    """
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection(trace_depth=10)
    aiocop.detect_slow_tasks(threshold_ms=30)
    aiocop.start_cpu_sampling(interval_ms=5, arm_after_ms=10, idle_interval_ms=20)
    yield
    aiocop.deactivate()
    aiocop.clear_slow_task_callbacks()
    aiocop.clear_context_providers()


@pytest.fixture
def captured_events():
    events: list[SlowTaskEvent] = []

    def callback(event: SlowTaskEvent) -> None:
        events.append(event)

    aiocop.register_slow_task_callback(callback)
    yield events
    aiocop.unregister_slow_task_callback(callback)


def _burn_cpu(duration_s: float) -> None:
    deadline = time.perf_counter() + duration_s
    while time.perf_counter() < deadline:
        sum(range(1000))


class TestCpuSamplingSetup:
    def test_start_cpu_sampling_is_exported(self) -> None:
        assert hasattr(aiocop, "start_cpu_sampling")
        assert hasattr(aiocop, "is_cpu_sampling_started")

    def test_package_dir_matches_the_installed_package(self) -> None:
        """The frame filter only works if the prefix is the real package dir."""
        assert cpu_sampler.__file__.startswith(cpu_sampler._AIOCOP_PACKAGE_DIR)

    def test_start_is_idempotent(self, setup_aiocop_with_sampler) -> None:
        assert aiocop.is_cpu_sampling_started() is True
        aiocop.start_cpu_sampling()  # second call must be a no-op
        assert aiocop.is_cpu_sampling_started() is True


class TestCpuSampling:
    def test_cpu_bound_slice_gets_stack_samples(self, setup_aiocop_with_sampler, captured_events) -> None:
        async def handler() -> None:
            await asyncio.sleep(0)
            _burn_cpu(0.08)

        async def main() -> None:
            aiocop.activate()
            await asyncio.create_task(handler())
            await asyncio.sleep(0)

        asyncio.run(main())

        slow = [e for e in captured_events if e.exceeded_threshold and e.reason == "cpu_blocking"]
        assert len(slow) > 0

        samples = slow[0].cpu_stack_samples
        assert len(samples) > 0
        assert samples[0]["count"] >= 1

        top_traces = " || ".join(sample["trace"] for sample in samples)
        assert "_burn_cpu" in top_traces
        # aiocop's own frames (e.g. monitored_wrapper) must be filtered out
        assert "monitored_wrapper" not in top_traces
        assert "slow_tasks.py" not in top_traces

    def test_fast_slices_get_no_samples(self, setup_aiocop_with_sampler, captured_events) -> None:
        async def fast_handler() -> None:
            for _ in range(50):
                await asyncio.sleep(0)

        async def main() -> None:
            aiocop.activate()
            await asyncio.create_task(fast_handler())
            await asyncio.sleep(0)

        asyncio.run(main())

        for event in captured_events:
            assert event.cpu_stack_samples == []

    def test_samples_are_aggregated_with_counts(self, setup_aiocop_with_sampler, captured_events) -> None:
        async def handler() -> None:
            await asyncio.sleep(0)
            _burn_cpu(0.1)

        async def main() -> None:
            aiocop.activate()
            await asyncio.create_task(handler())
            await asyncio.sleep(0)

        asyncio.run(main())

        slow = [e for e in captured_events if e.reason == "cpu_blocking" and e.cpu_stack_samples]
        assert len(slow) > 0

        samples = slow[0].cpu_stack_samples
        counts = [sample["count"] for sample in samples]
        assert counts == sorted(counts, reverse=True)
        assert all(sample["entry_point"] in sample["trace"] for sample in samples)


class TestFormatCpuSamples:
    def test_identical_stacks_collapse_into_one_sample(self) -> None:
        stack = [("/app/src/handler.py", 10, "handle"), ("/app/src/service.py", 42, "compute")]
        formatted = cpu_sampler.format_cpu_samples([stack, stack, stack])

        assert len(formatted) == 1
        assert formatted[0]["count"] == 3
        assert formatted[0]["entry_point"] == "handler.py:10:handle"
        assert formatted[0]["trace"] == "handler.py:10:handle <- service.py:42:compute"

    def test_distinct_stacks_sorted_by_count(self) -> None:
        hot = [("/app/src/hot.py", 1, "hot")]
        rare = [("/app/src/rare.py", 2, "rare")]
        formatted = cpu_sampler.format_cpu_samples([hot, rare, hot])

        assert [sample["count"] for sample in formatted] == [2, 1]
        assert formatted[0]["entry_point"] == "hot.py:1:hot"

    def test_empty_samples_format_to_empty_list(self) -> None:
        assert cpu_sampler.format_cpu_samples([]) == []


class TestCpuSamplingUnderUvloop:
    def test_cpu_bound_slice_gets_stack_samples_on_uvloop(self, setup_aiocop_with_sampler, captured_events) -> None:
        uvloop = pytest.importorskip("uvloop", reason="uvloop not available")
        if sys.platform == "win32":
            pytest.skip("uvloop not supported on Windows")

        async def handler() -> None:
            await asyncio.sleep(0)
            _burn_cpu(0.08)

        async def main() -> None:
            aiocop.activate()
            await asyncio.create_task(handler())
            await asyncio.sleep(0)

        uvloop.run(main())

        slow = [e for e in captured_events if e.exceeded_threshold and e.reason == "cpu_blocking"]
        assert len(slow) > 0

        samples = slow[0].cpu_stack_samples
        assert len(samples) > 0
        assert "_burn_cpu" in " || ".join(sample["trace"] for sample in samples)


class TestForkSafety:
    @pytest.mark.skipif(not hasattr(os, "fork"), reason="fork not available on this platform")
    def test_watchdog_is_restarted_in_forked_child(self) -> None:
        """A child forked after start_cpu_sampling() must sample again.

        Threads do not survive fork(), so without the at-fork hook a
        gunicorn --preload worker would inherit _sampler_started=True with no
        watchdog thread and silently produce no samples. Run the scenario in a
        subprocess to keep fork() out of the (multi-threaded) pytest process.
        """
        script = textwrap.dedent(
            """
            import asyncio
            import os
            import threading
            import time

            import aiocop

            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=5)
            aiocop.detect_slow_tasks(threshold_ms=30)
            aiocop.start_cpu_sampling(interval_ms=5, arm_after_ms=10, idle_interval_ms=20)
            time.sleep(0.05)

            pid = os.fork()
            if pid == 0:
                watchdog_alive = any(t.name == "aiocop-cpu-sampler" for t in threading.enumerate())

                events = []
                aiocop.register_slow_task_callback(events.append)

                def burn(duration_s):
                    deadline = time.perf_counter() + duration_s
                    while time.perf_counter() < deadline:
                        sum(range(1000))

                async def handler():
                    await asyncio.sleep(0)
                    burn(0.08)

                async def main():
                    aiocop.activate()
                    await asyncio.create_task(handler())
                    await asyncio.sleep(0)

                asyncio.run(main())

                sampled = any(e.reason == "cpu_blocking" and e.cpu_stack_samples for e in events)
                print(f"CHILD watchdog_alive={watchdog_alive} sampled={sampled}", flush=True)
                os._exit(0)

            os.waitpid(pid, 0)
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        assert "CHILD watchdog_alive=True sampled=True" in result.stdout, (result.stdout, result.stderr)
