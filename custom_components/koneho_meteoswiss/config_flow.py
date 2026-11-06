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
    CONF_POLLEN_STATION,
    CONF_POSTCODE,
    CONF_STATION,
    CONF_UPDATE_INTERVAL,
    CONF_WARNINGS_NUMBER,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    MAX_UPDATE_INTERVAL_MINUTES,
    MAX_WARNINGS_NUMBER,
    MIN_UPDATE_INTERVAL_MINUTES,
    MIN_WARNINGS_NUMBER,
    DOMAIN,
    update_interval_minutes,
    warnings_number,
)
from .pollen import build_pollen_station_options
from .stations import LatLon, build_station_options

_LOGGER = logging.getLogger(__name__)

_POSTCODE_RE = re.compile(r"^\d{4}$")
_STATION_RE = re.compile(r"^[A-Z]{3}$")


def _station_selector_field(
    options: list[tuple[str, str]] | None, current: str
) -> Any:
    """Dropdown selector for a station picker, text fallback on None.

    A currently configured value missing from the fetched list stays
    selectable so reconfiguring does not silently drop it.
    """
    if options is None:
        return str
    values = [value for value, _ in options]
    merged = list(options)
    if current and current not in values:
        merged.append((current, current))
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=value, label=label)
                for value, label in merged
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _form_schema(
    defaults: dict[str, Any],
    station_options: list[tuple[str, str]] | None = None,
    pollen_options: list[tuple[str, str]] | None = None,
) -> vol.Schema:
    """Build the user/reconfigure form schema.

    When ``station_options`` / ``pollen_options`` are available
    (metadata fetched), the station fields are dropdowns of
    "Name (CODE)" entries headed by the automatic choice. When one
    is None (metadata fetch failed), that field falls back to the
    free-text code field so setup never hard-blocks on the metadata
    endpoints.
    """
    station_default = defaults.get(CONF_STATION) or ""
    pollen_default = defaults.get(CONF_POLLEN_STATION) or ""
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME) or ""): str,
            vol.Required(CONF_POSTCODE, default=defaults.get(CONF_POSTCODE) or ""): str,
            vol.Optional(CONF_STATION, default=station_default): (
                _station_selector_field(station_options, station_default)
            ),
            vol.Optional(CONF_POLLEN_STATION, default=pollen_default): (
                _station_selector_field(pollen_options, pollen_default)
            ),
            vol.Optional(
                CONF_WARNINGS_NUMBER, default=warnings_number(defaults)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_WARNINGS_NUMBER,
                    max=MAX_WARNINGS_NUMBER,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
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

    def _home_coordinates(self) -> LatLon | None:
        """HA home location for distance labels, when configured."""
        latitude = getattr(self.hass.config, "latitude", None)
        longitude = getattr(self.hass.config, "longitude", None)
        if isinstance(latitude, (int, float)) and isinstance(
            longitude, (int, float)
        ):
            return (float(latitude), float(longitude))
        return None

    async def _async_station_options(self) -> list[tuple[str, str]] | None:
        """Station picker options, or None when metadata is unreachable."""
        client = MeteoSwissClient(async_get_clientsession(self.hass), "1000")
        try:
            directory = await client.async_fetch_station_directory()
            coordinates: dict[str, LatLon] = {}
            home = self._home_coordinates()
            if home is not None:
                coordinates = await client.async_fetch_station_coordinates()
        except MeteoSwissApiError as err:
            _LOGGER.debug("Station list unavailable for config flow: %s", err)
            return None
        if not directory:
            return None
        return build_station_options(directory, coordinates, home)

    async def _async_pollen_options(self) -> list[tuple[str, str]] | None:
        """Pollen picker options, or None when metadata is unreachable."""
        client = MeteoSwissClient(async_get_clientsession(self.hass), "1000")
        try:
            stations = await client.async_fetch_pollen_directory()
        except MeteoSwissApiError as err:
            _LOGGER.debug("Pollen station list unavailable for config flow: %s", err)
            return None
        if not stations:
            return None
        return build_pollen_station_options(stations, self._home_coordinates())

    async def _async_validate(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, Any] | None]:
        """Validate form input; return (errors, cleaned entry data)."""
        errors: dict[str, str] = {}
        name = (user_input.get(CONF_NAME) or "").strip()
        postcode = str(user_input.get(CONF_POSTCODE) or "").strip()
        station = (user_input.get(CONF_STATION) or "").strip().upper()
        pollen_station = (
            user_input.get(CONF_POLLEN_STATION) or ""
        ).strip().upper()

        if not _POSTCODE_RE.match(postcode) or not (1000 <= int(postcode) <= 9999):
            errors[CONF_POSTCODE] = "invalid_postcode"
        if station and not _STATION_RE.match(station):
            errors[CONF_STATION] = "invalid_station"
        if pollen_station and not _STATION_RE.match(pollen_station):
            errors[CONF_POLLEN_STATION] = "invalid_pollen_station"

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

        number_warnings = warnings_number(user_input)
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
            CONF_POLLEN_STATION: pollen_station,
            CONF_WARNINGS_NUMBER: number_warnings,
            CONF_UPDATE_INTERVAL: interval,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        station_options: list[tuple[str, str]] | None = None
        pollen_options: list[tuple[str, str]] | None = None
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
            pollen_options = await self._async_pollen_options()

        return self.async_show_form(
            step_id="user",
            data_schema=_form_schema(user_input or {}, station_options, pollen_options),
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
        pollen_options: list[tuple[str, str]] | None = None
        if user_input is not None:
            errors, data = await self._async_validate(user_input)
            if data is not None:
                return self.async_update_reload_and_abort(entry, data_updates=data)
        else:
            station_options = await self._async_station_options()
            pollen_options = await self._async_pollen_options()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_form_schema(dict(entry.data), station_options, pollen_options),
            errors=errors,
        )
