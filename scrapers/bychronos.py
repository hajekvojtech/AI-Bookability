"""
byChronos platform scraper.

Flow: Services page -> select service -> Next -> select specialist -> Next -> Time page
API interception: /api/timeslots-availability returns arrays of seconds-from-midnight.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

from scrapers.base import BaseScraper


class ByChronosScraper(BaseScraper):
    platform_name = "byChronos"

    async def list_services(self, url: str) -> list[dict]:
        from playwright.async_api import async_playwright

        services = []
        async with async_playwright() as p:
            browser, context, page = await self.create_browser_context(p)
            try:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                except Exception:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                # Try API first — byChronos exposes /api/service-categories
                # but it may not be available at the root path
                try:
                    service_cats = await page.evaluate("""
                        async () => {
                            const resp = await fetch('/api/service-categories');
                            if (!resp.ok) return null;
                            const ct = resp.headers.get('content-type') || '';
                            if (!ct.includes('json')) return null;
                            return await resp.json();
                        }
                    """)
                    if service_cats and isinstance(service_cats, list):
                        for cat in service_cats:
                            cat_name = cat.get("name", "")
                            for svc in cat.get("services", []):
                                name = svc.get("name", "")
                                duration = svc.get("duration")
                                price = svc.get("price")
                                services.append({
                                    "name": name,
                                    "category": cat_name or None,
                                    "duration_display": f"{duration} min" if duration else None,
                                    "price_display": f"${price / 100:.0f}" if price else None,
                                })
                except Exception:
                    pass

                # Fallback: extract service buttons from the DOM
                if not services:
                    print("[byChronos] API not available, extracting from DOM...")
                    buttons = await page.locator("button").all()
                    seen = set()
                    for btn in buttons:
                        try:
                            if not await btn.is_visible(timeout=500):
                                continue
                            text = (await btn.text_content() or "").strip()
                            # Skip navigation/generic buttons
                            if not text or len(text) < 3 or len(text) > 100:
                                continue
                            if text.lower() in {"next", "back", "sign in", "log in", "close"}:
                                continue
                            if text in seen:
                                continue
                            seen.add(text)

                            # Extract price from button text
                            price_match = re.search(r'\$[\d,.]+', text)
                            price_display = price_match.group(0) if price_match else None

                            # Extract duration (e.g. "1 hour 30 min", "30 min", "1 hour")
                            dur_match = re.search(
                                r'(\d+\s*hours?\s*(?:\d+\s*min(?:utes?)?)?|\d+\s*min(?:utes?)?)',
                                text, re.IGNORECASE
                            )
                            duration_display = dur_match.group(0).strip() if dur_match else None

                            # Clean name: remove price, duration suffix, and extra whitespace
                            name = re.sub(r'\s*\$[\d,.]+.*', '', text).strip()
                            # Remove trailing duration like "30 min", "1 hour 30 min"
                            name = re.sub(
                                r'\s*\d+\s*hours?\s*(?:\d+\s*min(?:utes?)?)?\s*$', '',
                                name, flags=re.IGNORECASE
                            ).strip()
                            name = re.sub(
                                r'\s*\d+\s*min(?:utes?)?\s*$', '',
                                name, flags=re.IGNORECASE
                            ).strip()
                            name = re.sub(r'\s+', ' ', name).strip()

                            if name and len(name) >= 3:
                                services.append({
                                    "name": name,
                                    "category": None,
                                    "duration_display": duration_display,
                                    "price_display": price_display,
                                })
                        except Exception:
                            continue
            except Exception as e:
                print(f"[byChronos] Error fetching services: {e}")
            finally:
                await browser.close()

        return services

    async def scrape(self, url: str, service_name: str, days: int = 30) -> dict:
        from playwright.async_api import async_playwright

        availability_data = []

        async with async_playwright() as p:
            browser, context, page = await self.create_browser_context(p)

            # Intercept timeslots-availability API responses
            async def on_response(response):
                if "timeslots-availability" in response.url:
                    try:
                        body = await response.json()
                        if isinstance(body, list):
                            availability_data.extend(body)
                    except Exception:
                        pass

            page.on("response", on_response)

            # STEP 1: Load services page
            print(f"[byChronos] Loading booking page: {url}")
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # STEP 2: Select the requested service
            print(f"[byChronos] Selecting service: {service_name}")
            service_btn = page.locator(f"button:has-text('{service_name}')").first
            try:
                await service_btn.click(timeout=5000)
            except Exception:
                all_buttons = await page.locator("button").all()
                clicked = False
                for btn in all_buttons:
                    text = (await btn.text_content() or "").strip()
                    if service_name.lower() in text.lower():
                        await btn.click()
                        clicked = True
                        break
                if not clicked:
                    raise RuntimeError(f"Could not find service '{service_name}' on the page")
            await asyncio.sleep(1)

            # STEP 3: Click Next to go to Specialist page
            print("[byChronos] Navigating to Specialist page...")
            next_buttons = await page.locator("button:has-text('Next')").all()
            for btn in next_buttons:
                if await btn.is_visible():
                    await btn.click()
                    break
            await asyncio.sleep(2)

            # STEP 4: Select "Any specialist"
            print("[byChronos] Selecting Any specialist...")
            specialist_selected = False
            for text in ["Any specialist", "Any Specialist", "Any"]:
                try:
                    el = page.get_by_text(text, exact=True).first
                    if await el.is_visible(timeout=2000):
                        await el.click()
                        specialist_selected = True
                        break
                except Exception:
                    continue

            if not specialist_selected:
                specialist_buttons = await page.locator("button").all()
                for btn in specialist_buttons:
                    text = (await btn.text_content() or "").strip()
                    if text and text not in ["Next", "Back", "Sign in"]:
                        await btn.click()
                        specialist_selected = True
                        break
            await asyncio.sleep(1)

            # STEP 5: Click Next to go to Time page
            print("[byChronos] Navigating to Time page...")
            next_buttons = await page.locator("button:has-text('Next')").all()
            for btn in next_buttons:
                if await btn.is_visible():
                    await btn.click()
                    break
            await asyncio.sleep(4)

            # STEP 6: Click dates across the range to trigger API batch loads
            today = date.today()
            print(f"[byChronos] Loading availability for {days} days...")
            weeks_needed = (days // 7) + 1
            for week_offset in range(weeks_needed):
                target_date = today + timedelta(days=week_offset * 7)
                day_abbr = target_date.strftime("%a")[:3]
                day_num = target_date.day
                btn_text = f"{day_abbr}{day_num}"

                try:
                    date_btn = page.locator(f"button:has-text('{btn_text}')").first
                    if await date_btn.is_visible(timeout=2000):
                        await date_btn.click()
                        await asyncio.sleep(1.5)
                except Exception:
                    pass

            await asyncio.sleep(2)

            # STEP 7: Get service info from the API
            service_info = None
            try:
                service_cats = await page.evaluate("""
                    async () => {
                        const resp = await fetch('/api/service-categories');
                        return await resp.json();
                    }
                """)
                for cat in service_cats:
                    for svc in cat.get("services", []):
                        if svc["name"].lower() == service_name.lower():
                            service_info = svc
                            break
            except Exception:
                pass

            await browser.close()

        # Process collected availability data
        print(f"[byChronos] Collected availability for {len(availability_data)} date entries")

        # Deduplicate by date (later responses override earlier ones)
        date_slots = {}
        for entry in availability_data:
            date_slots[entry["date"]] = {
                "closed": entry.get("closed", False),
                "time_slots": entry.get("time_slots", []),
            }

        merchant_name = self._extract_merchant_name(url)

        return self.build_result(
            merchant_name=merchant_name,
            booking_url=url,
            service_name=service_name,
            service_info=service_info,
            days=days,
            date_slots=date_slots,
        )

    def _extract_merchant_name(self, url: str) -> str:
        """Extract merchant name from byChronos URL slug."""
        # URL pattern: go.bychronos.com/l/{city}-{zip}-{name}-{id}/a/services
        match = re.search(r'/l/([\w-]+)/a/', url)
        if match:
            slug = match.group(1)
            parts = slug.split("-")
            # Find where the zip ends (5-digit number)
            name_parts = []
            found_zip = False
            for part in parts:
                if not found_zip and part.isdigit() and len(part) == 5:
                    found_zip = True
                    continue
                if found_zip:
                    if part.isdigit() and len(part) > 4:
                        break  # trailing merchant ID
                    name_parts.append(part)
            if name_parts:
                return " ".join(name_parts).title()
        return "Unknown Merchant"
