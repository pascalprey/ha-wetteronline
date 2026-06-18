"""DataUpdateCoordinator for WetterOnline."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WeatherData,
    WetterOnlineClient,
    WetterOnlineConnectionError,
    parse_weather,
)
from .const import (
    CONF_LOCATION_NAME,
    CONF_SCAN_INTERVAL,
    CONF_SLUG,
    DEFAULT_SCAN_INTERVAL_MIN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type WetterOnlineConfigEntry = ConfigEntry[WetterOnlineCoordinator]


class WetterOnlineCoordinator(DataUpdateCoordinator[WeatherData]):
    """Fetch and parse the wetteronline.de city page on a schedule."""

    config_entry: WetterOnlineConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: WetterOnlineConfigEntry
    ) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )
        self.client = WetterOnlineClient(async_get_clientsession(hass))
        self.slug: str = entry.data[CONF_SLUG]
        self.location_name: str = entry.data.get(CONF_LOCATION_NAME, self.slug)

    async def _async_update_data(self) -> WeatherData:
        try:
            raw_html = await self.client.async_fetch_html(self.slug)
        except WetterOnlineConnectionError as err:
            raise UpdateFailed(f"Error fetching wetteronline.de: {err}") from err

        # BeautifulSoup parsing is CPU-bound/blocking -> run off the event loop.
        data = await self.hass.async_add_executor_job(parse_weather, raw_html)
        if data.current.temperature is None and not data.daily:
            raise UpdateFailed("Could not parse any weather data from the page")
        return data
