# The polite scraper — FlyRank W5 · A9

A small, **polite** scraping pipeline for [Books to Scrape](https://books.toscrape.com/), a public
practice sandbox. It downloads the first three catalogue pages, visits all 60 book pages, turns
messy HTML into clean, schema-validated JSON, survives a broken page without crashing, and ends
every run with an honest report.

```
fetch → extract → normalize → validate → store → report
```

The pipeline is a plain Python library with two front ends: a **CLI** for one-shot runs and a
**FastAPI** service that runs the scraper and serves what it collected.

**Python lane:** Requests · Beautiful Soup · Pydantic · FastAPI.

---

## Quick start (under 5 minutes)

```bash
git clone https://github.com/gamalieldashuaDataFi/flyrank-polit-scraper.git
cd flyrank-polit-scraper

python3 -m venv .venv && source .venv/bin/activate   # Python 3.10+
pip install -r requirements.txt

python -m src.main            # <-- the one documented command
```

The first run takes about 40 seconds (63 real requests, half a second apart, by design). Every run
after that is served from `cache/` and finishes in ~2 seconds.

It writes:

| File | What is in it |
| --- | --- |
| `output/books.json` | the 60 validated records |
| `output/errors.json` | records that failed validation, each with the reason |
| `output/run-report.json` | the honest numbers for the last run |
| `output/runs/<run_id>.json` | one archived report per run |
| `output/books.csv` | flattened export (extra) |
| `cache/*.html` | the saved pages, so the site is asked once |

Useful flags:

```bash
python -m src.main --pages 1        # walk fewer catalogue pages
python -m src.main --refresh        # ignore the cache and ask the site again
python -m src.main --inject-broken  # the failure drill (see below)
python -m src.main --log-json       # structured logs, one JSON object per line
```

### Run it as an API

```bash
uvicorn src.api:app --reload        # then open http://127.0.0.1:8000/docs
```

| Endpoint | What it does |
| --- | --- |
| `GET /health` | liveness, target, how many records are loaded, whether a run is active |
| `POST /runs` | start a scrape in the background → `202` + `Location: /runs/{run_id}` |
| `GET /runs` | runs started by this process, newest first |
| `GET /runs/latest` | the last run report |
| `GET /runs/{run_id}` | live status, or the archived report |
| `GET /books` | validated records: `q`, `min_price`, `max_price`, `rating`, `in_stock`, `sort`, `desc`, `limit`, `offset` |
| `GET /books/{record_id}` | one record |
| `GET /books.csv` | the flattened export |
| `GET /errors` | records that failed validation, with the reason |

```bash
curl -X POST localhost:8000/runs -H 'content-type: application/json' -d '{"pages": 3}'
curl 'localhost:8000/books?q=light&limit=1' | jq
curl localhost:8000/runs/latest | jq '.valid_records, .failed_pages'
```

Two politeness rules are enforced at the HTTP layer too: **one run at a time** (a second `POST /runs`
gets `409` rather than doubling the traffic the sandbox sees), and reads never re-scrape — they serve
what a run already stored.

---

## Target classification (Stage 0)

| Question | Answer |
| --- | --- |
| **Which site?** | `https://books.toscrape.com` — the Books to Scrape sandbox, part of [toscrape.com](https://toscrape.com/). |
| **Why is it appropriate?** | The site describes itself as a **"Web Scraping Sandbox"** — *"A fictional bookstore that desperately wants to be scraped. It's a safe place for beginners learning web scraping and for developers validating their scraping technologies as well."* The catalogue header reads *"We love being scraped!"* and every page carries *"Warning! This is a demo website for web scraping purposes."* The data is fictional: no personal data, no paywall, no login. That sentence on their page is the permission this project relies on. |
| **How much?** | The **first 3 catalogue pages only** (`catalogue/page-1.html` → `page-3.html`), which is 60 book detail pages — not the full 1000-book catalogue. |
| **What data?** | Per book: title, product URL, price text, availability text, rating text, description, plus provenance (`source_page`, `fetched_at`). Nothing else. |
| **robots.txt** | Requested once on 2026-08-30: `GET https://books.toscrape.com/robots.txt` → **404 Not Found → no robots file found**. A missing file is *not* permission — it is just a missing file, so the scope above is kept deliberately small and the crawl stays polite regardless. Raw evidence: [`docs/robots-check.txt`](docs/robots-check.txt). |

> **I will not reuse this code on another site without checking its rules and terms first.**

### Ethics note

Scraping is a last resort, not a first one. If an official API or a bulk export exists, use it — it is
cheaper for me and for the site owner. I never bypass a login, a paywall, a CAPTCHA or a block: those
are the site saying "no", and a polite robot takes no for an answer. I collect only the fields I
actually need, identify myself honestly in the `User-Agent` so an operator reading their logs can find
me, keep the request rate far below anything that could affect the service, and cache aggressively so
the site is asked once for something I read fifty times. Public availability is not the same as
consent, and personal data is out of scope entirely.

---

## The politeness rules this code follows

| Rule | Where it lives | How it is enforced |
| --- | --- | --- |
| **Identify yourself** | `Settings.user_agent` | `FlyRankInternshipA9/1.0 (+https://github.com/gamalieldashuaDataFi/flyrank-polit-scraper)` — a name *and* a contact link, on every request. |
| **Time out** | `Settings.request_timeout_seconds` | 10 s. A request may never hang forever. |
| **Go slowly** | `PoliteFetcher._wait_turn` | ≥ 500 ms between two *real* requests. The floor is a schema constraint (`ge=0.5`), so it cannot be configured away. Cache hits wait for nothing — they never leave the computer. |
| **Check the status first** | `PoliteFetcher.fetch` | Only `200` is treated as HTML. Anything else is a failed fetch. |
| **Cache** | `HtmlCache` | Every page is saved to `cache/<readable-slug>.html` with a provenance sidecar. Development restarts read the copy, not the site. |
| **Retry only what deserves it** | `RETRYABLE_STATUSES` | One retry for a timeout, a connection error, `5xx` or `429`, with exponential backoff, jitter and `Retry-After` respected. **Never** for `404` (asking again will not create the page) or `403` (the site said no). |
| **One run at a time** | `ScrapeRunner` | The API refuses a concurrent run with `409`. |

---

## The record schema

**Raw record** (Stage 3) — exactly what the page said, eight keys, nothing invented:

```json
{
  "title": "A Light in the Attic",
  "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
  "price_text": "£51.77",
  "availability_text": "In stock (22 available)",
  "rating_text": "Three",
  "description": "It's hard to imagine a world without A Light in the Attic. …",
  "source_page": "https://books.toscrape.com/catalogue/page-1.html",
  "fetched_at": "2026-08-30T17:32:51.183067Z"
}
```

A book with no description stores `null`. `source_page` and `fetched_at` are the **provenance** — the
receipt showing where and when a fact came from — and are never overwritten.

**Validated record** (`src/models.py:Book`) — raw and clean values side by side:

| Field | Type | Required | Note |
| --- | --- | --- | --- |
| `record_id` | `str` | ✔ | slug from the canonical URL, e.g. `a-light-in-the-attic_1000` |
| `product_url` | `str` | ✔ | **canonical URL — the record's identity**; must start with `https://` |
| `title` | `str` (non-empty) | ✔ | whitespace collapsed |
| `price_gbp` | `float > 0` | ✔ | `"£51.77"` → `51.77` |
| `price_text` | `str` | ✔ | the original string, kept on purpose |
| `currency` | `str(3)` | ✔ | `GBP` |
| `rating` | `int` 1–5 | ✔ | `"Three"` → `3` |
| `rating_text` | `str` | ✔ | the original word |
| `availability_text` | `str` | ✔ | the original sentence |
| `in_stock` | `bool` | ✔ | derived from the sentence |
| `stock_count` | `int \| null` | — | `"In stock (22 available)"` → `22` |
| `description` | `str \| null` | — | **optional** — `null` when the page has none |
| `source_page` | `str` | ✔ | provenance; must start with `https://` |
| `fetched_at` | `datetime` | ✔ | provenance, UTC |

Validation happens **before** storage. A record that fails is written to `output/errors.json` with the
reason, the failing fields and the raw record — it never sneaks into `books.json`.

**Idempotency:** records are keyed by their canonical `product_url`, so a book listed twice counts
once and a rerun produces the same 60 records, never 120.

---

## Proof: a real run report

`output/run-report.json` from a cold run (empty cache), copied verbatim
([`docs/sample-run-report.json`](docs/sample-run-report.json)):

```json
{
  "run_id": "d6ccc27b6f06",
  "started_at": "2026-08-30T17:32:50.798026Z",
  "finished_at": "2026-08-30T17:33:29.470373Z",
  "duration_seconds": 38.673,
  "target": "https://books.toscrape.com/",
  "catalogue_pages": 3,
  "discovered": 60,
  "unique_urls": 60,
  "detail_pages": 60,
  "pages_fetched": 63,
  "cache_hits": 0,
  "retries": 0,
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 0,
  "failures": [],
  "outputs": {
    "books": "output/books.json",
    "errors": "output/errors.json",
    "csv": "output/books.csv",
    "report": "output/run-report.json"
  }
}
```

A sample of the stored records is in [`docs/sample-books.json`](docs/sample-books.json).

### The failure drill

`python -m src.main --inject-broken` adds one made-up book URL to the list — breaking things on our
side only, never by hammering the real site. The run still finishes, `books.json` still holds the 60
good records, and the report says so
([`docs/sample-run-report-with-failure.json`](docs/sample-run-report-with-failure.json)):

```json
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 1,
  "failures": [
    {
      "url": "https://books.toscrape.com/catalogue/this-book-does-not-exist_0/index.html",
      "stage": "fetch",
      "reason": "unexpected status 404",
      "status_code": 404,
      "attempts": 1
    }
  ]
```

`attempts: 1` is the point: a `404` is an answer, so it is never retried.

---

## Why this assignment needed no browser

The data is already in the HTML the server sends — titles, prices, availability and descriptions are
all in the response body — so a browser would only add cost. Measured on
`https://quotes.toscrape.com/js/`, a page that *does* render its content with JavaScript
(`python scripts/browser_cost.py`, raw numbers in [`docs/browser-cost.json`](docs/browser-cost.json)):

| Approach | Time | Peak memory | Bytes | Quotes found |
| --- | --- | --- | --- | --- |
| Plain HTTP (Requests + Beautiful Soup) | **0.91 s** | 31.8 MiB | 5.8 kB | **0** |
| Playwright driving Chrome | **6.21 s** | 40.8 MiB¹ | 9.0 kB | **10** |

¹ Measured with `getrusage`, which only sees this process and its direct children — Chrome's own
multi-process footprint is far larger. Treat it as a floor, not a measurement of Chrome.

So: ~7× slower for the page that needs it, and zero benefit for the page that doesn't. On
`quotes.toscrape.com/js` a plain request finds **no quotes at all** (view the source and they are
simply not there) and a browser is the only option; on `books.toscrape.com` the browser would render
the same bytes we already parsed.

---

## Tests

```bash
pytest          # 54 tests, ~1.5 s, no network access at all
ruff check src tests
```

A fake `requests.Session` serves the HTML fixtures in `tests/fixtures/`, so the suite runs offline and
deterministically. It covers price normalization, relative→absolute URLs, a missing description,
duplicate URLs, a malformed page, cache behaviour (including provenance and a corrupt entry), the
retry rules (`404` never, `500` once, timeout once), idempotent reruns, the failure drill, the run
report and the FastAPI contract.

---

## Project layout

```
src/
  main.py           CLI entry point  ..............  python -m src.main
  api.py            FastAPI app  ..................  uvicorn src.api:app
  config.py         settings; the politeness floor lives here
  logging_setup.py  structured key=value / JSON logs
  http_client.py    PoliteFetcher + HtmlCache      (fetch)
  discovery.py      catalogue crawl                (find the 60 URLs)
  extraction.py     HTML → the eight raw fields    (extract)
  normalization.py  raw strings → clean values     (normalize)
  models.py         Pydantic schemas               (validate)
  store.py          atomic JSON/CSV writes         (store)
  pipeline.py       the orchestrator               (report)
  repository.py     read side, used by the API
  runner.py         background run bookkeeping
scripts/browser_cost.py   the browser-cost measurement
tests/                    54 offline tests + HTML fixtures
docs/                     robots evidence, sample outputs
```

Each stage of the assignment is one commit: `git log --oneline`.

---

## Honest limitations

1. **The selectors are Books to Scrape's selectors.** `article.product_page`, `p.price_color`,
   `p.star-rating` — if the sandbox redesigns, extraction breaks. It breaks *loudly* (an
   `ExtractionError` per page, counted in the report) rather than silently storing nulls, but it
   breaks. There is no schema-drift alarm yet.
2. Scope is fixed to the **first three catalogue pages**; nothing here is built for the full
   1000-book catalogue, and there is no politeness budget across concurrent processes — the delay is
   per-process.
3. The cache never expires by default (`SCRAPER_CACHE_TTL_HOURS` sets one). Prices in `books.json`
   are therefore as old as the cache; `fetched_at` is what tells you how old.
4. `description` keeps the site's own quirk — the catalogue repeats a truncated teaser before the
   full text — because inventing a fix would be inventing data. The only thing trimmed is the literal
   `...more` UI marker, and the raw text stays in the raw record.
5. `stock_count` is `null` when the page says "In stock" without a number: unknown is not zero.
6. Not built: the bonus **AI rematch**, the local Ollama enrichment, and the queued-job background
   execution from the stretch list.

## Stage map

| Stage | Commit | Checkpoint |
| --- | --- | --- |
| 0 | `Stage 0: classify scraping target` | README names target, scope, robots result |
| 1 | `Stage 1: fetch and cache HTML` | run twice → `FETCH`, then `CACHE HIT` |
| 2 | `Stage 2: discover three catalogue pages` | `catalogue_pages=3 discovered=60 unique_urls=60` |
| 3 | `Stage 3: extract book details` | one raw record, all eight keys, `detail_pages=60` |
| 4 | `Stage 4: validate normalized records` | 60 records, numeric prices, https URLs, stable on rerun |
| 5 | `Stage 5: survive failures, report the run` | one fake URL → `failed_pages: 1`, 60 records survive |
| — | `API: expose the pipeline over HTTP with FastAPI` | `/health`, `/runs`, `/books` |
| — | `Tests: parser fixtures and an offline test suite` | `pytest` → 54 passed |
| 6 | `Stage 6: publish scraper evidence` | a stranger runs one command and gets `books.json` |
