"""Config flow for the MeteoSwiss (Koneho) integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import MeteoSwissApiError, MeteoSwissClient
from .const import CONF_NAME, CONF_POSTCODE, CONF_STATION, DOMAIN

_POSTCODE_RE = re.compile(r"^\d{4}$")
_STATION_RE = re.compile(r"^[A-Z]{3}$")


class MeteoSwissConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MeteoSwiss (Koneho)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or "").strip()
            postcode = str(user_input.get(CONF_POSTCODE) or "").strip()
            station = (user_input.get(CONF_STATION) or "").strip().upper()

            if not _POSTCODE_RE.match(postcode) or not (1000 <= int(postcode) <= 9999):
                errors[CONF_POSTCODE] = "invalid_postcode"
            if station and not _STATION_RE.match(station):
                errors[CONF_STATION] = "invalid_station"

            if not errors:
                await self.async_set_unique_id(f"{postcode}_{station or 'place'}")
                self._abort_if_unique_id_configured()
                client = MeteoSwissClient(
                    async_get_clientsession(self.hass), postcode, station or None
                )
                try:
                    await client.async_fetch_place()
                except MeteoSwissApiError:
                    errors["base"] = "cannot_connect"
                else:
                    if not name:
                        name = f"MeteoSwiss {postcode}"
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_NAME: name,
                            CONF_POSTCODE: postcode,
                            CONF_STATION: station,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=""): str,
                vol.Required(CONF_POSTCODE, default=""): str,
                vol.Optional(CONF_STATION, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
