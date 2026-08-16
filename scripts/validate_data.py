#!/usr/bin/env python3
"""Sanity-check data/companies.json before it gets deployed.

Run after fetch_data.py in CI: a refresh that returns nonsense (nulls, zero
market caps, a mangled category) should fail the build rather than ship a
broken map.

    python3 scripts/validate_data.py
"""

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "companies.json"

REQUIRED = ("ticker", "name", "category", "marketCap", "cash", "revenue", "netIncome", "founded", "blurb")


def main():
    errors = []
    warnings = []

    try:
        data = json.loads(DATA_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FATAL: cannot read {DATA_FILE}: {exc}", file=sys.stderr)
        return 1

    # asOf must be a real, non-future date.
    try:
        as_of = dt.date.fromisoformat(str(data.get("asOf")))
        if as_of > dt.date.today():
            errors.append(f"asOf {as_of} is in the future")
    except (TypeError, ValueError):
        errors.append(f"asOf is not an ISO date: {data.get('asOf')!r}")

    categories = data.get("categories") or []
    if not categories:
        errors.append("no categories defined")
    cat_ids = {c.get("id") for c in categories}

    companies = data.get("companies") or []
    if len(companies) < 10:
        errors.append(f"only {len(companies)} companies — expected the full roster")

    seen = set()
    for c in companies:
        tag = c.get("ticker", "<no ticker>")

        for field in REQUIRED:
            if field not in c:
                errors.append(f"{tag}: missing {field}")

        if tag in seen:
            errors.append(f"{tag}: duplicate ticker")
        seen.add(tag)

        if c.get("category") not in cat_ids:
            errors.append(f"{tag}: unknown category {c.get('category')!r}")

        cap = c.get("marketCap")
        if not isinstance(cap, (int, float)) or cap <= 0:
            errors.append(f"{tag}: marketCap must be a positive number, got {cap!r}")

        # These may legitimately be zero or negative, but must be numeric.
        for field in ("cash", "revenue", "netIncome"):
            if not isinstance(c.get(field), (int, float)):
                errors.append(f"{tag}: {field} must be numeric, got {c.get(field)!r}")

        year = c.get("founded")
        if not isinstance(year, int) or not (1800 <= year <= dt.date.today().year):
            errors.append(f"{tag}: implausible founded year {year!r}")

        # Not fatal, but a market cap this far out is usually a bad parse.
        if isinstance(cap, (int, float)) and cap > 0 and cap < 1e7:
            warnings.append(f"{tag}: market cap {cap:,.0f} looks suspiciously small")

    for w in warnings:
        print(f"warning: {w}")

    if errors:
        print(f"\n{len(errors)} validation error(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK — {len(companies)} companies across {len(cat_ids)} sectors, asOf {data['asOf']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
