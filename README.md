# The polite scraper — FlyRank W5 · A9

A small, **polite** scraping pipeline for [Books to Scrape](https://books.toscrape.com/), a public
practice sandbox. It downloads the first three catalogue pages, visits all 60 book pages, turns
messy HTML into clean, schema-validated JSON, survives a broken page without crashing, and ends
every run with an honest report.

The pipeline runs as a CLI **and** is exposed over HTTP with **FastAPI**.

---

## Target classification (Stage 0)

| Question | Answer |
| --- | --- |
| **Which site?** | `https://books.toscrape.com` — the Books to Scrape sandbox, part of [toscrape.com](https://toscrape.com/). |
| **Why is it appropriate?** | The site describes itself as a **"Web Scraping Sandbox"** — *"A fictional bookstore that desperately wants to be scraped. It's a safe place for beginners learning web scraping and for developers validating their scraping technologies as well."* The catalogue header reads *"We love being scraped!"* and every page carries *"Warning! This is a demo website for web scraping purposes."* The data is fictional: no personal data, no paywall, no login. That sentence on their page is the permission this project relies on. |
| **How much?** | The **first 3 catalogue pages only** (`catalogue/page-1.html` → `page-3.html`), which is 60 book detail pages. Not the full 1000-book catalogue. |
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

*Stages 1–6 documented below as they are built.*
