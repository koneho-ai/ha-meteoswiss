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


def _form_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME) or ""): str,
            vol.Required(CONF_POSTCODE, default=defaults.get(CONF_POSTCODE) or ""): str,
            vol.Optional(CONF_STATION, default=defaults.get(CONF_STATION) or ""): str,
        }
    )


class MeteoSwissConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MeteoSwiss (Koneho)."""

    VERSION = 1

    async def _async_validate(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, str] | None]:
        """Validate form input; return (errors, cleaned entry data)."""
        errors: dict[str, str] = {}
        name = (user_input.get(CONF_NAME) or "").strip()
        postcode = str(user_input.get(CONF_POSTCODE) or "").strip()
        station = (user_input.get(CONF_STATION) or "").strip().upper()

        if not _POSTCODE_RE.match(postcode) or not (1000 <= int(postcode) <= 9999):
            errors[CONF_POSTCODE] = "invalid_postcode"
        if station and not _STATION_RE.match(station):
            errors[CONF_STATION] = "invalid_station"
        if errors:
            return errors, None

        client = MeteoSwissClient(
            async_get_clientsession(self.hass), postcode, station or None
        )
        try:
            await client.async_fetch_place()
        except MeteoSwissApiError:
            return {"base": "cannot_connect"}, None

        if not name:
            name = f"MeteoSwiss {postcode}"
        return {}, {
            CONF_NAME: name,
            CONF_POSTCODE: postcode,
            CONF_STATION: station,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            postcode = str(user_input.get(CONF_POSTCODE) or "").strip()
            station = (user_input.get(CONF_STATION) or "").strip().upper()
            errors, data = await self._async_validate(user_input)
            if data is not None:
                await self.async_set_unique_id(f"{postcode}_{station or 'place'}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_form_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing name/postcode/station on an existing entry.

        The station field may be cleared to re-enable automatic
        nearest-station selection.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await self._async_validate(user_input)
            if data is not None:
                return self.async_update_reload_and_abort(entry, data_updates=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_form_schema(dict(entry.data)),
            errors=errors,
        )
