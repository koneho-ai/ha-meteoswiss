"""Tests for the config-flow form schema (station picker, interval).

HA and voluptuous are not installed in the test environment, so
minimal stand-ins are registered before importing ``config_flow``.
The stand-ins are *additive*: if another test module already
registered ``homeassistant`` stubs (test_weather_forecasts installs
its own set and skips re-installing when the package exists), the
pieces the config flow needs are added onto those modules, and the
weather pieces are included here so collection order does not matter.
"""

from __future__ import annotations

import enum
import sys
import types


def _module(name: str) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return mod


def _install_stubs() -> None:
    # --- voluptuous: record markers and schemas, validate nothing ---
    if "voluptuous" not in sys.modules:
        vol = types.ModuleType("voluptuous")

        class _Marker:
            def __init__(self, key, default=None):
                self.schema = key
                self.default = default

        def Optional(key, default=None):
            return _Marker(key, default)

        def Required(key, default=None):
            return _Marker(key, default)

        class Schema:
            def __init__(self, schema):
                self.schema = schema

        vol.Optional = Optional
        vol.Required = Required
        vol.Schema = Schema
        sys.modules["voluptuous"] = vol

    ha = _module("homeassistant")
    components = _module("homeassistant.components")
    helpers = _module("homeassistant.helpers")
    ha.components = components
    ha.helpers = helpers

    # --- config_entries (also used by weather.py) ---
    config_entries = _module("homeassistant.config_entries")
    if not hasattr(config_entries, "ConfigEntry"):

        class ConfigEntry:
            pass

        config_entries.ConfigEntry = ConfigEntry
    if not hasattr(config_entries, "ConfigFlow"):

        class ConfigFlow:
            def __init_subclass__(cls, **kwargs):
                pass

        config_entries.ConfigFlow = ConfigFlow
    if not hasattr(config_entries, "ConfigFlowResult"):
        config_entries.ConfigFlowResult = dict

    # --- core / const (used by weather.py) ---
    core = _module("homeassistant.core")
    if not hasattr(core, "HomeAssistant"):

        class HomeAssistant:
            pass

        core.HomeAssistant = HomeAssistant

    const = _module("homeassistant.const")
    for name, member, value in (
        ("UnitOfTemperature", "CELSIUS", "°C"),
        ("UnitOfPressure", "HPA", "hPa"),
        ("UnitOfSpeed", "KILOMETERS_PER_HOUR", "km/h"),
        ("UnitOfPrecipitationDepth", "MILLIMETERS", "mm"),
    ):
        if not hasattr(const, name):
            setattr(const, name, enum.StrEnum(name, {member: value}))

    # --- helpers.aiohttp_client ---
    aiohttp_client = _module("homeassistant.helpers.aiohttp_client")
    if not hasattr(aiohttp_client, "async_get_clientsession"):
        aiohttp_client.async_get_clientsession = lambda hass: None

    # --- helpers.selector ---
    selector = _module("homeassistant.helpers.selector")
    if not hasattr(selector, "SelectSelector"):

        class NumberSelectorMode(enum.Enum):
            BOX = "box"
            SLIDER = "slider"

        class SelectSelectorMode(enum.Enum):
            DROPDOWN = "dropdown"
            LIST = "list"

        def _config(**kwargs):
            return dict(kwargs)

        class _Selector:
            def __init__(self, config):
                self.config = config

        class SelectSelector(_Selector):
            pass

        class NumberSelector(_Selector):
            pass

        def SelectOptionDict(value=None, label=None):
            return {"value": value, "label": label}

        selector.NumberSelectorMode = NumberSelectorMode
        selector.SelectSelectorMode = SelectSelectorMode
        selector.NumberSelectorConfig = _config
        selector.SelectSelectorConfig = _config
        selector.SelectSelector = SelectSelector
        selector.NumberSelector = NumberSelector
        selector.SelectOptionDict = SelectOptionDict

    # --- weather pieces (so test_weather_forecasts works regardless
    # of which module's stubs were installed first) ---
    weather_mod = _module("homeassistant.components.weather")
    if not hasattr(weather_mod, "WeatherEntity"):

        class Forecast(dict):
            pass

        class WeatherEntity:
            pass

        class WeatherEntityFeature(enum.IntFlag):
            FORECAST_DAILY = 1
            FORECAST_HOURLY = 2
            FORECAST_TWICE_DAILY = 4

        weather_mod.Forecast = Forecast
        weather_mod.WeatherEntity = WeatherEntity
        weather_mod.WeatherEntityFeature = WeatherEntityFeature
    components.weather = weather_mod

    entity_platform = _module("homeassistant.helpers.entity_platform")
    if not hasattr(entity_platform, "AddEntitiesCallback"):
        entity_platform.AddEntitiesCallback = object

    update_coordinator = _module("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator, "DataUpdateCoordinator"):

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


_install_stubs()

from koneho_meteoswiss.config_flow import _form_schema  # noqa: E402
from koneho_meteoswiss.stations import build_station_options  # noqa: E402


def _field(schema, key):
    for marker, validator in schema.schema.items():
        if getattr(marker, "schema", None) == key:
            return marker, validator
    raise AssertionError(f"field {key!r} not in schema")


def test_station_field_falls_back_to_text_without_options():
    # Metadata fetch failed -> plain free-text field, setup never blocks.
    schema = _form_schema({})
    _marker, validator = _field(schema, "station")
    assert validator is str


def test_station_field_is_dropdown_with_options():
    options = build_station_options({"SMA": "Zürich / Fluntern", "UEB": "Uetliberg"})
    schema = _form_schema({}, options)
    marker, validator = _field(schema, "station")
    assert marker.default == ""
    assert validator.__class__.__name__ == "SelectSelector"
    assert validator.config["options"] == [
        {"value": "", "label": "Automatic (nearest station)"},
        {"value": "UEB", "label": "Uetliberg (UEB)"},
        {"value": "SMA", "label": "Zürich / Fluntern (SMA)"},
    ]


def test_configured_station_missing_from_list_stays_selectable():
    options = build_station_options({"SMA": "Zürich / Fluntern"})
    schema = _form_schema({"station": "XYZ"}, options)
    marker, validator = _field(schema, "station")
    assert marker.default == "XYZ"
    values = [opt["value"] for opt in validator.config["options"]]
    assert "XYZ" in values


def test_update_interval_field_default_and_range():
    schema = _form_schema({})
    marker, validator = _field(schema, "update_interval")
    assert marker.default == 15  # pre-0.2.2 cadence preserved
    assert validator.__class__.__name__ == "NumberSelector"
    assert validator.config["min"] == 1
    assert validator.config["max"] == 180

    schema = _form_schema({"update_interval": 30})
    marker, _validator = _field(schema, "update_interval")
    assert marker.default == 30
