"""Config flow for the MeteoSwiss (Koneho) integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .client import MeteoSwissApiError, MeteoSwissClient
from .const import (
    CONF_NAME,
    CONF_POSTCODE,
    CONF_STATION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    MAX_UPDATE_INTERVAL_MINUTES,
    MIN_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    update_interval_minutes,
)
from .stations import build_station_options

_LOGGER = logging.getLogger(__name__)

_POSTCODE_RE = re.compile(r"^\d{4}$")
_STATION_RE = re.compile(r"^[A-Z]{3}$")


def _form_schema(
    defaults: dict[str, Any],
    station_options: list[tuple[str, str]] | None = None,
) -> vol.Schema:
    """Build the user/reconfigure form schema.

    When ``station_options`` is available (station metadata fetched),
    the station field is a dropdown of "Name (CODE)" entries headed by
    the automatic choice. When it is None (metadata fetch failed), the
    field falls back to the free-text code field so setup never
    hard-blocks on the metadata endpoint.
    """
    station_default = defaults.get(CONF_STATION) or ""
    if station_options is not None:
        values = [value for value, _ in station_options]
        options = list(station_options)
        if station_default and station_default not in values:
            # A configured station that vanished from the current list
            # stays selectable so reconfiguring does not silently
            # drop it.
            options.append((station_default, station_default))
        station_field: Any = SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=value, label=label)
                    for value, label in options
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    else:
        station_field = str
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME) or ""): str,
            vol.Required(CONF_POSTCODE, default=defaults.get(CONF_POSTCODE) or ""): str,
            vol.Optional(CONF_STATION, default=station_default): station_field,
            vol.Optional(
                CONF_UPDATE_INTERVAL, default=update_interval_minutes(defaults)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_UPDATE_INTERVAL_MINUTES,
                    max=MAX_UPDATE_INTERVAL_MINUTES,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


class MeteoSwissConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MeteoSwiss (Koneho)."""

    VERSION = 1

    async def _async_station_options(self) -> list[tuple[str, str]] | None:
        """Station picker options, or None when metadata is unreachable."""
        client = MeteoSwissClient(async_get_clientsession(self.hass), "1000")
        try:
            directory = await client.async_fetch_station_directory()
        except MeteoSwissApiError as err:
            _LOGGER.debug("Station list unavailable for config flow: %s", err)
            return None
        if not directory:
            return None
        return build_station_options(directory)

    async def _async_validate(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, Any] | None]:
        """Validate form input; return (errors, cleaned entry data)."""
        errors: dict[str, str] = {}
        name = (user_input.get(CONF_NAME) or "").strip()
        postcode = str(user_input.get(CONF_POSTCODE) or "").strip()
        station = (user_input.get(CONF_STATION) or "").strip().upper()

        if not _POSTCODE_RE.match(postcode) or not (1000 <= int(postcode) <= 9999):
            errors[CONF_POSTCODE] = "invalid_postcode"
        if station and not _STATION_RE.match(station):
            errors[CONF_STATION] = "invalid_station"

        raw_interval = user_input.get(CONF_UPDATE_INTERVAL)
        if raw_interval is None:
            interval = DEFAULT_UPDATE_INTERVAL_MINUTES
        else:
            try:
                interval = int(raw_interval)  # NumberSelector may send floats
            except (TypeError, ValueError):
                interval = -1
            if not (MIN_UPDATE_INTERVAL_MINUTES <= interval <= MAX_UPDATE_INTERVAL_MINUTES):
                errors[CONF_UPDATE_INTERVAL] = "invalid_update_interval"
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
            CONF_UPDATE_INTERVAL: interval,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        station_options: list[tuple[str, str]] | None = None
        if user_input is not None:
            postcode = str(user_input.get(CONF_POSTCODE) or "").strip()
            station = (user_input.get(CONF_STATION) or "").strip().upper()
            errors, data = await self._async_validate(user_input)
            if data is not None:
                await self.async_set_unique_id(f"{postcode}_{station or 'place'}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=data[CONF_NAME], data=data)
        else:
            station_options = await self._async_station_options()

        return self.async_show_form(
            step_id="user",
            data_schema=_form_schema(user_input or {}, station_options),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing name/postcode/station/interval on an entry.

        The station field may be set back to the automatic choice to
        re-enable automatic nearest-station selection.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        station_options: list[tuple[str, str]] | None = None
        if user_input is not None:
            errors, data = await self._async_validate(user_input)
            if data is not None:
                return self.async_update_reload_and_abort(entry, data_updates=data)
        else:
            station_options = await self._async_station_options()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_form_schema(dict(entry.data), station_options),
            errors=errors,
        )
