"""MeteoSwiss (Koneho) integration.

Clean-room Home Assistant integration for MeteoSwiss weather data,
built from scratch against the public MeteoSwiss app API (dual
JSON/XML parsing) and the official SwissMetNet actual-values CSVs.
Source: MeteoSwiss.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import MeteoSwissApiError, MeteoSwissClient
from .const import (
    CONF_NAME,
    CONF_POLLEN_STATION,
    CONF_POSTCODE,
    CONF_STATION,
    DOMAIN,
    resolve_update_interval,
)
from .coordinator import MeteoSwissCoordinator
from .repairs import issue_id_for_entry

PLATFORMS: list[Platform] = [Platform.WEATHER, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one configured place from a config entry."""
    client = MeteoSwissClient(
        async_get_clientsession(hass),
        entry.data[CONF_POSTCODE],
        entry.data.get(CONF_STATION) or None,
        pollen_station=entry.data.get(CONF_POLLEN_STATION) or None,
        language=hass.config.language,
    )
    coordinator = MeteoSwissCoordinator(
        hass,
        client,
        entry.data.get(CONF_NAME) or entry.data[CONF_POSTCODE],
        update_interval=resolve_update_interval(entry.data),
        entry_id=entry.entry_id,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # coordinator wraps API errors in UpdateFailed
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        # Drop a possibly active dead-manual-station Repairs issue;
        # guarded like the coordinator's issue handling.
        try:
            from homeassistant.helpers import issue_registry as ir

            ir.async_delete_issue(hass, DOMAIN, issue_id_for_entry(entry.entry_id))
        except Exception:  # noqa: BLE001 - cleanup must not fail unloading
            pass
    return unloaded
