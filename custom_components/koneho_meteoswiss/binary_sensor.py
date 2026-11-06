"""Warnings binary sensor for the MeteoSwiss (Koneho) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_NAME, CONF_POSTCODE, DOMAIN
from .coordinator import MeteoSwissCoordinator
from .models import to_datetime


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the warnings binary sensor for a config entry."""
    coordinator: MeteoSwissCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeteoSwissWarningsSensor(coordinator, entry)])


class MeteoSwissWarningsSensor(
    CoordinatorEntity[MeteoSwissCoordinator], BinarySensorEntity
):
    """On while any MeteoSwiss warning is active for the place.

    The full warning records (text, htmlText, warnType, warnLevel,
    validFrom, regionId, ordering, outlook, links) are exposed as
    attributes so nothing from the payload is dropped.
    """

    _attr_has_entity_name = True
    # Renamed from "Warnings" in v0.2.0 (a readable Warnings *sensor*
    # now carries the text); the unique_id below is unchanged so the
    # entity keeps its identity/history.
    _attr_name = "Warnings active"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:alert"
    # The full warning records live in the attributes; keep them out
    # of the recorder so long warning texts don't bloat the database.
    _entity_component_unrecorded_attributes = MATCH_ALL

    def __init__(self, coordinator: MeteoSwissCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        name = entry.data.get(CONF_NAME) or entry.data[CONF_POSTCODE]
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_warnings"
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
    def is_on(self) -> bool:
        # Only warnings still in force count: expired records the API
        # still ships must not keep the sensor on.
        return bool(self._place.active_warnings())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        place = self._place
        warnings: list[dict[str, Any]] = []
        for warning in place.warnings:
            item = dict(warning)
            valid_from = to_datetime(item.get("validFrom"))
            if valid_from is not None:
                item["validFrom"] = valid_from.isoformat()
            warnings.append(item)
        levels = [
            w.get("warnLevel") for w in place.warnings if w.get("warnLevel") is not None
        ]
        overview_levels = [
            w.get("warnLevel")
            for w in place.warnings_overview
            if w.get("warnLevel") is not None
        ]
        all_levels = levels + overview_levels
        return {
            "source": ATTRIBUTION,
            "warnings": warnings,
            "warnings_overview": place.warnings_overview,
            "warnings_count": len(place.warnings),
            "max_warn_level": max(all_levels) if all_levels else None,
            "warn_types": sorted(
                {
                    w.get("warnType")
                    for w in place.warnings + place.warnings_overview
                    if w.get("warnType") is not None
                }
            ),
        }
