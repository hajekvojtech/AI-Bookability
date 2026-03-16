"""
Deep scan of byChronos JS bundle to find all API endpoints and auth flow.
"""
import asyncio
import re
import json
from config import USER_AGENTS

BOOKING_URL = "https://go.bychronos.com/l/worcester-01609-apple-foot-spa-805679/a/services"


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENTS[0])
        page = await context.new_page()

        await page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Fetch the main JS bundle
        content = await page.evaluate("""
            async () => {
                const resp = await fetch('https://go.bychronos.com/build/assets/app-CEP4XmiT.js');
                return await resp.text();
            }
        """)

        print(f"JS bundle size: {len(content)} chars")

        # Find ALL /api/ patterns
        api_patterns = re.findall(r'["`\'](/api/[a-zA-Z0-9/_${}-]+)["`\']', content)
        unique_apis = sorted(set(api_patterns))
        print(f"\n{'='*80}")
        print(f"All API endpoints ({len(unique_apis)}):")
        print(f"{'='*80}")
        for api in unique_apis:
            print(f"  {api}")

        # Find fetch/axios call patterns near auth/phone/otp keywords
        print(f"\n{'='*80}")
        print("Code snippets around phone/auth/otp/verify/appointment:")
        print(f"{'='*80}")

        search_terms = [
            'send-code', 'send_code', 'sendCode',
            'verify-code', 'verify_code', 'verifyCode',
            'otp', 'sms',
            'login-phone', 'loginPhone', 'login_phone',
            'appointment', 'booking', 'reservation',
            'checkout', 'confirm-book',
            '.post(', '.put(', '.patch(',
            'useMutation',
        ]

        for term in search_terms:
            indices = [m.start() for m in re.finditer(re.escape(term), content)]
            if indices:
                print(f"\n  --- '{term}' found {len(indices)} times ---")
                for idx in indices[:3]:  # Show first 3 occurrences
                    start = max(0, idx - 100)
                    end = min(len(content), idx + 200)
                    snippet = content[start:end]
                    # Clean up for readability
                    snippet = snippet.replace('\n', ' ').replace('\r', '')
                    print(f"    ...{snippet}...")

        # Also search for mutation hooks that might handle booking
        print(f"\n{'='*80}")
        print("React Query mutations (POST/PUT/PATCH calls):")
        print(f"{'='*80}")

        # Find useMutation patterns
        mutation_pattern = r'useMutation\s*\(\s*(?:async\s*)?\(?\s*(?:[a-zA-Z_$]+)\s*\)?\s*=>\s*[^,]+\.(?:post|put|patch|delete)\s*\(\s*["`\']([^"`\']+)["`\']'
        mutations = re.findall(mutation_pattern, content)
        if mutations:
            for m in sorted(set(mutations)):
                print(f"  Mutation endpoint: {m}")

        # Broader search: any .post( call
        post_calls = re.findall(r'\.post\s*\(\s*["`\']([^"`\']+)["`\']', content)
        print(f"\n  All .post() endpoints ({len(set(post_calls))}):")
        for ep in sorted(set(post_calls)):
            print(f"    POST {ep}")

        put_calls = re.findall(r'\.put\s*\(\s*["`\']([^"`\']+)["`\']', content)
        print(f"\n  All .put() endpoints ({len(set(put_calls))}):")
        for ep in sorted(set(put_calls)):
            print(f"    PUT {ep}")

        patch_calls = re.findall(r'\.patch\s*\(\s*["`\']([^"`\']+)["`\']', content)
        print(f"\n  All .patch() endpoints ({len(set(patch_calls))}):")
        for ep in sorted(set(patch_calls)):
            print(f"    PATCH {ep}")

        delete_calls = re.findall(r'\.delete\s*\(\s*["`\']([^"`\']+)["`\']', content)
        print(f"\n  All .delete() endpoints ({len(set(delete_calls))}):")
        for ep in sorted(set(delete_calls)):
            print(f"    DELETE {ep}")

        get_calls = re.findall(r'\.get\s*\(\s*["`\'](/api/[^"`\']+)["`\']', content)
        print(f"\n  All .get(/api/...) endpoints ({len(set(get_calls))}):")
        for ep in sorted(set(get_calls)):
            print(f"    GET {ep}")

        await browser.close()

    print("\n\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
