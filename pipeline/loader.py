"""
CSV loading, URL normalization, and merchant deduplication.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class Merchant:
    name: str
    website: str  # normalized URL
    raw_website: str  # original from CSV
    orders_30d: float = 0.0
    m1_vfm_30d: float = 0.0
    deal_count: int = 0
    deal_permalinks: list = field(default_factory=list)


def normalize_url(url: str) -> str:
    """Normalize a URL: add scheme, strip trailing whitespace, fix common issues."""
    url = url.strip()
    if not url or url.lower() == "unknown":
        return ""

    # Fix double-scheme issues like "https://https://..."
    url = re.sub(r"^(https?://)+(https?://)", r"\2", url)

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Fix "https:/" (missing second slash)
    url = re.sub(r"^(https?:)/([^/])", r"\1//\2", url)

    # Remove trailing slashes for consistency in dedup (but keep path slashes)
    parsed = urlparse(url)
    # Only strip trailing slash if path is just "/"
    if parsed.path == "/":
        url = url.rstrip("/")

    return url


def load_merchants(csv_path: str) -> list[Merchant]:
    """
    Load merchants from CSV, normalize URLs, and deduplicate by website.
    Multiple deals for the same merchant are merged: orders and VFM are summed,
    deal_permalinks are collected.
    """
    merchants_by_url = {}
    no_website = []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_url = row.get("website", "").strip()
            url = normalize_url(raw_url)
            name = row.get("merchant_name", "").strip()
            permalink = row.get("deal_permalink", "")

            try:
                orders = float(row.get("orders_30d", 0) or 0)
            except (ValueError, TypeError):
                orders = 0.0
            try:
                vfm = float(row.get("m1_vfm_30d", 0) or 0)
            except (ValueError, TypeError):
                vfm = 0.0
            try:
                deal_count_col = int(row.get("deal_count", 0) or 0)
            except (ValueError, TypeError):
                deal_count_col = 0

            if not url:
                no_website.append(
                    Merchant(
                        name=name,
                        website="",
                        raw_website=raw_url,
                        orders_30d=orders,
                        m1_vfm_30d=vfm,
                        deal_count=deal_count_col or 1,
                        deal_permalinks=[permalink] if permalink else [],
                    )
                )
                continue

            if url in merchants_by_url:
                m = merchants_by_url[url]
                m.orders_30d += orders
                m.m1_vfm_30d += vfm
                m.deal_count += deal_count_col or 1
                if permalink:
                    m.deal_permalinks.append(permalink)
                # Keep the longest name (usually more descriptive)
                if len(name) > len(m.name):
                    m.name = name
            else:
                merchants_by_url[url] = Merchant(
                    name=name,
                    website=url,
                    raw_website=raw_url,
                    orders_30d=orders,
                    m1_vfm_30d=vfm,
                    deal_count=deal_count_col or 1,
                    deal_permalinks=[permalink] if permalink else [],
                )

    merchants = list(merchants_by_url.values())
    # Sort by total orders descending (high-value merchants first)
    merchants.sort(key=lambda m: m.orders_30d, reverse=True)

    return merchants + no_website
