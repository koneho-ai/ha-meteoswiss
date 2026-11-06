"""DataUpdateCoordinator for the MeteoSwiss (Koneho) integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import MeteoSwissApiError, MeteoSwissClient
from .const import DOMAIN, UPDATE_INTERVAL
from .models import MeteoData
from .repairs import (
    ISSUE_TRANSLATION_KEY,
    ManualStationWatch,
    issue_id_for_entry,
    station_data_missing,
)

_LOGGER = logging.getLogger(__name__)


class MeteoSwissCoordinator(DataUpdateCoordinator[MeteoData]):
    """Fetch plzDetail/forecast + station data for one config entry.

    The update interval is per entry (configurable in the config /
    reconfigure flow, defaulting to ``UPDATE_INTERVAL``). Station
    handling (including automatic nearest-station selection when no
    station code is configured) lives in the client; every coordinator
    refresh re-runs it, so the auto-selected station can follow changes
    in station availability.

    For a *manually configured* station the coordinator also watches
    for the station vanishing from the SwissMetNet data and surfaces
    that as a Repairs issue (see :mod:`.repairs`); auto-selected
    stations are never watched — they re-pick silently.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: MeteoSwissClient,
        name: str,
        update_interval: timedelta | None = None,
        entry_id: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{name}",
            update_interval=update_interval or UPDATE_INTERVAL,
        )
        self.client = client
        self._entry_id = entry_id
        # Only manual stations are watched; without an entry id there
        # is no stable issue id, so the watch stays disabled.
        self._station_watch = (
            ManualStationWatch()
            if client.station is not None and entry_id is not None
            else None
        )

    async def _async_update_data(self) -> MeteoData:
        try:
            data = await self.client.async_get_data()
        except MeteoSwissApiError as err:
            raise UpdateFailed(str(err)) from err
        self._update_manual_station_issue(data)
        return data

    def _update_manual_station_issue(self, data: MeteoData) -> None:
        """Raise/clear the Repairs issue for a dead manual station."""
        watch = self._station_watch
        if watch is None or self._entry_id is None:
            return
        action = watch.observe(station_data_missing(data.station))
        if action is None:
            return
        # Local, guarded import — same pattern as the entity-registry
        # cleanup in sensor.py: an issue-registry API difference must
        # never break data updates.
        try:
            from homeassistant.helpers import issue_registry as ir
        except ImportError:  # pragma: no cover - HA is present in production
            return
        try:
            if action == "raise":
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id_for_entry(self._entry_id),
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_TRANSLATION_KEY,
                    translation_placeholders={"station": self.client.station or ""},
                )
            else:  # "clear"
                ir.async_delete_issue(
                    self.hass, DOMAIN, issue_id_for_entry(self._entry_id)
                )
        except Exception:  # noqa: BLE001 - issue handling must not fail updates
            _LOGGER.debug(
                "Could not %s Repairs issue for station %s",
                action,
                self.client.station,
                exc_info=True,
            )
