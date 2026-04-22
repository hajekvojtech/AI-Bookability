# Resumable SQLite-backed booking-platform classifier

Three tiers:

- **Tier 0** (prepass.py): free match on URL host against `BOOKING_PLATFORM_DOMAINS` + `SOCIAL_MEDIA_DOMAINS`. No network.
- **Tier 1** (crawler.py): httpx fetch, match signatures against raw HTML. 20 concurrent, 2s per-host rate limit, 10s timeout.
- **Tier 2** (crawler_playwright.py): rendered-DOM fallback for anything Tier 1 didn't resolve. 3 concurrent contexts, `domcontentloaded` + 2.5s settle, 20s timeout.

All progress lives in `data/results.db`. Kill any process at any time — restart picks up where it left off.

## One-time setup

```bash
cd <your-clone-dir>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium     # ~180 MB download
```

## Running the pipeline

Input CSV must live at `data/input.csv` with at minimum a `website` column. Any additional columns are stored as merchant metadata and included in the export join. Commonly useful extras: `account_id`, `merchant_name`, `category_v3`, `subcategory_v3`, `billingcity`, `billingstate`.

```bash
# 1. Seed input_domains + resolve Tier 0 matches (seconds)
python prepass.py data/input.csv

# 2. Tier 1 httpx (a few minutes for 100 rows)
python crawler.py

# 3. Tier 2 Playwright (5–15 minutes depending on how many Tier 1 left unresolved)
python crawler_playwright.py

# 4. Export CSV + summary
python export.py data/input.csv
# -> data/results.csv + printed summary
```

## Resumability

Kill any script with Ctrl-C. Re-run the same command. Progress resumes from SQLite.

Try it during Tier 1:

```bash
python crawler.py          # Ctrl-C after ~30 URLs
python crawler.py          # continues with remaining ~70
```

Each run prints a final line like `N done / M remaining / elapsed T`.

## Retry only the errors

```bash
python crawler.py --retry-errors
```

This deletes `results` rows whose Tier 1 status is `error|timeout|blocked` so they re-queue. Doesn't touch rows already classified as `bookable` or `no_signature`.

## Inspect the ledger directly

```bash
sqlite3 data/results.db "SELECT status, COUNT(*) FROM results GROUP BY status;"
sqlite3 data/results.db "SELECT platform, COUNT(*) FROM results WHERE status='bookable' GROUP BY platform;"
```

## Schema

```sql
input_domains(url PK, account_id, merchant_name, raw_website,
              category_v3, subcategory_v3, vertical,
              billingcity, billingstate, last_voucher_sold_date,
              merchant_segmentation, merchant_tier)

results(url PK, tier, status, platform, category, evidence,
        http_status, final_url, error, crawled_at)
```

`status` ∈ `{bookable, no_signature, error, timeout, blocked}`.
Primary key is the full normalized URL (not hostname), so two merchants
on the same platform don't collide.

## Coexistence with legacy pipeline

The legacy `run.py` + `pipeline/stage*` + JSON `StateStore` are untouched.
Both pipelines share `config.py` signatures and `pipeline/loader.normalize_url`
and `pipeline/detector.detect_from_html`.
