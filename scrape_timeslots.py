"""
Timeslot scraper dispatcher.

Detects the booking platform from a URL and dispatches to the
appropriate platform-specific scraper. Returns standardized JSON.

If the URL is a merchant's own website (not a known booking platform),
it fetches the page, detects which booking platform is linked/embedded,
and follows the booking URL automatically.

Usage:
    python3 scrape_timeslots.py --url URL --service "Service Name"
    python3 scrape_timeslots.py --url URL --service "Service Name" --days 7 --detail
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from urllib.parse import urlparse

from config import BOOKING_PLATFORM_DOMAINS


def normalize_url(url: str) -> str:
    """Ensure URL has a scheme (https://) prefix."""
    url = url.strip()
    if not url:
        return url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def detect_platform(url: str) -> str | None:
    """
    Detect booking platform from URL using config.py domain mappings.

    Returns platform name string or None if unknown.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().lstrip("www.")
    except Exception:
        return None

    for domain, platform in BOOKING_PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return platform

    return None


async def resolve_booking_url(url: str) -> tuple[str, str | None]:
    """
    If the URL is a merchant's website (not a known platform), visit it
    and detect the booking platform + booking URL from the page HTML.

    Returns (booking_url, platform_name) — may return the original URL
    unchanged if no booking platform is found.
    """
    from pipeline.detector import detect_from_html
    import httpx
    from config import USER_AGENTS

    print(f"Resolving booking URL from merchant site: {url}")
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": USER_AGENTS[0]},
        ) as client:
            resp = await client.get(url)
            html = resp.text

            # Check if we were redirected to a known platform
            final_url = str(resp.url)
            platform = detect_platform(final_url)
            if platform:
                print(f"Redirected to {platform}: {final_url}")
                return final_url, platform

            # Analyze page HTML for embedded/linked booking platforms
            result = detect_from_html(html, final_url)

            # If detector found a booking URL, use it
            if result.platform and result.booking_url:
                booking_url = result.booking_url
                if booking_url.startswith("/"):
                    parsed = urlparse(final_url)
                    booking_url = f"{parsed.scheme}://{parsed.netloc}{booking_url}"
                print(f"Found {result.platform} booking link: {booking_url}")
                return booking_url, result.platform

            # Detector found the platform but not the URL (e.g. HTML pattern
            # match). Scan all links in the page for known platform domains.
            if result.platform or not result.booking_url:
                import re
                links = re.findall(r'href=["\']([^"\'> ]+)["\']', html)
                for link in links:
                    link_platform = detect_platform(link)
                    if link_platform:
                        print(f"Found {link_platform} booking link: {link}")
                        return link, link_platform

            if result.platform:
                print(f"Detected {result.platform} on page but no direct booking URL found")
                return url, result.platform

    except Exception as e:
        print(f"Could not resolve booking URL: {e}")

    return url, None


async def fetch_services(url: str) -> dict:
    """
    Detect platform and fetch the list of available services.

    Returns dict with: platform, booking_url, services (list of dicts).
    """
    from scrapers import get_scraper

    url = normalize_url(url)
    platform = detect_platform(url)

    # If URL is not a known platform, try to resolve the booking URL
    if not platform:
        url, platform = await resolve_booking_url(url)

    if platform:
        print(f"Detected platform: {platform}")
    else:
        print(f"Unknown platform for {url} -- using generic scraper")

    scraper = get_scraper(platform or "")
    services = await scraper.list_services(url)

    return {
        "platform": platform or "Unknown",
        "booking_url": url,
        "services": services,
    }


async def scrape_timeslots(url: str, service_name: str, days: int = 30) -> dict:
    """
    Main entry point: detect platform and scrape timeslots.

    If the URL is a merchant website, resolves the actual booking URL first.

    Args:
        url: The booking page URL or merchant website.
        service_name: Service to check availability for.
        days: Number of days to look ahead.

    Returns:
        Standardized availability JSON dict.
    """
    from scrapers import get_scraper

    url = normalize_url(url)
    platform = detect_platform(url)

    # If URL is not a known platform, try to resolve the booking URL
    if not platform:
        url, platform = await resolve_booking_url(url)

    if platform:
        print(f"Detected platform: {platform}")
    else:
        print(f"Unknown platform for {url} -- using generic scraper")

    scraper = get_scraper(platform or "")

    return await scraper.scrape(url, service_name, days)


def print_summary(result: dict):
    """Print a detailed human-readable summary with individual timeslots."""
    print(f"\n{'='*60}")
    print(f"  {result['merchant']} - Available Timeslots")
    print(f"  Platform: {result['platform']}")
    print(f"  Service: {result['service']['name']}")
    if result['service']['price_display']:
        print(f"  Price: {result['service']['price_display']}")
    print(f"  Date range: {result['date_range']['from']} to {result['date_range']['to']}")
    print(f"{'='*60}")

    def _slot_hour_24(s):
        h = int(s.split(":")[0])
        is_pm = "PM" in s
        if is_pm and h != 12:
            h += 12
        elif not is_pm and h == 12:
            h = 0
        return h

    for day in result["availability"]:
        date_str = day["date"]
        day_name = day["day_of_week"]
        slots = day["timeslots"]
        closed = day.get("closed")

        if closed:
            print(f"\n  {day_name} {date_str}: CLOSED")
        elif not slots:
            note = day.get("note", "No slots available")
            print(f"\n  {day_name} {date_str}: {note}")
        else:
            print(f"\n  {day_name} {date_str}: {len(slots)} slots available")
            morning = [s for s in slots if _slot_hour_24(s) < 12]
            afternoon = [s for s in slots if 12 <= _slot_hour_24(s) < 18]
            evening = [s for s in slots if _slot_hour_24(s) >= 18]

            if morning:
                print(f"    Morning:   {', '.join(morning)}")
            if afternoon:
                print(f"    Afternoon: {', '.join(afternoon)}")
            if evening:
                print(f"    Evening:   {', '.join(evening)}")

    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Scrape booking timeslots from any platform")
    parser.add_argument("--url", required=True,
                        help="Booking page URL or merchant website")
    parser.add_argument("--service", required=True,
                        help="Service name to check availability for")
    parser.add_argument("--days", type=int, default=30,
                        help="Number of days to look ahead (default: 30)")
    parser.add_argument("--detail", action="store_true",
                        help="Show detailed per-slot breakdown")
    args = parser.parse_args()

    result = asyncio.run(scrape_timeslots(args.url, args.service, args.days))

    # Save JSON
    os.makedirs("output", exist_ok=True)
    output_path = "output/timeslots_result.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nJSON saved to {output_path}")

    if args.detail:
        print_summary(result)


if __name__ == "__main__":
    main()
