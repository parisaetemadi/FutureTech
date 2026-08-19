#!/usr/bin/env python3
"""Refresh data/companies.json from public market data.

Updates the market-driven fields (market cap, cash, revenue, profit) for every
ticker already listed in the file. The curated fields — category, founded,
blurb, name — are hand-maintained and are never overwritten.

Data sources
------------
The backbone is SEC EDGAR — official US government filings, public domain, no
API key, and automated access is explicitly permitted under a documented rate
limit. Yahoo Finance cannot be relied on here: it rate-limits by IP range and
returns HTTP 429 to every request from a GitHub Actions runner.

Each ticker is built up by merging across a chain of providers, each filling
in whatever the earlier ones could not supply:

    edgar   cash, revenue, profit and share count, straight from XBRL filings
    stooq   last close, free CSV, no key
    nasdaq  market cap and price, no key
    yahoo   everything, but blocked from datacenter IPs

Market cap is not in EDGAR, so it is derived as price x shares outstanding
when no provider supplies it directly.

Reporting basis: EDGAR figures are trailing twelve months where four quarterly
facts are available, otherwise the most recent annual figure. Foreign private
issuers that file 20-F/40-F (or do not file at all) have thinner XBRL coverage
and fall back to the other providers.

Usage:
    python3 scripts/fetch_data.py
    python3 scripts/fetch_data.py --dry-run
    python3 scripts/fetch_data.py --only NVDA,IONQ
    python3 scripts/fetch_data.py --providers nasdaq,stooq
    python3 scripts/fetch_data.py --fail-under 60

Requires: requests  (pip install requests)
"""

import argparse
import csv
import datetime as dt
import io
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

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

YAHOO_MODULES = "price,financialData,defaultKeyStatistics"
YAHOO_QUOTE = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_CRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
YAHOO_COOKIE = "https://fc.yahoo.com/"

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{concept}.json"
# SEC asks automated clients to identify themselves; point at the project
# rather than any personal contact details.
SEC_UA = "FutureTech-MarketMap/1.0 (+https://github.com/parisaetemadi/FutureTech)"

NASDAQ_INFO = "https://api.nasdaq.com/api/quote/{symbol}/info"
NASDAQ_SUMMARY = "https://api.nasdaq.com/api/quote/{symbol}/summary"
STOOQ_QUOTE = "https://stooq.com/q/l/"

FIELDS = ("marketCap", "cash", "revenue", "netIncome")
WANTED = FIELDS + ("sharesOutstanding",)


# ---------------------------------------------------------------- helpers


def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json,text/csv,*/*"})
    return s


def yahoo_crumb(session):
    """Yahoo needs a cookie plus a matching crumb on quoteSummary."""
    try:
        session.get(YAHOO_COOKIE, timeout=15)
    except requests.RequestException:
        pass
    try:
        r = session.get(YAHOO_CRUMB, timeout=15)
        if r.ok and r.text and "<" not in r.text:
            return r.text.strip()
    except requests.RequestException:
        pass
    return None


def unwrap(node, *keys):
    """Yahoo wraps numbers as {"raw": N, "fmt": "..."} — unwrap defensively."""
    for key in keys:
        val = node.get(key) if isinstance(node, dict) else None
        if isinstance(val, dict):
            val = val.get("raw")
        if isinstance(val, (int, float)):
            return val
    return None


def to_number(text):
    """Parse '4,508,000,000' or '$123.45' or '1.23B' into a float."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.upper() in {"N/A", "NA", "--", "UNCH"}:
        return None
    mult = 1.0
    if s[-1:].upper() in {"K", "M", "B", "T"}:
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1].upper()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


# ---------------------------------------------------------------- providers


def sec_get(session, url, **kw):
    """SEC requires a self-identifying User-Agent and rate-limits to 10 req/s."""
    headers = {"User-Agent": SEC_UA, "Accept": "application/json"}
    return session.get(url, headers=headers, timeout=30, **kw)


def sec_cik_map(session, state):
    """ticker -> CIK, fetched once per run."""
    if "cik_map" in state:
        return state["cik_map"]
    r = sec_get(session, SEC_TICKERS)
    r.raise_for_status()
    mapping = {}
    for row in (r.json() or {}).values():
        if isinstance(row, dict) and row.get("ticker"):
            mapping[row["ticker"].upper()] = int(row["cik_str"])
    state["cik_map"] = mapping
    return mapping


def sec_concept(session, cik, taxonomy, concept):
    """Fetch one XBRL concept for one filer.

    companyfacts returns every fact a company has ever filed — tens of
    megabytes each, which made a 63-ticker run crawl past ten minutes.
    companyconcept returns only the series asked for.
    """
    url = SEC_CONCEPT.format(cik=cik, taxonomy=taxonomy, concept=concept)
    r = sec_get(session, url)
    if r.status_code == 404:
        return []          # this filer simply does not report the concept
    r.raise_for_status()
    units = (r.json() or {}).get("units") or {}
    for unit in ("USD", "shares"):
        if units.get(unit):
            return units[unit]
    return []


def _first_concept(session, cik, candidates, picker, delay):
    """Try concepts in order; return the first that yields a value."""
    for taxonomy, concept in candidates:
        entries = sec_concept(session, cik, taxonomy, concept)
        time.sleep(delay)
        if entries:
            value = picker(entries)
            if value is not None:
                return value
    return None


def _latest_instant(entries):
    """Point-in-time concepts (cash, share count): newest reported value."""
    dated = [e for e in entries if e.get("end") and e.get("val") is not None]
    if not dated:
        return None
    return max(dated, key=lambda e: (e["end"], e.get("filed", "")))["val"]


def _trailing_twelve_months(entries):
    """Flow concepts (revenue, profit): sum four quarters, else latest annual."""
    spans = []
    for e in entries:
        if not (e.get("start") and e.get("end") and e.get("val") is not None):
            continue
        try:
            start = dt.date.fromisoformat(e["start"])
            end = dt.date.fromisoformat(e["end"])
        except ValueError:
            continue
        spans.append((end, start, (end - start).days, e["val"]))
    if not spans:
        return None
    spans.sort(key=lambda x: x[0], reverse=True)

    # Four most recent non-overlapping quarterly facts.
    quarters, cursor = [], None
    for end, start, days, val in spans:
        if not 60 <= days <= 115:
            continue
        if cursor is not None and end > cursor:
            continue
        quarters.append(val)
        cursor = start
        if len(quarters) == 4:
            return sum(quarters)

    for end, start, days, val in spans:
        if 330 <= days <= 400:
            return val
    return None


def fetch_edgar(session, symbol, state):
    """Fundamentals from SEC XBRL. EDGAR carries no market cap."""
    cik = sec_cik_map(session, state).get(symbol.upper())
    if not cik:
        raise ValueError("no CIK on file (foreign issuer or non-filer)")

    delay = state.get("sec_delay", 0.12)  # SEC allows 10 requests/second

    cash = _first_concept(session, cik, [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    ], _latest_instant, delay)

    revenue = _first_concept(session, cik, [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
    ], _trailing_twelve_months, delay)

    net_income = _first_concept(session, cik, [
        ("us-gaap", "NetIncomeLoss"),
    ], _trailing_twelve_months, delay)

    shares = _first_concept(session, cik, [
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
    ], _latest_instant, delay)

    out = {}
    if cash is not None:
        out["cash"] = cash
    if revenue is not None:
        out["revenue"] = revenue
    if net_income is not None:
        out["netIncome"] = net_income
    if shares:
        out["sharesOutstanding"] = shares
    if not out:
        raise ValueError("no usable XBRL facts")
    return out


def fetch_yahoo(session, symbol, state):
    params = {"modules": YAHOO_MODULES}
    if state.get("yahoo_crumb"):
        params["crumb"] = state["yahoo_crumb"]

    r = session.get(YAHOO_QUOTE.format(symbol=symbol), params=params, timeout=20)
    r.raise_for_status()
    result = (r.json().get("quoteSummary") or {}).get("result") or []
    if not result:
        raise ValueError("empty quoteSummary result")

    node = result[0]
    price = node.get("price") or {}
    fin = node.get("financialData") or {}
    stats = node.get("defaultKeyStatistics") or {}

    return {
        "marketCap": unwrap(price, "marketCap"),
        "cash": unwrap(fin, "totalCash"),
        "revenue": unwrap(fin, "totalRevenue"),
        "netIncome": unwrap(stats, "netIncomeToCommon"),
        "sharesOutstanding": unwrap(stats, "sharesOutstanding", "impliedSharesOutstanding"),
    }


def fetch_nasdaq(session, symbol, state):
    headers = {"Accept": "application/json", "User-Agent": UA}
    out = {}

    r = session.get(
        NASDAQ_INFO.format(symbol=symbol),
        params={"assetclass": "stocks"},
        headers=headers,
        timeout=20,
    )
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    if not data:
        raise ValueError("empty nasdaq info payload")

    out["marketCap"] = to_number(data.get("marketCap"))
    primary = data.get("primaryData") or {}
    price = to_number(primary.get("lastSalePrice"))
    if price and out.get("marketCap"):
        out["sharesOutstanding"] = out["marketCap"] / price

    if out.get("marketCap") is None:
        raise ValueError("nasdaq returned no market cap")
    return out


def fetch_stooq(session, symbol, state):
    """Price only. Market cap is derived from a previously cached share count."""
    r = session.get(
        STOOQ_QUOTE,
        params={"s": symbol.lower() + ".us", "f": "sd2t2ohlcv", "h": "", "e": "csv"},
        timeout=20,
    )
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows:
        raise ValueError("empty stooq csv")

    close = to_number(rows[0].get("Close"))
    if close is None:
        raise ValueError("stooq returned no close price (symbol may be unlisted there)")

    out = {"price": close}
    shares = state.get("shares")
    if shares:
        out["marketCap"] = close * shares
    return out


PROVIDERS = {
    "edgar": fetch_edgar,
    "stooq": fetch_stooq,
    "nasdaq": fetch_nasdaq,
    "yahoo": fetch_yahoo,
}


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="Refresh companies.json from public market data.")
    ap.add_argument("--dry-run", action="store_true", help="print changes without writing")
    ap.add_argument("--only", help="comma-separated tickers to refresh")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between requests")
    ap.add_argument(
        "--providers",
        default="edgar,stooq,nasdaq,yahoo",
        help="ordered provider chain to try per ticker",
    )
    ap.add_argument(
        "--fail-under",
        type=float,
        default=0.0,
        help="exit non-zero if fewer than this percent of tickers refresh",
    )
    args = ap.parse_args()

    chain = [p.strip() for p in args.providers.split(",") if p.strip()]
    unknown = [p for p in chain if p not in PROVIDERS]
    if unknown:
        sys.exit(f"unknown provider(s): {', '.join(unknown)}")

    data = json.loads(DATA_FILE.read_text())
    companies = data["companies"]

    wanted = None
    if args.only:
        wanted = {t.strip().upper() for t in args.only.split(",") if t.strip()}

    session = make_session()
    state = {}
    if "yahoo" in chain:
        state["yahoo_crumb"] = yahoo_crumb(session)
        if not state["yahoo_crumb"]:
            print("note: no Yahoo crumb obtained; Yahoo requests may be rejected", file=sys.stderr)

    updated, failed = 0, []
    by_provider = {}

    for company in companies:
        symbol = company["ticker"]
        if wanted and symbol not in wanted:
            continue

        state["shares"] = company.get("sharesOutstanding")
        merged, sources, errors = {}, [], []

        # No single open source covers everything, so each provider fills the
        # gaps the previous ones left rather than winning the ticker outright.
        for name in chain:
            if all(f in merged for f in WANTED):
                break
            try:
                candidate = PROVIDERS[name](session, symbol, state) or {}
            except Exception as exc:  # noqa: BLE001 - fall through to the next
                errors.append(f"{name}: {type(exc).__name__} {exc}".split("\n")[0][:110])
                time.sleep(args.delay)
                continue

            gained = False
            for key, value in candidate.items():
                if value is not None and key not in merged:
                    merged[key] = value
                    gained = True
            if candidate.get("sharesOutstanding"):
                state["shares"] = candidate["sharesOutstanding"]
            if gained:
                sources.append(name)
            time.sleep(args.delay)

        # EDGAR carries no market cap, so derive it from price x share count.
        if "marketCap" not in merged:
            shares = merged.get("sharesOutstanding") or state.get("shares")
            if merged.get("price") and shares:
                merged["marketCap"] = merged["price"] * shares
                sources.append("derived")

        if not merged.get("marketCap"):
            failed.append(symbol)
            print(f"  {symbol:<6} FAILED — keeping existing values", file=sys.stderr)
            for err in errors:
                print(f"           {err}", file=sys.stderr)
            continue

        changes = []
        for field in FIELDS + ("sharesOutstanding",):
            value = merged.get(field)
            if value is None:
                continue
            if company.get(field) != value:
                changes.append(field)
                if not args.dry_run:
                    company[field] = value

        updated += 1
        for name in sources:
            by_provider[name] = by_provider.get(name, 0) + 1
        summary = ", ".join(changes) if changes else "no change"
        print(f"  {symbol:<6} via {'+'.join(sources) or '?':<20} {summary}")

    attempted = updated + len(failed)
    rate = (updated / attempted * 100) if attempted else 0.0

    print(f"\nProviders used: {by_provider or 'none'}")

    if args.dry_run:
        print(f"Dry run: {updated}/{attempted} refreshed ({rate:.0f}%). Nothing written.")
        return 1 if rate < args.fail_under else 0

    if not updated:
        # Every provider failed. Leaving asOf alone matters: stamping today's
        # date on untouched numbers would advertise stale data as fresh.
        print("\nNo ticker refreshed — leaving the file untouched.", file=sys.stderr)
        return 1

    data["asOf"] = dt.date.today().isoformat()
    DATA_FILE.write_text(json.dumps(data, indent=2) + "\n")

    print(f"Wrote {DATA_FILE.relative_to(ROOT)} — {updated}/{attempted} refreshed ({rate:.0f}%).")
    if failed:
        print("Failed: " + ", ".join(failed))

    if rate < args.fail_under:
        print(f"Refresh rate {rate:.0f}% is below --fail-under {args.fail_under:.0f}%.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
