#!/usr/bin/env python3
"""
Tier 2: Playwright fallback.

Reads rows from `results` that didn't resolve in Tier 1 (status in
no_signature/error/timeout/blocked) and renders them in a real browser.
Matches signatures against the rendered DOM. Overwrites the Tier 1 row
with tier=2 + fresh outcome.

Uses `domcontentloaded` + 2.5s settle (not networkidle, which hangs on
sites with constant telemetry pings).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (  # noqa: E402
    CAT_3P_EMBEDDED,
    CAT_3P_EXTERNAL,
    CAT_3P_IS_WEBSITE,
    CAT_CALL_EMAIL,
    CAT_INTERNAL,
    CAT_NO_BOOKING,
    CAT_SOCIAL_MEDIA,
    USER_AGENTS,
)
from pipeline.detector import detect_from_html  # noqa: E402
from pipeline.sqlite_store import connect, init_db, stats, tier2_urls, upsert_result  # noqa: E402

DEFAULT_DB = "data/results.db"
CONCURRENCY = 3
PAGE_LOAD_TIMEOUT_MS = 20_000
SETTLE_SECONDS = 2.5

BOOKABLE_CATS = {CAT_3P_IS_WEBSITE, CAT_3P_EMBEDDED, CAT_3P_EXTERNAL, CAT_INTERNAL}

_stop = asyncio.Event()


def _install_sigint_handler() -> None:
    def handler(signum, frame):
        if not _stop.is_set():
            print("\n[SIGINT] cancelling pending pages…", file=sys.stderr)
            _stop.set()
        else:
            print("\n[SIGINT x2] hard exit", file=sys.stderr)
            sys.exit(130)

    signal.signal(signal.SIGINT, handler)


async def render_one(browser, url: str) -> dict:
    """Open a fresh context + page, return dict with outcome."""
    import random

    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1366, "height": 900},
    )
    page = await context.new_page()
    try:
        try:
            resp = await page.goto(
                url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS
            )
        except Exception as e:
            return {"status": "timeout" if "Timeout" in str(type(e).__name__) else "error",
                    "error": f"{type(e).__name__}: {e}"}

        # Settle: let SPAs finish mounting / late widgets inject
        try:
            await asyncio.sleep(SETTLE_SECONDS)
        except asyncio.CancelledError:
            raise

        http_status = resp.status if resp else None
        final_url = page.url
        html = await page.content()
    finally:
        try:
            await context.close()
        except Exception:
            pass

    if http_status and http_status >= 400:
        return {
            "status": "error" if http_status < 500 else "blocked",
            "http_status": http_status,
            "final_url": final_url,
            "error": f"HTTP {http_status}",
        }

    det = detect_from_html(html, final_url)
    evidence = "; ".join(det.evidence) if det.evidence else ""

    if det.category in BOOKABLE_CATS:
        return {
            "status": "bookable",
            "platform": det.platform or "",
            "category": det.category,
            "evidence": evidence,
            "http_status": http_status,
            "final_url": final_url,
        }

    category = det.category if det.category else CAT_NO_BOOKING
    return {
        "status": "no_signature",
        "category": category,
        "evidence": evidence or "no booking signature matched (rendered)",
        "http_status": http_status,
        "final_url": final_url,
    }


async def worker(url: str, browser, sem: asyncio.Semaphore, db_path: str, done_counter: dict):
    if _stop.is_set():
        return
    async with sem:
        if _stop.is_set():
            return
        try:
            result = await render_one(browser, url)
        except Exception as e:
            result = {"status": "error", "error": f"{type(e).__name__}: {e}"}

        with connect(db_path) as conn:
            upsert_result(
                conn,
                url=url,
                tier=2,
                status=result["status"],
                platform=result.get("platform"),
                category=result.get("category"),
                evidence=result.get("evidence"),
                http_status=result.get("http_status"),
                final_url=result.get("final_url"),
                error=result.get("error"),
            )
        done_counter["n"] += 1
        total = done_counter["total"]
        print(
            f"  [{done_counter['n']}/{total}] {url[:70]} -> {result['status']}"
            + (f" ({result.get('platform')})" if result.get("platform") else ""),
            flush=True,
        )


async def run_async(db_path: str, concurrency: int, statuses: tuple[str, ...] | None = None) -> dict:
    init_db(db_path)

    with connect(db_path) as conn:
        urls = tier2_urls(conn, statuses)
    urls = [u for u in urls if not u.startswith("__no_url__")]

    if not urls:
        print("  Nothing to upgrade. All URLs already resolved.")
        with connect(db_path) as conn:
            return stats(conn)

    print(f"  Queue: {len(urls)} URLs for Playwright upgrade")

    from playwright.async_api import async_playwright

    _install_sigint_handler()
    started = time.monotonic()
    done_counter = {"n": 0, "total": len(urls)}
    sem = asyncio.Semaphore(concurrency)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            tasks = [
                asyncio.create_task(worker(u, browser, sem, db_path, done_counter))
                for u in urls
            ]
            while tasks:
                done, pending = await asyncio.wait(
                    tasks, timeout=1.0, return_when=asyncio.FIRST_COMPLETED
                )
                tasks = [t for t in pending]
                if _stop.is_set():
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break
                if not done and not pending:
                    break
        finally:
            await browser.close()

    elapsed = time.monotonic() - started
    with connect(db_path) as conn:
        s = stats(conn)
    print(f"\n  {done_counter['n']} upgraded / elapsed {elapsed:.1f}s")
    return s


def main():
    ap = argparse.ArgumentParser(description="Tier 2 Playwright crawler")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY)
    ap.add_argument(
        "--scope",
        choices=["all", "recoverable", "blocked"],
        default="all",
        help="'all' = all non-bookable; 'recoverable' = error+timeout+blocked; 'blocked' = WAF-blocked only (best ROI at scale).",
    )
    args = ap.parse_args()

    statuses = None
    if args.scope == "recoverable":
        statuses = ("error", "timeout", "blocked")
    elif args.scope == "blocked":
        statuses = ("blocked",)
    print(f"Tier 2: rendering unresolved rows via {args.db} (scope={args.scope}, concurrency={args.concurrency})")
    asyncio.run(run_async(args.db, args.concurrency, statuses))


if __name__ == "__main__":
    main()
