"""
Stage 1: URL Pre-Classification (no network required).
Classifies merchants based purely on URL patterns.
"""
from __future__ import annotations

from urllib.parse import urlparse

from config import (
    BOOKING_PLATFORM_DOMAINS,
    CAT_3P_IS_WEBSITE,
    CAT_NO_WEBSITE,
    CAT_SOCIAL_MEDIA,
    SOCIAL_MEDIA_DOMAINS,
)
from pipeline.loader import Merchant
from pipeline.state import StateStore


def run_stage1(merchants: list[Merchant], state: StateStore) -> dict:
    """
    Pre-classify merchants by URL pattern.
    Returns stats dict with counts.
    """
    stats = {"skipped": 0, "no_website": 0, "social_media": 0, "platform_url": 0, "to_fetch": 0}

    for merchant in merchants:
        url = merchant.website

        # Skip already classified
        if state.is_completed(url, stage=1):
            stats["skipped"] += 1
            continue

        # No website
        if not url:
            state.set_result(url or f"__no_url__{merchant.name}", {
                "merchant_name": merchant.name,
                "url": "",
                "category": CAT_NO_WEBSITE,
                "platform": "",
                "confidence": 1.0,
                "evidence": ["No website URL provided"],
                "booking_url": "",
                "stage_completed": 3,  # No further processing needed
                "needs_stage3": False,
            })
            stats["no_website"] += 1
            continue

        # Parse domain
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().lstrip("www.")
        except Exception:
            host = ""

        # Check social media
        is_social = False
        for social_domain in SOCIAL_MEDIA_DOMAINS:
            if host == social_domain or host.endswith("." + social_domain):
                state.set_result(url, {
                    "merchant_name": merchant.name,
                    "url": url,
                    "category": CAT_SOCIAL_MEDIA,
                    "platform": social_domain.split(".")[0].capitalize(),
                    "confidence": 0.99,
                    "evidence": [f"URL is on social media domain: {social_domain}"],
                    "booking_url": "",
                    "stage_completed": 3,
                    "needs_stage3": False,
                })
                stats["social_media"] += 1
                is_social = True
                break

        if is_social:
            continue

        # Check if URL IS a booking platform — pre-tag but still send to
        # Stage 2 for HTTP reachability validation (catches dead pages, 403s).
        is_platform = False
        for domain, platform in BOOKING_PLATFORM_DOMAINS.items():
            if host == domain or host.endswith("." + domain):
                state.set_result(url, {
                    "merchant_name": merchant.name,
                    "url": url,
                    "category": CAT_3P_IS_WEBSITE,
                    "platform": platform,
                    "confidence": 0.99,
                    "evidence": [f"URL domain is booking platform: {domain}"],
                    "booking_url": url,
                    "stage_completed": 1,  # Pass to Stage 2 for validation
                    "needs_stage3": False,
                    "platform_pretagged": True,  # Flag so Stage 2 knows this was pre-tagged
                })
                stats["platform_url"] += 1
                is_platform = True
                break

        if is_platform:
            continue

        # Not pre-classified — needs Stage 2
        state.set_result(url, {
            "merchant_name": merchant.name,
            "url": url,
            "category": "",
            "platform": "",
            "confidence": 0.0,
            "evidence": [],
            "booking_url": "",
            "stage_completed": 1,
            "needs_stage3": False,
        })
        stats["to_fetch"] += 1

    state.save()
    return stats
