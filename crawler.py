#!/usr/bin/env python3
"""
Tier 1: httpx crawler.

Reads TODO queue from SQLite (input_domains \\ results), fetches each URL,
runs the HTML through detector.detect_from_html(), and writes one row to
results per URL. Commits after every URL — a kill at any moment loses at
most one in-flight result.

Errors, timeouts, and blocks are written as rows with status ∈
{error, timeout, blocked} — never silently dropped.

Rate limits:
  - GLOBAL_CONCURRENCY concurrent requests (default 20)
  - Max 1 request every PER_HOST_MIN_INTERVAL seconds per host (default 2s)
  - Jittered sleep between launches

SIGINT (Ctrl-C):
  Waits for in-flight tasks to settle, prints progress, exits clean.

--retry-errors:
  Deletes existing Tier 1 rows whose status is error/timeout/blocked so
  they get re-queued. Does not touch bookable / no_signature rows.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import signal
import sys
import time
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

from config import (  # noqa: E402
    CAT_3P_EMBEDDED,
    CAT_3P_EXTERNAL,
    CAT_3P_IS_WEBSITE,
    CAT_CALL_EMAIL,
    CAT_INTERNAL,
    CAT_NO_BOOKING,
    CAT_SOCIAL_MEDIA,
    CAPTCHA_PATTERNS,
    USER_AGENTS,
    WAF_PATTERNS,
)
from pipeline.detector import detect_from_html, find_booking_links  # noqa: E402
from pipeline.sqlite_store import (  # noqa: E402
    connect,
    delete_error_rows,
    init_db,
    stats,
    todo_urls,
    upsert_result,
)

DEFAULT_DB = "data/results.db"
GLOBAL_CONCURRENCY = 20
PER_HOST_MIN_INTERVAL = 2.0
REQUEST_TIMEOUT = 10.0
MAX_REDIRECTS = 5
JITTER = (0.5, 1.5)

BOOKABLE_CATS = {CAT_3P_IS_WEBSITE, CAT_3P_EMBEDDED, CAT_3P_EXTERNAL, CAT_INTERNAL}


_stop = asyncio.Event()


def _install_sigint_handler() -> None:
    def handler(signum, frame):
        if not _stop.is_set():
            print("\n[SIGINT] flushing in-flight requests and exiting…", file=sys.stderr)
            _stop.set()
        else:
            # Second Ctrl-C forces immediate exit
            print("\n[SIGINT x2] hard exit", file=sys.stderr)
            sys.exit(130)

    signal.signal(signal.SIGINT, handler)


class HostRateLimiter:
    """One slot per host. Enforces PER_HOST_MIN_INTERVAL between hits."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def acquire(self, host: str):
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            wait = self.min_interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()


def _classify_blocked(html: str) -> bool:
    h = html.lower()
    return any(p.lower() in h for p in CAPTCHA_PATTERNS + WAF_PATTERNS)


def _pick_ua() -> str:
    return random.choice(USER_AGENTS)


async def _fetch_html(client: httpx.AsyncClient, url: str) -> tuple[int | None, str, str, str | None]:
    """Return (status_code, html, final_url, error). error non-None means failure."""
    headers = {"User-Agent": _pick_ua()}
    try:
        r = await client.get(url, headers=headers, follow_redirects=True)
        return r.status_code, r.text or "", str(r.url), None
    except httpx.TimeoutException as e:
        return None, "", url, f"timeout:{type(e).__name__}: {e}"
    except httpx.HTTPError as e:
        return None, "", url, f"error:{type(e).__name__}: {e}"
    except Exception as e:
        return None, "", url, f"error:{type(e).__name__}: {e}"


async def fetch_one(
    client: httpx.AsyncClient,
    url: str,
    host_limiter: HostRateLimiter,
) -> dict:
    host = (urlparse(url).hostname or "").lower()
    await host_limiter.acquire(host)
    await asyncio.sleep(random.uniform(*JITTER))

    status_code, html, final_url, err = await _fetch_html(client, url)
    if err:
        status = "timeout" if err.startswith("timeout:") else "error"
        return {"status": status, "error": err.split(":", 1)[1]}

    if _classify_blocked(html):
        return {"status": "blocked", "http_status": status_code, "final_url": final_url,
                "evidence": "captcha/WAF pattern detected"}
    if status_code in (401, 403, 429, 503):
        return {"status": "blocked", "http_status": status_code, "final_url": final_url,
                "error": f"HTTP {status_code}"}
    if status_code and status_code >= 400:
        return {"status": "error", "http_status": status_code, "final_url": final_url,
                "error": f"HTTP {status_code}"}

    det = detect_from_html(html, final_url)
    evidence = "; ".join(det.evidence) if det.evidence else ""

    if det.category in BOOKABLE_CATS:
        return {"status": "bookable", "platform": det.platform or "",
                "category": det.category, "evidence": evidence,
                "http_status": status_code, "final_url": final_url}

    # Home page didn't match. If a booking button is visible OR the detector flagged
    # needs_stage3, follow up to 2 booking-related sub-page links and try again.
    home_has_button = det.needs_stage3 or any("Booking button" in e for e in det.evidence)
    if home_has_button:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            subpage_urls = find_booking_links(soup, final_url)[:2]
        except Exception:
            subpage_urls = []

        for sub in subpage_urls:
            sub_status, sub_html, sub_final, sub_err = await _fetch_html(client, sub)
            if sub_err or not sub_html or (sub_status and sub_status >= 400):
                continue
            sub_det = detect_from_html(sub_html, sub_final)
            if sub_det.category in BOOKABLE_CATS:
                combined_evidence = f"(sub-page {sub}) " + ("; ".join(sub_det.evidence) if sub_det.evidence else "")
                return {"status": "bookable", "platform": sub_det.platform or "",
                        "category": sub_det.category, "evidence": combined_evidence,
                        "http_status": status_code, "final_url": final_url}

        # Exhausted sub-pages, but home had a clear booking button. Mark as
        # bookable with unknown platform — classifier couldn't identify the vendor
        # but the merchant clearly offers online booking.
        return {"status": "bookable", "platform": "(unknown)",
                "category": "likely_bookable",
                "evidence": evidence + " | sub-page scan exhausted, vendor unidentified",
                "http_status": status_code, "final_url": final_url}

    # Non-bookable: social / call_email / no_booking (no button visible either)
    category = det.category if det.category else CAT_NO_BOOKING
    return {"status": "no_signature", "platform": None, "category": category,
            "evidence": evidence or "no booking signature matched",
            "http_status": status_code, "final_url": final_url}


async def worker(
    url: str,
    client: httpx.AsyncClient,
    host_limiter: HostRateLimiter,
    sem: asyncio.Semaphore,
    db_path: str,
    done_counter: dict,
):
    if _stop.is_set():
        return
    async with sem:
        if _stop.is_set():
            return
        result = await fetch_one(client, url, host_limiter)
        # Commit this result immediately.
        with connect(db_path) as conn:
            upsert_result(
                conn,
                url=url,
                tier=1,
                status=result["status"],
                platform=result.get("platform"),
                category=result.get("category"),
                evidence=result.get("evidence"),
                http_status=result.get("http_status"),
                final_url=result.get("final_url"),
                error=result.get("error"),
            )
        done_counter["n"] += 1
        if done_counter["n"] % 10 == 0:
            total = done_counter["total"]
            print(
                f"  [{done_counter['n']}/{total}] {url[:70]} -> {result['status']}"
                + (f" ({result.get('platform')})" if result.get("platform") else ""),
                flush=True,
            )


async def run_async(db_path: str, retry_errors: bool, concurrency: int) -> dict:
    init_db(db_path)

    if retry_errors:
        with connect(db_path) as conn:
            n_deleted = delete_error_rows(conn)
            print(f"  --retry-errors: removed {n_deleted} prior error rows")

    with connect(db_path) as conn:
        urls = todo_urls(conn)
        s = stats(conn)

    if not urls:
        print(f"  Nothing to crawl. inputs={s['inputs']} done={s['done']}")
        return s

    # Skip synthetic __no_url__ rows — prepass already wrote results for them.
    urls = [u for u in urls if not u.startswith("__no_url__")]

    print(f"  Queue: {len(urls)} URLs (total inputs={s['inputs']}, already done={s['done']})")
    done_counter = {"n": 0, "total": len(urls)}

    _install_sigint_handler()

    sem = asyncio.Semaphore(concurrency)
    host_limiter = HostRateLimiter(PER_HOST_MIN_INTERVAL)

    timeout_cfg = httpx.Timeout(REQUEST_TIMEOUT, connect=REQUEST_TIMEOUT)
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    transport = httpx.AsyncHTTPTransport(retries=0)

    started = time.monotonic()
    async with httpx.AsyncClient(
        timeout=timeout_cfg,
        limits=limits,
        transport=transport,
        max_redirects=MAX_REDIRECTS,
        http2=True,
        verify=True,
    ) as client:
        tasks = [
            asyncio.create_task(worker(u, client, host_limiter, sem, db_path, done_counter))
            for u in urls
        ]
        # Wait but respect SIGINT — cancel pending on stop
        try:
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
        except asyncio.CancelledError:
            pass

    elapsed = time.monotonic() - started
    with connect(db_path) as conn:
        s = stats(conn)
    remaining = s["inputs"] - s["done"]
    print(
        f"\n  {done_counter['n']} done / {remaining} remaining / elapsed {elapsed:.1f}s"
    )
    return s


def main():
    ap = argparse.ArgumentParser(description="Tier 1 httpx crawler")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--retry-errors", action="store_true",
                    help="Delete tier-1 error/timeout/blocked rows and re-queue")
    ap.add_argument("--concurrency", type=int, default=GLOBAL_CONCURRENCY)
    args = ap.parse_args()

    print(f"Tier 1: crawling via {args.db}")
    asyncio.run(run_async(args.db, args.retry_errors, args.concurrency))


if __name__ == "__main__":
    main()
