#!/usr/bin/env python3
"""
Merchant Website Booking Classifier

Crawls Groupon merchant websites and classifies their booking capabilities.

Usage:
    python run.py                       # Run full pipeline (resume if interrupted)
    python run.py --reset               # Start fresh, ignore previous state
    python run.py --stage 1             # Run only Stage 1
    python run.py --stage 2             # Run only Stages 1-2
    python run.py --stage 3             # Run only Stage 3 (requires Stages 1-2 done)
    python run.py --url URL             # Test a single URL
    python run.py --report              # Generate report from existing state
    python run.py --concurrency 5       # Override Stage 2 concurrency
    python run.py --input FILE          # Specify input CSV path
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    CAT_3P_EMBEDDED,
    CAT_3P_EXTERNAL,
    CAT_3P_IS_WEBSITE,
    CAT_BLOCKED,
    CAT_CALL_EMAIL,
    CAT_INTERNAL,
    CAT_NO_BOOKING,
    CAT_NO_WEBSITE,
    CAT_SOCIAL_MEDIA,
    CAT_UNREACHABLE,
)
from pipeline.loader import load_merchants
from pipeline.stage1_preclass import run_stage1
from pipeline.state import StateStore

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = os.path.join(PROJECT_DIR, "data", "input.csv")
STATE_FILE = os.path.join(PROJECT_DIR, "output", "state.json")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, "screenshots")


def main():
    parser = argparse.ArgumentParser(description="Merchant Website Booking Classifier")
    parser.add_argument("--input", "-i", default=DEFAULT_INPUT, help="Input CSV path")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3], help="Run up to this stage only")
    parser.add_argument("--reset", action="store_true", help="Start fresh")
    parser.add_argument("--url", help="Test a single URL")
    parser.add_argument("--report", action="store_true", help="Generate report from state")
    parser.add_argument("--concurrency", type=int, help="Override Stage 2 concurrency")
    args = parser.parse_args()

    # Single URL mode
    if args.url:
        asyncio.run(_test_single_url(args.url))
        return

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    # Report-only mode
    if args.report:
        state = StateStore(STATE_FILE)
        generate_outputs(state, args.input)
        return

    # Check input file
    if not os.path.exists(args.input):
        print(f"ERROR: Input CSV not found: {args.input}")
        print(f"Place your CSV at {DEFAULT_INPUT} or use --input PATH")
        sys.exit(1)

    # Reset if requested
    if args.reset and os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        print("State reset.")

    # Override concurrency if specified
    if args.concurrency:
        import config
        config.STAGE2_CONCURRENCY = args.concurrency

    # Initialize state
    state = StateStore(STATE_FILE)

    # Load merchants
    print(f"\nLoading merchants from {args.input}...")
    merchants = load_merchants(args.input)
    print(f"  Loaded {len(merchants)} unique merchants")

    # Stage 1
    print("\n--- Stage 1: URL Pre-Classification ---")
    stats = run_stage1(merchants, state)
    print(f"  Platform URLs: {stats['platform_url']}")
    print(f"  Social media:  {stats['social_media']}")
    print(f"  No website:    {stats['no_website']}")
    print(f"  Skipped:       {stats['skipped']}")
    print(f"  Need fetch:    {stats['to_fetch']}")

    if args.stage == 1:
        print("\nStopped after Stage 1.")
        _print_summary(state)
        generate_outputs(state, args.input)
        return

    # Stage 2
    print("\n--- Stage 2: HTTP Fetch + HTML Analysis ---")
    from pipeline.stage2_fetch import run_stage2
    asyncio.run(run_stage2(state))
    _print_summary(state)

    if args.stage == 2:
        print("\nStopped after Stage 2.")
        generate_outputs(state, args.input)
        return

    # Stage 3
    print("\n--- Stage 3: Playwright Booking Flow Simulation ---")
    from pipeline.stage3_deep import run_stage3
    asyncio.run(run_stage3(state, SCREENSHOTS_DIR))
    _print_summary(state)

    # Generate outputs
    print("\n--- Generating Outputs ---")
    generate_outputs(state, args.input)

    print("\nDone!")


async def _test_single_url(url: str):
    """Test classification of a single URL."""
    from pipeline.loader import normalize_url
    from pipeline.detector import check_url_is_platform

    url = normalize_url(url)
    print(f"Testing: {url}\n")

    # Stage 1: URL check
    platform_check = check_url_is_platform(url)
    if platform_check:
        print(f"Stage 1 Result:")
        print(f"  Category:   {platform_check.category}")
        print(f"  Platform:   {platform_check.platform}")
        print(f"  Confidence: {platform_check.confidence}")
        print(f"  Evidence:   {platform_check.evidence}")
        return

    # Check social media
    from urllib.parse import urlparse
    from config import SOCIAL_MEDIA_DOMAINS
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().lstrip("www.")
    for domain in SOCIAL_MEDIA_DOMAINS:
        if host == domain or host.endswith("." + domain):
            print(f"Stage 1 Result:")
            print(f"  Category: {CAT_SOCIAL_MEDIA}")
            print(f"  Domain:   {domain}")
            return

    # Stage 2: HTTP fetch
    print("Stage 1: No match, proceeding to Stage 2...")
    from pipeline.stage2_fetch import fetch_single_url
    result = await fetch_single_url(url)
    print(f"\nStage 2 Result:")
    for key, value in result.items():
        if key != "html":
            print(f"  {key}: {value}")

    # Stage 3 preview
    if result.get("needs_stage3"):
        print(f"\n  → Would proceed to Stage 3 (booking flow simulation)")
        if result.get("booking_button_selector"):
            print(f"    Button to click: {result['booking_button_selector']}")


def _print_summary(state: StateStore):
    """Print a quick summary of current classification status."""
    cats = state.count_by_category()
    stages = state.count_by_stage()
    total = sum(cats.values())

    print(f"\n  Current status ({total} merchants):")
    for cat in [
        CAT_3P_IS_WEBSITE, CAT_3P_EMBEDDED, CAT_3P_EXTERNAL, CAT_INTERNAL,
        CAT_CALL_EMAIL, CAT_NO_BOOKING, CAT_SOCIAL_MEDIA,
        CAT_UNREACHABLE, CAT_BLOCKED, CAT_NO_WEBSITE, "",
    ]:
        if cat in cats:
            pct = cats[cat] / total * 100 if total else 0
            print(f"    {cat or 'pending':30s} {cats[cat]:4d}  ({pct:.1f}%)")

    print(f"  Stages: {stages}")


def generate_outputs(state: StateStore, input_csv: str):
    """Generate CSV, JSON, and summary report outputs."""
    results = state.get_all_results()
    if not results:
        print("  No results to output")
        return

    # --- booking_classification.csv ---
    csv_path = os.path.join(OUTPUT_DIR, "booking_classification.csv")
    fieldnames = [
        "merchant_name", "website_url", "final_url", "category", "platform",
        "confidence", "evidence", "booking_url", "booking_flow_verified",
        "http_status", "screenshot", "orders_30d", "m1_vfm_30d", "deal_count",
    ]

    # Load merchant metadata for orders/vfm
    merchant_meta = {}
    if os.path.exists(input_csv):
        merchants = load_merchants(input_csv)
        for m in merchants:
            key = m.website or f"__no_url__{m.name}"
            merchant_meta[key] = m

    rows = []
    for url, result in results.items():
        meta = merchant_meta.get(url)
        row = {
            "merchant_name": result.get("merchant_name", ""),
            "website_url": result.get("url", url),
            "final_url": result.get("final_url", ""),
            "category": result.get("category", ""),
            "platform": result.get("platform", ""),
            "confidence": f"{result.get('confidence', 0):.2f}",
            "evidence": "; ".join(result.get("evidence", [])),
            "booking_url": result.get("booking_url", ""),
            "booking_flow_verified": result.get("booking_flow_verified", ""),
            "http_status": result.get("http_status", ""),
            "screenshot": result.get("screenshot", ""),
            "orders_30d": meta.orders_30d if meta else "",
            "m1_vfm_30d": f"{meta.m1_vfm_30d:.2f}" if meta else "",
            "deal_count": meta.deal_count if meta else "",
        }
        rows.append(row)

    # Sort by orders descending
    rows.sort(key=lambda r: float(r["orders_30d"] or 0), reverse=True)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  CSV: {csv_path}")

    # --- booking_classification.json ---
    json_path = os.path.join(OUTPUT_DIR, "booking_classification.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  JSON: {json_path}")

    # --- summary_report.txt ---
    report_path = os.path.join(OUTPUT_DIR, "summary_report.txt")
    _generate_summary_report(report_path, results, rows)
    print(f"  Report: {report_path}")

    # --- deals_with_booking.csv ---
    if os.path.exists(input_csv):
        deals_path = os.path.join(OUTPUT_DIR, "deals_with_booking.csv")
        _generate_deals_output(deals_path, input_csv, results)
        print(f"  Deals CSV: {deals_path}")


def _generate_summary_report(path: str, results: dict, rows: list):
    """Generate human-readable summary report."""
    total = len(results)
    cats = {}
    platforms = {}
    for r in results.values():
        cat = r.get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1
        plat = r.get("platform", "")
        if plat:
            platforms[plat] = platforms.get(plat, 0) + 1

    with open(path, "w") as f:
        f.write("=" * 60 + "\n")
        f.write("  Merchant Booking Classification Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total merchants: {total}\n\n")

        f.write("--- Category Breakdown ---\n\n")
        category_order = [
            CAT_3P_IS_WEBSITE, CAT_3P_EMBEDDED, CAT_3P_EXTERNAL, CAT_INTERNAL,
            CAT_CALL_EMAIL, CAT_NO_BOOKING, CAT_SOCIAL_MEDIA,
            CAT_UNREACHABLE, CAT_BLOCKED, CAT_NO_WEBSITE,
        ]
        for cat in category_order:
            count = cats.get(cat, 0)
            pct = count / total * 100 if total else 0
            f.write(f"  {cat:35s} {count:4d}  ({pct:5.1f}%)\n")

        # Online booking total
        online_total = (
            cats.get(CAT_3P_IS_WEBSITE, 0)
            + cats.get(CAT_3P_EMBEDDED, 0)
            + cats.get(CAT_3P_EXTERNAL, 0)
            + cats.get(CAT_INTERNAL, 0)
        )
        pct = online_total / total * 100 if total else 0
        f.write(f"\n  {'TOTAL WITH ONLINE BOOKING':35s} {online_total:4d}  ({pct:5.1f}%)\n")

        f.write("\n--- Platform Breakdown ---\n\n")
        for plat, count in sorted(platforms.items(), key=lambda x: -x[1]):
            f.write(f"  {plat:30s} {count:4d}\n")

        # Top merchants without online booking
        f.write("\n--- Top Merchants Without Online Booking (by orders) ---\n\n")
        no_booking = [
            r for r in rows
            if r["category"] in (CAT_NO_BOOKING, CAT_CALL_EMAIL)
            and r["orders_30d"]
        ]
        no_booking.sort(key=lambda r: float(r["orders_30d"] or 0), reverse=True)
        for i, r in enumerate(no_booking[:20], 1):
            name = str(r['merchant_name'])[:40]
            orders = str(r['orders_30d'])
            f.write(
                f"  {i:2d}. {name:40s} "
                f"orders={orders:>8s}  "
                f"category={r['category']}\n"
            )

        # Verified booking flows
        verified = sum(
            1 for r in results.values() if r.get("booking_flow_verified")
        )
        f.write(f"\n--- Booking Flow Verification ---\n\n")
        f.write(f"  Verified booking flows: {verified}\n")
        f.write(f"  Screenshots saved: {sum(1 for r in results.values() if r.get('screenshot'))}\n")


def _generate_deals_output(path: str, input_csv: str, results: dict):
    """Generate original deals CSV joined with booking classification."""
    from pipeline.loader import normalize_url

    # Build URL -> result lookup
    url_to_result = {}
    for url, result in results.items():
        url_to_result[url] = result

    with open(input_csv, newline="", encoding="utf-8-sig") as fin:
        reader = csv.DictReader(fin)
        input_fields = reader.fieldnames or []
        output_fields = input_fields + [
            "booking_category", "booking_platform", "booking_confidence",
            "booking_url", "booking_flow_verified",
        ]

        with open(path, "w", newline="") as fout:
            writer = csv.DictWriter(fout, fieldnames=output_fields)
            writer.writeheader()

            for row in reader:
                raw_url = row.get("website", "").strip()
                url = normalize_url(raw_url)
                result = url_to_result.get(url, {})

                row["booking_category"] = result.get("category", "")
                row["booking_platform"] = result.get("platform", "")
                row["booking_confidence"] = f"{result.get('confidence', 0):.2f}"
                row["booking_url"] = result.get("booking_url", "")
                row["booking_flow_verified"] = result.get("booking_flow_verified", "")
                writer.writerow(row)


if __name__ == "__main__":
    main()
