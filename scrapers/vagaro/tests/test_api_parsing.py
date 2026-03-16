"""
Unit tests for Vagaro API response parsing.

These tests run against captured fixtures (no network needed).
If Vagaro changes their API response shape, update the constants
in api_schema.py and refresh the fixtures.
"""
import json
from pathlib import Path

import pytest

from scrapers.vagaro.api_schema import (
    parse_service_list,
    parse_availability_response,
    extract_service_info,
    parse_app_date,
    parse_avail_date,
)
from scrapers.base import BaseScraper

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Reusable time converter from BaseScraper
_base = type("_B", (BaseScraper,), {
    "scrape": lambda *a: None,
    "platform_name": "test",
})()


def _time_str_to_seconds(t):
    return _base.time_str_to_seconds(t)


# --- Service list parsing ---

class TestParseServiceList:
    @pytest.fixture
    def service_response(self):
        with open(FIXTURES / "getonlinebookingtabdetail.json") as f:
            return json.load(f)

    def test_returns_only_actual_services(self, service_response):
        services = parse_service_list(service_response)
        # Should exclude level-0 category headers
        names = [s["name"] for s in services]
        assert "Hair Services" not in names
        assert "Color Services" not in names
        assert "Women's Haircut" in names
        assert "Men's Haircut" in names
        assert "Full Color" in names

    def test_service_count(self, service_response):
        services = parse_service_list(service_response)
        assert len(services) == 3

    def test_service_fields(self, service_response):
        services = parse_service_list(service_response)
        womens = next(s for s in services if s["name"] == "Women's Haircut")
        assert womens["category"] == "Hair Services"
        assert womens["duration_display"] == "60 min"
        assert womens["price_display"] == "$75"

    def test_empty_response(self):
        assert parse_service_list({}) == []
        assert parse_service_list({"lstOnlineServiceDetail": []}) == []


# --- Availability parsing ---

class TestParseAvailabilityResponse:
    @pytest.fixture
    def avail_response(self):
        with open(FIXTURES / "getavailablemultiappointments.json") as f:
            return json.load(f)

    def test_returns_date_slots(self, avail_response):
        result = parse_availability_response(avail_response, _time_str_to_seconds)
        assert len(result) >= 2  # At least 2 dates with timeslots

    def test_date_format(self, avail_response):
        result = parse_availability_response(avail_response, _time_str_to_seconds)
        for date_str in result:
            # Should be ISO format YYYY-MM-DD
            assert len(date_str) == 10
            assert date_str[4] == "-" and date_str[7] == "-"

    def test_time_slots_are_sorted_seconds(self, avail_response):
        result = parse_availability_response(avail_response, _time_str_to_seconds)
        for entry in result.values():
            slots = entry["time_slots"]
            assert slots == sorted(slots)
            assert all(isinstance(s, int) for s in slots)

    def test_first_date_has_slots(self, avail_response):
        result = parse_availability_response(avail_response, _time_str_to_seconds)
        # "16 Mar 2026" should have 8 timeslots
        assert "2026-03-16" in result
        assert len(result["2026-03-16"]["time_slots"]) == 8

    def test_empty_available_time(self, avail_response):
        result = parse_availability_response(avail_response, _time_str_to_seconds)
        # "18 Mar 2026" has empty AvailableTime
        assert "2026-03-18" in result
        assert result["2026-03-18"]["time_slots"] == []
        assert result["2026-03-18"]["closed"] is False

    def test_fallback_date(self, avail_response):
        result = parse_availability_response(
            avail_response, _time_str_to_seconds,
            fallback_date="2026-03-15",
        )
        # Fallback date should be stored if different from API date
        assert "2026-03-15" in result

    def test_empty_response(self):
        result = parse_availability_response({}, _time_str_to_seconds)
        assert result == {}


# --- Service info extraction ---

class TestExtractServiceInfo:
    @pytest.fixture
    def avail_response(self):
        with open(FIXTURES / "getavailablemultiappointments.json") as f:
            return json.load(f)

    def test_finds_matching_service(self, avail_response):
        info = extract_service_info(avail_response, "Women's Haircut")
        assert info is not None
        assert info["id"] == 26744247
        assert info["duration"] == 60
        assert info["price"] == 7500  # cents

    def test_case_insensitive(self, avail_response):
        info = extract_service_info(avail_response, "women's haircut")
        assert info is not None

    def test_partial_match(self, avail_response):
        info = extract_service_info(avail_response, "Haircut")
        assert info is not None

    def test_no_match(self, avail_response):
        info = extract_service_info(avail_response, "Nonexistent Service")
        assert info is None


# --- Date parsing ---

class TestDateParsing:
    def test_parse_app_date(self):
        d = parse_app_date("16 Mar 2026")
        assert d is not None
        assert d.year == 2026
        assert d.month == 3
        assert d.day == 16

    def test_parse_app_date_invalid(self):
        assert parse_app_date("invalid") is None
        assert parse_app_date("") is None

    def test_parse_avail_date(self):
        d = parse_avail_date("Mar 16,2026")
        assert d is not None
        assert d.year == 2026
        assert d.month == 3
        assert d.day == 16

    def test_parse_avail_date_invalid(self):
        assert parse_avail_date("invalid") is None
        assert parse_avail_date("") is None
