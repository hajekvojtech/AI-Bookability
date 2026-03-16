"""
Intercept the actual network requests when clicking "Get code" on byChronos
to discover the real auth API endpoint and payload format.
"""
import asyncio
import json
import os
from config import USER_AGENTS

LOCATION_SLUG = "worcester-01609-apple-foot-spa-805679"
BOOKING_URL = f"https://go.bychronos.com/l/{LOCATION_SLUG}/a/services"

# Use a real-looking but obviously fake number for testing
FAKE_PHONE = "0000000000"


async def main():
    from playwright.async_api import async_playwright

    os.makedirs("output", exist_ok=True)
    all_requests = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=200)
        context = await browser.new_context(user_agent=USER_AGENTS[0])
        page = await context.new_page()

        # Intercept ALL requests (not just responses)
        async def on_request(request):
            if "google" in request.url.lower() or "track" in request.url.lower():
                return
            method = request.method
            url = request.url
            post_data = request.post_data
            headers = request.headers

            entry = {
                "method": method,
                "url": url,
                "post_data": post_data,
                "content_type": headers.get("content-type", ""),
                "x_location_url": headers.get("x-location-url", ""),
            }
            all_requests.append(entry)

            if method == "POST":
                print(f"  [REQ] {method} {url}")
                if post_data:
                    print(f"        Body: {post_data[:500]}")
                if headers.get("x-location-url"):
                    print(f"        X-Location-URL: {headers['x-location-url']}")

        async def on_response(response):
            url = response.url
            if "google" in url.lower() or "track" in url.lower():
                return
            ct = response.headers.get("content-type", "")
            if "json" in ct:
                try:
                    body = await response.json()
                    print(f"  [RES] {response.status} {url}")
                    print(f"        {json.dumps(body, indent=2)[:500]}")
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        # Navigate through the booking flow to the auth page
        print("Step 1: Load services page")
        await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        print("\nStep 2: Select 60 Mins Bodywork")
        btn = page.locator("button:has-text('60 Mins Bodywork')").first
        await btn.click()
        await asyncio.sleep(1)

        print("\nStep 3: Click Next")
        next_btns = await page.locator("button:has-text('Next')").all()
        for b in next_btns:
            if await b.is_visible():
                await b.click()
                break
        await asyncio.sleep(2)

        print("\nStep 4: Select Any specialist")
        for text in ["Any specialist", "Any Specialist"]:
            try:
                el = page.get_by_text(text, exact=True).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    break
            except Exception:
                continue
        await asyncio.sleep(1)

        print("\nStep 5: Click Next to Time page")
        next_btns = await page.locator("button:has-text('Next')").all()
        for b in next_btns:
            if await b.is_visible():
                await b.click()
                break
        await asyncio.sleep(4)

        print("\nStep 6: Click Mon 23")
        try:
            date_btn = page.locator("button:has-text('Mon23')").first
            await date_btn.click()
            await asyncio.sleep(2)
        except Exception:
            pass

        print("\nStep 7: Select 10:00 AM")
        try:
            slot = page.locator("text='10:00 AM'").first
            await slot.click()
            await asyncio.sleep(2)
        except Exception:
            pass

        print("\nStep 8: Now on auth page. Entering phone number...")
        # Clear the request log for this step
        all_requests.clear()

        # Enter the phone number
        phone_input = page.locator("input[name='phone']")
        await phone_input.fill(FAKE_PHONE)
        await asyncio.sleep(1)

        print("\nStep 9: CLICKING 'Get code' - watching network...")
        print("=" * 80)

        # Click "Get code"
        get_code_btn = page.locator("button:has-text('Get code')")
        await get_code_btn.click()
        await asyncio.sleep(5)

        # Also check for any dialog/error
        await page.screenshot(path="output/intercept_after_getcode.png")
        body_text = await page.inner_text("body")
        print(f"\nPage text after Get code:\n{body_text[:500]}")

        # Save all captured requests
        with open("output/intercept_requests.json", "w") as f:
            json.dump(all_requests, f, indent=2, default=str)
        print(f"\nSaved {len(all_requests)} requests to output/intercept_requests.json")

        # Print summary of POST requests
        print("\n" + "=" * 80)
        print("POST requests captured during 'Get code' click:")
        print("=" * 80)
        for req in all_requests:
            if req["method"] == "POST":
                print(f"\n  POST {req['url']}")
                if req["post_data"]:
                    print(f"  Body: {req['post_data'][:500]}")
                if req["x_location_url"]:
                    print(f"  X-Location-URL: {req['x_location_url']}")

        await browser.close()

    print("\n\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
