"""
Book via byChronos API using location-scoped endpoints.
Flow: Register → Login → Navigate booking flow → Create appointment
"""
import asyncio
import json
import os
from config import USER_AGENTS

LOCATION_SLUG = "worcester-01609-apple-foot-spa-805679"
LOCATION_URL = f"https://go.bychronos.com/l/{LOCATION_SLUG}"
BOOKING_URL = f"{LOCATION_URL}/a/services"

FIRST_NAME = "Vojtěch"
LAST_NAME = "Hájek"
EMAIL = "hajek.vojtech@gmail.com"
PASSWORD = "BookingTest2026!"  # Temp password for the account

SERVICE_ID = 84229
TARGET_DATE = "2026-03-23"
TARGET_TIME_SECONDS = 36000  # 10:00 AM


async def api_call(page, method, path, body=None, extra_headers=None):
    """Make an API call from within the page context."""
    headers_dict = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
    }
    if extra_headers:
        headers_dict.update(extra_headers)

    js = f"""
        async () => {{
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
            const headers = {json.dumps(headers_dict)};
            if (csrf) headers['X-CSRF-TOKEN'] = csrf;

            const opts = {{ method: '{method}', headers, credentials: 'same-origin' }};
            {f'opts.body = JSON.stringify({json.dumps(body)});' if body else ''}

            try {{
                const resp = await fetch('{path}', opts);
                const text = await resp.text();
                let parsed = null;
                try {{ parsed = JSON.parse(text); }} catch(e) {{}}

                // Get response cookies
                return {{
                    status: resp.status,
                    body: parsed || text.substring(0, 5000),
                    headers: Object.fromEntries(resp.headers.entries()),
                }};
            }} catch(e) {{
                return {{ error: e.message }};
            }}
        }}
    """
    return await page.evaluate(js)


async def main():
    from playwright.async_api import async_playwright

    os.makedirs("output", exist_ok=True)
    print(f"Booking: 60 Mins Bodywork on {TARGET_DATE} at 10:00 AM")
    print(f"Customer: {FIRST_NAME} {LAST_NAME} <{EMAIL}>")
    print()

    all_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENTS[0])
        page = await context.new_page()

        # Track all API responses
        async def on_response(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if ("json" in ct or "api" in url.lower()) and "google" not in url.lower() and "track" not in url.lower():
                try:
                    body = await response.json()
                    all_responses.append({
                        "method": response.request.method,
                        "url": url,
                        "status": response.status,
                        "body": body,
                    })
                except Exception:
                    pass

        page.on("response", on_response)

        # Load booking page to establish session
        print("Loading booking page...")
        await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # ============================================================
        # Step 1: Register account
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 1: Register account")
        print("=" * 80)

        result = await api_call(page, "POST", f"/l/{LOCATION_SLUG}/register", {
            "first_name": FIRST_NAME,
            "last_name": LAST_NAME,
            "email": EMAIL,
            "phone_number": "",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        })
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:1000]}")

        registered = result.get('status') in [200, 201]
        if not registered and result.get('status') == 422:
            body = result.get('body', {})
            errors = body.get('errors', {})
            if 'email' in errors and 'taken' in str(errors['email']).lower():
                print("  Account already exists, will try login...")
                registered = True

        # ============================================================
        # Step 2: Login
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 2: Login")
        print("=" * 80)

        result = await api_call(page, "POST", f"/l/{LOCATION_SLUG}/login", {
            "email": EMAIL,
            "password": PASSWORD,
        })
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:1000]}")

        logged_in = result.get('status') == 200

        if logged_in:
            print("  Successfully logged in!")

            # Check user status
            result = await api_call(page, "GET", "/api/user")
            print(f"\n  User API: Status {result.get('status')}")
            print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")
        else:
            print("  Login failed. Trying the UI-based phone verification flow...")
            # The phone verification is required. Let's try the verification flow.

        # ============================================================
        # Step 3: Try the verification send endpoint
        # ============================================================
        print("\n" + "=" * 80)
        print("STEP 3: Try verification endpoints (from location context)")
        print("=" * 80)

        # Navigate to the auth page within the booking flow
        # to get proper routing context
        await page.goto(f"{LOCATION_URL}/a/auth", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
        await page.screenshot(path="output/api_auth_page.png")

        # Check what page we're on
        body_text = await page.inner_text("body")
        print(f"  Auth page text:\n{body_text[:500]}")

        # Try the verification send from this context
        result = await api_call(page, "POST", "/auth/verification/send", {
            "phone": "+10000000000",
            "channel": "sms",
        }, {"X-Location-URL": LOCATION_URL})
        print(f"\n  Verification send (root): Status {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")

        # Try location-scoped verification
        result = await api_call(page, "POST", f"/l/{LOCATION_SLUG}/auth/verification/send", {
            "phone": "+10000000000",
            "channel": "sms",
        })
        print(f"\n  Verification send (location-scoped): Status {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")

        # ============================================================
        # Step 4: If we got logged in, try to create appointment
        # ============================================================
        if logged_in:
            print("\n" + "=" * 80)
            print("STEP 4: Create appointment")
            print("=" * 80)

            # Navigate back to booking context
            await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            appointment_data = {
                "guests": [{
                    "services": [{
                        "service_id": SERVICE_ID,
                        "resource_id": None,
                        "modifiers": [],
                    }]
                }],
                "date": TARGET_DATE,
                "time": TARGET_TIME_SECONDS,
                "notes": "",
            }

            result = await api_call(page, "POST", "/appointments", appointment_data,
                                    {"X-Location-URL": LOCATION_URL})
            print(f"  Status: {result.get('status')}")
            print(f"  Body: {json.dumps(result.get('body'), indent=2)[:2000]}")

            if result.get('status') in [200, 201]:
                print("\n  *** BOOKING SUCCESSFUL! ***")
                appt = result.get('body', {})
                print(f"  Appointment ID: {appt.get('id')}")
                print(f"  Date: {appt.get('date')}")
                print(f"  Time: {appt.get('time')}")
                print(f"  Status: {appt.get('status')}")
        else:
            print("\n" + "=" * 80)
            print("STEP 4: Try UI-based booking flow with phone verification")
            print("=" * 80)

            # Go through the full booking flow in the UI
            await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Select service
            service_btn = page.locator(f"button:has-text('60 Mins Bodywork')").first
            await service_btn.click()
            await asyncio.sleep(1)

            # Click Next
            next_btn = page.locator("button:has-text('Next')").first
            await next_btn.click()
            await asyncio.sleep(2)

            # Select any specialist
            for text in ["Any specialist", "Any Specialist"]:
                try:
                    el = page.get_by_text(text, exact=True).first
                    if await el.is_visible(timeout=2000):
                        await el.click()
                        break
                except Exception:
                    continue
            await asyncio.sleep(1)

            # Click Next
            next_buttons = await page.locator("button:has-text('Next')").all()
            for btn in next_buttons:
                if await btn.is_visible():
                    await btn.click()
                    break
            await asyncio.sleep(3)

            # Click target date
            from datetime import date, timedelta
            target = date(2026, 3, 23)
            day_abbr = target.strftime("%a")[:3]
            btn_text = f"{day_abbr}{target.day}"
            try:
                date_btn = page.locator(f"button:has-text('{btn_text}')").first
                if await date_btn.is_visible(timeout=3000):
                    await date_btn.click()
                    await asyncio.sleep(2)
            except Exception:
                pass

            # Select 10:00 AM
            try:
                slot = page.locator("text='10:00 AM'").first
                await slot.click()
                await asyncio.sleep(2)
            except Exception:
                pass

            # Now we should be on the auth page
            await page.screenshot(path="output/api_flow_auth.png")
            body_text = await page.inner_text("body")
            print(f"  Current page:\n{body_text[:500]}")

            # Check if we see a "Sign in" option or can switch to email login
            print("\n  Looking for email/password login option...")
            # Check if there are tabs or links to switch to email login
            tabs = await page.locator("[role='tab']").all()
            for tab in tabs:
                text = (await tab.text_content() or "").strip()
                print(f"    Tab: '{text}'")
                if "email" in text.lower() or "password" in text.lower() or "sign in" in text.lower():
                    await tab.click()
                    await asyncio.sleep(1)
                    break

            # Check for any link/button that says "Sign in", "Log in", "Email"
            for sel_text in ["Sign in", "Log in", "Email", "Use email", "Already have account"]:
                try:
                    link = page.get_by_text(sel_text).first
                    if await link.is_visible(timeout=1000):
                        print(f"    Found: '{sel_text}' - clicking")
                        await link.click()
                        await asyncio.sleep(1)
                except Exception:
                    continue

            await page.screenshot(path="output/api_flow_auth2.png")
            body_text = await page.inner_text("body")
            print(f"\n  After looking for email login:\n{body_text[:500]}")

        # Save all API responses
        with open("output/api_booking_log.json", "w") as f:
            json.dump(all_responses, f, indent=2, default=str)

        await browser.close()

    print("\n\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
