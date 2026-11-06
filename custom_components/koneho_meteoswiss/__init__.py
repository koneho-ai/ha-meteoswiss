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
from .const import CONF_NAME, CONF_POSTCODE, CONF_STATION, DOMAIN
from .coordinator import MeteoSwissCoordinator

PLATFORMS: list[Platform] = [Platform.WEATHER, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one configured place from a config entry."""
    client = MeteoSwissClient(
        async_get_clientsession(hass),
        entry.data[CONF_POSTCODE],
        entry.data.get(CONF_STATION) or None,
    )
    coordinator = MeteoSwissCoordinator(
        hass, client, entry.data.get(CONF_NAME) or entry.data[CONF_POSTCODE]
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
    return unloaded
