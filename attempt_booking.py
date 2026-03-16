"""
Attempt to book an actual timeslot on Apple Foot Spa via byChronos.

Flow: Services → Specialist → Time → Select slot → Customer info → Book
"""
import asyncio
import json
import os
from datetime import date, timedelta

from config import USER_AGENTS, PAGE_LOAD_TIMEOUT


BOOKING_URL = "https://go.bychronos.com/l/worcester-01609-apple-foot-spa-805679/a/services"
SERVICE_NAME = "60 Mins Bodywork"

# Customer details
FIRST_NAME = "Vojtěch"
LAST_NAME = "Hájek"
EMAIL = "hajek.vojtech@gmail.com"

# Book at least 1 week from now
TARGET_DATE = date.today() + timedelta(days=8)


async def main():
    from playwright.async_api import async_playwright

    os.makedirs("output", exist_ok=True)
    print(f"Attempting to book: {SERVICE_NAME}")
    print(f"Target date: {TARGET_DATE} ({TARGET_DATE.strftime('%A')})")
    print(f"Customer: {FIRST_NAME} {LAST_NAME} <{EMAIL}>")
    print()

    all_api_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=200)
        context = await browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        # Intercept ALL network responses
        async def on_response(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if "json" in ct or ("api" in url.lower() and "google" not in url.lower()):
                try:
                    body = await response.text()
                    try:
                        parsed = json.loads(body)
                    except (json.JSONDecodeError, ValueError):
                        parsed = None
                    entry = {
                        "step": "unknown",
                        "url": url,
                        "status": response.status,
                        "method": response.request.method,
                        "body": parsed if parsed else body[:3000],
                    }
                    all_api_responses.append(entry)
                    print(f"  [API] {response.request.method} {response.status} {url}")
                    if parsed:
                        preview = json.dumps(parsed, indent=2)[:300]
                        print(f"        {preview}")
                except Exception:
                    pass

        # Intercept requests too (to see POST bodies)
        async def on_request(request):
            if request.method == "POST" and "api" in request.url.lower():
                try:
                    post_data = request.post_data
                    print(f"  [REQ] POST {request.url}")
                    if post_data:
                        print(f"        Body: {post_data[:500]}")
                except Exception:
                    pass

        page.on("response", on_response)
        page.on("request", on_request)

        # ============================================================
        # STEP 1: Load services page
        # ============================================================
        print("=" * 80)
        print("STEP 1: Load services page")
        print("=" * 80)
        try:
            await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        except Exception:
            await page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await page.screenshot(path="output/book_1_services.png")

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "1_services"

        # ============================================================
        # STEP 2: Select service
        # ============================================================
        print("\n" + "=" * 80)
        print(f"STEP 2: Select service '{SERVICE_NAME}'")
        print("=" * 80)

        service_btn = page.locator(f"button:has-text('{SERVICE_NAME}')").first
        await service_btn.click()
        await asyncio.sleep(2)
        await page.screenshot(path="output/book_2_service_selected.png")

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "2_service_selected"

        # ============================================================
        # STEP 3: Click Next → Specialist page
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 3: Navigate to Specialist page")
        print("=" * 80)

        next_buttons = await page.locator("button:has-text('Next')").all()
        for btn in next_buttons:
            if await btn.is_visible():
                await btn.click()
                break
        await asyncio.sleep(3)
        await page.screenshot(path="output/book_3_specialist.png")

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "3_specialist"

        # ============================================================
        # STEP 4: Select "Any specialist"
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 4: Select specialist")
        print("=" * 80)

        for text in ["Any specialist", "Any Specialist", "Any", "Anyone"]:
            try:
                el = page.get_by_text(text, exact=True).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    print(f"  Selected: '{text}'")
                    break
            except Exception:
                continue
        await asyncio.sleep(2)

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "4_specialist_selected"

        # ============================================================
        # STEP 5: Click Next → Time page
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 5: Navigate to Time page")
        print("=" * 80)

        next_buttons = await page.locator("button:has-text('Next')").all()
        for btn in next_buttons:
            if await btn.is_visible():
                await btn.click()
                break
        await asyncio.sleep(5)
        await page.screenshot(path="output/book_5_time_page.png", full_page=True)

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "5_time_page"

        # ============================================================
        # STEP 6: Navigate to the target date and select a timeslot
        # ============================================================
        print("\n" + "=" * 80)
        print(f"STEP 6: Navigate to target date {TARGET_DATE}")
        print("=" * 80)

        # Click through weeks to get to target date
        target_day_abbr = TARGET_DATE.strftime("%a")[:3]
        target_day_num = TARGET_DATE.day
        btn_text = f"{target_day_abbr}{target_day_num}"
        print(f"  Looking for date button: '{btn_text}'")

        # We may need to click the forward arrow to advance weeks
        # First try clicking the date directly
        date_found = False
        for attempt in range(8):  # Try advancing up to 8 weeks
            try:
                date_btn = page.locator(f"button:has-text('{btn_text}')").first
                if await date_btn.is_visible(timeout=2000):
                    await date_btn.click()
                    date_found = True
                    print(f"  Clicked date button: '{btn_text}'")
                    await asyncio.sleep(3)
                    break
            except Exception:
                pass

            # Try clicking forward/next week arrow
            try:
                # Look for right arrow / chevron / forward button on the calendar
                forward_selectors = [
                    "button[aria-label*='next']",
                    "button[aria-label*='Next']",
                    "button[aria-label*='forward']",
                    "button:has(svg)",  # Arrow buttons often use SVGs
                ]
                clicked_forward = False
                for sel in forward_selectors:
                    try:
                        arrows = await page.locator(sel).all()
                        for arrow in arrows:
                            # Get the arrow that's to the right (forward)
                            text = (await arrow.text_content() or "").strip()
                            aria = await arrow.get_attribute("aria-label") or ""
                            if "next" in aria.lower() or "forward" in aria.lower() or ">" in text or "›" in text:
                                await arrow.click()
                                clicked_forward = True
                                print(f"  Clicked forward arrow (attempt {attempt + 1})")
                                await asyncio.sleep(2)
                                break
                    except Exception:
                        continue
                    if clicked_forward:
                        break

                if not clicked_forward:
                    # Try finding any right-pointing arrow buttons
                    all_btns = await page.locator("button").all()
                    for btn in all_btns:
                        text = (await btn.text_content() or "").strip()
                        html = await btn.evaluate("el => el.outerHTML.substring(0, 200)")
                        if ("chevron" in html.lower() or "arrow" in html.lower() or
                            "right" in html.lower() or text in [">", "›", "→", "▸"]):
                            bbox = await btn.bounding_box()
                            if bbox and bbox["x"] > 600:  # Right side of page
                                await btn.click()
                                clicked_forward = True
                                print(f"  Clicked right arrow button")
                                await asyncio.sleep(2)
                                break
            except Exception as e:
                print(f"  Forward navigation error: {e}")

        await page.screenshot(path="output/book_6_target_date.png", full_page=True)

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "6_target_date"

        if not date_found:
            print(f"  WARNING: Could not find date button '{btn_text}'")
            # List all visible buttons for debugging
            print("\n  All visible buttons:")
            all_btns = await page.locator("button").all()
            for btn in all_btns:
                if await btn.is_visible():
                    text = (await btn.text_content() or "").strip()
                    if text:
                        print(f"    '{text[:80]}'")

        # ============================================================
        # STEP 7: Select a timeslot
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 7: Select a timeslot")
        print("=" * 80)

        # Look for time slot buttons (AM/PM format)
        time_elements = await page.locator("text=/\\d{1,2}:\\d{2}\\s*(AM|PM)/i").all()
        print(f"  Found {len(time_elements)} time elements")

        selected_time = None
        for el in time_elements:
            text = (await el.text_content() or "").strip()
            print(f"    Available: '{text}'")

        # Try to click a mid-morning slot (like 10:00 AM or 11:00 AM)
        preferred_times = ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "10:00AM", "10:30AM"]
        for ptime in preferred_times:
            try:
                slot = page.locator(f"text='{ptime}'").first
                if await slot.is_visible(timeout=1000):
                    await slot.click()
                    selected_time = ptime
                    print(f"\n  Selected timeslot: {ptime}")
                    break
            except Exception:
                continue

        # If preferred times not found, click first available
        if not selected_time and time_elements:
            try:
                first_time = time_elements[0]
                text = (await first_time.text_content() or "").strip()
                await first_time.click()
                selected_time = text
                print(f"\n  Selected first available timeslot: {text}")
            except Exception as e:
                print(f"  Error clicking timeslot: {e}")

        # Also try clicking button elements that contain times
        if not selected_time:
            print("\n  Trying button-based time selection...")
            all_btns = await page.locator("button").all()
            for btn in all_btns:
                text = (await btn.text_content() or "").strip()
                if "AM" in text or "PM" in text:
                    print(f"    Found time button: '{text}'")
                    if not selected_time:
                        await btn.click()
                        selected_time = text
                        print(f"    Clicked: '{text}'")

        await asyncio.sleep(3)
        await page.screenshot(path="output/book_7_slot_selected.png", full_page=True)

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "7_slot_selected"

        # ============================================================
        # STEP 8: Look for and click "Next" or "Book" button
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 8: Advance to booking/customer info page")
        print("=" * 80)

        # Try "Next" first, then "Book", "Confirm", etc.
        advance_texts = ["Next", "Book", "Book Now", "Continue", "Confirm", "Proceed"]
        advanced = False
        for txt in advance_texts:
            try:
                btns = await page.locator(f"button:has-text('{txt}')").all()
                for btn in btns:
                    if await btn.is_visible():
                        await btn.click()
                        advanced = True
                        print(f"  Clicked '{txt}' button")
                        break
            except Exception:
                continue
            if advanced:
                break

        await asyncio.sleep(4)
        await page.screenshot(path="output/book_8_after_advance.png", full_page=True)

        # Dump current page text for analysis
        body_text = await page.inner_text("body")
        print(f"\n--- Page text after advancing ---")
        print(body_text[:3000])

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "8_after_advance"

        # ============================================================
        # STEP 9: Look for customer info form and fill it
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 9: Fill customer information")
        print("=" * 80)

        # Look for input fields
        all_inputs = await page.locator("input").all()
        print(f"  Found {len(all_inputs)} input fields:")
        for inp in all_inputs:
            try:
                input_type = await inp.get_attribute("type") or "text"
                name = await inp.get_attribute("name") or ""
                placeholder = await inp.get_attribute("placeholder") or ""
                aria_label = await inp.get_attribute("aria-label") or ""
                label_text = ""
                # Try to get associated label
                input_id = await inp.get_attribute("id") or ""
                if input_id:
                    try:
                        label = page.locator(f"label[for='{input_id}']").first
                        label_text = (await label.text_content() or "").strip()
                    except Exception:
                        pass
                visible = await inp.is_visible()
                print(f"    type={input_type} name='{name}' placeholder='{placeholder}' "
                      f"aria='{aria_label}' label='{label_text}' visible={visible}")
            except Exception:
                pass

        # Try to fill in the form fields
        field_mappings = {
            "first": FIRST_NAME,
            "last": LAST_NAME,
            "email": EMAIL,
            "name": FIRST_NAME,  # fallback
        }

        filled_fields = []
        for inp in all_inputs:
            try:
                if not await inp.is_visible():
                    continue
                name = (await inp.get_attribute("name") or "").lower()
                placeholder = (await inp.get_attribute("placeholder") or "").lower()
                aria_label = (await inp.get_attribute("aria-label") or "").lower()
                input_type = (await inp.get_attribute("type") or "text").lower()
                input_id = (await inp.get_attribute("id") or "").lower()

                # Get label text
                label_text = ""
                raw_id = await inp.get_attribute("id") or ""
                if raw_id:
                    try:
                        label = page.locator(f"label[for='{raw_id}']").first
                        label_text = (await label.text_content() or "").strip().lower()
                    except Exception:
                        pass

                all_hints = f"{name} {placeholder} {aria_label} {label_text} {input_id}"

                if input_type in ["hidden", "submit", "button", "checkbox", "radio"]:
                    continue

                value = None
                field_name = None

                if "first" in all_hints and "name" in all_hints:
                    value = FIRST_NAME
                    field_name = "First Name"
                elif "last" in all_hints and "name" in all_hints:
                    value = LAST_NAME
                    field_name = "Last Name"
                elif "email" in all_hints:
                    value = EMAIL
                    field_name = "Email"
                elif "phone" in all_hints or "tel" in all_hints or input_type == "tel":
                    value = ""  # Skip phone - not required hopefully
                    field_name = "Phone (skipped)"
                elif "name" in all_hints and "first" not in all_hints and "last" not in all_hints:
                    # Generic name field - put full name
                    value = f"{FIRST_NAME} {LAST_NAME}"
                    field_name = "Name"

                if value is not None and value != "":
                    await inp.fill(value)
                    filled_fields.append(f"{field_name}: {value}")
                    print(f"  Filled {field_name}: {value}")

            except Exception as e:
                print(f"  Error filling field: {e}")

        await asyncio.sleep(1)
        await page.screenshot(path="output/book_9_form_filled.png", full_page=True)

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "9_form_filled"

        # ============================================================
        # STEP 10: Look for and click the final "Book" / "Confirm" button
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 10: Submit booking")
        print("=" * 80)

        # Before clicking, let's see what buttons are available
        all_btns = await page.locator("button").all()
        print("  Available buttons:")
        for btn in all_btns:
            if await btn.is_visible():
                text = (await btn.text_content() or "").strip()
                if text:
                    print(f"    '{text}'")

        # Try to submit
        submit_texts = ["Book", "Book Now", "Confirm", "Confirm Booking", "Submit",
                        "Complete Booking", "Reserve", "Schedule", "Book Appointment",
                        "Next"]
        submitted = False
        for txt in submit_texts:
            try:
                btns = await page.locator(f"button:has-text('{txt}')").all()
                for btn in btns:
                    if await btn.is_visible():
                        print(f"\n  Clicking '{txt}' button to submit booking...")
                        await btn.click()
                        submitted = True
                        break
            except Exception:
                continue
            if submitted:
                break

        if not submitted:
            # Try submit-type inputs
            try:
                submit_input = page.locator("input[type='submit']").first
                if await submit_input.is_visible(timeout=2000):
                    await submit_input.click()
                    submitted = True
                    print("  Clicked submit input")
            except Exception:
                pass

        await asyncio.sleep(5)
        await page.screenshot(path="output/book_10_after_submit.png", full_page=True)

        # Check the result
        body_text = await page.inner_text("body")
        print(f"\n--- Page text after submit ---")
        print(body_text[:3000])

        for r in all_api_responses:
            if r["step"] == "unknown":
                r["step"] = "10_after_submit"

        # Check for success indicators
        success_keywords = ["confirmed", "booked", "thank you", "confirmation",
                           "successfully", "appointment", "scheduled"]
        error_keywords = ["error", "failed", "invalid", "required", "please enter",
                         "try again"]

        body_lower = body_text.lower()
        print("\n--- Booking result analysis ---")
        for kw in success_keywords:
            if kw in body_lower:
                print(f"  SUCCESS indicator found: '{kw}'")
        for kw in error_keywords:
            if kw in body_lower:
                print(f"  ERROR indicator found: '{kw}'")

        # Save final state
        html = await page.content()
        with open("output/book_final_page.html", "w") as f:
            f.write(html)

        with open("output/book_api_log.json", "w") as f:
            json.dump(all_api_responses, f, indent=2, default=str)
        print(f"\nAPI log saved ({len(all_api_responses)} responses)")

        # Print summary of all API calls
        print("\n" + "=" * 80)
        print("SUMMARY: All API calls by step")
        print("=" * 80)
        for r in all_api_responses:
            url = r["url"]
            if "google" not in url and "track" not in url:
                print(f"  [{r['step']}] {r.get('method', '?')} {r['status']} {url}")

        await browser.close()

    print("\n\nBooking attempt complete!")
    print(f"Screenshots saved to output/book_*.png")


if __name__ == "__main__":
    asyncio.run(main())
