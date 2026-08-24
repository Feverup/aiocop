"""CPU stack sampling for slow event-loop slices.

Blocking IO events get stack attribution from the audit hook, but a callback
slice that freezes the loop with pure CPU work (reason="cpu_blocking") carries
no clue about where the time went. This module closes that gap: a watchdog
daemon thread samples the main thread's stack while a monitored callback has
been running longer than an arming delay, and the samples are attached to the
resulting SlowTaskEvent.

Overhead model:
- Hot path (every monitored callback): two module-global stores to publish and
  clear the slice marker, plus one global read on the common no-samples exit.
  No locks, no allocations.
- Watchdog thread: sleeps at ``interval_ms``; while the loop is idle or slices
  are short it wakes, reads one global, and goes back to sleep. Stack capture
  via sys._current_frames() happens only for slices already older than
  ``arm_after_ms``.

Known limitation: a single long-running C call that never releases the GIL
(e.g. a pathological regex) starves the watchdog, so such a slice yields fewer
samples than requested — few samples for a long slice is itself a signal that
one C-level call dominated it.
"""

import logging
import os
import sys
import threading
import time

from aiocop.types.events import CpuStackSample

logger = logging.getLogger(__name__)

# The aiocop package directory, used to exclude aiocop's own frames from
# samples. A path-prefix match, unlike a substring check, cannot swallow user
# code that happens to live under a directory with "aiocop" in its name.
_AIOCOP_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + os.sep

_sampler_started = False
_main_thread_id: int | None = None

_interval_s: float = 0.010
_idle_interval_s: float = 0.050
_arm_after_ns: int = 15_000_000
_max_samples_per_slice: int = 32
_trace_depth: int = 20

# Written by the event loop thread (monitored_wrapper), read by the watchdog.
# Single int stores/reads are atomic under the GIL. 0 means "no active slice";
# any other value is the slice's perf_counter_ns start time, used as its id.
_current_slice_id: int = 0

# Written by the watchdog, read by the event loop thread. The unlocked read of
# _samples_slice_id on the hot path is a fast-exit hint only; ownership of
# _samples is always confirmed under the lock.
_samples_lock = threading.Lock()
_samples_slice_id: int = 0
_samples: list[list[tuple[str, int, str]]] = []


def start_cpu_sampling(
    interval_ms: int = 10,
    arm_after_ms: int = 15,
    idle_interval_ms: int = 50,
    max_samples_per_slice: int = 32,
    trace_depth: int = 20,
) -> None:
    """
    Start the CPU stack sampling watchdog thread.

    Args:
        interval_ms: Sampling interval while a slice is running (default: 10ms).
        arm_after_ms: Minimum age of the current slice before sampling starts.
            Slices shorter than this are never sampled (default: 15ms).
        idle_interval_ms: Watchdog wake-up interval while no slice is running,
            trading idle CPU for sampling start latency (default: 50ms).
        max_samples_per_slice: Cap on samples kept per slice (default: 32).
        trace_depth: Number of stack frames captured per sample (default: 20).

    Optional — without it aiocop behaves exactly as before and cpu_blocking
    events carry no stack samples. Should be called after detect_slow_tasks().
    """
    global _sampler_started, _main_thread_id, _interval_s, _idle_interval_s, _arm_after_ns
    global _max_samples_per_slice, _trace_depth

    if _sampler_started is True:
        logger.warning("start_cpu_sampling called more than once, ignoring")
        return

    _main_thread_id = threading.main_thread().ident
    _interval_s = interval_ms / 1000
    _idle_interval_s = idle_interval_ms / 1000
    _arm_after_ns = arm_after_ms * 1_000_000
    _max_samples_per_slice = max_samples_per_slice
    _trace_depth = trace_depth

    watchdog = threading.Thread(target=_watchdog_loop, name="aiocop-cpu-sampler", daemon=True)
    watchdog.start()

    # Threads do not survive fork(): a child forked after this call (e.g. a
    # gunicorn --preload worker) would report sampling as started while no
    # watchdog exists, silently producing no samples. Restart it in the child.
    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=_reinit_after_fork)

    _sampler_started = True
    logger.info("CPU stack sampling started (interval=%sms, arm_after=%sms)", interval_ms, arm_after_ms)


def is_cpu_sampling_started() -> bool:
    """Return whether the CPU sampling watchdog has been started."""
    return _sampler_started


def _reinit_after_fork() -> None:
    """Restart the watchdog in a forked child (registered via os.register_at_fork).

    Runs while the child is still single-threaded. The inherited lock may have
    been held by the parent's watchdog at fork time, so a fresh lock is the
    only safe option; slice state is reset because any in-flight slice or
    pending samples belong to the parent. The main-thread id is re-read since
    the child's main thread is whichever thread called fork() in the parent.
    """
    global _samples_lock, _current_slice_id, _samples_slice_id, _main_thread_id

    if _sampler_started is not True:
        return

    _samples_lock = threading.Lock()
    _current_slice_id = 0
    _samples_slice_id = 0
    _samples.clear()
    _main_thread_id = threading.main_thread().ident

    threading.Thread(target=_watchdog_loop, name="aiocop-cpu-sampler", daemon=True).start()


def _slice_started(slice_id: int) -> None:
    """Publish the current slice to the watchdog. Called on the hot path."""
    global _current_slice_id
    _current_slice_id = slice_id


def _slice_finished(slice_id: int) -> list[list[tuple[str, int, str]]]:
    """Clear the slice marker and collect any samples taken for this slice.

    Called on the hot path: the common case (no samples) is one unlocked
    global read and a compare.
    """
    global _current_slice_id, _samples_slice_id
    _current_slice_id = 0

    if _samples_slice_id != slice_id:
        return []

    with _samples_lock:
        if _samples_slice_id != slice_id:
            return []
        collected = _samples[:]
        _samples.clear()
        _samples_slice_id = 0

    return collected


def _watchdog_loop() -> None:
    global _samples_slice_id

    sleep_s = _idle_interval_s

    while True:
        time.sleep(sleep_s)

        slice_id = _current_slice_id
        if slice_id == 0:
            sleep_s = _idle_interval_s
            continue

        sleep_s = _interval_s

        if (time.perf_counter_ns() - slice_id) < _arm_after_ns:
            continue

        stack = _capture_main_thread_stack()
        if not stack:
            continue

        # The slice may have finished while the stack was being captured, in
        # which case the frames belong to whatever runs now — drop them.
        if _current_slice_id != slice_id:
            continue

        with _samples_lock:
            if _samples_slice_id != slice_id:
                _samples.clear()
                _samples_slice_id = slice_id
            if len(_samples) < _max_samples_per_slice:
                _samples.append(stack)


def format_cpu_samples(raw_samples: list[list[tuple[str, int, str]]]) -> list[CpuStackSample]:
    """Aggregate raw stack samples into unique stacks with occurrence counts.

    Samples are ordered by count descending, so the first entry is where the
    slice most likely spent its CPU time.
    """
    from aiocop.core.blocking_io import format_stack_frame

    counts: dict[tuple[tuple[str, int, str], ...], int] = {}
    for stack in raw_samples:
        key = tuple(stack)
        counts[key] = counts.get(key, 0) + 1

    formatted: list[CpuStackSample] = []
    for stack_key, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        formatted_frames = [format_stack_frame(frame) for frame in stack_key]
        formatted.append(
            {
                "trace": " <- ".join(formatted_frames),
                "entry_point": formatted_frames[0] if len(formatted_frames) > 0 else "unknown",
                "count": count,
            }
        )

    return formatted


def _capture_main_thread_stack() -> list[tuple[str, int, str]]:
    frame = sys._current_frames().get(_main_thread_id)

    captured_frames = []
    try:
        while frame is not None:
            filename = frame.f_code.co_filename
            if not filename.startswith(_AIOCOP_PACKAGE_DIR):
                captured_frames.append((filename, frame.f_lineno, frame.f_code.co_name))

                if len(captured_frames) >= _trace_depth:
                    break

            frame = frame.f_back
    finally:
        # Frames hold locals alive; make sure no reference outlives the walk.
        del frame

    return captured_frames
