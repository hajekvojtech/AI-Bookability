"""
Booking platform detection rules engine.
Analyzes HTML content to identify booking platforms and mechanisms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from config import (
    BOOKING_BUTTON_TEXTS,
    BOOKING_LINK_KEYWORDS,
    BOOKING_PLATFORM_DOMAINS,
    CALL_EMAIL_PATTERNS,
    CAT_3P_EMBEDDED,
    CAT_3P_EXTERNAL,
    CAT_3P_IS_WEBSITE,
    CAT_CALL_EMAIL,
    CAT_INTERNAL,
    CAT_NO_BOOKING,
    PLATFORM_SIGNATURES,
)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


@dataclass
class DetectionResult:
    category: str
    platform: str = ""
    confidence: float = 0.0
    evidence: list = field(default_factory=list)
    booking_url: str = ""
    booking_button_selector: str = ""  # CSS selector for Stage 3 to click
    booking_subpage_urls: list = field(default_factory=list)  # discovered sub-pages
    needs_stage3: bool = False


def check_url_is_platform(url: str) -> DetectionResult | None:
    """Check if the URL itself is on a known booking platform domain."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        host = host.lower().lstrip("www.")
    except Exception:
        return None

    for domain, platform in BOOKING_PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return DetectionResult(
                category=CAT_3P_IS_WEBSITE,
                platform=platform,
                confidence=0.99,
                evidence=[f"URL domain is {domain}"],
                booking_url=url,
            )
    return None


def detect_from_html(html: str, page_url: str) -> DetectionResult:
    """
    Run detection rules against HTML content.
    Returns the best matching DetectionResult.
    """
    if not BeautifulSoup:
        return DetectionResult(
            category=CAT_NO_BOOKING,
            evidence=["BeautifulSoup not installed"],
        )

    soup = BeautifulSoup(html, "lxml")
    html_lower = html.lower()

    # Collect all src/href attributes
    script_srcs = [
        tag.get("src", "") for tag in soup.find_all("script", src=True)
    ]
    iframe_srcs = [
        tag.get("src", "") for tag in soup.find_all("iframe", src=True)
    ]
    all_links = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        text = tag.get_text(strip=True).lower()
        all_links.append((href, text))

    # --- Priority 1: Check redirected URL against known platforms ---
    platform_result = check_url_is_platform(page_url)
    if platform_result:
        return platform_result

    # --- Priority 2: Embedded widgets (scripts/iframes) ---
    for platform, sigs in PLATFORM_SIGNATURES.items():
        # Check script sources
        for script_sig in sigs.get("scripts", []):
            for src in script_srcs:
                if script_sig.lower() in src.lower():
                    return DetectionResult(
                        category=CAT_3P_EMBEDDED,
                        platform=platform,
                        confidence=0.95,
                        evidence=[f"Script src contains '{script_sig}': {src}"],
                    )

        # Check iframe sources
        for iframe_sig in sigs.get("iframes", []):
            for src in iframe_srcs:
                if iframe_sig.lower() in src.lower():
                    return DetectionResult(
                        category=CAT_3P_EMBEDDED,
                        platform=platform,
                        confidence=0.95,
                        evidence=[f"Iframe src contains '{iframe_sig}': {src}"],
                    )

        # Check HTML patterns (regex)
        for pattern in sigs.get("html_patterns", []):
            if re.search(pattern, html_lower):
                return DetectionResult(
                    category=CAT_3P_EMBEDDED,
                    platform=platform,
                    confidence=0.80,
                    evidence=[f"HTML pattern match: {pattern}"],
                )

    # --- Priority 3: External booking links ---
    for platform, sigs in PLATFORM_SIGNATURES.items():
        for link_sig in sigs.get("links", []):
            for href, text in all_links:
                if link_sig.lower() in href.lower():
                    is_booking_text = any(
                        kw in text for kw in ["book", "schedule", "appointment", "reserve"]
                    )
                    return DetectionResult(
                        category=CAT_3P_EXTERNAL,
                        platform=platform,
                        confidence=0.85 if is_booking_text else 0.65,
                        evidence=[f"Link to {href} (text: '{text}')"],
                        booking_url=href,
                    )

    # --- Priority 4: Generic booking form detection ---
    booking_form = _detect_booking_form(soup, html_lower)
    if booking_form:
        return booking_form

    # --- Priority 5: Call/email only ---
    call_email = _detect_call_email(html_lower, soup)
    if call_email:
        return call_email

    # --- Priority 6: Booking button text present but no platform detected ---
    booking_buttons = find_booking_buttons(soup)
    if booking_buttons:
        selector, text = booking_buttons[0]
        return DetectionResult(
            category=CAT_NO_BOOKING,
            confidence=0.3,
            evidence=[f"Booking button found: '{text}'"],
            booking_button_selector=selector,
            needs_stage3=True,  # Need Playwright to click and see what happens
        )

    return DetectionResult(
        category=CAT_NO_BOOKING,
        confidence=0.5,
        evidence=["No booking indicators found"],
    )


def _detect_booking_form(soup, html_lower: str) -> DetectionResult | None:
    """Detect custom/internal booking forms."""
    forms = soup.find_all("form")
    for form in forms:
        form_html = str(form).lower()
        has_date = bool(
            form.find("input", {"type": "date"})
            or "datepicker" in form_html
            or "date-picker" in form_html
            or "calendar" in form_html
        )
        has_time = bool(
            form.find("input", {"type": "time"})
            or "timepicker" in form_html
            or "time-picker" in form_html
            or "time-slot" in form_html
        )
        has_service = bool(
            re.search(r"service|treatment|session|class", form_html)
        )
        has_submit = bool(
            re.search(r"book|schedule|reserve|appointment", form_html)
        )

        if (has_date or has_time) and has_submit:
            return DetectionResult(
                category=CAT_INTERNAL,
                confidence=0.75,
                evidence=[
                    f"Booking form detected (date={has_date}, time={has_time}, "
                    f"service={has_service}, submit={has_submit})"
                ],
            )

    # Check for booking-related input fields outside forms
    if re.search(
        r'(type=["\']date["\']|datepicker|date-picker).*'
        r'(book|schedule|reserve|appointment)',
        html_lower,
    ):
        return DetectionResult(
            category=CAT_INTERNAL,
            confidence=0.60,
            evidence=["Date input and booking keywords found in page"],
            needs_stage3=True,
        )

    return None


def _detect_call_email(html_lower: str, soup) -> DetectionResult | None:
    """Detect call/email-only booking patterns.
    Low confidence — nearly every salon site has 'call us' text
    alongside online booking widgets. Always escalate to Stage 3.
    """
    for pattern in CALL_EMAIL_PATTERNS:
        match = re.search(pattern, html_lower)
        if match:
            return DetectionResult(
                category=CAT_CALL_EMAIL,
                confidence=0.40,
                evidence=[f"Call/email pattern: '{match.group()}'"],
                needs_stage3=True,
            )
    return None


def find_booking_buttons(soup) -> list[tuple[str, str]]:
    """
    Find clickable elements that look like booking buttons.
    Returns list of (CSS selector, text) tuples.
    """
    results = []
    # Check buttons and links
    for tag in soup.find_all(["a", "button"]):
        text = tag.get_text(strip=True).lower()
        if any(bt in text for bt in BOOKING_BUTTON_TEXTS):
            # Build a CSS selector
            selector = _build_selector(tag)
            results.append((selector, text))

    # Check elements with role="button"
    for tag in soup.find_all(attrs={"role": "button"}):
        text = tag.get_text(strip=True).lower()
        if any(bt in text for bt in BOOKING_BUTTON_TEXTS):
            selector = _build_selector(tag)
            results.append((selector, text))

    return results


def find_booking_links(soup, base_url: str) -> list[str]:
    """
    Find sub-page URLs that are likely booking/appointment pages.
    Returns list of URLs to fetch.
    """
    try:
        base_parsed = urlparse(base_url)
        base_domain = base_parsed.hostname or ""
    except Exception:
        return []

    booking_urls = []
    seen = set()

    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        text = tag.get_text(strip=True).lower()

        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        # Check if link text or URL contains booking keywords
        is_booking = any(kw in text for kw in BOOKING_LINK_KEYWORDS) or any(
            kw in href.lower() for kw in BOOKING_LINK_KEYWORDS
        )

        if not is_booking:
            continue

        # Resolve relative URLs
        if href.startswith("/"):
            href = f"{base_parsed.scheme}://{base_parsed.hostname}{href}"
        elif not href.startswith("http"):
            href = f"{base_url.rstrip('/')}/{href}"

        # Only follow links to the same domain
        try:
            link_parsed = urlparse(href)
            link_domain = link_parsed.hostname or ""
        except Exception:
            continue

        if link_domain != base_domain:
            # External booking link — don't follow but note it
            continue

        if href not in seen:
            seen.add(href)
            booking_urls.append(href)

    return booking_urls


def _build_selector(tag) -> str:
    """Build a CSS selector for a BeautifulSoup tag."""
    tag_name = tag.name
    tag_id = tag.get("id", "")
    tag_class = tag.get("class", [])

    if tag_id:
        return f"#{tag_id}"
    if tag_class:
        classes = ".".join(tag_class)
        return f"{tag_name}.{classes}"

    # Fall back to text content selector
    text = tag.get_text(strip=True)
    if text:
        # Playwright-style text selector
        return f"text={text}"

    return tag_name
