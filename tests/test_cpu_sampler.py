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
    # Explicit sampler config must precede detect_slow_tasks, whose default
    # cpu_sampling=True would otherwise auto-start with default parameters.
    aiocop.start_cpu_sampling(interval_ms=5, arm_after_ms=10, idle_interval_ms=20)
    aiocop.detect_slow_tasks(threshold_ms=30)
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
            aiocop.start_cpu_sampling(interval_ms=5, arm_after_ms=10, idle_interval_ms=20)
            aiocop.detect_slow_tasks(threshold_ms=30)
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


class TestDefaultOn:
    def _run(self, script: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    def test_detect_slow_tasks_starts_sampling_with_derived_arm(self) -> None:
        """cpu_sampling defaults to True and arms at threshold_ms / 2.

        Subprocess: sampler start is once-per-process, and this module's
        fixture already started it here.
        """
        out = self._run(
            """
            import aiocop
            from aiocop.core import cpu_sampler

            aiocop.detect_slow_tasks(threshold_ms=100)
            arm_ns, idle_s = cpu_sampler._effective_arm_and_idle()
            print(f"started={aiocop.is_cpu_sampling_started()} arm_ns={arm_ns} idle_s={idle_s}", flush=True)
            """
        )
        # idle follows the derived arm (min(50ms, arm)) so a fresh slice gets
        # its first look no later than its arming age
        assert "started=True arm_ns=50000000 idle_s=0.05" in out

    def test_derived_idle_tracks_a_small_arm(self) -> None:
        """threshold 30 -> arm 15ms -> idle 15ms, not the fixed 50ms that
        would let just-over-threshold slices finish inside one idle sleep."""
        out = self._run(
            """
            import aiocop
            from aiocop.core import cpu_sampler

            aiocop.detect_slow_tasks(threshold_ms=30)
            arm_ns, idle_s = cpu_sampler._effective_arm_and_idle()
            print(f"arm_ns={arm_ns} idle_s={idle_s}", flush=True)
            """
        )
        assert "arm_ns=15000000 idle_s=0.015" in out

    def test_pre_start_rederives_arm_when_detect_sets_the_threshold(self) -> None:
        """Customizing only other knobs before detect_slow_tasks must not
        freeze the arming delay against the module-default threshold."""
        out = self._run(
            """
            import aiocop
            from aiocop.core import cpu_sampler

            aiocop.start_cpu_sampling(interval_ms=5)
            aiocop.detect_slow_tasks(threshold_ms=100)
            arm_ns, idle_s = cpu_sampler._effective_arm_and_idle()
            print(f"arm_ns={arm_ns} idle_s={idle_s}", flush=True)
            """
        )
        assert "arm_ns=50000000 idle_s=0.05" in out

    def test_pre_start_rederives_arm_below_a_small_threshold(self) -> None:
        """A threshold below the module default must pull the derived arm
        under it — otherwise violations could never carry samples."""
        out = self._run(
            """
            import aiocop
            from aiocop.core import cpu_sampler

            aiocop.start_cpu_sampling(interval_ms=5)
            aiocop.detect_slow_tasks(threshold_ms=10)
            print(f"arm_ns={cpu_sampler._effective_arm_and_idle()[0]}", flush=True)
            """
        )
        assert "arm_ns=5000000" in out

    def test_zero_arm_does_not_spin_the_watchdog(self) -> None:
        """arm_after_ms=0 means "sample every slice immediately"; the derived
        idle must floor at the sampling interval instead of becoming a
        time.sleep(0) busy loop."""
        out = self._run(
            """
            import aiocop
            from aiocop.core import cpu_sampler

            aiocop.start_cpu_sampling(arm_after_ms=0)
            aiocop.detect_slow_tasks(threshold_ms=30)
            arm_ns, idle_s = cpu_sampler._effective_arm_and_idle()
            print(f"arm_ns={arm_ns} idle_s={idle_s}", flush=True)
            """
        )
        assert "arm_ns=0 idle_s=0.01" in out

    def test_just_over_threshold_slice_is_sampled_with_default_pairing(self) -> None:
        """End to end: with derived arm+idle a slice moderately over the
        threshold gets samples even when the watchdog was idling before it."""
        out = self._run(
            """
            import asyncio
            import time

            import aiocop

            aiocop.patch_audit_functions()
            aiocop.start_blocking_io_detection(trace_depth=5)
            aiocop.detect_slow_tasks(threshold_ms=30)

            events = []
            aiocop.register_slow_task_callback(events.append)

            def burn(duration_s):
                deadline = time.perf_counter() + duration_s
                while time.perf_counter() < deadline:
                    sum(range(1000))

            async def main():
                aiocop.activate()
                await asyncio.sleep(0.2)  # let the watchdog settle into idle cadence
                burn(0.06)
                await asyncio.sleep(0)

            asyncio.run(main())

            slow = [e for e in events if e.reason == "cpu_blocking" and e.exceeded_threshold]
            sampled = any(e.cpu_stack_samples for e in slow)
            print(f"violations={len(slow) > 0} sampled={sampled}", flush=True)
            """
        )
        assert "violations=True sampled=True" in out

    def test_cpu_sampling_false_disables_the_auto_start(self) -> None:
        out = self._run(
            """
            import aiocop

            aiocop.detect_slow_tasks(threshold_ms=30, cpu_sampling=False)
            print(f"started={aiocop.is_cpu_sampling_started()}", flush=True)
            """
        )
        assert "started=False" in out

    def test_explicit_start_before_detect_wins_over_the_auto_start(self) -> None:
        out = self._run(
            """
            import aiocop
            from aiocop.core import cpu_sampler

            aiocop.start_cpu_sampling(arm_after_ms=7)
            aiocop.detect_slow_tasks(threshold_ms=100)
            print(f"arm_ns={cpu_sampler._effective_arm_and_idle()[0]}", flush=True)
            """
        )
        assert "arm_ns=7000000" in out


class TestNonMainThreadLoop:
    def test_loop_running_off_the_main_thread_is_sampled(self, setup_aiocop_with_sampler, captured_events) -> None:
        """The watchdog samples the thread that published the slice, so an
        event loop running outside the main thread still gets attribution."""
        import threading

        async def handler() -> None:
            await asyncio.sleep(0)
            _burn_cpu(0.08)

        async def main() -> None:
            aiocop.activate()
            await asyncio.create_task(handler())
            await asyncio.sleep(0)

        worker = threading.Thread(target=lambda: asyncio.run(main()))
        worker.start()
        worker.join(timeout=10)
        assert worker.is_alive() is False

        slow = [e for e in captured_events if e.exceeded_threshold and e.reason == "cpu_blocking"]
        assert len(slow) > 0

        samples = slow[0].cpu_stack_samples
        assert len(samples) > 0
        assert "_burn_cpu" in " || ".join(sample["trace"] for sample in samples)
