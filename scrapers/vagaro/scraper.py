"""
Vagaro platform scraper.

Vagaro booking pages (vagaro.com/{slug}) render availability via
client-side API calls. This scraper navigates the booking widget and
intercepts the `getavailablemultiappointments` API to get time slots.

Flow:
  1. Navigate to /book-now
  2. Dismiss cookie dialogs (Osano + OneTrust)
  3. Select service via select2 dropdown
  4. Click Continue past add-ons
  5. Click Search to trigger initial availability load
  6. Iterate through date blocks, calling SetSelectedDate()
  7. Intercept getavailablemultiappointments responses
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

from scrapers.base import BaseScraper
from scrapers.vagaro.selectors import (
    BOOKING_PATH_SUFFIX,
    SERVICE_DROPDOWN_CONTAINER, SERVICE_SEARCH_RESULTS,
    CONTINUE_BUTTON_ID, SEARCH_BUTTON_ID,
    DATE_BLOCK_QUERY, DATE_BLOCK_ATTR, JS_SET_SELECTED_DATE,
    COOKIE_DISMISS_SELECTORS, COOKIE_OVERLAY_HIDE_JS,
    AVAILABILITY_API_PATTERN, SERVICE_LIST_API_PATTERN,
)
from scrapers.vagaro.api_schema import (
    parse_service_list, parse_availability_response,
    extract_service_info, parse_avail_date,
)
from scrapers.error_report import (
    ScrapeErrorReport, capture_dom_snapshot, capture_screenshot,
)


class VagaroScraper(BaseScraper):
    platform_name = "Vagaro"

    async def list_services(self, url: str) -> list[dict]:
        """
        Fetch business-specific services from Vagaro's booking tab API.

        Navigates to the /book-now page which triggers
        getonlinebookingtabdetail -- the business-specific service list
        with prices and durations.
        """
        from playwright.async_api import async_playwright

        services = []
        booking_detail = []

        booking_url = url.rstrip("/")
        if not booking_url.endswith(BOOKING_PATH_SUFFIX):
            booking_url += BOOKING_PATH_SUFFIX

        async with async_playwright() as p:
            browser, context, page = await self.create_browser_context(p)

            async def on_response(response):
                if SERVICE_LIST_API_PATTERN in response.url.lower():
                    try:
                        body = await response.json()
                        booking_detail.append(body)
                    except Exception:
                        pass

            page.on("response", on_response)

            try:
                try:
                    await page.goto(booking_url, wait_until="networkidle", timeout=30000)
                except Exception:
                    await page.goto(booking_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(4)

                await self._dismiss_cookie_dialog(page)
                await asyncio.sleep(1)

                if booking_detail:
                    services = parse_service_list(booking_detail[0])

                if not services:
                    print("[Vagaro] Could not fetch business-specific services")

            except Exception as e:
                print(f"[Vagaro] Error fetching services: {e}")
            finally:
                await browser.close()

        return services

    async def scrape(self, url: str, service_name: str, days: int = 30) -> dict:
        """
        Scrape timeslot availability by intercepting Vagaro's
        getavailablemultiappointments API.
        """
        from playwright.async_api import async_playwright

        date_slots = {}
        service_info = None
        availability_responses = []

        booking_url = url.rstrip("/")
        if not booking_url.endswith(BOOKING_PATH_SUFFIX):
            booking_url += BOOKING_PATH_SUFFIX

        async with async_playwright() as p:
            browser, context, page = await self.create_browser_context(p)

            async def on_response(response):
                if AVAILABILITY_API_PATTERN in response.url.lower():
                    try:
                        body = await response.json()
                        availability_responses.append(body)
                    except Exception:
                        pass

            page.on("response", on_response)

            try:
                # STEP 1: Navigate to /book-now
                print(f"[Vagaro] Loading booking page: {booking_url}")
                try:
                    await page.goto(booking_url, wait_until="networkidle", timeout=30000)
                except Exception:
                    await page.goto(booking_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                # STEP 2: Dismiss cookie dialogs
                await self._dismiss_cookie_dialog(page)

                # STEP 3: Select service from the booking search bar
                print(f"[Vagaro] Selecting service: {service_name}")
                await self._select_service(page, service_name)

                # STEP 4: Click Continue past add-ons panel
                await self._click_continue(page)

                # STEP 5: Click Search to trigger initial availability load
                print("[Vagaro] Triggering availability search...")
                availability_responses.clear()
                await page.evaluate(
                    f'document.getElementById("{SEARCH_BUTTON_ID}").click()'
                )
                await asyncio.sleep(5)

                # Parse initial response for service info
                if availability_responses:
                    service_info = extract_service_info(
                        availability_responses[0], service_name
                    )

                # STEP 6: Iterate through date blocks to load all availability
                print(f"[Vagaro] Loading availability for {days} days...")
                await self._collect_availability(
                    page, days, date_slots, availability_responses
                )

                merchant_name = self._extract_merchant_name(url)

            except Exception as e:
                print(f"[Vagaro] Error during scrape: {e}")
                merchant_name = self._extract_merchant_name(url)
                await self._generate_error_report(
                    page, url, "scrape", e, availability_responses
                )
            finally:
                await browser.close()

        return self.build_result(
            merchant_name=merchant_name,
            booking_url=url,
            service_name=service_name,
            service_info=service_info,
            days=days,
            date_slots=date_slots,
        )

    # --- Navigation helpers ---

    async def _dismiss_cookie_dialog(self, page):
        """Dismiss Vagaro's cookie consent dialogs."""
        for selector in COOKIE_DISMISS_SELECTORS:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await asyncio.sleep(0.3)
                    break
            except Exception:
                continue

        await page.evaluate(COOKIE_OVERLAY_HIDE_JS)

    async def _select_service(self, page, service_name: str):
        """Select a service from the booking search bar's select2 dropdown."""
        service_container = page.locator(SERVICE_DROPDOWN_CONTAINER).first
        try:
            await service_container.click(timeout=5000)
        except Exception as e:
            await self._generate_error_report(
                page, page.url, "select_service", e, [],
                selector=SERVICE_DROPDOWN_CONTAINER,
            )
            raise RuntimeError("Could not find service dropdown on booking page")

        await asyncio.sleep(0.5)

        search_term = service_name.split()[0] if service_name else service_name
        await page.keyboard.type(search_term, delay=50)
        await asyncio.sleep(1)

        results = await page.locator(SERVICE_SEARCH_RESULTS).all()
        for r in results:
            try:
                if not await r.is_visible(timeout=300):
                    continue
                text = (await r.text_content() or "").strip()
                if service_name.lower() in text.lower():
                    await r.click()
                    await asyncio.sleep(2)
                    return
            except Exception:
                continue

        # If exact match not found, click first visible result
        for r in results:
            try:
                if await r.is_visible(timeout=300):
                    await r.click()
                    await asyncio.sleep(2)
                    print(f"[Vagaro] No exact match for '{service_name}', used first result")
                    return
            except Exception:
                continue

        raise RuntimeError(f"Could not select service '{service_name}' from dropdown")

    async def _click_continue(self, page):
        """Click Continue button to skip the add-ons panel."""
        try:
            btn = page.locator(f"#{CONTINUE_BUTTON_ID}").first
            if await btn.is_visible(timeout=3000):
                await btn.click(timeout=5000)
                await asyncio.sleep(3)
                return
        except Exception:
            pass

        # Fallback: JS click
        try:
            await page.evaluate(
                f'var btn = document.getElementById("{CONTINUE_BUTTON_ID}"); if (btn) btn.click();'
            )
            await asyncio.sleep(3)
        except Exception:
            pass

    async def _collect_availability(
        self, page, days: int, date_slots: dict, availability_responses: list
    ):
        """
        Iterate through date blocks in the date slider,
        clicking each enabled date to trigger availability API calls.
        """
        today = date.today()
        end_date = today + timedelta(days=days)

        # Parse any already-collected responses
        for resp in availability_responses:
            parsed = parse_availability_response(resp, self.time_str_to_seconds)
            date_slots.update(parsed)

        # Get all date block info
        date_blocks = await page.evaluate(
            f"""() => {{
            var blocks = document.querySelectorAll("{DATE_BLOCK_QUERY}");
            var results = [];
            for (var i = 0; i < blocks.length; i++) {{
                var el = blocks[i];
                results.push({{
                    index: i,
                    availdate: el.getAttribute("{DATE_BLOCK_ATTR}") || "",
                    enabled: el.classList.contains("enabled"),
                    inactive: el.classList.contains("inactive"),
                    selected: el.classList.contains("selected")
                }});
            }}
            return results;
        }}"""
        )

        if not date_blocks:
            print("[Vagaro] No date blocks found in slider")
            return

        print(
            f"[Vagaro] Found {len(date_blocks)} date blocks, "
            f"{sum(1 for d in date_blocks if d['enabled'])} enabled"
        )

        for block in date_blocks:
            if block["selected"]:
                continue

            if not block["enabled"]:
                parsed_date = parse_avail_date(block["availdate"])
                if parsed_date and today <= parsed_date < end_date:
                    date_str = parsed_date.isoformat()
                    if date_str not in date_slots:
                        date_slots[date_str] = {"closed": True, "time_slots": []}
                continue

            parsed_date = parse_avail_date(block["availdate"])
            if not parsed_date or parsed_date >= end_date:
                continue

            # Click this date
            availability_responses.clear()
            idx = block["index"]
            expected_date_str = parsed_date.isoformat()
            try:
                await page.evaluate(
                    f"""() => {{
                    var blocks = document.querySelectorAll("{DATE_BLOCK_QUERY}");
                    if (blocks[{idx}]) {{
                        {JS_SET_SELECTED_DATE}(blocks[{idx}]);
                        return true;
                    }}
                    return false;
                }}"""
                )
            except Exception:
                continue

            await asyncio.sleep(2)

            for resp in availability_responses:
                parsed = parse_availability_response(
                    resp, self.time_str_to_seconds,
                    fallback_date=expected_date_str,
                )
                date_slots.update(parsed)

    def _extract_merchant_name(self, url: str) -> str:
        """Extract merchant name from Vagaro URL."""
        match = re.search(r'vagaro\.com/([^/?#]+)', url)
        if match:
            slug = match.group(1)
            return slug.replace("-", " ").replace("_", " ").title()
        return "Unknown Merchant"

    async def _generate_error_report(
        self, page, url: str, step: str, error: Exception,
        intercepted_responses: list, selector: str = "",
    ):
        """Capture page state and generate an AI-diagnosable error report."""
        try:
            dom = await capture_dom_snapshot(page)
            screenshot = await capture_screenshot(page, "vagaro", step)
            api_urls = []
            for r in intercepted_responses:
                if isinstance(r, dict):
                    api_urls.append(f"[response body with {len(r)} keys]")

            report = ScrapeErrorReport(
                connector="vagaro",
                merchant_url=url,
                step_failed=step,
                error_type=type(error).__name__,
                error_message=str(error),
                selector_attempted=selector,
                page_url_at_failure=page.url,
                screenshot_path=screenshot,
                intercepted_apis=api_urls,
                dom_snapshot=dom,
            )
            path = report.save()
            print(f"[Vagaro] AI diagnosis prompt:\n{report.to_ai_prompt()}")
        except Exception as report_error:
            print(f"[Vagaro] Could not generate error report: {report_error}")
