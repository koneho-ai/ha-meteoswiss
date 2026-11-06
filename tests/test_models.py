"""Tests for icon mapping and forecast building."""

from __future__ import annotations

from datetime import date

from koneho_meteoswiss.client import parse_payload
from koneho_meteoswiss.icons import icon_to_condition
from koneho_meteoswiss.models import PlaceForecast


def test_icon_mapping():
    assert icon_to_condition(1) == "sunny"
    assert icon_to_condition(101) == "clear-night"
    assert icon_to_condition(2) == "partlycloudy"
    assert icon_to_condition(3) == "partlycloudy"
    assert icon_to_condition(103) == "partlycloudy"
    assert icon_to_condition(4) == "cloudy"
    assert icon_to_condition(5) == "rainy"
    assert icon_to_condition(6) == "snowy-rainy"
    assert icon_to_condition(7) == "snowy"
    assert icon_to_condition(107) == "snowy"
    assert icon_to_condition(11) == "fog"
    assert icon_to_condition(14) == "lightning-rainy"
    assert icon_to_condition(114) == "lightning-rainy"
    assert icon_to_condition(17) == "rainy"
    # Unknown codes and missing values map to no condition, never crash.
    assert icon_to_condition(999) is None
    assert icon_to_condition(None) is None
    assert icon_to_condition("x") is None


def _place(fixture_bytes) -> PlaceForecast:
    payload = parse_payload(fixture_bytes("plzdetail_8808.json"))
    return PlaceForecast.from_payload(payload, "8808", "plzDetail")


def test_daily_forecast_building(fixture_bytes):
    place = _place(fixture_bytes)
    daily = place.daily_forecast()
    assert len(daily) == 8

    first = daily[0]
    assert first["datetime"] == "2026-11-06"
    assert first["condition"] == "lightning-rainy"  # iconDay 14
    assert first["native_temperature"] == 8
    assert first["native_templow"] == 6
    assert first["native_precipitation"] == 3.3
    assert first["precipitation_min"] == 1.4
    assert first["precipitation_max"] == 7.8
    assert first["icon_code"] == 14
    assert first["sunrise"] is not None and first["sunrise"].startswith("2026-11-06")
    assert first["sunset"] is not None

    dates = [entry["datetime"] for entry in daily]
    assert dates == sorted(dates)


def test_hourly_forecast_building(fixture_bytes):
    place = _place(fixture_bytes)
    hourly = place.hourly_forecast()
    assert len(hourly) == 192  # one entry per temperatureMean1h point

    first = hourly[0]
    assert first["datetime"] == "2026-11-05T23:00:00+00:00"
    assert first["native_temperature"] == 6.3
    assert first["native_templow"] == 6.3
    # weatherIcon3h[0] is 103 (night, partly cloudy)
    assert first["condition"] == "partlycloudy"
    assert first["icon_code"] == 103

    moments = [entry["datetime"] for entry in hourly]
    assert moments == sorted(moments)


def test_daily_aggregates(fixture_bytes):
    place = _place(fixture_bytes)
    today = date(2026, 11, 6)

    precip = place.precipitation_for_day(today)
    assert precip["precipitation"] is not None and precip["precipitation"] > 0
    assert precip["precipitation_min"] is not None
    assert precip["precipitation_max"] is not None
    assert precip["precipitation_min"] <= precip["precipitation_max"]

    probability = place.max_precipitation_probability_for_day(today)
    assert probability is not None and 0 <= probability <= 100

    wind = place.max_wind_for_day(today)
    assert wind["wind_speed_max"] is not None and wind["wind_speed_max"] > 0
    assert wind["wind_gust_max"] is not None
    assert wind["wind_gust_max"] >= wind["wind_speed_max"]

    sunshine = place.sunshine_hours_for_day(today)
    assert sunshine is not None and 0 <= sunshine <= 24
