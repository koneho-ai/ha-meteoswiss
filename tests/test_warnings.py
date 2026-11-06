"""Tests for the readable warnings summary (v0.2.0)."""

from __future__ import annotations

from koneho_meteoswiss.client import parse_payload
from koneho_meteoswiss.models import PlaceForecast


def _place(fixture_bytes, name: str) -> PlaceForecast:
    payload = parse_payload(fixture_bytes(name))
    return PlaceForecast.from_payload(payload, "8808", "plzDetail")


def test_forest_fire_warning_state(fixture_bytes):
    # Live-captured fixture: warnType 10, warnLevel 2 for Pfäffikon SZ.
    place = _place(fixture_bytes, "plzdetail_8808.json")
    summary = place.warnings_summary()
    assert summary["state"] == "Level 2: Forest fire"
    assert summary["count"] == 1
    assert summary["max_level"] == 2
    assert summary["warn_types"] == [10]
    assert summary["warn_type_names"] == ["Forest fire"]
    assert "FOEN" in summary["text_joined"]
    assert summary["valid_from"] is not None
    assert place.highest_warning()["warnType"] == 10


def test_no_warnings_state(fixture_bytes):
    place = _place(fixture_bytes, "plzdetail_8048.json")
    summary = place.warnings_summary()
    assert summary["state"] == "None"
    assert summary["count"] == 0
    assert summary["max_level"] is None
    assert summary["text_joined"] == ""
    assert place.highest_warning() is None


def test_unknown_warning_type():
    payload = {
        "currentWeather": {"icon": 1, "temperature": 20.0},
        "forecast": [],
        "graph": {},
        "warnings": [
            {"warnType": 99, "warnLevel": 3, "text": "Something unusual."}
        ],
        "warningsOverview": [{"warnType": 99, "warnLevel": 3}],
    }
    place = PlaceForecast.from_payload(payload, "1000", "plzDetail")
    summary = place.warnings_summary()
    assert summary["state"] == "Level 3: Type 99"
    assert summary["text_joined"] == "Something unusual."


def test_multiple_warning_texts_joined():
    payload = {
        "currentWeather": {},
        "forecast": [],
        "graph": {},
        "warnings": [
            {"warnType": 1, "warnLevel": 4, "text": "Wind text."},
            {"warnType": 3, "warnLevel": 2, "text": "Rain text."},
        ],
        "warningsOverview": [],
    }
    place = PlaceForecast.from_payload(payload, "1000", "plzDetail")
    summary = place.warnings_summary()
    assert summary["state"] == "Level 4: Wind"  # highest level wins
    assert summary["text_joined"] == "Wind text.\n\nRain text."
    assert summary["warn_types"] == [1, 3]
