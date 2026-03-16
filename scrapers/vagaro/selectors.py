"""
Vagaro UI selectors and patterns. Last verified: 2026-03-15

When Vagaro changes their UI, update ONLY this file.
Run `pytest scrapers/vagaro/tests/test_api_parsing.py` to verify.
"""

# --- URL ---
BOOKING_PATH_SUFFIX = "/book-now"

# --- Service selection (select2 dropdown) ---
SERVICE_DROPDOWN_CONTAINER = ".service-book-what .select2-container"
SERVICE_SEARCH_RESULTS = ".select2-results li"

# --- Navigation buttons ---
CONTINUE_BUTTON_ID = "btnContinue"
SEARCH_BUTTON_ID = "ancSearchbook"

# --- Date slider ---
DATE_BLOCK_QUERY = '#date-slider-container #dayBlock'
DATE_BLOCK_ATTR = "data-availdate"

# --- JavaScript functions ---
JS_SET_SELECTED_DATE = "SetSelectedDate"

# --- Cookie consent ---
COOKIE_DISMISS_SELECTORS = [
    # Osano
    ".osano-cm-accept",
    ".osano-cm-accept-all",
    "button.osano-cm-close",
    ".osano-cm-dialog__close",
    # OneTrust
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept All')",
    "button:has-text('Accept')",
]
COOKIE_OVERLAY_HIDE_JS = (
    'document.querySelectorAll(".osano-cm-window, .osano-cm-dialog, #onetrust-banner-sdk")'
    '.forEach(function(el) { el.style.display = "none"; })'
)

# --- API interception patterns ---
AVAILABILITY_API_PATTERN = "getavailablemultiappointments"
SERVICE_LIST_API_PATTERN = "getonlinebookingtabdetail"
