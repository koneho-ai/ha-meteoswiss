"""Weather entity for the MeteoSwiss (Koneho) integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_NAME, CONF_POSTCODE, DOMAIN
from .coordinator import MeteoSwissCoordinator
from .icons import icon_to_condition
from .models import MeteoData, station_current_conditions


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the weather entity for a config entry."""
    coordinator: MeteoSwissCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeteoSwissWeather(coordinator, entry)])


class MeteoSwissWeather(CoordinatorEntity[MeteoSwissCoordinator], WeatherEntity):
    """Weather entity backed by the MeteoSwiss place payload.

    Current condition/temperature come from ``currentWeather``; daily
    and hourly forecasts come from the forecast list and the graph
    series. *Every* remaining field of the payload (all graph series,
    warnings overview, klimaGraph, raw current/forecast blocks) is
    exposed through ``extra_state_attributes``.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: MeteoSwissCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        name = entry.data.get(CONF_NAME) or entry.data[CONF_POSTCODE]
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_weather"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": name,
            "manufacturer": "MeteoSwiss",
            "model": "MeteoSwiss place forecast",
        }

    @property
    def _place(self):
        return self.coordinator.data.place

    @property
    def native_temperature(self) -> float | None:
        return self._place.current.temperature

    @property
    def condition(self) -> str | None:
        return icon_to_condition(self._place.current.icon)

    # Current conditions the place payload does not carry (it has only
    # icon + temperature) are taken from the station observation —
    # manual or auto-selected — via models.station_current_conditions.
    @property
    def _station_conditions(self) -> dict:
        data = self.coordinator.data
        return station_current_conditions(data.station if data else None)

    @property
    def humidity(self) -> float | None:
        # HA's WeatherEntity reads ``humidity`` (already a percentage);
        # there is no ``native_humidity`` property in the HA 2026.11
        # weather API. Defining only native_humidity silently left the
        # weather entity's humidity at None even with station data.
        return self._station_conditions["humidity"]

    @property
    def native_pressure(self) -> float | None:
        return self._station_conditions["pressure"]

    @property
    def native_dew_point(self) -> float | None:
        return self._station_conditions["dew_point"]

    @property
    def native_wind_speed(self) -> float | None:
        return self._station_conditions["wind_speed"]

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._station_conditions["wind_gust_speed"]

    @property
    def wind_bearing(self) -> int | None:
        return self._station_conditions["wind_bearing"]

    async def async_forecast_daily(self) -> list[Forecast]:
        """Return the daily forecast.

        This (and ``async_forecast_hourly``) is the method HA's
        ``weather.get_forecasts`` service actually dispatches to; an
        ``async_get_forecasts`` method is never called by HA.
        """
        return self._build_forecasts("daily")

    async def async_forecast_hourly(self) -> list[Forecast]:
        """Return the hourly forecast (see ``async_forecast_daily``)."""
        return self._build_forecasts("hourly")

    def _build_forecasts(self, forecast_type: str) -> list[Forecast]:
        """Build daily or hourly forecasts in HA Forecast shape."""
        place = self._place
        if forecast_type == "hourly":
            raw = place.hourly_forecast()
            return [
                Forecast(
                    datetime=entry["datetime"],
                    condition=entry["condition"],
                    native_temperature=entry["native_temperature"],
                    native_templow=entry["native_templow"],
                    native_apparent_temperature=entry["native_apparent_temperature"],
                    native_precipitation=entry["native_precipitation"],
                    precipitation_probability=(
                        int(entry["precipitation_probability"])
                        if entry["precipitation_probability"] is not None
                        else None
                    ),
                    native_wind_speed=entry["native_wind_speed"],
                    native_wind_gust_speed=entry["native_wind_gust_speed"],
                    wind_bearing=(
                        int(entry["wind_bearing"])
                        if entry["wind_bearing"] is not None
                        else None
                    ),
                )
                for entry in raw
            ]
        raw = place.daily_forecast()
        return [
            Forecast(
                datetime=entry["datetime"],
                condition=entry["condition"],
                native_temperature=entry["native_temperature"],
                native_templow=entry["native_templow"],
                native_precipitation=entry["native_precipitation"],
                precipitation_probability=(
                    int(entry["precipitation_probability"])
                    if entry["precipitation_probability"] is not None
                    else None
                ),
                native_wind_speed=entry["native_wind_speed"],
                native_wind_gust_speed=entry["native_wind_gust_speed"],
            )
            for entry in raw
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the complete payload: no field is dropped."""
        place = self._place
        graph = place.graph
        attrs: dict[str, Any] = {
            "source": ATTRIBUTION,
            "source_endpoint": place.source_endpoint,
            "postcode": place.plz,
            "current_weather": place.current.raw,
            "current_icon_code": place.current.icon,
            "current_icon_code_v2": place.current.icon_v2,
            "graph_start": graph.start.isoformat() if graph.start else None,
            "graph_start_low_resolution": (
                graph.start_low_resolution.isoformat()
                if graph.start_low_resolution
                else None
            ),
            # Every graph series, exactly as delivered.
            "graph": graph.series,
            "forecast_days": [day.raw for day in place.days],
            "warnings_overview": place.warnings_overview,
            "warnings_count": len(place.warnings),
        }
        if place.climate is not None:
            attrs["klima_graph"] = place.climate.raw
        return attrs

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None
