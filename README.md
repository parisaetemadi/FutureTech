# Future Tech Market Map

A treemap of public companies with a future-tech story — sized by market cap,
grouped by sector, with cash, revenue and profit on every tile.

Static site. No build step, no framework, no dependencies.

![Sectors: AI & data centers, nuclear, rare earth, space, robotics, quantum, genomics, digital assets](https://img.shields.io/badge/sectors-8-blue) ![63 companies](https://img.shields.io/badge/companies-63-green)

## Run it

The page loads its data with `fetch()`, so it needs to be served over HTTP
rather than opened as a `file://` URL:

```bash
python3 -m http.server 8000
# then open http://localhost:8000
```

## What's on screen

- **Tile size** = market cap.
- **Tile label** = ticker, market cap, then `cash · revenue · profit` (TTM).
  Negative profit is shown in red with a proper minus sign.
- **Colour** = sector. Eight of them, listed in the legend.
- Detail appears progressively as a tile gets bigger — a small tile shows just
  the ticker, a large one adds the stats line and a one-line description.
  Hovering any tile shows the full figures as a tooltip.

### Filters

| Control | What it does |
| --- | --- |
| **Sector** | Narrow to one of the eight sectors |
| **Market cap** | Presets for both ends of the range — `≤ $2B` … `≤ $100B`, `≥ $20B` … `≥ $1T`, plus banded options like `$20B – $100B` |
| **Min $B / Max $B** | Free-form range in billions. Typing here switches the preset to *Custom* |
| **Max company age** | Filter by years since founding (of the current operating entity) |
| **Reset** | Back to the default `≤ $20B` view |

The market-cap control is deliberately two-sided: `≥ $100B` gives you the
megacap view (Nvidia, Broadcom, Tesla, Palantir, Vertiv, Intuitive Surgical),
while `≤ $20B` gives the small- and mid-cap map where most of the actual
future-tech story sits. The default is `≤ $20B` — with an unfiltered range,
Nvidia alone is ~42% of the combined market cap and everything else becomes
unreadable.

## Sectors

| Sector | Examples |
| --- | --- |
| AI, Cloud & Data Centers | NVDA, AVGO, PLTR, VRT, NBIS, CRWV, IREN, CIFR, APLD, WULF |
| Nuclear & Energy | CEG, CCJ, VST, TLN, BWXT, OKLO, LEU, SMR, NNE |
| Rare Earth & Materials | ALB, MP, USAR, UUUU, TMC |
| Space & Defense | RKLB, ASTS, KTOS, AVAV, FLY, LUNR, PL, RDW, BKSY |
| Robotics & Autonomy | TSLA, ISRG, SYM, AUR, JOBY, ACHR, PONY, OUST, WRD, SERV |
| Quantum | IONQ, QBTS, RGTI, QUBT, ARQQ |
| Genomics & Bio-AI | ILMN, TEM, CRSP, BEAM, RXRX, NTLA, SDGR |
| Digital Assets | HOOD, MSTR, COIN, CRCL, GLXY, RIOT, MARA |

## Data

`data/companies.json` holds the whole dataset — one entry per company:

```json
{
  "ticker": "IONQ",
  "name": "IonQ",
  "category": "quantum",
  "marketCap": 17630000000,
  "cash": 2120000000,
  "revenue": 246000000,
  "netIncome": -1360000000,
  "founded": 2015,
  "blurb": "Trapped-ion quantum computers"
}
```

**Provenance and accuracy.** Market caps are mid-August 2026 snapshots compiled
from public market data. Cash, revenue and profit come from the most recent
reported quarter or trailing-twelve-month figures. A few of the smaller names
carry rounded figures where a precise current filing wasn't available — the
market caps that drive the treemap layout are the well-sourced numbers, and
`fetch_data.py` replaces every market-driven field with live data in one pass.
Treat the checked-in JSON as a dated snapshot, not a live feed.

`founded` is the year the **current operating entity** was established. For
spin-offs and SPAC-merged companies that is the year of the new company, not
the year of the predecessor business — so Constellation Energy is 2022 (spun
out of Exelon) rather than tracing back through Exelon's history. This is what
the age filter reads.

### Refreshing

The numbers refresh **automatically every day** — see [Deployment](#deployment).
To run it by hand:

```bash
pip install requests
python3 scripts/fetch_data.py             # refresh in place
python3 scripts/fetch_data.py --dry-run   # show what would change
python3 scripts/fetch_data.py --only NVDA,IONQ
python3 scripts/validate_data.py          # sanity-check the result
```

The script updates `marketCap`, `cash`, `revenue` and `netIncome` for every
ticker in the file and stamps a new `asOf` date. It never touches `category`,
`founded`, `blurb` or `name` — those are hand-maintained.

### Where the numbers come from

The backbone is **SEC EDGAR** — official US government filings, public domain,
no API key, and automated access is explicitly permitted under a documented
rate limit. No single free source covers everything, so each ticker is built up
by merging across a chain, each provider filling gaps the earlier ones left:

| Provider | Supplies | Notes |
| --- | --- | --- |
| `edgar` | cash, revenue, profit, share count | SEC XBRL company facts, open data |
| `stooq` | last close | free CSV, no key |
| `nasdaq` | market cap, price | no key |
| `yahoo` | everything | blocked from datacenter IPs, so last resort |

EDGAR carries no market cap, so it is derived as **price × shares outstanding**.
Share counts are cached back into the dataset, so the price-only path can still
produce a market cap on later runs.

Pick the chain explicitly with `--providers edgar,stooq`.

#### EDGAR needs a contact address

SEC policy asks automated clients to identify a contact in their User-Agent,
and `www.sec.gov` returns **403** without one. The address is read from the
`SEC_CONTACT` environment variable so no personal address is committed:

```bash
SEC_CONTACT="you@example.com" python3 scripts/fetch_data.py
```

In CI it comes from a repository secret — **Settings → Secrets and variables
→ Actions → Secrets → New repository secret**, named `SEC_CONTACT`. A secret
rather than a variable, so the address is not readable from a public repo.

It is optional. Without it EDGAR is skipped and the remaining providers carry
the run, which still refreshes **market cap** but leaves cash, revenue and
profit at their stored values.

**Reporting basis:** EDGAR figures are trailing twelve months where four
quarterly facts are available, otherwise the latest annual figure. Foreign
private issuers filing 20-F/40-F have thinner XBRL coverage and fall through to
the other providers.

### Why not just Yahoo

Yahoo Finance rate-limits by IP range. From a GitHub Actions runner it returns
HTTP 429 for **every** request — the first scheduled run failed all 63 tickers
that way. It stays in the chain because it works fine from a laptop, but it
cannot be relied on for the scheduled job.

### Guards

- **If every provider fails for every ticker the file is left untouched** and
  the script exits non-zero. Stamping today's date onto unchanged numbers would
  advertise stale data as fresh, which is worse than an obvious failure.
- **`--fail-under N`** exits non-zero when fewer than N% of tickers refresh, so
  a partial outage fails the build instead of shipping a half-updated map. CI
  uses `--fail-under 60`.
- **A failed refresh never blocks the deploy.** The site stays published with
  the last good figures, clearly dated; the run still goes red.
- **A market cap more than 10x away from the stored one is rejected.** EDGAR's
  `EntityCommonStockSharesOutstanding` is a cover-page fact that some
  multi-class filers report per share class, which would scale a derived cap by
  a whole multiple rather than a few percent. No real session moves a cap that
  far, so the previous figure is kept and the ticker counts as failed.

`scripts/test_fetch_logic.py` covers the parsing (TTM assembly, instant facts,
number formats) with no network, and runs in CI before any request is made.
`scripts/validate_data.py` then gates the deploy: required fields, positive
market caps, numeric financials, known category ids, no duplicate tickers, and
a non-future `asOf`.

Adding a company means adding one object to `companies` (the four curated
fields are enough) and running the script to fill in the numbers.

## Deployment

The site is served by **GitHub Pages** from `.github/workflows/deploy.yml`,
which runs on three triggers:

| Trigger | What happens |
| --- | --- |
| Weekdays at 21:30 UTC | Refresh the data, validate, commit any change, deploy |
| Push to `main` | Validate and deploy (no API calls — a code change shouldn't burn them) |
| Manual dispatch | Same as the daily run, on demand |

21:30 UTC lands shortly after the US close year-round — 16:30 ET under EST
(close 21:00 UTC) and 17:30 ET under EDT (close 20:00 UTC) — so each run picks
up that day's closing figures.

GitHub does not run scheduled jobs on the minute; under load they arrive late,
and roughly 17 minutes has been typical for this repo. That still lands well
after the bell under either offset, which is why the schedule is not set any
closer to the close.

Weekends are excluded — nothing closes, so there is nothing to pick up. On a
market holiday the run finds unchanged prices, produces an empty diff, and
makes no commit.

The deploy job checks out `main` explicitly rather than the triggering SHA, so
it publishes the commit the refresh job just pushed instead of the older one
that started the run.

The site serves at `https://<owner>.github.io/FutureTech/`.

### If the deploy fails at `configure-pages`

The workflow passes `enablement: true`, which asks GitHub to turn Pages on
via the API so no manual setup is needed. If that step still fails with
`Get Pages site failed ... Not Found`, the API call was refused and Pages has
to be switched on by hand:

**Settings → Pages → Build and deployment → Source: GitHub Actions**

Then re-run the workflow.

## Layout

`js/treemap.js` is a standalone implementation of the squarified treemap
algorithm (Bruls, Huizing & van Wijk, 2000), used twice per render: once to
place the sector panels, then once inside each panel to place its companies.
It aims for near-square tiles, which is what keeps labels readable.

Tiles narrower than 26px or shorter than 17px are dropped rather than rendered
as an unreadable sliver. They still count in the header's company count and
combined total, so the numbers always describe the full filtered set.

## Layout of the repo

```
index.html                     markup and the filter controls
css/app.css                    all styling
js/treemap.js                  squarified treemap layout
js/app.js                      filtering, rendering, formatting
data/companies.json            the dataset
scripts/fetch_data.py          refresh from SEC EDGAR + price providers
scripts/test_fetch_logic.py    offline unit tests for the parsing
scripts/validate_data.py       pre-deploy sanity checks
.github/workflows/deploy.yml   daily refresh + Pages deploy
```
