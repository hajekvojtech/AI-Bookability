"""
Base class and shared utilities for platform-specific timeslot scrapers.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta

from config import USER_AGENTS

# Day-part boundaries in seconds from midnight
MORNING_END = 43200      # 12:00 PM
EVENING_START = 64800    # 6:00 PM

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class BaseScraper(ABC):
    """
    Abstract base class for platform-specific timeslot scrapers.

    Every platform scraper must implement:
      - scrape(url, service_name, days) -> dict

    The returned dict must conform to the standardized JSON schema
    that the UI heat map consumes.
    """

    platform_name: str = "Unknown"

    async def list_services(self, url: str) -> list[dict]:
        """
        Fetch available services from the booking URL.

        Returns list of dicts with keys: name, category, duration_display, price_display.
        Default implementation: navigate to page and scan DOM for service-like elements.
        Platform-specific scrapers should override this with more reliable extraction.
        """
        from playwright.async_api import async_playwright

        services = []
        async with async_playwright() as p:
            browser, context, page = await self.create_browser_context(p)
            try:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                except Exception:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                # Scan for elements that look like service items
                candidates = await page.locator(
                    "button, a, [role='button'], .service, .service-item, "
                    "[class*='service'], [class*='Service']"
                ).all()

                seen_names = set()
                for el in candidates:
                    try:
                        if not await el.is_visible(timeout=500):
                            continue
                        text = (await el.text_content() or "").strip()
                        # Filter: must be 3-80 chars, not nav/generic text
                        if not text or len(text) < 3 or len(text) > 80:
                            continue
                        skip_words = {"next", "back", "sign in", "log in", "menu",
                                      "home", "about", "contact", "close", "cancel"}
                        if text.lower() in skip_words:
                            continue
                        if text in seen_names:
                            continue
                        seen_names.add(text)

                        # Try to find price nearby
                        import re
                        price_match = re.search(r'\$\d+', text)
                        price_display = price_match.group(0) if price_match else None

                        # Clean service name (remove price from name)
                        name = re.sub(r'\s*\$\d+.*', '', text).strip()
                        if name and len(name) >= 3:
                            services.append({
                                "name": name,
                                "category": None,
                                "duration_display": None,
                                "price_display": price_display,
                            })
                    except Exception:
                        continue
            finally:
                await browser.close()

        return services

    @abstractmethod
    async def scrape(self, url: str, service_name: str, days: int = 30) -> dict:
        """
        Scrape timeslot availability from the given booking URL.

        Returns:
            Standardized availability dict with keys:
            merchant, platform, booking_url, extracted_at,
            service, capacity, date_range, availability
        """
        ...

    # --- Shared helper methods ---

    def seconds_to_time(self, seconds: int) -> str:
        """Convert seconds-from-midnight to 'h:MM AM/PM' format."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        period = "AM" if hours < 12 else "PM"
        display_hour = hours if hours <= 12 else hours - 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{minutes:02d} {period}"

    def time_str_to_seconds(self, time_str: str) -> int:
        """Convert 'h:MM AM/PM' or 'HH:MM' to seconds from midnight."""
        time_str = time_str.strip().upper()
        if "AM" in time_str or "PM" in time_str:
            is_pm = "PM" in time_str
            time_str = time_str.replace("AM", "").replace("PM", "").strip()
            parts = time_str.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            if is_pm and h != 12:
                h += 12
            elif not is_pm and h == 12:
                h = 0
            return h * 3600 + m * 60
        else:
            parts = time_str.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            return h * 3600 + m * 60

    def compute_day_parts(self, time_slots_seconds: list[int]) -> dict:
        """Compute slot counts per day-part from seconds-from-midnight list."""
        morning = sum(1 for s in time_slots_seconds if s < MORNING_END)
        afternoon = sum(1 for s in time_slots_seconds if MORNING_END <= s < EVENING_START)
        evening = sum(1 for s in time_slots_seconds if s >= EVENING_START)
        return {"morning": morning, "afternoon": afternoon, "evening": evening}

    def build_result(
        self,
        merchant_name: str,
        booking_url: str,
        service_name: str,
        service_info: dict | None,
        days: int,
        date_slots: dict[str, dict],
    ) -> dict:
        """
        Build the standardized output JSON from collected date->slots data.

        Args:
            merchant_name: Name of the merchant/business.
            booking_url: The booking URL that was scraped.
            service_name: The service that was checked.
            service_info: Optional dict with duration, price, id.
            days: Number of days requested.
            date_slots: Mapping of date_str -> {
                "closed": bool,
                "time_slots": list[int]  (seconds from midnight)
            }
        """
        today = date.today()
        target_dates = [today + timedelta(days=i) for i in range(days)]

        # Determine max slots per day-part (= theoretical full capacity)
        max_parts = {"morning": 0, "afternoon": 0, "evening": 0}
        for entry in date_slots.values():
            if not entry.get("closed", False):
                parts = self.compute_day_parts(entry.get("time_slots", []))
                for k in max_parts:
                    max_parts[k] = max(max_parts[k], parts[k])
        max_total = sum(max_parts.values()) or 1

        availability_output = []
        for target_date in target_dates:
            date_str = target_date.isoformat()
            day_name = DAY_NAMES[target_date.weekday()]
            entry = date_slots.get(date_str)

            if entry:
                closed = entry.get("closed", False)
                raw_slots = entry.get("time_slots", [])

                if closed:
                    availability_output.append({
                        "date": date_str, "day_of_week": day_name,
                        "closed": True, "total_slots": 0,
                        "morning_slots": 0, "afternoon_slots": 0, "evening_slots": 0,
                        "morning_pct": 0, "afternoon_pct": 0, "evening_pct": 0,
                        "overall_pct": 0, "timeslots": [],
                    })
                else:
                    parts = self.compute_day_parts(raw_slots)
                    total = sum(parts.values())
                    availability_output.append({
                        "date": date_str, "day_of_week": day_name,
                        "closed": False, "total_slots": total,
                        "morning_slots": parts["morning"],
                        "afternoon_slots": parts["afternoon"],
                        "evening_slots": parts["evening"],
                        "morning_pct": round(parts["morning"] / max_parts["morning"], 2) if max_parts["morning"] else 0,
                        "afternoon_pct": round(parts["afternoon"] / max_parts["afternoon"], 2) if max_parts["afternoon"] else 0,
                        "evening_pct": round(parts["evening"] / max_parts["evening"], 2) if max_parts["evening"] else 0,
                        "overall_pct": round(total / max_total, 2),
                        "timeslots": [self.seconds_to_time(s) for s in raw_slots],
                    })
            else:
                availability_output.append({
                    "date": date_str, "day_of_week": day_name,
                    "closed": None, "total_slots": 0,
                    "morning_slots": 0, "afternoon_slots": 0, "evening_slots": 0,
                    "morning_pct": 0, "afternoon_pct": 0, "evening_pct": 0,
                    "overall_pct": 0, "timeslots": [],
                    "note": "No data loaded for this date",
                })

        return {
            "merchant": merchant_name,
            "platform": self.platform_name,
            "booking_url": booking_url,
            "extracted_at": datetime.now().isoformat(),
            "service": {
                "name": service_name,
                "duration_minutes": service_info.get("duration") if service_info else None,
                "price_cents": service_info.get("price") if service_info else None,
                "price_display": f"${service_info['price'] / 100:.0f}" if service_info and service_info.get("price") else None,
                "service_id": service_info.get("id") if service_info else None,
            },
            "capacity": {
                "max_morning": max_parts["morning"],
                "max_afternoon": max_parts["afternoon"],
                "max_evening": max_parts["evening"],
                "max_total": max_total,
            },
            "date_range": {
                "from": target_dates[0].isoformat(),
                "to": target_dates[-1].isoformat(),
            },
            "availability": availability_output,
        }

    async def create_browser_context(self, playwright):
        """Create a standard Playwright browser context. Returns (browser, context, page)."""
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = await context.new_page()
        return browser, context, page

    def extract_dates_from_json(self, data, date_slots: dict):
        """Recursively search any JSON for date+timeslot availability patterns."""
        if isinstance(data, list):
            for item in data:
                self.extract_dates_from_json(item, date_slots)
        elif isinstance(data, dict):
            # Look for {"date": "YYYY-MM-DD", "times": [...]} patterns
            date_val = data.get("date") or data.get("Date") or data.get("appointmentDate")
            times = (data.get("times") or data.get("Times") or
                     data.get("availableTimes") or data.get("timeSlots") or
                     data.get("slots") or data.get("time_slots"))

            if date_val and isinstance(date_val, str) and re.match(r"\d{4}-\d{2}-\d{2}", date_val):
                if times and isinstance(times, list):
                    slots = []
                    for t in times:
                        if isinstance(t, (int, float)):
                            slots.append(int(t))
                        elif isinstance(t, str):
                            try:
                                slots.append(self.time_str_to_seconds(t))
                            except Exception:
                                pass
                        elif isinstance(t, dict):
                            time_val = t.get("time") or t.get("startTime") or t.get("start")
                            if time_val:
                                try:
                                    if isinstance(time_val, (int, float)):
                                        slots.append(int(time_val))
                                    else:
                                        slots.append(self.time_str_to_seconds(str(time_val)))
                                except Exception:
                                    pass
                    if slots:
                        date_slots[date_val] = {"closed": False, "time_slots": sorted(slots)}

            # Recurse into dict values
            for v in data.values():
                if isinstance(v, (dict, list)):
                    self.extract_dates_from_json(v, date_slots)
