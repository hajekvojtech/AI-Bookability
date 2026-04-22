# AI-Bookability

Given a list of merchant websites, figure out whether each one offers online booking — and if so, which platform they use (Mindbody, Vagaro, Booksy, Square Appointments, Boulevard, etc.).

Deterministic string/regex matching against known platform signatures. No LLM calls in the crawl loop.

## Two pipelines live in this repo

| pipeline | files | state backend | status |
|---|---|---|---|
| **New (recommended)** | `prepass.py` · `crawler.py` · `crawler_playwright.py` · `export.py` · `pipeline/sqlite_store.py` | SQLite ledger (`data/results.db`) | Active. Resumable, sub-page follow, tracks 31 platforms, marks unidentified-but-booking merchants as `(unknown)`. |
| Legacy | `run.py` + `pipeline/stage1_preclass.py` · `stage2_fetch.py` · `stage3_deep.py` + `pipeline/state.py` | JSON state file (`output/state.json`) | Still works. Left in place for reference. |

Both pipelines share `config.py` (platform signatures), `pipeline/loader.normalize_url`, and `pipeline/detector.detect_from_html`.

**If you are starting fresh, use the new pipeline. See [`README_pilot.md`](README_pilot.md) for the full runbook.**

## Quick start (new pipeline)

```bash
git clone https://github.com/hajekvojtech/AI-Bookability.git
cd AI-Bookability
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Put your input CSV at `data/input.csv`. It must have a `website` column; other columns are preserved as metadata.

```bash
python prepass.py data/input.csv     # Tier 0: URL-host matches (no network)
python crawler.py                    # Tier 1: httpx + HTML signature match
python crawler_playwright.py         # Tier 2: Playwright fallback for blocked/unresolved
python export.py                     # Writes data/results.csv + prints summary
```

Results land in `data/results.db`. Kill any script with Ctrl-C and re-run the same command — it resumes from where it left off.

## What the classifier outputs

For each merchant URL:

| field | values |
|---|---|
| `status` | `bookable` · `no_signature` · `error` · `timeout` · `blocked` |
| `platform` | platform name (e.g. `Vagaro`) · `(unknown)` when booking intent is clear but vendor isn't identified · empty for internal/custom booking forms |
| `category` | fine-grained: `3p_booking_is_website` · `3p_booking_embedded` · `3p_booking_external` · `internal_booking` · `social_media_only` · `call_email_only` · `no_booking_found` · `likely_bookable` |
| `evidence` | truncated snippet showing why the classifier reached its verdict |
| `tier` | `0` (URL host), `1` (httpx), `2` (Playwright) |

## Platforms currently recognized

Wix Bookings · GlossGenius · Square Appointments · Vagaro · Acuity Scheduling · Mindbody · Zenoti · Booksy · Fresha · MassageBook · Boulevard · LeadConnector · Jane App · Booker · byChronos · Setmore · StyleSeat · Calendly · PocketSuite · Schedulicity · Salon Lofts · Smiley · WellnessLiving · SimplyBook.me · Genbook · PushPress · Restore Hyper Wellness · Timely · Myoryx · Picktime.

Adding a new platform is a 5-line change in `config.py` (domain + scripts/iframes/links/html_patterns).

## Design notes

- **Primary key is the normalized URL, not the hostname** — two different merchants on the same platform (e.g. both on `vagaro.com`) are separate rows.
- **Errors are results, not silence.** Dead DNS, timeouts, WAF blocks all get a row in the ledger with the failure reason. They count as processed, not skipped.
- **Per-URL commit.** A kill at any moment loses at most one in-flight result.
- **Sub-page follow (Tier 1).** When the home page has a "Book Appointment" / "Schedule" button but no platform match, the crawler follows up to 2 booking-related links 1 hop deep and re-detects. Catches widgets gated behind `/appointments/`, `/schedule/`, `/book/` pages.
- **Unknown-platform marking.** If the sub-page scan is exhausted and no vendor is identified, the merchant is still tagged `bookable / platform=(unknown)` rather than buried in `no_signature`. Captures real booking intent we couldn't attribute.

## Data lives in `data/` (gitignored)

Your input CSV, the SQLite ledger, and the exported results CSV all stay local. Nothing in `data/` is committed.

## License

No license file yet. If you intend to reuse this, open an issue.
