"""
Scraper registry: maps platform names to scraper classes.
"""
from __future__ import annotations

from scrapers.base import BaseScraper
from scrapers.bychronos import ByChronosScraper
from scrapers.vagaro import VagaroScraper
from scrapers.generic import GenericScraper

# Registry: platform name (lowercase, no spaces) -> scraper instance
SCRAPER_REGISTRY: dict[str, BaseScraper] = {
    "bychronos": ByChronosScraper(),
    "vagaro": VagaroScraper(),
}

# Fallback for unknown platforms
GENERIC_SCRAPER = GenericScraper()


def get_scraper(platform_name: str) -> BaseScraper:
    """
    Get the appropriate scraper for a platform.
    Falls back to GenericScraper if no specific scraper exists.
    """
    key = platform_name.lower().replace(" ", "")
    return SCRAPER_REGISTRY.get(key, GENERIC_SCRAPER)
