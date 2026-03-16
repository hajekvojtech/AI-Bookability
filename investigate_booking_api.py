"""
Investigate byChronos booking API to find if we can create appointments
directly via API calls, bypassing the phone verification UI.
"""
import asyncio
import json
import os

from config import USER_AGENTS


BASE_URL = "https://go.bychronos.com"
BOOKING_URL = f"{BASE_URL}/l/worcester-01609-apple-foot-spa-805679/a/services"


async def main():
    from playwright.async_api import async_playwright

    os.makedirs("output", exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        # Load the page to get cookies/CSRF token
        await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Get the CSRF token
        csrf = await page.evaluate("document.querySelector('meta[name=\"csrf-token\"]')?.content")
        print(f"CSRF Token: {csrf}")

        # Try various API endpoints to understand the booking flow
        endpoints_to_test = [
            # Auth/user related
            ("GET", "/api/user", None),
            ("GET", "/api/location", None),

            # Try to discover booking/appointment endpoints
            ("GET", "/api/appointments", None),
            ("GET", "/api/bookings", None),
            ("GET", "/api/reservations", None),

            # Auth endpoints
            ("POST", "/api/auth/phone", json.dumps({"phone": "+10000000000", "country_code": "+1"})),
            ("POST", "/api/login", json.dumps({"phone": "+10000000000"})),
            ("POST", "/api/auth/send-code", json.dumps({"phone": "+10000000000"})),
            ("POST", "/api/send-code", json.dumps({"phone": "+10000000000"})),
            ("POST", "/api/verify", json.dumps({"phone": "+10000000000", "code": "000000"})),
            ("POST", "/api/auth/verify", json.dumps({"phone": "+10000000000", "code": "000000"})),
            ("POST", "/api/otp/send", json.dumps({"phone": "+10000000000"})),

            # Guest booking?
            ("POST", "/api/guest-booking", json.dumps({"email": "test@test.com"})),
            ("POST", "/api/guest/appointments", json.dumps({})),

            # Service/resource info
            ("GET", "/api/service-categories", None),
            ("GET", "/api/resources?services=84229&source=appointment", None),

            # Try common appointment creation endpoints
            ("POST", "/api/appointments", json.dumps({
                "service_id": 84229,
                "date": "2026-03-23",
                "time": "10:00",
                "guest": {
                    "first_name": "Test",
                    "last_name": "User",
                    "email": "test@test.com",
                }
            })),
        ]

        print("\n" + "=" * 80)
        print("Testing API endpoints")
        print("=" * 80)

        for method, endpoint, body in endpoints_to_test:
            try:
                js_code = f"""
                    async () => {{
                        const headers = {{
                            'Accept': 'application/json',
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest',
                        }};
                        const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
                        if (csrf) headers['X-CSRF-TOKEN'] = csrf;

                        const opts = {{ method: '{method}', headers }};
                        {'opts.body = ' + repr(body) + ';' if body else ''}

                        try {{
                            const resp = await fetch('{endpoint}', opts);
                            const text = await resp.text();
                            let parsed = null;
                            try {{ parsed = JSON.parse(text); }} catch(e) {{}}
                            return {{
                                status: resp.status,
                                statusText: resp.statusText,
                                body: parsed || text.substring(0, 2000),
                                headers: Object.fromEntries(resp.headers.entries()),
                            }};
                        }} catch(e) {{
                            return {{ error: e.message }};
                        }}
                    }}
                """
                result = await page.evaluate(js_code)
                status = result.get("status", "?")
                body_preview = json.dumps(result.get("body", ""), indent=2)[:500] if result.get("body") else ""

                # Only show interesting results (not 404)
                if status != 404 or "error" in result:
                    print(f"\n  {method} {endpoint}")
                    print(f"    Status: {status} {result.get('statusText', '')}")
                    if body_preview:
                        print(f"    Body: {body_preview}")
                else:
                    print(f"  {method} {endpoint} → 404")

            except Exception as e:
                print(f"  {method} {endpoint} → Error: {e}")

        # Now let's try to understand the phone verification flow
        # by looking at the JavaScript bundle
        print("\n\n" + "=" * 80)
        print("Searching for API patterns in JavaScript bundles")
        print("=" * 80)

        # Get all script src URLs
        scripts = await page.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('script[src]'))
                    .map(s => s.src)
                    .filter(s => s.includes('bychronos'));
            }
        """)
        print(f"\nbyChronos scripts: {scripts}")

        # Search for API endpoint patterns in the app bundle
        for script_url in scripts:
            if 'app-' in script_url or 'vendor' in script_url:
                try:
                    # Fetch the script content
                    content = await page.evaluate(f"""
                        async () => {{
                            const resp = await fetch('{script_url}');
                            return await resp.text();
                        }}
                    """)
                    # Search for API patterns
                    import re
                    # Find all API endpoint references
                    api_patterns = re.findall(r'["\'](/api/[a-zA-Z0-9/_-]+)["\']', content)
                    unique_apis = sorted(set(api_patterns))
                    if unique_apis:
                        print(f"\n  API endpoints found in {script_url.split('/')[-1]}:")
                        for api in unique_apis:
                            print(f"    {api}")

                    # Find anything related to phone, auth, booking, appointment
                    booking_patterns = re.findall(
                        r'["\']([^"\']*(?:phone|auth|book|appoint|reserv|confirm|guest|checkout|otp|sms|verify|login|register)[^"\']*)["\']',
                        content, re.IGNORECASE
                    )
                    unique_booking = sorted(set(booking_patterns))
                    if unique_booking:
                        print(f"\n  Booking/auth related strings in {script_url.split('/')[-1]}:")
                        for bp in unique_booking[:50]:  # Limit output
                            if len(bp) < 200:  # Skip very long strings
                                print(f"    '{bp}'")

                except Exception as e:
                    print(f"  Error fetching {script_url}: {e}")

        await browser.close()

    print("\n\nAPI investigation complete!")


if __name__ == "__main__":
    asyncio.run(main())
