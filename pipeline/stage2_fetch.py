"""
Stage 2: Async HTTP fetch + HTML analysis.
Fetches merchant websites and runs booking detection rules.
"""
from __future__ import annotations

import asyncio
import ssl
import re
from urllib.parse import urlparse

import httpx
from tqdm import tqdm

from config import (
    CAPTCHA_PATTERNS,
    CAT_3P_IS_WEBSITE,
    CAT_BLOCKED,
    CAT_CALL_EMAIL,
    CAT_NO_BOOKING,
    CAT_UNREACHABLE,
    CONNECT_TIMEOUT,
    MAX_REDIRECTS,
    MAX_RETRIES,
    MAX_SUBPAGES,
    REQUEST_TIMEOUT,
    STAGE2_BATCH_SIZE,
    STAGE2_CONCURRENCY,
    USER_AGENTS,
    WAF_PATTERNS,
    BOOKING_PLATFORM_DOMAINS,
)
from pipeline.detector import (
    DetectionResult,
    check_url_is_platform,
    detect_from_html,
    find_booking_links,
)
from pipeline.state import StateStore


async def run_stage2(state: StateStore):
    """
    Fetch and analyze all merchants that completed Stage 1 but not Stage 2.
    """
    # Collect merchants needing Stage 2
    to_process = []
    for url, result in state.get_all_results().items():
        if result.get("stage_completed") == 1:
            to_process.append((url, result))

    if not to_process:
        print("  No merchants need Stage 2 processing")
        return

    print(f"  Processing {len(to_process)} merchants...")

    sem = asyncio.Semaphore(STAGE2_CONCURRENCY)
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
    processed = 0

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        headers={"User-Agent": USER_AGENTS[0]},
        verify=True,
    ) as client:
        pbar = tqdm(total=len(to_process), desc="  Stage 2", unit="site")

        # Process in batches for checkpointing
        for batch_start in range(0, len(to_process), STAGE2_BATCH_SIZE):
            batch = to_process[batch_start : batch_start + STAGE2_BATCH_SIZE]
            tasks = [
                _fetch_and_classify(sem, client, url, result, state)
                for url, result in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            processed += len(batch)
            pbar.update(len(batch))
            state.save()

        pbar.close()

    print(f"  Stage 2 complete: {processed} merchants processed")


async def _fetch_and_classify(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    url: str,
    existing_result: dict,
    state: StateStore,
):
    """Fetch a single merchant's website and classify it."""
    async with sem:
        result = await _fetch_with_retry(client, url)

        if result.get("category") in (CAT_UNREACHABLE, CAT_BLOCKED):
            # If this was a platform-pretagged URL that can't be reached,
            # override the Stage 1 classification — it's not actually bookable.
            state.update_result(url, {
                "category": result["category"],
                "confidence": result["confidence"],
                "evidence": result["evidence"],
                "http_status": result.get("http_status", 0),
                "final_url": result.get("final_url", url),
                "stage_completed": 2,
                "needs_stage3": False,
                "error": result.get("error", ""),
                "platform_pretagged": False,
            })
            return

        # We got HTML — run detection
        html = result["html"]
        final_url = result["final_url"]
        http_status = result["http_status"]

        # If this was platform-pretagged in Stage 1 and it loaded OK,
        # the platform classification is validated — mark complete.
        if existing_result.get("platform_pretagged"):
            state.update_result(url, {
                "category": existing_result["category"],
                "platform": existing_result.get("platform", ""),
                "confidence": existing_result.get("confidence", 0.99),
                "evidence": existing_result.get("evidence", []) + [f"HTTP {http_status} — page loads OK"],
                "booking_url": existing_result.get("booking_url", url),
                "http_status": http_status,
                "final_url": final_url,
                "stage_completed": 3,
                "needs_stage3": False,
            })
            return

        # Check if redirect landed on a booking platform
        platform_check = check_url_is_platform(final_url)
        if platform_check:
            state.update_result(url, {
                "category": platform_check.category,
                "platform": platform_check.platform,
                "confidence": platform_check.confidence,
                "evidence": platform_check.evidence + [f"Redirected from {url} to {final_url}"],
                "booking_url": final_url,
                "http_status": http_status,
                "final_url": final_url,
                "stage_completed": 3,
                "needs_stage3": False,
            })
            return

        # Run detection on homepage HTML
        detection = detect_from_html(html, final_url)

        # If no booking found on homepage, try sub-pages
        if detection.category == CAT_NO_BOOKING and detection.confidence < 0.8:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                sub_urls = find_booking_links(soup, final_url)[:MAX_SUBPAGES]

                for sub_url in sub_urls:
                    sub_result = await _fetch_page(client, sub_url)
                    if sub_result and sub_result.get("html"):
                        sub_detection = detect_from_html(
                            sub_result["html"], sub_result.get("final_url", sub_url)
                        )
                        if sub_detection.category != CAT_NO_BOOKING:
                            sub_detection.evidence.append(
                                f"Found on sub-page: {sub_url}"
                            )
                            detection = sub_detection
                            break
            except Exception:
                pass

        # Determine if Stage 3 is needed
        needs_stage3 = detection.needs_stage3
        # Always send no_booking and call_email to Stage 3 for Playwright verification.
        # call_email sites almost always also have booking widgets;
        # no_booking sites may have JS-rendered widgets invisible to httpx.
        if detection.category in (CAT_NO_BOOKING, CAT_CALL_EMAIL):
            needs_stage3 = True

        state.update_result(url, {
            "category": detection.category,
            "platform": detection.platform,
            "confidence": detection.confidence,
            "evidence": detection.evidence,
            "booking_url": detection.booking_url,
            "booking_button_selector": detection.booking_button_selector,
            "http_status": http_status,
            "final_url": final_url,
            "stage_completed": 2,
            "needs_stage3": needs_stage3,
        })


async def _fetch_with_retry(client: httpx.AsyncClient, url: str) -> dict:
    """Fetch a URL with retry logic for different error types."""
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            ua = USER_AGENTS[attempt % len(USER_AGENTS)]
            response = await client.get(
                url,
                headers={"User-Agent": ua},
            )

            html = response.text
            final_url = str(response.url)
            status = response.status_code

            # Check for captcha/WAF
            if _is_captcha_or_waf(html, status):
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2)
                    continue
                return {
                    "category": CAT_BLOCKED,
                    "confidence": 0.85,
                    "evidence": ["Captcha or WAF detected"],
                    "http_status": status,
                    "final_url": final_url,
                }

            if status == 403 or status == 429:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2)
                    continue
                return {
                    "category": CAT_BLOCKED,
                    "confidence": 0.80,
                    "evidence": [f"HTTP {status} after {attempt + 1} attempts"],
                    "http_status": status,
                    "final_url": final_url,
                }

            if status >= 400:
                return {
                    "category": CAT_UNREACHABLE,
                    "confidence": 0.90,
                    "evidence": [f"HTTP {status}"],
                    "http_status": status,
                    "final_url": final_url,
                }

            return {
                "html": html,
                "final_url": final_url,
                "http_status": status,
            }

        except httpx.ConnectError as e:
            last_error = f"Connection error: {e}"
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1)
        except httpx.TimeoutException as e:
            last_error = f"Timeout: {e}"
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1)
        except ssl.SSLError:
            # Retry without SSL verification
            try:
                response = await client.get(
                    url,
                    headers={"User-Agent": USER_AGENTS[0]},
                    extensions={"sni_hostname": None},
                )
                return {
                    "html": response.text,
                    "final_url": str(response.url),
                    "http_status": response.status_code,
                }
            except Exception as e2:
                last_error = f"SSL error (retry failed): {e2}"
        except httpx.TooManyRedirects:
            last_error = "Too many redirects"
            break
        except Exception as e:
            last_error = f"Unexpected error: {type(e).__name__}: {e}"
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1)

    # Check if it's a DNS issue
    if "Name or service not known" in last_error or "getaddrinfo" in last_error or "nodename nor servname" in last_error:
        return {
            "category": CAT_UNREACHABLE,
            "confidence": 0.95,
            "evidence": [f"DNS resolution failed: {last_error}"],
            "http_status": 0,
            "final_url": url,
            "error": last_error,
        }

    return {
        "category": CAT_UNREACHABLE,
        "confidence": 0.80,
        "evidence": [last_error],
        "http_status": 0,
        "final_url": url,
        "error": last_error,
    }


async def _fetch_page(client: httpx.AsyncClient, url: str) -> dict | None:
    """Fetch a single page, return None on any error."""
    try:
        response = await client.get(url, headers={"User-Agent": USER_AGENTS[0]})
        if response.status_code < 400:
            return {
                "html": response.text,
                "final_url": str(response.url),
                "http_status": response.status_code,
            }
    except Exception:
        pass
    return None


def _is_captcha_or_waf(html: str, status: int) -> bool:
    """Detect captcha or WAF challenge pages."""
    html_lower = html.lower()

    for pattern in CAPTCHA_PATTERNS:
        if pattern in html_lower:
            return True

    # Only check WAF patterns on short pages (real content is usually longer)
    if len(html) < 10000:
        waf_count = sum(1 for p in WAF_PATTERNS if p in html_lower)
        if waf_count >= 2:
            return True

    return False


def _is_js_heavy(html: str) -> bool:
    """
    Detect if a page is likely a JavaScript SPA that needs browser rendering.
    """
    html_lower = html.lower()

    # Very short body suggests content is rendered by JS
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "lxml")
        body = soup.find("body")
        if body:
            body_text = body.get_text(strip=True)
            if len(body_text) < 200:
                # Check for SPA frameworks
                if any(kw in html_lower for kw in [
                    "react", "__next", "nuxt", "vue", "angular",
                    "gatsby", "webpack", "bundle.js", "app.js",
                    "root\"></div>", "app\"></div>",
                ]):
                    return True
    except Exception:
        pass

    return False


async def fetch_single_url(url: str) -> dict:
    """
    Fetch and classify a single URL. Used for --url mode.
    """
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        headers={"User-Agent": USER_AGENTS[0]},
        verify=True,
    ) as client:
        result = await _fetch_with_retry(client, url)
        if "html" not in result:
            return result

        detection = detect_from_html(result["html"], result["final_url"])
        return {
            "category": detection.category,
            "platform": detection.platform,
            "confidence": detection.confidence,
            "evidence": detection.evidence,
            "booking_url": detection.booking_url,
            "http_status": result["http_status"],
            "final_url": result["final_url"],
            "needs_stage3": detection.needs_stage3,
            "booking_button_selector": detection.booking_button_selector,
        }
