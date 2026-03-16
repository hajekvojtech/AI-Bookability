"""
Attempt to book via byChronos API directly.
Try registration and appointment creation endpoints.
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

SERVICE_ID = 84229
TARGET_DATE = "2026-03-23"
# 10:00 AM = 36000 seconds from midnight
TARGET_TIME_SECONDS = 36000


async def try_api_call(page, method, url, body=None, extra_headers=None):
    """Make an API call from within the page context."""
    headers_js = """
        const headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        };
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
        if (csrf) headers['X-CSRF-TOKEN'] = csrf;
    """
    if extra_headers:
        for k, v in extra_headers.items():
            headers_js += f"\n        headers['{k}'] = '{v}';"

    body_js = f"opts.body = JSON.stringify({json.dumps(body)});" if body else ""

    js = f"""
        async () => {{
            {headers_js}
            const opts = {{ method: '{method}', headers, credentials: 'same-origin' }};
            {body_js}
            try {{
                const resp = await fetch('{url}', opts);
                const text = await resp.text();
                let parsed = null;
                try {{ parsed = JSON.parse(text); }} catch(e) {{}}
                return {{
                    status: resp.status,
                    body: parsed || text.substring(0, 3000),
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

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENTS[0])
        page = await context.new_page()

        # Load page to get session cookies
        await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        location_url_header = {"X-Location-URL": LOCATION_URL}

        # ============================================================
        # 1. Try account lookup
        # ============================================================
        print("=" * 80)
        print("1. Account lookup")
        print("=" * 80)

        result = await try_api_call(page, "POST", "/auth/account/lookup", {
            "email": EMAIL,
        }, location_url_header)
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")

        # ============================================================
        # 2. Try verification lookup (phone)
        # ============================================================
        print("\n" + "=" * 80)
        print("2. Verification lookup")
        print("=" * 80)

        result = await try_api_call(page, "POST", "/auth/verification/lookup", {
            "phone": "+10000000000",
        }, location_url_header)
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")

        # ============================================================
        # 3. Try location-specific registration
        # ============================================================
        print("\n" + "=" * 80)
        print("3. Location-specific registration")
        print("=" * 80)

        # First try with just email
        result = await try_api_call(page, "POST", f"/l/{LOCATION_SLUG}/register", {
            "first_name": FIRST_NAME,
            "last_name": LAST_NAME,
            "email": EMAIL,
            "phone_number": "+10000000000",
        })
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")

        # ============================================================
        # 4. Try account registration
        # ============================================================
        print("\n" + "=" * 80)
        print("4. Account registration")
        print("=" * 80)

        result = await try_api_call(page, "POST", "/auth/account/register", {
            "first_name": FIRST_NAME,
            "last_name": LAST_NAME,
            "email": EMAIL,
            "password": "TempPass123!",
            "password_confirmation": "TempPass123!",
        }, location_url_header)
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")

        # ============================================================
        # 5. Try creating appointment without auth (to see error shape)
        # ============================================================
        print("\n" + "=" * 80)
        print("5. Create appointment (unauthenticated - expect 401)")
        print("=" * 80)

        result = await try_api_call(page, "POST", "/appointments", {
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
        }, location_url_header)
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:1000]}")

        # ============================================================
        # 6. Try location-specific login with email
        # ============================================================
        print("\n" + "=" * 80)
        print("6. Location login")
        print("=" * 80)

        result = await try_api_call(page, "POST", f"/l/{LOCATION_SLUG}/login", {
            "email": EMAIL,
            "password": "TempPass123!",
        })
        print(f"  Status: {result.get('status')}")
        print(f"  Body: {json.dumps(result.get('body'), indent=2)[:500]}")

        # ============================================================
        # 7. Check if there's any location-specific settings about auth
        # ============================================================
        print("\n" + "=" * 80)
        print("7. Location details (check appointment_setting)")
        print("=" * 80)

        # Navigate to location page first to get correct API context
        await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        result = await try_api_call(page, "GET", "/api/location")
        print(f"  Status: {result.get('status')}")
        body = result.get('body', {})
        if isinstance(body, dict):
            # Print full response to see all settings
            print(f"  Full location data:")
            print(json.dumps(body, indent=2)[:3000])

        await browser.close()

    print("\n\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
