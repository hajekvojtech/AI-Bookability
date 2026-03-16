"""
Generic fallback timeslot scraper for unknown booking platforms.

Strategy:
1. Navigate to the booking URL
2. Intercept ALL JSON API responses during page load
3. Try to find and click the service
4. Look for calendar/date elements and click dates
5. Extract time slots from:
   a. Intercepted API responses (look for date/time patterns)
   b. Visible DOM elements matching time patterns (h:MM AM/PM)
6. Build standardized output
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

from scrapers.base import BaseScraper


class GenericScraper(BaseScraper):
    platform_name = "Unknown"

    async def scrape(self, url: str, service_name: str, days: int = 30) -> dict:
        from playwright.async_api import async_playwright

        api_responses = []
        date_slots = {}
        # Limit generic scraper to 14 days to avoid excessive scraping
        effective_days = min(days, 14)

        async with async_playwright() as p:
            browser, context, page = await self.create_browser_context(p)

            # Intercept ALL JSON responses
            async def on_response(response):
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        body = await response.json()
                        api_responses.append({"url": response.url, "body": body})
                    except Exception:
                        pass

            page.on("response", on_response)

            # STEP 1: Load the page
            print(f"[Generic] Loading: {url}")
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # STEP 2: Try to click the service
            print(f"[Generic] Looking for service: {service_name}")
            await self._try_click_service(page, service_name)
            await asyncio.sleep(2)

            # STEP 3: Try common navigation patterns
            for btn_text in ["Next", "Continue", "Book Now", "Book", "Select",
                             "Choose Date", "See Availability", "View Times"]:
                try:
                    btn = page.locator(f"button:has-text('{btn_text}')").first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue

            # STEP 4: Extract time slots from the current page
            visible_slots = await self._extract_time_slots_from_dom(page)
            if visible_slots:
                today_str = date.today().isoformat()
                date_slots[today_str] = {"closed": False, "time_slots": visible_slots}

            # STEP 5: Click through dates if a calendar is visible
            print(f"[Generic] Scanning dates for up to {effective_days} days...")
            today = date.today()
            for day_offset in range(effective_days):
                target_date = today + timedelta(days=day_offset)
                clicked = await self._try_click_date(page, target_date)
                if clicked:
                    await asyncio.sleep(1.5)
                    slots = await self._extract_time_slots_from_dom(page)
                    if slots:
                        date_slots[target_date.isoformat()] = {
                            "closed": False,
                            "time_slots": slots,
                        }

            # STEP 6: Parse intercepted API responses
            api_slots = self._parse_all_api_responses(api_responses)
            for d, entry in api_slots.items():
                if d not in date_slots:
                    date_slots[d] = entry

            # Try to detect platform from page content
            rendered_html = await page.content()
            detected_platform = self._detect_platform_from_html(rendered_html)
            if detected_platform:
                self.platform_name = detected_platform

            merchant_name = await self._extract_merchant_name(page)

            await browser.close()

        return self.build_result(
            merchant_name=merchant_name,
            booking_url=url,
            service_name=service_name,
            service_info=None,
            days=days,
            date_slots=date_slots,
        )

    async def _try_click_service(self, page, service_name: str):
        """Try various strategies to click a service by name."""
        for selector in [
            f"button:has-text('{service_name}')",
            f"a:has-text('{service_name}')",
            f"div:has-text('{service_name}')",
            f"text='{service_name}'",
        ]:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    return
            except Exception:
                continue

        # Case-insensitive partial match
        all_clickable = await page.locator("a, button, [role='button']").all()
        for el in all_clickable:
            text = (await el.text_content() or "").strip()
            if service_name.lower() in text.lower():
                await el.click()
                return

    async def _extract_time_slots_from_dom(self, page) -> list[int]:
        """Scan the visible page for time patterns and return as seconds."""
        slots = []
        time_elements = await page.locator("text=/\\d{1,2}:\\d{2}\\s*[AP]M/i").all()
        for el in time_elements:
            text = (await el.text_content() or "").strip()
            match = re.search(r'(\d{1,2}:\d{2}\s*[AP]M)', text, re.IGNORECASE)
            if match:
                try:
                    seconds = self.time_str_to_seconds(match.group(1))
                    if seconds not in slots:
                        slots.append(seconds)
                except Exception:
                    pass
        slots.sort()
        return slots

    async def _try_click_date(self, page, target_date: date) -> bool:
        """Try common patterns for clicking a date in a calendar."""
        day_num = target_date.day

        # Try data attributes
        for attr in ["data-date", "data-day", "data-value"]:
            try:
                el = page.locator(f"[{attr}='{target_date.isoformat()}']").first
                if await el.is_visible(timeout=500):
                    await el.click()
                    return True
            except Exception:
                pass

        # Try calendar cells
        try:
            cells = await page.locator("td, [role='gridcell'], [class*='day']").all()
            for cell in cells:
                text = (await cell.text_content() or "").strip()
                if text == str(day_num):
                    await cell.click()
                    return True
        except Exception:
            pass

        return False

    def _parse_all_api_responses(self, api_responses: list) -> dict:
        """Parse all intercepted JSON responses looking for availability."""
        date_slots = {}
        for resp in api_responses:
            body = resp.get("body")
            if body:
                self.extract_dates_from_json(body, date_slots)
        return date_slots

    def _detect_platform_from_html(self, html: str) -> str | None:
        """Try to identify the platform from rendered HTML."""
        from config import PLATFORM_SIGNATURES
        html_lower = html.lower()
        for platform, sigs in PLATFORM_SIGNATURES.items():
            for pattern in sigs.get("html_patterns", []):
                if re.search(pattern, html_lower):
                    return platform
        return None

    async def _extract_merchant_name(self, page) -> str:
        """Try to extract merchant name from page title."""
        try:
            title = await page.title()
            if title and len(title) > 2:
                for suffix in [" - Book Online", " | Online Booking",
                               " - Appointments", " | Book Now",
                               " - Schedule", " | Schedule"]:
                    if suffix in title:
                        return title.split(suffix)[0].strip()
                return title.strip()
        except Exception:
            pass
        return "Unknown Merchant"
