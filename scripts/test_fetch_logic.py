#!/usr/bin/env python3
"""Unit tests for the pure parsing logic in fetch_data.py.

These need no network, so they run in CI on every trigger and catch parsing
regressions without waiting for a live provider call.

    python3 scripts/test_fetch_logic.py
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fetch_data", ROOT / "scripts" / "fetch_data.py")
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)

FAILURES = []


def check(name, got, want):
    if got == want:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        FAILURES.append(name)


def test_trailing_twelve_months():
    quarters = [
        {"start": "2025-07-01", "end": "2025-09-30", "val": 10},
        {"start": "2025-04-01", "end": "2025-06-30", "val": 20},
        {"start": "2025-01-01", "end": "2025-03-31", "val": 30},
        {"start": "2024-10-01", "end": "2024-12-31", "val": 40},
        {"start": "2024-07-01", "end": "2024-09-30", "val": 99},
    ]
    check("sums the four newest quarters", fd._trailing_twelve_months(quarters), 100)

    # An annual fact covering the same period must not be added on top of the
    # quarters that compose it, or revenue doubles.
    mixed = [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 500},
        {"start": "2025-10-01", "end": "2025-12-31", "val": 10},
        {"start": "2025-07-01", "end": "2025-09-30", "val": 10},
        {"start": "2025-04-01", "end": "2025-06-30", "val": 10},
        {"start": "2025-01-01", "end": "2025-03-31", "val": 10},
    ]
    check("ignores an overlapping annual fact", fd._trailing_twelve_months(mixed), 40)

    sparse = [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 777},
        {"start": "2025-10-01", "end": "2025-12-31", "val": 10},
    ]
    check("falls back to the annual figure", fd._trailing_twelve_months(sparse), 777)
    check("malformed dates are skipped", fd._trailing_twelve_months([{"start": "x", "end": "y", "val": 1}]), None)
    check("no entries", fd._trailing_twelve_months([]), None)


def test_latest_instant():
    entries = [
        {"end": "2024-12-31", "val": 111},
        {"end": "2026-06-30", "val": 333},
        {"end": "2025-06-30", "val": 222},
    ]
    check("newest end date wins", fd._latest_instant(entries), 333)
    check("no entries", fd._latest_instant([]), None)


def test_to_number():
    cases = [
        ("4,508,000,000", 4.508e9),
        ("$123.45", 123.45),
        ("1.23B", 1.23e9),
        ("2.5T", 2.5e12),
        ("850M", 850e6),
        ("N/A", None),
        ("--", None),
        ("", None),
        (None, None),
        (42, 42.0),
    ]
    for raw, want in cases:
        check(f"to_number({raw!r})", fd.to_number(raw), want)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}", file=sys.stderr)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
