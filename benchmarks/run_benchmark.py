#!/usr/bin/env python3
"""
aiocop Benchmark Script

Measures the overhead of aiocop monitoring on async workloads.
Supports both standard asyncio and uvloop.

Usage:
    python benchmarks/run_benchmark.py
    python benchmarks/run_benchmark.py --asyncio-only
    python benchmarks/run_benchmark.py --uvloop-only

Or with uv:
    uv run python benchmarks/run_benchmark.py
"""

import argparse
import asyncio
import gc
import os
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Add parent directory to path for importing aiocop
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    name: str
    loop_type: str
    num_tasks: int
    without_aiocop_ms: float
    with_aiocop_ms: float
    overhead_per_task_us: float  # microseconds per task


def format_results(results: list[BenchmarkResult], loop_type: str) -> str:
    """Format benchmark results for a specific loop type."""
    filtered = [r for r in results if r.loop_type == loop_type]
    if not filtered:
        return ""

    lines = []
    lines.append(f"\n{loop_type.upper()} Results:")
    lines.append("-" * 70)
    lines.append(f"  {'Scenario':<40} {'Overhead':<15} {'Impact on 50ms'}")
    lines.append(f"  {'-' * 40} {'-' * 15} {'-' * 14}")

    for r in filtered:
        impact_percent = (r.overhead_per_task_us / 50000) * 100
        lines.append(f"  {r.name:<40} {r.overhead_per_task_us:>8.1f} us      {impact_percent:.3f}%")

    avg_overhead = statistics.mean(r.overhead_per_task_us for r in filtered)
    avg_impact = (avg_overhead / 50000) * 100
    lines.append(f"\n  Average: {avg_overhead:.1f} us per task ({avg_impact:.3f}% on 50ms request)")

    return "\n".join(lines)


def format_comparison(results: list[BenchmarkResult]) -> str:
    """Format a comparison between asyncio and uvloop results."""
    asyncio_results = {r.name: r for r in results if r.loop_type == "asyncio"}
    uvloop_results = {r.name: r for r in results if r.loop_type == "uvloop"}

    if not asyncio_results or not uvloop_results:
        return ""

    lines = []
    lines.append("\n" + "=" * 70)
    lines.append("COMPARISON: asyncio vs uvloop")
    lines.append("=" * 70)
    lines.append(f"  {'Scenario':<30} {'asyncio':<12} {'uvloop':<12} {'Difference'}")
    lines.append(f"  {'-' * 30} {'-' * 12} {'-' * 12} {'-' * 12}")

    for name in asyncio_results:
        if name in uvloop_results:
            asyncio_us = asyncio_results[name].overhead_per_task_us
            uvloop_us = uvloop_results[name].overhead_per_task_us
            diff = uvloop_us - asyncio_us
            diff_str = f"{diff:+.1f} us" if diff != 0 else "same"
            lines.append(f"  {name:<30} {asyncio_us:>8.1f} us   {uvloop_us:>8.1f} us   {diff_str}")

    asyncio_avg = statistics.mean(r.overhead_per_task_us for r in asyncio_results.values())
    uvloop_avg = statistics.mean(r.overhead_per_task_us for r in uvloop_results.values())
    diff_avg = uvloop_avg - asyncio_avg

    lines.append("")
    lines.append(f"  {'Average':<30} {asyncio_avg:>8.1f} us   {uvloop_avg:>8.1f} us   {diff_avg:+.1f} us")

    return "\n".join(lines)


async def run_scenario(
    name: str,
    task_fn: Callable[[], asyncio.Future],
    num_tasks: int,
    loop_type: str,
    iterations: int = 5,
) -> BenchmarkResult:
    """Run a benchmark scenario with and without aiocop."""
    import aiocop

    async def run_tasks():
        tasks = [asyncio.create_task(task_fn()) for _ in range(num_tasks)]
        await asyncio.gather(*tasks)

    # Warmup
    await run_tasks()
    gc.collect()

    # Benchmark WITHOUT aiocop
    aiocop.deactivate()
    times_without = []
    for _ in range(iterations):
        gc.collect()
        start = time.perf_counter()
        await run_tasks()
        elapsed = (time.perf_counter() - start) * 1000
        times_without.append(elapsed)

    without_ms = statistics.median(times_without)

    # Benchmark WITH aiocop
    aiocop.activate()
    times_with = []
    for _ in range(iterations):
        gc.collect()
        start = time.perf_counter()
        await run_tasks()
        elapsed = (time.perf_counter() - start) * 1000
        times_with.append(elapsed)

    with_ms = statistics.median(times_with)

    overhead_ms = with_ms - without_ms
    overhead_per_task_us = (overhead_ms * 1000) / num_tasks

    return BenchmarkResult(
        name=name,
        loop_type=loop_type,
        num_tasks=num_tasks,
        without_aiocop_ms=without_ms,
        with_aiocop_ms=with_ms,
        overhead_per_task_us=overhead_per_task_us,
    )


async def fast_async_task():
    """A fast async task with no blocking I/O."""
    await asyncio.sleep(0)


async def task_with_stat():
    """Task that performs os.stat (light blocking)."""
    os.stat(".")
    await asyncio.sleep(0)


async def task_with_getcwd():
    """Task with trivial blocking (os.getcwd)."""
    os.getcwd()
    await asyncio.sleep(0)


async def task_with_file_read():
    """Task that reads an existing file."""
    try:
        with open(__file__) as f:
            f.read(100)
    except Exception:
        pass
    await asyncio.sleep(0)


async def realistic_http_handler():
    """
    Simulates a realistic async HTTP handler.
    Most time is spent in async I/O, with occasional light blocking.
    """
    await asyncio.sleep(0.001)  # 1ms async work
    os.path.exists(".")
    os.getcwd()
    await asyncio.sleep(0.001)  # 1ms async work


def noop_callback(event) -> None:
    """No-op callback for benchmarking."""
    pass


def reset_aiocop_state():
    """Reset aiocop state for fresh benchmark run."""
    from aiocop.core import slow_tasks, state

    state._monitoring_active = False
    state._on_activate_hooks.clear()
    slow_tasks._detect_slow_tasks_configured = False

    import aiocop

    aiocop.clear_slow_task_callbacks()
    aiocop.clear_context_providers()


async def run_all_scenarios(loop_type: str) -> list[BenchmarkResult]:
    """Run all benchmark scenarios."""
    results = []

    # Scenario 1: Pure async (baseline - no blocking I/O to detect)
    result = await run_scenario(
        name="Pure async (no blocking)",
        task_fn=fast_async_task,
        num_tasks=10_000,
        loop_type=loop_type,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 2: Trivial blocking (os.getcwd - WEIGHT_TRIVIAL)
    result = await run_scenario(
        name="Trivial blocking (getcwd)",
        task_fn=task_with_getcwd,
        num_tasks=5_000,
        loop_type=loop_type,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 3: Light blocking (os.stat - WEIGHT_LIGHT)
    result = await run_scenario(
        name="Light blocking (stat)",
        task_fn=task_with_stat,
        num_tasks=5_000,
        loop_type=loop_type,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 4: Moderate blocking (file read - WEIGHT_MODERATE)
    result = await run_scenario(
        name="Moderate blocking (file read)",
        task_fn=task_with_file_read,
        num_tasks=2_000,
        loop_type=loop_type,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 5: Realistic HTTP handler simulation
    result = await run_scenario(
        name="Realistic HTTP handler",
        task_fn=realistic_http_handler,
        num_tasks=500,
        loop_type=loop_type,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    return results


def setup_aiocop():
    """Setup aiocop for benchmarking."""
    import aiocop

    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection(trace_depth=5)
    aiocop.detect_slow_tasks(threshold_ms=1000, on_slow_task=noop_callback)


def run_asyncio_benchmark() -> list[BenchmarkResult]:
    """Run benchmark with standard asyncio."""
    reset_aiocop_state()
    setup_aiocop()

    async def main():
        return await run_all_scenarios("asyncio")

    return asyncio.run(main())


def run_uvloop_benchmark() -> list[BenchmarkResult]:
    """Run benchmark with uvloop."""
    try:
        import uvloop
    except ImportError:
        print("  [skip] uvloop not available")
        return []

    reset_aiocop_state()
    setup_aiocop()

    async def main():
        # Verify we're on uvloop
        loop = asyncio.get_running_loop()
        assert type(loop).__name__ == "Loop", f"Not running on uvloop: {type(loop)}"
        return await run_all_scenarios("uvloop")

    return uvloop.run(main())


def main():
    parser = argparse.ArgumentParser(description="aiocop Performance Benchmark")
    parser.add_argument("--asyncio-only", action="store_true", help="Only run asyncio benchmark")
    parser.add_argument("--uvloop-only", action="store_true", help="Only run uvloop benchmark")
    args = parser.parse_args()

    import aiocop

    print("")
    print("aiocop Performance Benchmark")
    print("=" * 50)
    print("")

    results: list[BenchmarkResult] = []

    # Run asyncio benchmark
    if not args.uvloop_only:
        print("Running asyncio benchmarks...")
        results.extend(run_asyncio_benchmark())
        print("")

    # Run uvloop benchmark
    if not args.asyncio_only:
        print("Running uvloop benchmarks...")
        uvloop_results = run_uvloop_benchmark()
        results.extend(uvloop_results)
        print("")

    # Print results
    print("")
    print("=" * 70)
    print("aiocop Benchmark Results")
    print("=" * 70)

    if not args.uvloop_only:
        print(format_results(results, "asyncio"))

    if not args.asyncio_only and any(r.loop_type == "uvloop" for r in results):
        print(format_results(results, "uvloop"))

    # Print comparison if both were run
    if not args.asyncio_only and not args.uvloop_only:
        print(format_comparison(results))

    print("")
    print("-" * 70)
    print("")
    print("System Info:")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {sys.platform}")
    print(f"  aiocop: {aiocop.__version__}")

    # Check uvloop version if available
    try:
        import uvloop

        print(f"  uvloop: {uvloop.__version__}")
    except ImportError:
        pass

    print("")


if __name__ == "__main__":
    main()
