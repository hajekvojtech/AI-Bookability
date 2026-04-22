#!/usr/bin/env python3
"""
Export results.db to CSV + print a summary report.

Joins results to input_domains so each row has full merchant metadata
alongside the classification.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.sqlite_store import connect  # noqa: E402

DEFAULT_DB = "data/results.db"
DEFAULT_OUT = "data/results.csv"

FIELDS = [
    "account_id", "merchant_name", "raw_website", "url", "final_url",
    "category_v3", "subcategory_v3", "vertical",
    "billingcity", "billingstate", "last_voucher_sold_date", "merchant_tier",
    "tier", "status", "platform", "category", "evidence",
    "http_status", "error", "crawled_at",
]


def export(db_path: str, out_csv: str) -> dict:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                i.account_id, i.merchant_name, i.raw_website, i.url,
                r.final_url,
                i.category_v3, i.subcategory_v3, i.vertical,
                i.billingcity, i.billingstate, i.last_voucher_sold_date, i.merchant_tier,
                r.tier, r.status, r.platform, r.category, r.evidence,
                r.http_status, r.error, r.crawled_at
            FROM input_domains i
            LEFT JOIN results r USING(url)
            ORDER BY r.status, r.platform NULLS LAST, i.merchant_name
            """
        ).fetchall()

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] if r[k] is not None else "" for k in FIELDS})

    return {"rows": len(rows)}


def summarize(db_path: str) -> None:
    with connect(db_path) as conn:
        total_inputs = conn.execute("SELECT COUNT(*) AS n FROM input_domains").fetchone()["n"]
        total_results = conn.execute("SELECT COUNT(*) AS n FROM results").fetchone()["n"]

        status_counts = conn.execute(
            "SELECT status, COUNT(*) AS n FROM results GROUP BY status ORDER BY n DESC"
        ).fetchall()

        tier_counts = conn.execute(
            "SELECT tier, COUNT(*) AS n FROM results GROUP BY tier ORDER BY tier"
        ).fetchall()

        platform_counts = conn.execute(
            """
            SELECT platform, COUNT(*) AS n FROM results
            WHERE status = 'bookable' AND platform IS NOT NULL
            GROUP BY platform ORDER BY n DESC
            """
        ).fetchall()

        sample_bookable = conn.execute(
            """
            SELECT i.merchant_name, i.url, r.platform, r.evidence
            FROM results r JOIN input_domains i USING(url)
            WHERE r.status = 'bookable'
            ORDER BY RANDOM() LIMIT 5
            """
        ).fetchall()

        sample_no_sig = conn.execute(
            """
            SELECT i.merchant_name, i.url
            FROM results r JOIN input_domains i USING(url)
            WHERE r.status = 'no_signature'
            ORDER BY RANDOM() LIMIT 5
            """
        ).fetchall()

    print(f"\n=== Summary ===")
    print(f"  Total inputs:   {total_inputs}")
    print(f"  Total results:  {total_results}")
    print(f"  Coverage:       {total_results}/{total_inputs}")

    print(f"\n  By status:")
    for row in status_counts:
        pct = row["n"] / total_results * 100 if total_results else 0
        print(f"    {row['status']:15s} {row['n']:4d}  ({pct:5.1f}%)")

    print(f"\n  By tier:")
    for row in tier_counts:
        print(f"    tier {row['tier']}:  {row['n']}")

    print(f"\n  Bookable by platform:")
    for row in platform_counts:
        print(f"    {row['platform']:25s} {row['n']}")

    print(f"\n  Sample bookable (5 random):")
    for r in sample_bookable:
        name = (r["merchant_name"] or "")[:35]
        url = (r["url"] or "")[:55]
        ev = (r["evidence"] or "")[:70]
        print(f"    [{r['platform']}] {name}  {url}")
        print(f"        evidence: {ev}")

    print(f"\n  Sample no_signature (5 random):")
    for r in sample_no_sig:
        name = (r["merchant_name"] or "")[:35]
        url = (r["url"] or "")[:55]
        print(f"    {name}  {url}")


def main():
    ap = argparse.ArgumentParser(description="Export results.db + summary")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--quiet", action="store_true", help="Skip printed summary")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: {args.db} does not exist", file=sys.stderr)
        sys.exit(1)

    result = export(args.db, args.out)
    print(f"Wrote {result['rows']} rows -> {args.out}")
    if not args.quiet:
        summarize(args.db)


if __name__ == "__main__":
    main()
