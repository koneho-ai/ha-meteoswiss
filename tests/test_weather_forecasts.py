"""Tests for the weather entity's forecast dispatch methods.

Regression test for the 0.2.0/0.2.1 live failure: the entity implemented
``async_get_forecasts(forecast_type)``, which Home Assistant never
calls — the ``weather.get_forecasts`` service dispatches to
``async_forecast_daily()`` / ``async_forecast_hourly()``, so cards showed
no forecast and the service returned ``unknown_error``.

HA is not installed in the test environment, so minimal stand-ins for
the ``homeassistant`` modules that ``weather.py``/``coordinator.py``
import are registered before importing the entity module. Only what the
forecast path touches is modelled (``Forecast`` as a dict, like HA's
TypedDict; a coordinator that just holds ``data``).
"""

from __future__ import annotations

import asyncio
import enum
import sys
import types
from types import SimpleNamespace


def _install_ha_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    helpers = types.ModuleType("homeassistant.helpers")

    weather_mod = types.ModuleType("homeassistant.components.weather")

    class Forecast(dict):
        """HA's Forecast is a TypedDict; a dict covers construction/access."""

    class WeatherEntity:
        pass

    class WeatherEntityFeature(enum.IntFlag):
        FORECAST_DAILY = 1
        FORECAST_HOURLY = 2
        FORECAST_TWICE_DAILY = 4

    weather_mod.Forecast = Forecast
    weather_mod.WeatherEntity = WeatherEntity
    weather_mod.WeatherEntityFeature = WeatherEntityFeature

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        pass

    config_entries.ConfigEntry = ConfigEntry

    const = types.ModuleType("homeassistant.const")

    class UnitOfTemperature(enum.StrEnum):
        CELSIUS = "°C"

    class UnitOfPressure(enum.StrEnum):
        HPA = "hPa"

    class UnitOfSpeed(enum.StrEnum):
        KILOMETERS_PER_HOUR = "km/h"

    class UnitOfPrecipitationDepth(enum.StrEnum):
        MILLIMETERS = "mm"

    const.UnitOfTemperature = UnitOfTemperature
    const.UnitOfPressure = UnitOfPressure
    const.UnitOfSpeed = UnitOfSpeed
    const.UnitOfPrecipitationDepth = UnitOfPrecipitationDepth

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        pass

    core.HomeAssistant = HomeAssistant

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object  # annotation only

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        __class_getitem__ = classmethod(lambda cls, item: cls)

        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return True

    class DataUpdateCoordinator:
        __class_getitem__ = classmethod(lambda cls, item: cls)

        def __init__(self, *args, **kwargs):
            pass

    class UpdateFailed(Exception):
        pass

    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed

    ha.components = components
    ha.helpers = helpers
    ha.config_entries = config_entries
    ha.const = const
    ha.core = core
    components.weather = weather_mod
    helpers.entity_platform = entity_platform
    helpers.update_coordinator = update_coordinator

    sys.modules.update(
        {
            "homeassistant": ha,
            "homeassistant.components": components,
            "homeassistant.components.weather": weather_mod,
            "homeassistant.config_entries": config_entries,
            "homeassistant.const": const,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_platform": entity_platform,
            "homeassistant.helpers.update_coordinator": update_coordinator,
        }
    )


_install_ha_stubs()

from koneho_meteoswiss.client import parse_payload  # noqa: E402
from koneho_meteoswiss.models import MeteoData, PlaceForecast  # noqa: E402
from koneho_meteoswiss.weather import MeteoSwissWeather  # noqa: E402


def _entity(fixture_bytes) -> MeteoSwissWeather:
    payload = parse_payload(fixture_bytes("plzdetail_8808.json"))
    place = PlaceForecast.from_payload(payload, "8808", "plzDetail")
    coordinator = SimpleNamespace(data=MeteoData(place=place))
    entry = SimpleNamespace(
        data={"name": "Pfaffikon", "postcode": "8808"},
        unique_id="8808_place",
        entry_id="test-entry-id",
    )
    return MeteoSwissWeather(coordinator, entry)


def test_entity_exposes_ha_dispatch_methods():
    # weather.get_forecasts dispatches to these two methods; the old
    # async_get_forecasts name is never called by HA.
    assert callable(getattr(MeteoSwissWeather, "async_forecast_daily", None))
    assert callable(getattr(MeteoSwissWeather, "async_forecast_hourly", None))
    assert not hasattr(MeteoSwissWeather, "async_get_forecasts")


def test_async_forecast_daily(fixture_bytes):
    daily = asyncio.run(_entity(fixture_bytes).async_forecast_daily())
    assert len(daily) == 8

    first = daily[0]
    assert first["datetime"] == "2026-11-06"
    assert first["condition"] == "lightning-rainy"  # iconDay 14
    assert first["native_temperature"] == 8
    assert first["native_templow"] == 6


def test_async_forecast_hourly(fixture_bytes):
    hourly = asyncio.run(_entity(fixture_bytes).async_forecast_hourly())
    assert len(hourly) == 192  # one entry per temperatureMean1h point

    first = hourly[0]
    assert first["datetime"] == "2026-11-05T23:00:00+00:00"
    assert first["condition"] == "partlycloudy"  # weatherIcon3h 103
    assert first["native_temperature"] == 6.3
