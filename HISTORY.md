# History

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
