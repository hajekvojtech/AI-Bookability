# Vagaro Connector Specification

## Platform: Vagaro (vagaro.com)
## Last verified: 2026-03-15
## Status: Working

## Architecture
- **Navigation**: Playwright browser automation of booking widget
- **Data extraction**: API response interception (not DOM scraping)
- **Key APIs**:
  - `getonlinebookingtabdetail` - service list with prices/durations
  - `getavailablemultiappointments` - availability timeslots per date

## Booking Flow (7 steps)
1. Navigate to `{merchant_url}/book-now`
2. Dismiss cookie consent (Osano or OneTrust vendor)
3. Select service from select2 dropdown
4. Click Continue (skip add-ons panel)
5. Click Search to trigger availability API call
6. Iterate date blocks in date slider, call `SetSelectedDate(block)` for each
7. Collect intercepted API responses and parse timeslots

## File Layout
```
scrapers/vagaro/
    __init__.py         # Exports VagaroScraper
    scraper.py          # Orchestrator: Playwright flow + calls api_schema parsers
    selectors.py        # ALL volatile CSS selectors, JS snippets, URL patterns
    api_schema.py       # API field name constants + parsing functions
    CONNECTOR_SPEC.md   # This file
    fixtures/           # Captured API responses for testing
    tests/              # Unit tests against fixtures
```

## Volatile Elements (likely to break on platform updates)

| Element | File | Constant | Current Value |
|---------|------|----------|---------------|
| Booking page path | selectors.py | `BOOKING_PATH_SUFFIX` | `/book-now` |
| Service dropdown | selectors.py | `SERVICE_DROPDOWN_CONTAINER` | `.service-book-what .select2-container` |
| Search results | selectors.py | `SERVICE_SEARCH_RESULTS` | `.select2-results li` |
| Continue button | selectors.py | `CONTINUE_BUTTON_ID` | `btnContinue` |
| Search button | selectors.py | `SEARCH_BUTTON_ID` | `ancSearchbook` |
| Date blocks | selectors.py | `DATE_BLOCK_QUERY` | `#date-slider-container #dayBlock` |
| Date attribute | selectors.py | `DATE_BLOCK_ATTR` | `data-availdate` |
| JS date setter | selectors.py | `JS_SET_SELECTED_DATE` | `SetSelectedDate` |
| Availability API | selectors.py | `AVAILABILITY_API_PATTERN` | `getavailablemultiappointments` |
| Service list API | selectors.py | `SERVICE_LIST_API_PATTERN` | `getonlinebookingtabdetail` |
| Availability list | api_schema.py | `AVAILABILITY_LIST_KEY` | `d` |
| Date field | api_schema.py | `APP_DATE_KEY` | `AppDate` |
| Time field | api_schema.py | `AVAILABLE_TIME_KEY` | `AvailableTime` |
| Provider data | api_schema.py | `PROVIDER_DATA_KEY` | `ServicepPoviderData` (Vagaro's typo) |
| Service name | api_schema.py | `PROVIDER_SERVICE_NAME_KEY` | `ServiceName` |
| Price field | api_schema.py | `PROVIDER_PRICE_KEY` | `SerivcePrice` (Vagaro's typo) |
| Date format (API) | api_schema.py | `APP_DATE_FORMAT` | `%d %b %Y` ("16 Mar 2026") |
| Date format (DOM) | api_schema.py | `AVAIL_DATE_FORMAT` | `%b %d,%Y` ("Mar 16,2026") |

## Common Failure Modes

1. **Selector not found** - Vagaro redesigned UI. Update the selector in `selectors.py`.
2. **API response empty** - API endpoint name changed. Update `AVAILABILITY_API_PATTERN` in `selectors.py`.
3. **Dates parse incorrectly** - Date format changed. Update `APP_DATE_FORMAT` / `AVAIL_DATE_FORMAT` in `api_schema.py`.
4. **Cookie overlay blocks clicks** - New consent vendor added. Add selectors to `COOKIE_DISMISS_SELECTORS` in `selectors.py`.
5. **No timeslots returned** - Could be legitimate (merchant has no availability) or service selection failed silently. Check if `_select_service` completed.
6. **JSON field names changed** - Update the corresponding `*_KEY` constants in `api_schema.py`, then run unit tests against fixtures.

## Test Commands
```bash
# Unit: parse fixtures (no network needed)
pytest scrapers/vagaro/tests/test_api_parsing.py -v

# Integration: full scrape of known merchant (needs network + Playwright)
python3 scrape_timeslots.py --url https://www.vagaro.com/certifiedglamour --service "Women's Haircut" --days 3 --detail
```

## API Response Examples

### getavailablemultiappointments
```json
{
  "d": [
    {
      "AppDate": "16 Mar 2026",
      "AvailableTime": "10:00 AM, 10:30 AM, 11:00 AM",
      "ServicepPoviderData": [
        {
          "ServiceID": 26744247,
          "ServiceName": "Women's Haircut",
          "Duration": 60,
          "SerivcePrice": 75.0
        }
      ]
    }
  ]
}
```

### getonlinebookingtabdetail
```json
{
  "lstOnlineServiceDetail": [
    {"serviceID": 100, "serviceTitle": "Hair Services", "serviceLevel": 0, "parentServiceID": 0},
    {"serviceID": 26744247, "serviceTitle": "Women's Haircut", "serviceLevel": 1, "parentServiceID": 100, "price": 75.0, "duration": 60}
  ]
}
```
