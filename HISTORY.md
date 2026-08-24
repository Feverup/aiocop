# History

## 1.2.0 (2026-08-24)

* New feature: **CPU stack sampling** — a watchdog daemon thread samples the loop thread's stack during CPU-bound slices, attaching aggregated stacks with counts to `SlowTaskEvent.cpu_stack_samples`, so `cpu_blocking` events carry attribution like IO events do
* On by default: `detect_slow_tasks()` starts it automatically (`cpu_sampling=False` to opt out); `start_cpu_sampling()` called beforehand customizes it
* Derived defaults: arming delay follows half the slow-task threshold; idle wake-up follows `min(50ms, max(arm, interval))` with a 1ms sleep floor, so no configuration can busy-loop the watchdog
* Samples the thread that published the slice — event loops running outside the main thread are attributed correctly
* Fork-safe: forked children (e.g. gunicorn `--preload` workers) restart the watchdog via `os.register_at_fork`
* aiocop's own frames are excluded from samples via a package-path prefix match

## 1.1.5 (2026-07-20)

* Fix `time.sleep` being double-counted on Python 3.13+, which emits a native audit event for it (#11, #12)
* Make `patch_audit_functions()` and `start_blocking_io_detection()` idempotent — repeat calls now warn and no-op instead of silently double-counting events (#9, #10)

## 1.1.4 (2026-02-26)

* Capture context both before and after callback execution, merging non-None post values over pre values to handle spans set lazily

## 1.1.2 (2026-02-12)

* Capture context provider before call

## 1.0.0 (2026-01-07)

* First stable release

## 0.1.3 (2026-01-05)

* Add classifiers

## 0.1.2 (2026-01-05)

* Small fixes

## 0.1.0 (2025-12-30)

* First release on PyPI.
