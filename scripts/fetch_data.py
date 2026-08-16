#!/usr/bin/env python3
"""Refresh data/companies.json from Yahoo Finance.

Updates the market-driven fields (market cap, cash, revenue, profit) for every
ticker already listed in the file. The curated fields — category, founded,
blurb, name — are hand-maintained and are never overwritten.

Usage:
    python3 scripts/fetch_data.py              # refresh in place
    python3 scripts/fetch_data.py --dry-run    # print what would change
    python3 scripts/fetch_data.py --only NVDA,IONQ

Requires: requests  (pip install requests)

Note: Yahoo's endpoints are unofficial and rate-limited. If a ticker fails, the
existing values for that ticker are kept and a warning is printed, so a partial
outage never blanks the dataset.
"""

import argparse
import datetime as dt
import json
import pathlib
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("This script needs `requests`. Install it with: pip install requests")

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "companies.json"

MODULES = "price,financialData,defaultKeyStatistics"
QUOTE_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def make_session():
    """Yahoo requires a cookie + matching crumb on quoteSummary."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})

    # fc.yahoo.com 404s but hands back the auth cookie we need.
    try:
        s.get(COOKIE_URL, timeout=15)
    except requests.RequestException:
        pass

    crumb = None
    try:
        r = s.get(CRUMB_URL, timeout=15)
        if r.ok and r.text and "<" not in r.text:
            crumb = r.text.strip()
    except requests.RequestException:
        pass

    return s, crumb


def pick(node, *keys):
    """Yahoo wraps numbers as {"raw": N, "fmt": "..."} — unwrap defensively."""
    for key in keys:
        val = node.get(key) if isinstance(node, dict) else None
        if isinstance(val, dict):
            val = val.get("raw")
        if isinstance(val, (int, float)):
            return val
    return None


def fetch_one(session, crumb, symbol):
    params = {"modules": MODULES}
    if crumb:
        params["crumb"] = crumb

    r = session.get(QUOTE_URL.format(symbol=symbol), params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()

    result = (payload.get("quoteSummary") or {}).get("result") or []
    if not result:
        raise ValueError("empty quoteSummary result")

    node = result[0]
    price = node.get("price") or {}
    fin = node.get("financialData") or {}
    stats = node.get("defaultKeyStatistics") or {}

    return {
        "marketCap": pick(price, "marketCap"),
        "cash": pick(fin, "totalCash"),
        "revenue": pick(fin, "totalRevenue"),
        "netIncome": pick(stats, "netIncomeToCommon"),
    }


def main():
    ap = argparse.ArgumentParser(description="Refresh companies.json from Yahoo Finance.")
    ap.add_argument("--dry-run", action="store_true", help="print changes without writing")
    ap.add_argument("--only", help="comma-separated tickers to refresh")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    ap.add_argument(
        "--fail-under",
        type=float,
        default=0.0,
        help="exit non-zero if fewer than this percent of tickers refresh "
        "(use in CI so a bad run fails loudly instead of silently shipping stale data)",
    )
    args = ap.parse_args()

    data = json.loads(DATA_FILE.read_text())
    companies = data["companies"]

    wanted = None
    if args.only:
        wanted = {t.strip().upper() for t in args.only.split(",") if t.strip()}

    session, crumb = make_session()
    if not crumb:
        print("warning: no crumb obtained — Yahoo may reject requests", file=sys.stderr)

    updated, failed = 0, []

    for company in companies:
        symbol = company["ticker"]
        if wanted and symbol not in wanted:
            continue

        try:
            fresh = fetch_one(session, crumb, symbol)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the run
            failed.append(symbol)
            print(f"  {symbol:<6} FAILED ({exc}) — keeping existing values", file=sys.stderr)
            time.sleep(args.delay)
            continue

        changes = []
        for field, value in fresh.items():
            if value is None:
                continue
            old = company.get(field)
            if old != value:
                changes.append(f"{field}: {old} -> {value}")
                if not args.dry_run:
                    company[field] = value

        updated += 1
        status = "; ".join(changes) if changes else "no change"
        print(f"  {symbol:<6} {status}")
        time.sleep(args.delay)

    attempted = updated + len(failed)
    rate = (updated / attempted * 100) if attempted else 0.0

    if args.dry_run:
        print(f"\nDry run: {updated}/{attempted} tickers fetched ({rate:.0f}%). Nothing written.")
        return 1 if rate < args.fail_under else 0

    if not updated:
        # Every ticker failed. Leaving asOf alone matters: stamping today's date
        # on untouched numbers would advertise stale data as fresh.
        print("\nNo ticker refreshed — leaving the file untouched.", file=sys.stderr)
        return 1

    data["asOf"] = dt.date.today().isoformat()
    DATA_FILE.write_text(json.dumps(data, indent=2) + "\n")

    print(f"\nWrote {DATA_FILE.relative_to(ROOT)} — {updated}/{attempted} refreshed ({rate:.0f}%).")
    if failed:
        print("Failed: " + ", ".join(failed))

    if rate < args.fail_under:
        print(f"Refresh rate {rate:.0f}% is below --fail-under {args.fail_under:.0f}%.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
