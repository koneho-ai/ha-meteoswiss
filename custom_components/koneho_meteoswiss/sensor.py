"""Sensors for the MeteoSwiss (Koneho) integration.

Two families:

- Place sensors derived from the plzDetail/forecast payload (today's
  sunshine, precipitation, precipitation probability, wind/gust,
  sunrise, sunset, current icon code, current forecast wind speed /
  gust / direction, and a readable Warnings sensor whose attributes
  carry the full warning texts), plus two diagnostic sensors that
  expose the *complete* graph series and the klimaGraph so no field
  returned by the API is dropped.
- Station sensors: one per SwissMetNet CSV column that carries a
  value for the effective station — manually configured or the
  auto-selected nearest one (VQHA80, merged with VQHA98).
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
    DEGREE,
    MATCH_ALL,
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
    WARN_LEVEL_NAMES,
    warnings_number,
)
from .coordinator import MeteoSwissCoordinator
from .models import (
    MeteoData,
    PlaceForecast,
    StationObservation,
    present_station_columns,
    stale_station_sensor_unique_ids,
)
from .pollen import (
    POLLEN_LEVELS,
    POLLEN_PLANT_KEYS,
    POLLEN_PLANT_NAMES,
    PollenData,
    pollen_level_color,
)

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
        key="wind_speed_current",
        name="Wind speed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-windy",
    ),
    SensorEntityDescription(
        key="wind_gust_current",
        name="Wind gust",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-windy-variant",
    ),
    SensorEntityDescription(
        key="wind_direction_current",
        name="Wind direction",
        native_unit_of_measurement=DEGREE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
        # HA requires MEASUREMENT_ANGLE (not MEASUREMENT) for the
        # wind_direction device class.
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        icon="mdi:compass-outline",
    ),
    SensorEntityDescription(
        key="warnings_summary",
        name="Warnings",
        icon="mdi:alert-outline",
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
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
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


def _remove_stale_station_sensor_entities(
    hass: HomeAssistant, entry: ConfigEntry, current_columns: tuple[str, ...]
) -> None:
    """Remove registry entries for station columns with no current value.

    Upgraded installs created one entity for every CSV column before
    v0.2.1, including instruments a station does not report. Removing
    only this config entry's sensor-platform entries whose station
    unique ID is absent from the current, present-column set lets those
    dead entities disappear without touching place sensors or entries
    belonging to other integrations/config entries.

    The entity-registry import is local and guarded: this module's pure
    selection/model helpers remain testable in environments where HA is
    unavailable, and a registry API difference should not prevent the
    remaining sensors from being set up.
    """
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:  # pragma: no cover - HA is present in production
        return

    try:
        registry = er.async_get(hass)
        try:
            registry_entries = er.async_entries_for_config_entry(
                registry, entry.entry_id
            )
        except (AttributeError, TypeError):
            registry_entries = [
                registry_entry
                for registry_entry in registry.entities.values()
                if registry_entry.config_entry_id == entry.entry_id
            ]
        candidates = [
            registry_entry
            for registry_entry in list(registry_entries)
            if getattr(registry_entry, "platform", None) == DOMAIN
            and getattr(registry_entry, "domain", None) == "sensor"
        ]
        stale_unique_ids = set(
            stale_station_sensor_unique_ids(
                (getattr(registry_entry, "unique_id", "") for registry_entry in candidates),
                entry.unique_id or entry.entry_id,
                current_columns,
            )
        )
        for registry_entry in candidates:
            if registry_entry.unique_id in stale_unique_ids:
                registry.async_remove(registry_entry.entity_id)
    except (AttributeError, KeyError, TypeError, ValueError):
        # Registry cleanup is a migration nicety, not a reason to fail
        # the whole sensor platform if a future HA registry shape moves.
        return


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
        station_columns = present_station_columns(data.station)
        _remove_stale_station_sensor_entities(hass, entry, station_columns)
        # Use the *effective* station code (manually configured or
        # auto-selected) from the coordinator data for naming.
        entities.extend(
            MeteoSwissStationSensor(coordinator, entry, column, data.station.code)
            for column in station_columns
        )
    # Per-rank warning sensor pairs (type + level), count from the
    # entry's warnings_number setting. Created unconditionally like
    # the other place sensors; they read as unknown while no warning
    # is active at their rank.
    for rank in range(warnings_number(entry.data)):
        entities.append(MeteoSwissWarningTypeSensor(coordinator, entry, rank))
        entities.append(MeteoSwissWarningLevelSensor(coordinator, entry, rank))
    # Pollen sensors only exist while pollen data is available for
    # the entry's pollen station (sparse network; most stations
    # report all seven plants, but availability is data-driven).
    if data is not None and data.pollen is not None:
        entities.append(MeteoSwissPollenSensor(coordinator, entry, "timestamp"))
        for plant_key in POLLEN_PLANT_KEYS:
            entities.append(
                MeteoSwissPollenSensor(coordinator, entry, "value", plant_key)
            )
            entities.append(
                MeteoSwissPollenSensor(coordinator, entry, "level", plant_key)
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
        if description.key == "warnings_summary":
            # The summary carries the full warning records as
            # attributes; keep those out of the recorder.
            self._entity_component_unrecorded_attributes = MATCH_ALL

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
        if key == "wind_speed_current":
            value = place.graph.value_at("windSpeed1h", datetime.now(timezone.utc))
            return float(value) if value is not None else None
        if key == "wind_gust_current":
            value = place.graph.value_at("gustSpeed1h", datetime.now(timezone.utc))
            return float(value) if value is not None else None
        if key == "wind_direction_current":
            value = place.graph.value_at(
                "windDirection3h", datetime.now(timezone.utc)
            )
            return float(value) if value is not None else None
        if key == "warnings_summary":
            return place.warnings_summary()["state"]
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
        elif key == "wind_speed_current":
            attrs["wind_speed_series_1h"] = place.graph.get("windSpeed1h")
            attrs["wind_speed_q10_series_1h"] = place.graph.get("windSpeed1hq10")
            attrs["wind_speed_q90_series_1h"] = place.graph.get("windSpeed1hq90")
            attrs["wind_speed_series_3h"] = place.graph.get("windSpeed3h")
        elif key == "wind_gust_current":
            attrs["wind_gust_series_1h"] = place.graph.get("gustSpeed1h")
            attrs["wind_gust_q10_series_1h"] = place.graph.get("gustSpeed1hq10")
            attrs["wind_gust_q90_series_1h"] = place.graph.get("gustSpeed1hq90")
        elif key == "wind_direction_current":
            attrs["wind_direction_series_3h"] = place.graph.get("windDirection3h")
        elif key == "warnings_summary":
            summary = place.warnings_summary()
            attrs["warnings_count"] = summary["count"]
            # Only warnings still in force (the summary filters
            # expired records); the raw payload records stay on the
            # forecast-graph sensor attributes.
            attrs["warnings"] = summary["warnings"]
            attrs["warnings_text"] = summary["text_joined"]
            attrs["warn_types"] = summary["warn_types"]
            attrs["warn_type_names"] = summary["warn_type_names"]
            attrs["max_warn_level"] = summary["max_level"]
            attrs["valid_from"] = summary["valid_from"]
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
            data = self.coordinator.data
            attrs["station_code"] = data.station.code if data and data.station else None
            attrs["station_auto_selected"] = bool(data and data.station_auto_selected)
            attrs["station_distance_km"] = data.station_distance_km if data else None
            attrs["station_temperature_available"] = (
                data.station_has_temperature if data else None
            )
            pollen = data.pollen if data else None
            attrs["pollen_station_code"] = (
                getattr(pollen, "station_code", None) if pollen else None
            )
            attrs["pollen_station_name"] = (
                getattr(pollen, "station_name", None) if pollen else None
            )
        return attrs


class MeteoSwissStationSensor(_BaseSensor):
    """One sensor per SwissMetNet CSV column for the configured station."""

    def __init__(
        self,
        coordinator: MeteoSwissCoordinator,
        entry: ConfigEntry,
        column: str,
        station_code: str = "",
    ) -> None:
        super().__init__(coordinator, entry)
        name, unit, device_class, state_class = STATION_COLUMNS[column]
        self._column = column
        if not station_code:
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
        # Entities are created only for columns present at platform
        # setup. A later individual '-' should not make the whole
        # entity unavailable merely because its current value is None;
        # presence of the station row is the availability signal here.
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


class _WarningRankSensorBase(_BaseSensor):
    """Base for the per-rank warning sensors.

    Rank 0 is the most severe *active* warning (expired records are
    filtered by the model). The pair per rank mirrors the classic
    hass-swissweather warning sensors: a type sensor carrying the
    full warning detail as attributes and a level sensor carrying a
    numeric level + icon colour. Both keep their attributes out of
    the recorder — warning texts and HTML are heavy and change rarely.
    """

    _entity_component_unrecorded_attributes = MATCH_ALL

    def __init__(
        self,
        coordinator: MeteoSwissCoordinator,
        entry: ConfigEntry,
        rank: int,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._rank = rank
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_{description.key}"
        )

    @property
    def _details(self) -> dict[str, Any] | None:
        return self._place.warning_at_rank(self._rank)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source": ATTRIBUTION}


class MeteoSwissWarningTypeSensor(_WarningRankSensorBase):
    """Type of the warning at one severity rank."""

    def __init__(
        self,
        coordinator: MeteoSwissCoordinator,
        entry: ConfigEntry,
        rank: int,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            rank,
            SensorEntityDescription(
                key=f"warning_{rank + 1}_type",
                name=f"Warning {rank + 1} type",
                icon="mdi:alert",
            ),
        )

    @property
    def native_value(self) -> str | None:
        details = self._details
        return details["type_name"] if details else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        details = self._details
        if details is None:
            return attrs
        attrs.update(
            {
                "level": details["level"],
                "level_numeric": details["level_numeric"],
                "text": details["text"],
                "html_text": details["html_text"],
                "valid_from": details["valid_from"],
                "valid_to": details["valid_to"],
                "links": details["links"],
                "outlook": details["outlook"],
                "icon_color": details["icon_color"],
            }
        )
        return attrs


class MeteoSwissWarningLevelSensor(_WarningRankSensorBase):
    """Level (hazard name) of the warning at one severity rank."""

    def __init__(
        self,
        coordinator: MeteoSwissCoordinator,
        entry: ConfigEntry,
        rank: int,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            rank,
            SensorEntityDescription(
                key=f"warning_{rank + 1}_level",
                name=f"Warning {rank + 1} level",
                icon="mdi:alert",
                device_class=SensorDeviceClass.ENUM,
            ),
        )
        self._attr_options = list(WARN_LEVEL_NAMES.values())

    @property
    def native_value(self) -> str | None:
        details = self._details
        return details["level"] if details else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        details = self._details
        if details is not None:
            attrs["numeric"] = details["level_numeric"]
            attrs["icon_color"] = details["icon_color"]
        return attrs


class MeteoSwissPollenSensor(_BaseSensor):
    """Pollen concentration / level / measurement-time sensor.

    One instance per plant and mode ("value" concentration in
    pollen/m³, "level" load class), plus one station-wide
    "timestamp" instance. Entities are only created while pollen
    data is available; a later failed pollen fetch makes them
    unavailable for that cycle instead of failing the update.
    """

    def __init__(
        self,
        coordinator: MeteoSwissCoordinator,
        entry: ConfigEntry,
        mode: str,
        plant_key: str | None = None,
    ) -> None:
        super().__init__(coordinator, entry)
        self._mode = mode
        self._plant_key = plant_key
        if mode == "timestamp":
            key = "pollen_measured_at"
            name = "Pollen measurement"
            description = SensorEntityDescription(
                key=key,
                name=name,
                icon="mdi:clock-outline",
                device_class=SensorDeviceClass.TIMESTAMP,
            )
        elif mode == "value":
            plant_name = POLLEN_PLANT_NAMES[plant_key]  # type: ignore[index]
            description = SensorEntityDescription(
                key=f"pollen_{plant_key}",
                name=f"Pollen {plant_name}",
                icon="mdi:flower-pollen",
                native_unit_of_measurement="p/m³",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
            )
        else:
            plant_name = POLLEN_PLANT_NAMES[plant_key]  # type: ignore[index]
            description = SensorEntityDescription(
                key=f"pollen_{plant_key}_level",
                name=f"Pollen {plant_name} level",
                icon="mdi:flower-pollen-outline",
                device_class=SensorDeviceClass.ENUM,
            )
            self._attr_options = list(POLLEN_LEVELS)
            # The level sensor carries the raw concentration as an
            # attribute; keep it out of the recorder.
            self._entity_component_unrecorded_attributes = MATCH_ALL
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @property
    def _pollen(self) -> PollenData | None:
        data = self.coordinator.data
        pollen = data.pollen if data else None
        return pollen if isinstance(pollen, PollenData) else None

    @property
    def available(self) -> bool:
        return super().available and self._pollen is not None

    @property
    def native_value(self) -> Any:
        pollen = self._pollen
        if pollen is None:
            return None
        if self._mode == "timestamp":
            return pollen.measured_at
        if self._mode == "value":
            return pollen.value(self._plant_key)  # type: ignore[arg-type]
        return pollen.level(self._plant_key)  # type: ignore[arg-type]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pollen = self._pollen
        attrs: dict[str, Any] = {
            "source": ATTRIBUTION,
            "pollen_station_code": pollen.station_code if pollen else None,
            "pollen_station_name": pollen.station_name if pollen else None,
        }
        if self._mode == "level" and pollen is not None:
            level = pollen.level(self._plant_key)  # type: ignore[arg-type]
            attrs["icon_color"] = pollen_level_color(level)
            attrs["concentration"] = pollen.value(self._plant_key)  # type: ignore[arg-type]
        return attrs
