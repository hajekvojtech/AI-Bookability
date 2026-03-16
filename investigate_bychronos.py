"""
Investigation script: Follow the full byChronos booking flow to discover
the availability/timeslot API endpoint.

Flow: Services → Next → Specialist → Next → Time (calendar + slots)

Usage: python3 investigate_bychronos.py
"""
import asyncio
import json
import os

from config import USER_AGENTS, PAGE_LOAD_TIMEOUT


BOOKING_URL = "https://go.bychronos.com/l/worcester-01609-apple-foot-spa-805679/a/services"
SERVICE_NAME = "60 Mins Bodywork"


async def main():
    from playwright.async_api import async_playwright

    os.makedirs("output", exist_ok=True)
    print(f"Investigating full booking flow for: {SERVICE_NAME}\n")

    all_api_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=100)
        context = await browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        # --- Intercept all network responses ---
        async def on_response(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if "json" in ct or ("api" in url.lower() and "google" not in url.lower()):
                status = response.status
                try:
                    body = await response.text()
                    try:
                        parsed = json.loads(body)
                    except (json.JSONDecodeError, ValueError):
                        parsed = None

                    entry = {
                        "step": "unknown",
                        "url": url,
                        "status": status,
                        "content_type": ct,
                        "body": parsed if parsed else body[:3000],
                    }
                    all_api_responses.append(entry)

                    preview = json.dumps(parsed, indent=2)[:2000] if parsed else body[:2000]
                    print(f"\n  [API] {status} {url}")
                    print(f"  Body: {preview[:500]}")
                except Exception as e:
                    print(f"  [API] {status} {url} (error: {e})")

        page.on("response", on_response)

        # ============================================================
        # STEP 1: Load the services page
        # ============================================================
        print("=" * 80)
        print("STEP 1: Load services page")
        print("=" * 80)
        try:
            await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        except Exception:
            await page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        print(f"\nURL: {page.url}")
        await page.screenshot(path="output/flow_1_services.png")

        # Mark API responses from this step
        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "1_services_page"

        # ============================================================
        # STEP 2: Click the "60 Mins Bodywork" service button
        # ============================================================
        print("\n" + "=" * 80)
        print(f"STEP 2: Select service '{SERVICE_NAME}'")
        print("=" * 80)

        # Click the specific service button (button with exact service name)
        service_btn = page.locator(f"button:has-text('{SERVICE_NAME}')").first
        await service_btn.click()
        await asyncio.sleep(2)

        # Verify selection - check the sidebar
        body_text = await page.inner_text("body")
        print(f"\nService selected. Cart shows:")
        for line in body_text.split("\n"):
            line = line.strip()
            if "Bodywork" in line or "Total" in line or "$" in line:
                print(f"  {line}")

        await page.screenshot(path="output/flow_2_service_selected.png")

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "2_service_selected"

        # ============================================================
        # STEP 3: Click "Next" to go to Specialist page
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 3: Click 'Next' to Specialist page")
        print("=" * 80)

        # There are two "Next" buttons - click the visible one
        next_buttons = await page.locator("button:has-text('Next')").all()
        for btn in next_buttons:
            if await btn.is_visible():
                await btn.click()
                break
        await asyncio.sleep(3)

        print(f"URL: {page.url}")
        body_text = await page.inner_text("body")
        print(f"\n--- Specialist page text (first 2000 chars) ---")
        print(body_text[:2000])

        await page.screenshot(path="output/flow_3_specialist.png")

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "3_specialist_page"

        # ============================================================
        # STEP 4: Select "Any" specialist
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 4: Select specialist")
        print("=" * 80)

        specialist_selected = False
        # Try "Any Specialist" or "Any" first
        for text in ["Any Specialist", "Any specialist", "Any", "Anyone"]:
            try:
                el = page.get_by_text(text, exact=True).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    specialist_selected = True
                    print(f"Selected: '{text}'")
                    break
            except Exception:
                continue

        if not specialist_selected:
            # Click first specialist/staff option
            print("No 'Any' option found. Looking for specialist elements...")
            body_text = await page.inner_text("body")
            print(f"Page text:\n{body_text[:2000]}")
            # Try clicking the first clickable item that looks like a person/specialist
            specialist_buttons = await page.locator("button").all()
            for btn in specialist_buttons:
                text = (await btn.text_content() or "").strip()
                if text and text not in ["Next", "Back", "Sign in"] and "service" not in text.lower():
                    await btn.click()
                    specialist_selected = True
                    print(f"Clicked specialist: '{text[:60]}'")
                    break

        await asyncio.sleep(3)
        await page.screenshot(path="output/flow_4_specialist_selected.png")

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "4_specialist_selected"

        # ============================================================
        # STEP 5: Click "Next" to go to Time page
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 5: Click 'Next' to Time page")
        print("=" * 80)

        next_buttons = await page.locator("button:has-text('Next')").all()
        for btn in next_buttons:
            if await btn.is_visible():
                await btn.click()
                break
        await asyncio.sleep(5)  # Give extra time for calendar/availability to load

        print(f"URL: {page.url}")
        body_text = await page.inner_text("body")
        print(f"\n--- Time page text (first 5000 chars) ---")
        print(body_text[:5000])

        await page.screenshot(path="output/flow_5_time_page.png", full_page=True)

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "5_time_page"

        # ============================================================
        # STEP 6: Analyze the time page structure
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 6: Analyze time/calendar/slot elements")
        print("=" * 80)

        # Search for all elements that could be timeslots or calendar cells
        selectors_to_check = [
            "[class*='slot']", "[class*='Slot']",
            "[class*='time']", "[class*='Time']",
            "[class*='calendar']", "[class*='Calendar']",
            "[class*='date']", "[class*='Date']",
            "[class*='avail']", "[class*='Avail']",
            "[class*='day']", "[class*='hour']",
            "[data-date]", "[data-time]", "[data-slot]",
            "[role='gridcell']", "[role='option']",
            "table td", "table th",
            "[class*='picker']", "[class*='Picker']",
            "[class*='schedule']", "[class*='Schedule']",
        ]

        for sel in selectors_to_check:
            try:
                elements = await page.query_selector_all(sel)
                if elements:
                    print(f"\n  '{sel}' → {len(elements)} matches")
                    for el in elements[:8]:
                        text = (await el.text_content() or "").strip()
                        cls = await el.get_attribute("class") or ""
                        outer = await el.evaluate("el => el.outerHTML.substring(0, 300)")
                        if text:
                            print(f"    text='{text[:100]}' class='{cls[:80]}'")
                            print(f"    html: {outer[:250]}")
            except Exception:
                pass

        # Also look for AM/PM time patterns in any element
        print("\n\n--- Elements containing time patterns (AM/PM) ---")
        time_elements = await page.locator("text=/\\d{1,2}:\\d{2}\\s*(AM|PM)/i").all()
        print(f"Found {len(time_elements)} elements with AM/PM times")
        for el in time_elements[:20]:
            text = (await el.text_content() or "").strip()
            print(f"  '{text[:80]}'")

        # Also check for just hour numbers
        print("\n--- All buttons on Time page ---")
        all_buttons = await page.locator("button").all()
        for btn in all_buttons:
            text = (await btn.text_content() or "").strip()
            cls = await btn.get_attribute("class") or ""
            if text:
                print(f"  button: '{text[:80]}' class='{cls[:60]}'")

        # ============================================================
        # FINAL: Save all data
        # ============================================================
        html = await page.content()
        with open("output/bychronos_time_page.html", "w") as f:
            f.write(html)
        print("\nTime page HTML saved to output/bychronos_time_page.html")

        with open("output/bychronos_api_log.json", "w") as f:
            json.dump(all_api_responses, f, indent=2, default=str)
        print(f"API log saved ({len(all_api_responses)} responses)")

        # Print summary of all API calls
        print("\n" + "=" * 80)
        print("SUMMARY: All API calls by step")
        print("=" * 80)
        for r in all_api_responses:
            url = r["url"]
            if "google" not in url and "track" not in url:
                print(f"  [{r['step']}] {r['status']} {url}")

        await browser.close()

    print("\n\nInvestigation complete!")


if __name__ == "__main__":
    asyncio.run(main())
