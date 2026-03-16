"""
Stage 3: Playwright booking flow simulation.
Uses a headless browser to click booking buttons and verify the flow works.
"""
from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import urlparse

from tqdm import tqdm

from config import (
    BOOKING_BUTTON_TEXTS,
    BOOKING_PLATFORM_DOMAINS,
    CAT_3P_EMBEDDED,
    CAT_3P_EXTERNAL,
    CAT_3P_IS_WEBSITE,
    CAT_BLOCKED,
    CAT_CALL_EMAIL,
    CAT_INTERNAL,
    CAT_NO_BOOKING,
    CAT_UNREACHABLE,
    CLICK_WAIT_TIMEOUT,
    PAGE_LOAD_TIMEOUT,
    PLATFORM_SIGNATURES,
    STAGE3_CONCURRENCY,
    USER_AGENTS,
)
from pipeline.detector import detect_from_html, check_url_is_platform
from pipeline.state import StateStore


# Booking platform API endpoint patterns (caught via network interception)
PLATFORM_API_PATTERNS = {
    "Mindbody": ["mindbodyonline.com", "healcode.com"],
    "Vagaro": ["vagaro.com/api", "vagaro.com/resources"],
    "Acuity Scheduling": ["acuityscheduling.com", "squarespacescheduling.com"],
    "Calendly": ["calendly.com/api"],
    "Square Appointments": ["squareup.com/appointments", "square.site"],
    "Booksy": ["booksy.com/api"],
    "Zenoti": ["zenoti.com/api", "zenoti.com/webstore"],
    "Jane App": ["janeapp.com"],
    "Boulevard": ["joinblvd.com/api"],
    "WellnessLiving": ["wellnessliving.com"],
    "Fresha": ["fresha.com/api"],
    "Wix Bookings": ["bookings.wixapps.net", "wix-bookings"],
    "Booker": ["booker.com", "location.booker.com"],
}


async def run_stage3(state: StateStore, screenshots_dir: str):
    """
    Run Playwright booking flow simulation for merchants needing deep crawl.
    """
    # Collect merchants needing Stage 3
    to_process = []
    for url, result in state.get_all_results().items():
        if result.get("needs_stage3") and result.get("stage_completed", 0) < 3:
            to_process.append((url, result))

    if not to_process:
        print("  No merchants need Stage 3 processing")
        return

    print(f"  Processing {len(to_process)} merchants with Playwright...")
    os.makedirs(screenshots_dir, exist_ok=True)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  ERROR: Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return

    sem = asyncio.Semaphore(STAGE3_CONCURRENCY)
    pbar = tqdm(total=len(to_process), desc="  Stage 3", unit="site")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )

        tasks = [
            _simulate_booking(sem, context, url, result, state, screenshots_dir, pbar)
            for url, result in to_process
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        await context.close()
        await browser.close()

    pbar.close()
    state.save()
    print(f"  Stage 3 complete: {len(to_process)} merchants processed")


async def _simulate_booking(
    sem: asyncio.Semaphore,
    context,
    url: str,
    existing_result: dict,
    state: StateStore,
    screenshots_dir: str,
    pbar,
):
    """Simulate the booking flow for a single merchant."""
    async with sem:
        try:
            page = await context.new_page()
            platform_apis_seen = []

            # Set up network request interception
            async def on_request(request):
                req_url = request.url.lower()
                for platform, patterns in PLATFORM_API_PATTERNS.items():
                    for pattern in patterns:
                        if pattern in req_url:
                            platform_apis_seen.append((platform, req_url))
                            return

            page.on("request", on_request)

            # Navigate to the page
            target_url = existing_result.get("final_url", url)
            try:
                await page.goto(target_url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
            except Exception as e:
                if "net::ERR" in str(e) or "Timeout" in str(e):
                    state.update_result(url, {
                        "stage_completed": 3,
                        "needs_stage3": False,
                        "stage3_error": str(e)[:200],
                    })
                    return
                # Try with domcontentloaded instead
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                except Exception:
                    state.update_result(url, {
                        "stage_completed": 3,
                        "needs_stage3": False,
                        "stage3_error": str(e)[:200],
                    })
                    return

            # Wait a bit for dynamic content
            await asyncio.sleep(2)

            # Get rendered HTML
            rendered_html = await page.content()

            # Re-run detection on rendered HTML (catches JS-rendered widgets)
            detection = detect_from_html(rendered_html, str(page.url))

            # Check platform APIs seen during page load
            # Upgrade both no_booking AND call_email — call_email is weak evidence
            # and platform API traffic is strong evidence of embedded booking
            if platform_apis_seen and detection.category in (CAT_NO_BOOKING, CAT_CALL_EMAIL):
                platform, api_url = platform_apis_seen[0]
                detection.category = CAT_3P_EMBEDDED
                detection.platform = platform
                detection.confidence = 0.90
                detection.evidence.append(f"Network request to {platform} API: {api_url[:100]}")

            # Try to find and click booking button
            booking_clicked = False
            click_result = None

            # Use selector from Stage 2 if available
            selector = existing_result.get("booking_button_selector", "")
            if selector:
                click_result = await _try_click_booking(page, selector, screenshots_dir, url)
                if click_result:
                    booking_clicked = True

            # If no selector or click failed, try finding buttons by text
            if not booking_clicked:
                for btn_text in BOOKING_BUTTON_TEXTS:
                    click_result = await _try_click_by_text(page, btn_text, screenshots_dir, url)
                    if click_result:
                        booking_clicked = True
                        break

            # Take screenshot of current state
            slug = _url_to_slug(url)
            screenshot_path = os.path.join(screenshots_dir, f"{slug}.png")
            try:
                await page.screenshot(path=screenshot_path, full_page=False)
            except Exception:
                screenshot_path = ""

            # Analyze click result
            updates = {
                "stage_completed": 3,
                "needs_stage3": False,
                "screenshot": screenshot_path,
            }

            if click_result:
                updates.update(_analyze_click_result(click_result, detection, url, platform_apis_seen))
            elif detection.category not in (CAT_NO_BOOKING, CAT_CALL_EMAIL):
                # Detection found something definitive even without clicking
                updates["category"] = detection.category
                updates["platform"] = detection.platform
                updates["confidence"] = detection.confidence
                updates["evidence"] = detection.evidence
                updates["booking_url"] = detection.booking_url
            else:
                # No definitive detection (no_booking or call_email are weak)
                # Check if platform APIs were seen — strong signal
                if platform_apis_seen:
                    platform, api_url = platform_apis_seen[0]
                    updates["category"] = CAT_3P_EMBEDDED
                    updates["platform"] = platform
                    updates["confidence"] = 0.85
                    updates["evidence"] = [f"Platform API detected: {api_url[:100]}"]
                elif detection.category == CAT_CALL_EMAIL:
                    # Keep call_email but with low confidence
                    updates["category"] = CAT_CALL_EMAIL
                    updates["confidence"] = 0.40
                    updates["evidence"] = detection.evidence + [
                        "Stage 3: No booking widget found after browser rendering"
                    ]
                else:
                    updates["category"] = CAT_NO_BOOKING
                    updates["confidence"] = 0.70
                    updates["evidence"] = detection.evidence + [
                        "Stage 3: No booking flow found after browser rendering"
                    ]

            state.update_result(url, updates)

        except Exception as e:
            state.update_result(url, {
                "stage_completed": 3,
                "needs_stage3": False,
                "stage3_error": f"{type(e).__name__}: {str(e)[:200]}",
            })
        finally:
            try:
                await page.close()
            except Exception:
                pass
            pbar.update(1)


async def _try_click_booking(page, selector: str, screenshots_dir: str, url: str) -> dict | None:
    """Try clicking a booking button by CSS selector."""
    try:
        # Handle text= selectors for Playwright
        if selector.startswith("text="):
            element = page.get_by_text(selector[5:], exact=False).first
        else:
            element = page.locator(selector).first

        if not await element.is_visible():
            return None

        # Record state before click
        url_before = page.url

        await element.click(timeout=5000)
        await asyncio.sleep(2)

        # Wait for navigation or new content
        try:
            await page.wait_for_load_state("networkidle", timeout=CLICK_WAIT_TIMEOUT)
        except Exception:
            pass

        url_after = page.url
        html_after = await page.content()

        return {
            "url_before": url_before,
            "url_after": url_after,
            "navigated": url_before != url_after,
            "html_after": html_after,
            "selector": selector,
        }
    except Exception:
        return None


async def _try_click_by_text(page, button_text: str, screenshots_dir: str, url: str) -> dict | None:
    """Try clicking a booking button by text content."""
    try:
        # Try both button and link elements
        element = page.get_by_role("link", name=re.compile(button_text, re.IGNORECASE)).first
        try:
            if not await element.is_visible(timeout=1000):
                raise Exception("not visible")
        except Exception:
            element = page.get_by_role("button", name=re.compile(button_text, re.IGNORECASE)).first
            try:
                if not await element.is_visible(timeout=1000):
                    return None
            except Exception:
                return None

        url_before = page.url
        await element.click(timeout=5000)
        await asyncio.sleep(2)

        try:
            await page.wait_for_load_state("networkidle", timeout=CLICK_WAIT_TIMEOUT)
        except Exception:
            pass

        url_after = page.url
        html_after = await page.content()

        return {
            "url_before": url_before,
            "url_after": url_after,
            "navigated": url_before != url_after,
            "html_after": html_after,
            "selector": f"text={button_text}",
        }
    except Exception:
        return None


def _analyze_click_result(
    click_result: dict,
    pre_detection: "DetectionResult",
    original_url: str,
    platform_apis: list,
) -> dict:
    """Analyze what happened after clicking a booking button."""
    updates = {}
    url_after = click_result["url_after"]
    html_after = click_result["html_after"]
    navigated = click_result["navigated"]

    # Check if we navigated to a booking platform
    if navigated:
        platform_check = check_url_is_platform(url_after)
        if platform_check:
            return {
                "category": CAT_3P_EXTERNAL,
                "platform": platform_check.platform,
                "confidence": 0.95,
                "evidence": [
                    f"Clicking '{click_result['selector']}' navigated to {url_after}",
                    f"Platform: {platform_check.platform}",
                ],
                "booking_url": url_after,
                "booking_flow_verified": True,
            }

        # Check if new URL is on known platform domain
        try:
            parsed = urlparse(url_after)
            host = (parsed.hostname or "").lower().lstrip("www.")
            for domain, platform in BOOKING_PLATFORM_DOMAINS.items():
                if host == domain or host.endswith("." + domain):
                    return {
                        "category": CAT_3P_EXTERNAL,
                        "platform": platform,
                        "confidence": 0.95,
                        "evidence": [f"Navigated to booking platform: {url_after}"],
                        "booking_url": url_after,
                        "booking_flow_verified": True,
                    }
        except Exception:
            pass

    # Re-run detection on the post-click HTML
    post_detection = detect_from_html(html_after, url_after)

    if post_detection.category in (CAT_3P_EMBEDDED, CAT_3P_EXTERNAL, CAT_INTERNAL):
        return {
            "category": post_detection.category,
            "platform": post_detection.platform,
            "confidence": max(post_detection.confidence, 0.85),
            "evidence": post_detection.evidence + [
                f"Detected after clicking '{click_result['selector']}'"
            ],
            "booking_url": post_detection.booking_url or url_after,
            "booking_flow_verified": True,
        }

    # Check for booking form indicators in post-click HTML
    html_lower = html_after.lower()
    has_service_selection = bool(re.search(
        r"(select.*service|choose.*service|service.*type|treatment.*type|select.*treatment"
        r"|pick.*service|our.*services|service.*menu|menu.*service)",
        html_lower,
    ))
    has_date_time = bool(re.search(
        r"(date.*picker|calendar|select.*date|choose.*time|time.*slot|available.*time"
        r"|pick.*date|pick.*time|availability|datepicker|flatpickr|pikaday)",
        html_lower,
    ))
    has_booking_form = bool(re.search(
        r"(booking.*form|appointment.*form|reservation.*form|schedule.*form"
        r"|book.*appointment|book.*online|schedule.*online|request.*appointment"
        r"|make.*appointment|make.*reservation|book.*now|booking-widget"
        r"|appointment-widget|scheduling-widget|booking_widget|appointment_widget)",
        html_lower,
    ))
    # Check for new iframes that appeared (booking widgets are often embedded iframes)
    has_booking_iframe = bool(re.search(
        r'<iframe[^>]+src=["\'][^"\']*('
        r'book|schedule|appointment|reserve|calendar|widget'
        r')[^"\']*["\']',
        html_lower,
    ))

    if has_service_selection or has_date_time or has_booking_form or has_booking_iframe:
        # Check if any platform API was called
        if platform_apis:
            platform, api_url = platform_apis[0]
            return {
                "category": CAT_3P_EMBEDDED,
                "platform": platform,
                "confidence": 0.90,
                "evidence": [
                    f"Booking form appeared after click (services={has_service_selection}, "
                    f"datetime={has_date_time}, iframe={has_booking_iframe})",
                    f"Platform API: {api_url[:100]}",
                ],
                "booking_url": url_after,
                "booking_flow_verified": True,
            }
        else:
            return {
                "category": CAT_INTERNAL,
                "confidence": 0.80,
                "evidence": [
                    f"Internal booking form after click (services={has_service_selection}, "
                    f"datetime={has_date_time}, form={has_booking_form}, iframe={has_booking_iframe})",
                ],
                "booking_url": url_after,
                "booking_flow_verified": True,
            }

    # NOTE: We intentionally do NOT check for call/email patterns here.
    # Nearly every salon page has "call us" text or a phone number.
    # If we clicked a "Book Now" button, finding a phone number does NOT
    # mean the site is call-only — it likely has booking alongside the phone.

    # Use pre-detection result if it had something definitive
    # (but NOT call_email — it's too weak and ubiquitous on salon sites)
    if pre_detection.category not in (CAT_NO_BOOKING, CAT_CALL_EMAIL):
        return {
            "category": pre_detection.category,
            "platform": pre_detection.platform,
            "confidence": pre_detection.confidence,
            "evidence": pre_detection.evidence + [
                f"Button '{click_result['selector']}' clicked but no clear booking flow"
            ],
            "booking_url": pre_detection.booking_url,
            "booking_flow_verified": False,
        }

    # call_email pre-detection is not reliable — downgrade to no_booking
    # since we clicked a button and didn't find a real booking flow
    return {
        "category": CAT_NO_BOOKING,
        "confidence": 0.50,
        "evidence": [
            f"Clicked '{click_result['selector']}', navigated={navigated}, "
            f"no booking flow detected"
        ],
        "booking_flow_verified": False,
    }


def _url_to_slug(url: str) -> str:
    """Convert URL to a filesystem-safe slug."""
    try:
        parsed = urlparse(url)
        slug = parsed.hostname or url
        slug = slug.replace("www.", "")
        slug = re.sub(r"[^\w\-.]", "_", slug)
        return slug[:100]  # limit length
    except Exception:
        return re.sub(r"[^\w\-.]", "_", url)[:100]
