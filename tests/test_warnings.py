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


# --- v0.3.0: active-warning filtering, ranking, level names ---------------

from datetime import datetime, timezone  # noqa: E402

from koneho_meteoswiss.const import (  # noqa: E402
    WARN_LEVEL_NAMES,
    warning_level_color,
    warning_level_name,
)
from koneho_meteoswiss.models import warning_details  # noqa: E402

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _place_with(warnings, overview=None):
    payload = {
        "currentWeather": {},
        "forecast": [],
        "graph": {},
        "warnings": warnings,
        "warningsOverview": overview or [],
    }
    return PlaceForecast.from_payload(payload, "1000", "plzDetail")


def test_expired_warnings_are_not_active():
    expired = {
        "warnType": 1, "warnLevel": 5, "text": "Old wind.",
        "validFrom": _ms(datetime(2026, 11, 5, tzinfo=timezone.utc)),
        "validTo": _ms(datetime(2026, 11, 6, 6, 0, tzinfo=timezone.utc)),
    }
    active = {
        "warnType": 10, "warnLevel": 2, "text": "Fire.",
        "validFrom": _ms(datetime(2026, 11, 4, tzinfo=timezone.utc)),
        "validTo": _ms(datetime(2026, 11, 20, tzinfo=timezone.utc)),
    }
    place = _place_with([expired, active], overview=[{"warnType": 1, "warnLevel": 5}])
    summary = place.warnings_summary(now=NOW)
    assert summary["state"] == "Level 2: Forest fire"
    assert summary["count"] == 1
    assert summary["max_level"] == 2
    assert [w["warnType"] for w in summary["warnings"]] == [10]
    assert place.highest_warning(now=NOW)["warnType"] == 10


def test_all_expired_full_records_mean_no_active_warning():
    expired = {
        "warnType": 1, "warnLevel": 4, "text": "Old.",
        "validTo": _ms(datetime(2026, 11, 1, tzinfo=timezone.utc)),
    }
    # The overview still lists the type; full records are authoritative.
    place = _place_with([expired], overview=[{"warnType": 1, "warnLevel": 4}])
    summary = place.warnings_summary(now=NOW)
    assert summary["state"] == "None"
    assert summary["count"] == 0
    assert place.active_warnings(now=NOW) == []


def test_overview_entries_used_when_no_full_records():
    place = _place_with([], overview=[{"warnType": 3, "warnLevel": 3}])
    active = place.active_warnings(now=NOW)
    assert len(active) == 1
    assert place.warnings_summary(now=NOW)["state"] == "Level 3: Rain"


def test_active_warnings_sorted_by_level_descending():
    place = _place_with([
        {"warnType": 3, "warnLevel": 2, "text": "Rain."},
        {"warnType": 1, "warnLevel": 4, "text": "Wind."},
        {"warnType": 5, "warnLevel": 3, "text": "Snow."},
    ])
    levels = [w["warnLevel"] for w in place.active_warnings(now=NOW)]
    assert levels == [4, 3, 2]


def test_warning_at_rank_details():
    place = _place_with([
        {"warnType": 3, "warnLevel": 2, "text": "Rain.", "outlook": False},
        {
            "warnType": 1, "warnLevel": 4, "text": "Wind.",
            "htmlText": "Wind <b>html</b>", "outlook": True,
            "links": [{"link": "https://example.com", "text_de": "x"}],
            "validFrom": _ms(datetime(2026, 11, 6, tzinfo=timezone.utc)),
            "validTo": _ms(datetime(2026, 11, 7, tzinfo=timezone.utc)),
        },
    ])
    top = place.warning_at_rank(0, now=NOW)
    assert top["type_name"] == "Wind"
    assert top["level"] == "Severe hazard"
    assert top["level_numeric"] == 4
    assert top["icon_color"] == "red"
    assert top["outlook"] is True
    assert top["links"] == [{"link": "https://example.com", "text_de": "x"}]
    assert top["valid_from"] == "2026-11-06T00:00:00+00:00"
    second = place.warning_at_rank(1, now=NOW)
    assert second["type_name"] == "Rain"
    assert second["level"] == "Moderate hazard"
    assert second["icon_color"] == "amber"
    assert place.warning_at_rank(2, now=NOW) is None


def test_warning_details_normalises_levels():
    details = warning_details({"warnType": 10, "warnLevel": 2})
    assert details["type_name"] == "Forest fire"
    assert details["level"] == WARN_LEVEL_NAMES[2]
    assert details["valid_from"] is None
    assert details["links"] == []
    assert details["outlook"] is False


def test_warning_level_names_and_colors():
    assert warning_level_name(0) == "No danger"
    assert warning_level_name(1) == "No or minimal hazard"
    assert warning_level_name(2) == "Moderate hazard"
    assert warning_level_name(5) == "Very severe hazard"
    assert warning_level_name("x") is None
    assert warning_level_color(0) == "gray"
    assert warning_level_color(1) == "gray"
    assert warning_level_color(2) == "amber"
    assert warning_level_color(3) == "red"
    assert warning_level_color(None) == "gray"
