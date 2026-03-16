"""
Vagaro API response schema mappings. Last verified: 2026-03-15

Maps Vagaro's API field names to our internal representation.
When Vagaro changes their API response shape, update this file.
Run `pytest scrapers/vagaro/tests/test_api_parsing.py` to verify.
"""
from __future__ import annotations

from datetime import datetime, date

# --- getonlinebookingtabdetail response (service list) ---
SERVICE_LIST_KEY = "lstOnlineServiceDetail"
SERVICE_LEVEL_KEY = "serviceLevel"
SERVICE_TITLE_KEY = "serviceTitle"
SERVICE_ID_KEY = "serviceID"
SERVICE_PARENT_ID_KEY = "parentServiceID"
SERVICE_PRICE_KEY = "price"
SERVICE_DURATION_KEY = "duration"

# --- getavailablemultiappointments response (availability) ---
AVAILABILITY_LIST_KEY = "d"
APP_DATE_KEY = "AppDate"
AVAILABLE_TIME_KEY = "AvailableTime"
PROVIDER_DATA_KEY = "ServicepPoviderData"  # Note: Vagaro's typo "pP"
PROVIDER_SERVICE_NAME_KEY = "ServiceName"
PROVIDER_SERVICE_ID_KEY = "ServiceID"
PROVIDER_DURATION_KEY = "Duration"
PROVIDER_PRICE_KEY = "SerivcePrice"  # Note: Vagaro's typo "Serivce"

# --- Date formats ---
APP_DATE_FORMAT = "%d %b %Y"    # API response: "16 Mar 2026"
AVAIL_DATE_FORMAT = "%b %d,%Y"  # DOM data-availdate: "Mar 16,2026"
TIME_SEPARATOR = ","


def parse_service_list(response: dict) -> list[dict]:
    """Parse a getonlinebookingtabdetail response into service dicts.

    Returns list of {"name", "category", "duration_display", "price_display"}.
    """
    svc_list = response.get(SERVICE_LIST_KEY, [])

    # Build category map from level-0 entries
    category_map = {}
    for svc in svc_list:
        if svc.get(SERVICE_LEVEL_KEY, 0) == 0:
            category_map[svc.get(SERVICE_ID_KEY)] = svc.get(SERVICE_TITLE_KEY, "")

    services = []
    for svc in svc_list:
        if svc.get(SERVICE_LEVEL_KEY, 0) == 0:
            continue

        name = svc.get(SERVICE_TITLE_KEY, "").strip()
        if not name:
            continue

        price = svc.get(SERVICE_PRICE_KEY, 0)
        duration = svc.get(SERVICE_DURATION_KEY, 0)
        parent_id = svc.get(SERVICE_PARENT_ID_KEY)
        category = category_map.get(parent_id, None)

        services.append({
            "name": name,
            "category": category,
            "duration_display": f"{duration} min" if duration > 0 else None,
            "price_display": f"${price:.0f}" if price > 0 else None,
        })

    return services


def parse_availability_response(
    response: dict, time_str_to_seconds, fallback_date: str | None = None
) -> dict[str, dict]:
    """Parse a getavailablemultiappointments response into date_slots.

    Args:
        response: Raw API response dict.
        time_str_to_seconds: Callable to convert "h:MM AM/PM" -> seconds from midnight.
        fallback_date: ISO date string to use if the API's AppDate
                       doesn't match the date we clicked (timezone shift).

    Returns:
        Dict of date_str -> {"closed": bool, "time_slots": [int]}.
    """
    date_slots = {}
    d_list = response.get(AVAILABILITY_LIST_KEY, [])

    for item in d_list:
        app_date_str = item.get(APP_DATE_KEY, "")
        if not app_date_str:
            continue

        parsed_date = parse_app_date(app_date_str)
        if not parsed_date:
            continue

        date_str = parsed_date.isoformat()
        available_time = item.get(AVAILABLE_TIME_KEY, "")

        if available_time:
            time_parts = [t.strip() for t in available_time.split(TIME_SEPARATOR) if t.strip()]
            slots_seconds = []
            for t in time_parts:
                try:
                    seconds = time_str_to_seconds(t)
                    if seconds not in slots_seconds:
                        slots_seconds.append(seconds)
                except Exception:
                    continue
            slots_seconds.sort()
            slot_entry = {"closed": False, "time_slots": slots_seconds}
        else:
            slot_entry = {"closed": False, "time_slots": []}

        date_slots[date_str] = slot_entry

        # Also store under the fallback date if it differs from API date
        # (handles timezone offset between server and business timezone)
        if fallback_date and fallback_date != date_str and fallback_date not in date_slots:
            date_slots[fallback_date] = slot_entry

    return date_slots


def extract_service_info(response: dict, service_name: str) -> dict | None:
    """Extract service info (id, duration, price) from an availability response."""
    d_list = response.get(AVAILABILITY_LIST_KEY, [])
    for item in d_list:
        for provider in item.get(PROVIDER_DATA_KEY, []):
            svc_name = provider.get(PROVIDER_SERVICE_NAME_KEY, "")
            if service_name.lower() in svc_name.lower():
                return {
                    "id": provider.get(PROVIDER_SERVICE_ID_KEY),
                    "duration": provider.get(PROVIDER_DURATION_KEY),
                    "price": int(provider.get(PROVIDER_PRICE_KEY, 0) * 100),
                }
    return None


def parse_app_date(date_str: str) -> date | None:
    """Parse Vagaro's 'DD Mon YYYY' format (e.g., '16 Mar 2026')."""
    try:
        return datetime.strptime(date_str.strip(), APP_DATE_FORMAT).date()
    except ValueError:
        return None


def parse_avail_date(date_str: str) -> date | None:
    """Parse Vagaro's data-availdate format (e.g., 'Mar 16,2026')."""
    try:
        return datetime.strptime(date_str.strip(), AVAIL_DATE_FORMAT).date()
    except ValueError:
        return None
