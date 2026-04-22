#!/usr/bin/env python3
"""
Tier 0: load input CSV, normalize URLs, seed input_domains, and resolve
everything we can without network.

Writes three kinds of Tier 0 rows to `results`:
  - status=bookable, tier=0   : URL host is on BOOKING_PLATFORM_DOMAINS
  - status=no_signature, tier=0, category=social_media_only : URL on social
  - status=error, tier=0, error='no_parseable_website'      : junk/empty

Everything else is inserted into input_domains only and will be picked up
by crawler.py.

Idempotent: re-running re-seeds input_domains and re-resolves Tier 0 matches
without duplicating work.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BOOKING_PLATFORM_DOMAINS, SOCIAL_MEDIA_DOMAINS
from pipeline.loader import normalize_url
from pipeline.sqlite_store import (
    connect,
    init_db,
    stats,
    upsert_input_domain,
    upsert_result,
)

DEFAULT_DB = "data/results.db"


def host_of(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        if h.startswith("www."):
            h = h[4:]
        return h
    except Exception:
        return ""


def match_platform(host: str) -> tuple[str, str] | None:
    for domain, platform in BOOKING_PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return domain, platform
    return None


def match_social(host: str) -> str | None:
    for domain in SOCIAL_MEDIA_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def run(input_csv: str, db_path: str) -> dict:
    init_db(db_path)
    seen_urls: dict[str, dict] = {}
    bad_rows: list[dict] = []

    with open(input_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = (row.get("website") or "").strip()
            url = normalize_url(raw)
            record = {
                "url": url,
                "account_id": row.get("account_id", ""),
                "merchant_name": row.get("merchant_name", ""),
                "raw_website": raw,
                "category_v3": row.get("category_v3", ""),
                "subcategory_v3": row.get("subcategory_v3", ""),
                "vertical": row.get("vertical", ""),
                "billingcity": row.get("billingcity", ""),
                "billingstate": row.get("billingstate", ""),
                "last_voucher_sold_date": row.get("last_voucher_sold_date", ""),
                "merchant_segmentation": row.get("merchant_segmentation", ""),
                "merchant_tier": row.get("merchant_tier", ""),
            }
            if not url:
                bad_rows.append(record)
                continue
            # Dedupe by normalized URL. First occurrence wins; later occurrences
            # are dropped silently (same merchant listed twice).
            if url not in seen_urls:
                seen_urls[url] = record

    counts = {
        "input_rows": 0,
        "dedup_inputs": len(seen_urls),
        "bad_websites": len(bad_rows),
        "tier0_bookable": 0,
        "tier0_social": 0,
    }

    with connect(db_path) as conn:
        conn.execute("BEGIN")
        try:
            for record in seen_urls.values():
                upsert_input_domain(conn, record)
                counts["input_rows"] += 1

                host = host_of(record["url"])
                platform_match = match_platform(host)
                if platform_match:
                    domain, platform = platform_match
                    upsert_result(
                        conn,
                        url=record["url"],
                        tier=0,
                        status="bookable",
                        platform=platform,
                        category="3p_booking_is_website",
                        evidence=f"URL host is booking platform domain: {domain}",
                    )
                    counts["tier0_bookable"] += 1
                    continue

                social_match = match_social(host)
                if social_match:
                    upsert_result(
                        conn,
                        url=record["url"],
                        tier=0,
                        status="no_signature",
                        platform=None,
                        category="social_media_only",
                        evidence=f"URL host is social media: {social_match}",
                    )
                    counts["tier0_social"] += 1

            # Junk websites — seed a synthetic URL keyed on account_id so the row
            # exists but doesn't collide with real normalized URLs.
            for bad in bad_rows:
                synth_url = f"__no_url__{bad['account_id'] or bad['merchant_name']}"
                bad["url"] = synth_url
                upsert_input_domain(conn, bad)
                upsert_result(
                    conn,
                    url=synth_url,
                    tier=0,
                    status="error",
                    error="no_parseable_website",
                    evidence=f"raw_website={bad['raw_website'][:200]!r}",
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        s = stats(conn)

    return {**counts, **s}


def main():
    ap = argparse.ArgumentParser(description="Tier 0 prepass")
    ap.add_argument("input_csv", nargs="?", default="data/input_100.csv")
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()

    if not os.path.exists(args.input_csv):
        print(f"ERROR: input CSV not found: {args.input_csv}", file=sys.stderr)
        sys.exit(1)

    print(f"Prepass: {args.input_csv} -> {args.db}")
    result = run(args.input_csv, args.db)
    print(f"  unique URLs seeded:  {result['dedup_inputs']}")
    print(f"  tier 0 bookable:     {result['tier0_bookable']}")
    print(f"  tier 0 social:       {result['tier0_social']}")
    print(f"  tier 0 bad websites: {result['bad_websites']}")
    print(f"  total in input_domains: {result['inputs']}")
    print(f"  total in results:       {result['done']}")
    print(f"  remaining (for crawler): {result['remaining']}")


if __name__ == "__main__":
    main()
