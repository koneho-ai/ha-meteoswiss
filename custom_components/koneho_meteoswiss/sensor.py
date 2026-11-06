"""Sensors for the MeteoSwiss (Koneho) integration.

Two families:

- Place sensors derived from the plzDetail/forecast payload (today's
  sunshine, precipitation, precipitation probability, wind/gust,
  sunrise, sunset, current icon code), plus two diagnostic sensors
  that expose the *complete* graph series and the klimaGraph so no
  field returned by the API is dropped.
- Station sensors: one per SwissMetNet CSV column that carries a
  value for the configured station (VQHA80, merged with VQHA98).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    CONF_NAME,
    CONF_POSTCODE,
    CONF_STATION,
    DOMAIN,
    STATION_COLUMNS,
)
from .coordinator import MeteoSwissCoordinator
from .models import MeteoData, PlaceForecast, StationObservation

_DEVICE_CLASSES = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    # HA has no dew_point device class; dew point is a temperature (HA docs).
    "dew_point": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "pressure": SensorDeviceClass.PRESSURE,
    "wind_speed": SensorDeviceClass.WIND_SPEED,
    # HA has no wind_gust_speed device class; gusts use wind_speed.
    "wind_gust_speed": SensorDeviceClass.WIND_SPEED,
    "precipitation": SensorDeviceClass.PRECIPITATION,
    "irradiance": SensorDeviceClass.IRRADIANCE,
    "duration": SensorDeviceClass.DURATION,
}
_UNITS = {
    "°C": UnitOfTemperature.CELSIUS,
    "%": PERCENTAGE,
    "hPa": UnitOfPressure.HPA,
    "km/h": UnitOfSpeed.KILOMETERS_PER_HOUR,
    "mm": UnitOfPrecipitationDepth.MILLIMETERS,
    "W/m²": UnitOfIrradiance.WATTS_PER_SQUARE_METER,
    "min": UnitOfTime.MINUTES,
}

PLACE_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="sunshine_today",
        name="Sunshine today",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-sunny",
    ),
    SensorEntityDescription(
        key="precipitation_today",
        name="Precipitation today",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-rainy",
    ),
    SensorEntityDescription(
        key="precipitation_probability_max_today",
        name="Max precipitation probability today",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
    ),
    SensorEntityDescription(
        key="wind_max_today",
        name="Max wind today",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-windy",
    ),
    SensorEntityDescription(
        key="sunrise",
        name="Sunrise",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-up",
    ),
    SensorEntityDescription(
        key="sunset",
        name="Sunset",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-down",
    ),
    SensorEntityDescription(
        key="current_icon_code",
        name="Current icon code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:image-outline",
    ),
    SensorEntityDescription(
        key="climate_normals",
        name="Climate normals",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chart-bell-curve",
    ),
    SensorEntityDescription(
        key="forecast_graph",
        name="Forecast graph data",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chart-line",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up place and station sensors for a config entry."""
    coordinator: MeteoSwissCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        MeteoSwissPlaceSensor(coordinator, entry, description)
        for description in PLACE_SENSORS
    ]
    data: MeteoData | None = coordinator.data
    if data is not None and data.station is not None:
        entities.extend(
            MeteoSwissStationSensor(coordinator, entry, column)
            for column in data.station.values
            if column in STATION_COLUMNS
        )
    async_add_entities(entities)


class _BaseSensor(CoordinatorEntity[MeteoSwissCoordinator], SensorEntity):
    """Shared device info / attribution handling."""

    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: MeteoSwissCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        name = entry.data.get(CONF_NAME) or entry.data[CONF_POSTCODE]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": name,
            "manufacturer": "MeteoSwiss",
            "model": "MeteoSwiss place forecast",
        }

    @property
    def _place(self) -> PlaceForecast:
        return self.coordinator.data.place

    @property
    def _today(self) -> date:
        from .models import LOCAL_TZ

        return datetime.now(LOCAL_TZ).date()


class MeteoSwissPlaceSensor(_BaseSensor):
    """One derived or diagnostic sensor from the place payload."""

    def __init__(
        self,
        coordinator: MeteoSwissCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        place = self._place
        key = self.entity_description.key
        if key == "sunshine_today":
            return place.sunshine_hours_for_day(self._today)
        if key == "precipitation_today":
            return place.precipitation_for_day(self._today)["precipitation"]
        if key == "precipitation_probability_max_today":
            return place.max_precipitation_probability_for_day(self._today)
        if key == "wind_max_today":
            return place.max_wind_for_day(self._today)["wind_speed_max"]
        if key == "sunrise":
            return place.graph.sunrise(0)
        if key == "sunset":
            return place.graph.sunset(0)
        if key == "current_icon_code":
            return place.current.icon
        if key == "climate_normals":
            if place.climate is None:
                return None
            return place.climate.current_month_norm_temperature(
                datetime.now(timezone.utc)
            )
        if key == "forecast_graph":
            start = place.graph.start
            return start.isoformat() if start else None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        place = self._place
        key = self.entity_description.key
        attrs: dict[str, Any] = {"source": ATTRIBUTION}
        if key == "sunshine_today":
            attrs["sunshine_minutes"] = (
                round(v * 60, 1)
                if (v := place.sunshine_hours_for_day(self._today)) is not None
                else None
            )
            attrs["sunshine_series_1h"] = place.graph.get("sunshine1h")
        elif key == "precipitation_today":
            sums = place.precipitation_for_day(self._today)
            attrs["precipitation_min_today"] = sums["precipitation_min"]
            attrs["precipitation_max_today"] = sums["precipitation_max"]
            attrs["precipitation_series_1h"] = place.graph.get("precipitation1h")
            attrs["precipitation_series_10m"] = place.graph.get("precipitation10m")
            attrs["precipitation_min_series_1h"] = place.graph.get("precipitationMin1h")
            attrs["precipitation_max_series_1h"] = place.graph.get("precipitationMax1h")
            attrs["precipitation_min_series_10m"] = place.graph.get("precipitationMin10m")
            attrs["precipitation_max_series_10m"] = place.graph.get("precipitationMax10m")
        elif key == "precipitation_probability_max_today":
            attrs["precipitation_probability_series_3h"] = place.graph.get(
                "precipitationProbability3h"
            )
        elif key == "wind_max_today":
            attrs["wind_gust_max_today"] = place.max_wind_for_day(self._today)[
                "wind_gust_max"
            ]
            attrs["wind_speed_series_1h"] = place.graph.get("windSpeed1h")
            attrs["wind_gust_series_1h"] = place.graph.get("gustSpeed1h")
            attrs["wind_speed_q10_series_1h"] = place.graph.get("windSpeed1hq10")
            attrs["wind_speed_q90_series_1h"] = place.graph.get("windSpeed1hq90")
            attrs["wind_gust_q10_series_1h"] = place.graph.get("gustSpeed1hq10")
            attrs["wind_gust_q90_series_1h"] = place.graph.get("gustSpeed1hq90")
            attrs["wind_speed_series_3h"] = place.graph.get("windSpeed3h")
            attrs["wind_direction_series_3h"] = place.graph.get("windDirection3h")
        elif key == "sunrise":
            attrs["sunrise_series"] = [
                ts.isoformat()
                for ts in (
                    place.graph.sunrise(i) for i in range(len(place.graph.get("sunrise")))
                )
                if ts is not None
            ]
        elif key == "sunset":
            attrs["sunset_series"] = [
                ts.isoformat()
                for ts in (
                    place.graph.sunset(i) for i in range(len(place.graph.get("sunset")))
                )
                if ts is not None
            ]
        elif key == "current_icon_code":
            attrs["icon_code_v2"] = place.current.icon_v2
            attrs["current_weather_time"] = (
                place.current.time.isoformat() if place.current.time else None
            )
            attrs["weather_icon_series_3h"] = place.graph.get("weatherIcon3h")
            attrs["weather_icon_series_3h_v2"] = place.graph.get("weatherIcon3hV2")
        elif key == "climate_normals" and place.climate is not None:
            climate = place.climate
            attrs["klima_plz"] = climate.plz
            attrs["klima_start"] = climate.start.isoformat() if climate.start else None
            attrs["temperature_graph_values"] = climate.temperature
            attrs["precipitation_graph_values"] = climate.precipitation
            attrs["sunshine_graph_values"] = climate.sunshine
        elif key == "forecast_graph":
            # The complete graph: every series the API returned.
            attrs["graph_series"] = place.graph.series
            attrs["graph_start_low_resolution"] = (
                place.graph.start_low_resolution.isoformat()
                if place.graph.start_low_resolution
                else None
            )
            attrs["source_endpoint"] = place.source_endpoint
        return attrs


class MeteoSwissStationSensor(_BaseSensor):
    """One sensor per SwissMetNet CSV column for the configured station."""

    def __init__(
        self,
        coordinator: MeteoSwissCoordinator,
        entry: ConfigEntry,
        column: str,
    ) -> None:
        super().__init__(coordinator, entry)
        name, unit, device_class, state_class = STATION_COLUMNS[column]
        self._column = column
        station_code = (entry.data.get(CONF_STATION) or "").upper()
        self.entity_description = SensorEntityDescription(
            key=f"station_{column}",
            name=f"{station_code} {name}" if station_code else name,
            native_unit_of_measurement=_UNITS.get(unit) if unit else None,
            device_class=_DEVICE_CLASSES.get(device_class) if device_class else None,
            state_class=SensorStateClass.MEASUREMENT if state_class else None,
        )
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_station_{column}"
        )

    @property
    def _station(self) -> StationObservation | None:
        data = self.coordinator.data
        return data.station if data else None

    @property
    def native_value(self) -> float | None:
        station = self._station
        return station.get(self._column) if station else None

    @property
    def available(self) -> bool:
        # A column that exists but currently reports '-' still yields an
        # entity whose state is unknown/None, so treat presence of the
        # station row as available.
        return super().available and self._station is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station
        attrs: dict[str, Any] = {
            "source": ATTRIBUTION,
            "station_code": station.code if station else None,
            "column": self._column,
            "data_file": station.source if station else None,
        }
        if station is not None and station.measured_at is not None:
            attrs["measured_at"] = station.measured_at.isoformat()
        return attrs
