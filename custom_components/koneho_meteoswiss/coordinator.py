"""DataUpdateCoordinator for the MeteoSwiss (Koneho) integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import MeteoSwissApiError, MeteoSwissClient
from .const import DOMAIN, UPDATE_INTERVAL
from .models import MeteoData

_LOGGER = logging.getLogger(__name__)


class MeteoSwissCoordinator(DataUpdateCoordinator[MeteoData]):
    """Fetch plzDetail/forecast + station data every 15 minutes.

    Station handling (including automatic nearest-station selection
    when no station code is configured) lives in the client; every
    coordinator refresh re-runs it, so the auto-selected station can
    follow changes in station availability.
    """

    def __init__(
        self, hass: HomeAssistant, client: MeteoSwissClient, name: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{name}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> MeteoData:
        try:
            return await self.client.async_get_data()
        except MeteoSwissApiError as err:
            raise UpdateFailed(str(err)) from err
