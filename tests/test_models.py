"""Tests for icon mapping and forecast building."""

from __future__ import annotations

from datetime import date, datetime, timezone

from koneho_meteoswiss.client import parse_payload
from koneho_meteoswiss.icons import icon_to_condition
from koneho_meteoswiss.models import PlaceForecast


def test_icon_mapping():
    # Expectations follow MeteoSwiss's published symbol table (v0.2.2).
    assert icon_to_condition(1) == "sunny"
    assert icon_to_condition(101) == "clear-night"
    assert icon_to_condition(2) == "partlycloudy"
    assert icon_to_condition(3) == "partlycloudy"
    assert icon_to_condition(103) == "partlycloudy"
    assert icon_to_condition(4) == "partlycloudy"
    assert icon_to_condition(5) == "cloudy"
    assert icon_to_condition(6) == "rainy"
    assert icon_to_condition(7) == "snowy-rainy"
    assert icon_to_condition(107) == "snowy-rainy"
    assert icon_to_condition(11) == "snowy"
    assert icon_to_condition(14) == "rainy"
    assert icon_to_condition(114) == "rainy"
    assert icon_to_condition(17) == "rainy"
    # Unknown codes and missing values map to no condition, never crash.
    assert icon_to_condition(999) is None
    assert icon_to_condition(None) is None
    assert icon_to_condition("x") is None


def _place(fixture_bytes) -> PlaceForecast:
    payload = parse_payload(fixture_bytes("plzdetail_8808.json"))
    return PlaceForecast.from_payload(payload, "8808", "plzDetail")


def test_climate_normals_use_annual_norm_cycle(fixture_bytes):
    place = _place(fixture_bytes)
    assert place.climate is not None

    # The fixture's klimaGraph starts in November 2024 and contains 24
    # monthly entries. November 2026 is therefore beyond an absolute
    # list offset, but its climate normal is the November entry of the
    # repeated annual ``norm`` cycle: 5.4 °C.
    assert place.climate.current_month_norm_temperature(
        datetime(2026, 11, 6, tzinfo=timezone.utc)
    ) == 5.4
    # July maps to the July normal in the same annual cycle.
    assert place.climate.current_month_norm_temperature(
        datetime(2026, 7, 1, tzinfo=timezone.utc)
    ) == 19.5


def test_daily_forecast_building(fixture_bytes):
    place = _place(fixture_bytes)
    daily = place.daily_forecast()
    assert len(daily) == 8

    first = daily[0]
    assert first["datetime"] == "2026-11-06"
    assert first["condition"] == "rainy"  # iconDay 14, official symbol table
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


# --- v0.3.0: sentinel values, icon preference, hourly sunshine/filter ------

from koneho_meteoswiss.models import CurrentWeather  # noqa: E402


def test_current_weather_sentinel_is_missing():
    current = CurrentWeather.from_dict(
        {"icon": 32767, "iconV2": 32767, "temperature": 32767, "time": None}
    )
    assert current.icon is None
    assert current.icon_v2 is None
    assert current.temperature is None
    assert current.condition_icon is None


def test_current_weather_prefers_icon_v2():
    current = CurrentWeather.from_dict(
        {"icon": 1, "iconV2": 101, "temperature": 5.0}
    )
    assert current.condition_icon == 101
    # V2 missing -> legacy icon.
    current = CurrentWeather.from_dict({"icon": 2, "iconV2": 32767})
    assert current.condition_icon == 2
    # V2 present alone.
    current = CurrentWeather.from_dict({"iconV2": 5})
    assert current.condition_icon == 5


def test_hourly_forecast_carries_sunshine_and_filters(fixture_bytes):
    from datetime import datetime, timezone

    place = _place(fixture_bytes)
    full = place.hourly_forecast()
    assert len(full) == 192
    assert "sunshine" in full[0]
    # sunshine1h is in the fixture graph; values are minutes or None.
    assert full[0]["sunshine"] is None or isinstance(full[0]["sunshine"], (int, float))

    now = datetime(2026, 11, 6, 10, 30, tzinfo=timezone.utc)
    filtered = place.hourly_forecast(now=now)
    assert filtered[0]["datetime"] == "2026-11-06T10:00:00+00:00"
    assert len(filtered) == 192 - 11
    # Sunshine stays index-aligned after filtering.
    assert filtered[0]["sunshine"] == full[11]["sunshine"]
    # A now before the window changes nothing; after it, empty.
    assert len(place.hourly_forecast(now=datetime(2026, 1, 1, tzinfo=timezone.utc))) == 192
    assert place.hourly_forecast(now=datetime(2027, 1, 1, tzinfo=timezone.utc)) == []
