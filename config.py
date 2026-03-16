"""
Configuration: platform signatures, social media domains, user agents, timeouts.
"""

# --- Classification categories ---
CAT_3P_IS_WEBSITE = "3p_booking_is_website"
CAT_3P_EMBEDDED = "3p_booking_embedded"
CAT_3P_EXTERNAL = "3p_booking_external"
CAT_INTERNAL = "internal_booking"
CAT_CALL_EMAIL = "call_email_only"
CAT_NO_BOOKING = "no_booking_found"
CAT_SOCIAL_MEDIA = "social_media_only"
CAT_UNREACHABLE = "website_unreachable"
CAT_BLOCKED = "crawl_blocked"
CAT_NO_WEBSITE = "no_website"

# --- Booking platform URL domains ---
# If the merchant's website URL itself is on one of these domains,
# classify as 3p_booking_is_website.
BOOKING_PLATFORM_DOMAINS = {
    "vagaro.com": "Vagaro",
    "square.site": "Square Appointments",
    "glossgenius.com": "GlossGenius",
    "massagebook.com": "MassageBook",
    "booksy.com": "Booksy",
    "schedulicity.com": "Schedulicity",
    "styleseat.com": "StyleSeat",
    "fresha.com": "Fresha",
    "zenoti.com": "Zenoti",
    "mindbodyonline.com": "Mindbody",
    "clients.mindbodyonline.com": "Mindbody",
    "acuityscheduling.com": "Acuity Scheduling",
    "app.squarespacescheduling.com": "Acuity Scheduling",
    "as.me": "Acuity Scheduling",
    "janeapp.com": "Jane App",
    "joinblvd.com": "Boulevard",
    "wellnessliving.com": "WellnessLiving",
    "simplybook.me": "SimplyBook.me",
    "setmore.com": "Setmore",
    "my.setmore.com": "Setmore",
    "gettimely.com": "Timely",
    "genbook.com": "Genbook",
    "phorest.com": "Phorest",
    "pocketsuite.io": "PocketSuite",
    "restore.com": "Restore Hyper Wellness",
    "salonlofts.com": "Salon Lofts",
    "book.squareup.com": "Square Appointments",
    "calendly.com": "Calendly",
    "bookwhen.com": "Bookwhen",
    "picktime.com": "Picktime",
    "mfrbeauty.com": "MFR Beauty",
    "go.bychronos.com": "byChronos",
    "bychronos.com": "byChronos",
    "booker.com": "Booker",
    "location.booker.com": "Booker",
}

# --- Social media domains ---
SOCIAL_MEDIA_DOMAINS = {
    "facebook.com",
    "m.facebook.com",
    "instagram.com",
    "yelp.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "spafinder.com",
    "pinterest.com",
    "youtube.com",
}

# --- Embedded widget signatures ---
# Used by detector.py to find booking widgets in page HTML.
# Each platform has: scripts (src patterns), iframes (src patterns),
# links (href patterns), html_patterns (regex in full HTML).
PLATFORM_SIGNATURES = {
    "Mindbody": {
        "scripts": [
            "healcode.com",
            "brandedweb.mindbodyonline.com",
            "widgets.mindbodyonline.com",
        ],
        "iframes": [
            "clients.mindbodyonline.com",
            "brandedweb.mindbodyonline.com",
        ],
        "links": [
            "clients.mindbodyonline.com",
            "mindbodyonline.com/classic/ws",
        ],
        "html_patterns": [
            r"healcode-widget",
            r"data-widget-id.*mindbody",
            r"mindbody-branded-web",
            r"healcode",
        ],
    },
    "Vagaro": {
        "scripts": [
            "vagaro.com/resources/WidgetEmbeddedLoader",
            "vagaro.com/resources/embed",
        ],
        "iframes": ["vagaro.com"],
        "links": ["vagaro.com/"],
        "html_patterns": [
            r"VagaroEmbedWidget",
            r"data-vagaro",
            r"vagaro\.com/Widget",
        ],
    },
    "Acuity Scheduling": {
        "scripts": [
            "acuityscheduling.com/embed",
            "squarecdn.com/appointments",
            "squarespacescheduling.com",
        ],
        "iframes": [
            "app.acuityscheduling.com",
            "app.squarespacescheduling.com",
        ],
        "links": [
            "app.acuityscheduling.com",
            "app.squarespacescheduling.com",
            "as.me/",
        ],
        "html_patterns": [
            r"acuity-embed",
            r"acuity-inline-widget",
            r"squarespacescheduling",
        ],
    },
    "Calendly": {
        "scripts": [
            "assets.calendly.com",
            "calendly.com/assets/inline/widget",
        ],
        "iframes": ["calendly.com/"],
        "links": ["calendly.com/"],
        "html_patterns": [
            r"calendly-inline-widget",
            r"data-url.*calendly\.com",
        ],
    },
    "Square Appointments": {
        "scripts": [
            "squareup.com/appointments",
            "square.site",
        ],
        "iframes": [
            "squareup.com/appointments",
            "square.site",
            "book.squareup.com",
        ],
        "links": [
            "squareup.com/appointments",
            "book.squareup.com",
        ],
        "html_patterns": [
            r"sq-appointment",
            r"square-appointments",
        ],
    },
    "Booksy": {
        "scripts": ["booksy.com/widget"],
        "iframes": ["booksy.com"],
        "links": ["booksy.com/"],
        "html_patterns": [r"booksy-widget", r"booksy\.com/en-us"],
    },
    "Zenoti": {
        "scripts": ["zenoti.com"],
        "iframes": ["zenoti.com/webstoreNew", "zenoti.com/webstore"],
        "links": ["zenoti.com/webstoreNew", "zenoti.com/webstore"],
        "html_patterns": [r"zenoti-webstore", r"zenoti\.com"],
    },
    "Jane App": {
        "scripts": ["janeapp.com"],
        "iframes": ["janeapp.com"],
        "links": ["janeapp.com/"],
        "html_patterns": [r"jane-widget", r"jane-iframe", r"janeapp\.com"],
    },
    "Boulevard": {
        "scripts": ["joinblvd.com"],
        "iframes": ["joinblvd.com"],
        "links": ["joinblvd.com/"],
        "html_patterns": [r"blvd-book-button", r"joinblvd\.com"],
    },
    "WellnessLiving": {
        "scripts": ["wellnessliving.com/rs/url-widget"],
        "iframes": ["wellnessliving.com"],
        "links": ["wellnessliving.com/rs/"],
        "html_patterns": [r"wl-widget", r"wellness-living-widget"],
    },
    "SimplyBook.me": {
        "scripts": ["simplybook.me/v2/widget"],
        "iframes": ["simplybook.me"],
        "links": ["simplybook.me/"],
        "html_patterns": [r"simplybook-widget"],
    },
    "Setmore": {
        "scripts": ["my.setmore.com"],
        "iframes": ["my.setmore.com"],
        "links": ["my.setmore.com/", "setmore.com/"],
        "html_patterns": [r"setmore-appointments"],
    },
    "Fresha": {
        "scripts": ["fresha.com"],
        "iframes": ["fresha.com"],
        "links": ["fresha.com/"],
        "html_patterns": [r"fresha-widget"],
    },
    "GlossGenius": {
        "scripts": [],
        "iframes": [],
        "links": ["glossgenius.com/"],
        "html_patterns": [],
    },
    "MassageBook": {
        "scripts": [],
        "iframes": [],
        "links": ["massagebook.com/"],
        "html_patterns": [],
    },
    "Wix Bookings": {
        "scripts": ["bookings.wixapps.net", "wix-bookings"],
        "iframes": ["bookings.wixapps.net"],
        "links": [],
        "html_patterns": [
            r"wix-bookings",
            r"bookings\.wixapps\.net",
            r"_api/bookings-viewer",
            r"wixBookingsWidget",
        ],
    },
    "Schedulicity": {
        "scripts": [],
        "iframes": ["schedulicity.com"],
        "links": ["schedulicity.com/"],
        "html_patterns": [r"schedulicity"],
    },
    "StyleSeat": {
        "scripts": [],
        "iframes": [],
        "links": ["styleseat.com/"],
        "html_patterns": [],
    },
    "PocketSuite": {
        "scripts": [],
        "iframes": [],
        "links": ["pocketsuite.io/"],
        "html_patterns": [r"pocketsuite"],
    },
    "Timely": {
        "scripts": ["gettimely.com"],
        "iframes": ["gettimely.com"],
        "links": ["gettimely.com/"],
        "html_patterns": [r"timely-book"],
    },
    "Genbook": {
        "scripts": ["genbook.com"],
        "iframes": ["genbook.com"],
        "links": ["genbook.com/"],
        "html_patterns": [r"genbook"],
    },
    "byChronos": {
        "scripts": ["bychronos.com"],
        "iframes": ["bychronos.com"],
        "links": ["go.bychronos.com/", "bychronos.com/"],
        "html_patterns": [r"bychronos"],
    },
    "Booker": {
        "scripts": ["booker.com"],
        "iframes": ["booker.com", "location.booker.com"],
        "links": ["booker.com/", "location.booker.com/"],
        "html_patterns": [r"booker\.com", r"booker-widget", r"BookerEmbed"],
    },
}

# --- Booking-related keywords for sub-page discovery ---
BOOKING_LINK_KEYWORDS = [
    "book",
    "appointment",
    "schedule",
    "reserve",
    "services",
    "pricing",
    "contact",
    "booking",
]

# --- Button/link text patterns for booking entry points (Stage 3) ---
BOOKING_BUTTON_TEXTS = [
    "book now",
    "book online",
    "book an appointment",
    "book appointment",
    "schedule now",
    "schedule appointment",
    "schedule an appointment",
    "reserve now",
    "reserve",
    "get started",
    "make an appointment",
    "make appointment",
    "book a session",
    "book session",
    "book here",
    "book today",
    "schedule online",
    "schedule a visit",
    "schedule consultation",
    "request appointment",
]

# --- Call/email indicators ---
CALL_EMAIL_PATTERNS = [
    r"call\s+(?:us\s+)?(?:to|for)\s+(?:book|schedule|appointment|reserve)",
    r"call\s+(?:us\s+)?(?:at|:)\s*[\(\d]",
    r"phone\s+(?:us\s+)?(?:to|for)\s+(?:book|schedule|appointment)",
    r"email\s+(?:us\s+)?(?:to|for)\s+(?:book|schedule|appointment)",
    r"(?:please\s+)?call\s+(?:to\s+)?(?:book|schedule|make)",
    r"appointments?\s+(?:by|via)\s+(?:phone|call|email)",
    r"book(?:ing)?\s+(?:by|via)\s+(?:phone|call|email)",
]

# --- Captcha/WAF detection patterns ---
CAPTCHA_PATTERNS = [
    "cf-browser-verification",
    "challenge-platform",
    "__cf_chl_rt_tk",
    "g-recaptcha",
    "recaptcha.net",
    "hcaptcha.com",
    "challenges.cloudflare.com",
]

WAF_PATTERNS = [
    "access denied",
    "request blocked",
    "security check",
    "sucuri",
    "wordfence",
    "please verify you are a human",
    "checking your browser",
    "please wait while we verify",
]

# --- HTTP settings ---
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
]

REQUEST_TIMEOUT = 15.0  # seconds
CONNECT_TIMEOUT = 10.0
MAX_REDIRECTS = 5
MAX_RETRIES = 2

# Concurrency
STAGE2_CONCURRENCY = 10  # concurrent HTTP requests
STAGE3_CONCURRENCY = 5  # concurrent Playwright pages
STAGE2_BATCH_SIZE = 50  # save state after this many merchants
MAX_SUBPAGES = 3  # max sub-pages to fetch per merchant

# Stage 3 timeouts
PAGE_LOAD_TIMEOUT = 20000  # ms
CLICK_WAIT_TIMEOUT = 10000  # ms
