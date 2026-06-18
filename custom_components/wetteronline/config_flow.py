"""Config flow for WetterOnline."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
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

from .api import (
    LocationResult,
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
    MAX_SCAN_INTERVAL_MIN,
    MIN_SCAN_INTERVAL_MIN,
)

CONF_QUERY = "query"
CONF_SELECTION = "selection"


class WetterOnlineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WetterOnline."""

    VERSION = 1

    def __init__(self) -> None:
        self._results: list[LocationResult] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: ask for a location search string."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = WetterOnlineClient(async_get_clientsession(self.hass))
            try:
                results = await client.async_search_locations(user_input[CONF_QUERY])
            except WetterOnlineConnectionError:
                errors["base"] = "cannot_connect"
            else:
                if not results:
                    errors["base"] = "not_found"
                elif len(results) == 1:
                    return await self._create_entry(results[0])
                else:
                    self._results = results
                    return await self.async_step_select()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): str}),
            errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Disambiguate when the search returned several locations."""
        if user_input is not None:
            chosen = next(
                (r for r in self._results if r.slug == user_input[CONF_SELECTION]),
                None,
            )
            if chosen is not None:
                return await self._create_entry(chosen)

        options = [
            SelectOptionDict(value=r.slug, label=f"{r.name} ({r.slug})")
            for r in self._results
        ]
        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTION): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )

    async def _create_entry(self, result: LocationResult) -> ConfigFlowResult:
        """Validate the slug is reachable and create the config entry."""
        await self.async_set_unique_id(result.slug)
        self._abort_if_unique_id_configured()

        client = WetterOnlineClient(async_get_clientsession(self.hass))
        try:
            raw_html = await client.async_fetch_html(result.slug)
        except WetterOnlineConnectionError:
            return self.async_abort(reason="cannot_connect")

        data = await self.hass.async_add_executor_job(parse_weather, raw_html)
        name = data.location_name or result.name

        return self.async_create_entry(
            title=name,
            data={CONF_SLUG: result.slug, CONF_LOCATION_NAME: name},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> WetterOnlineOptionsFlow:
        return WetterOnlineOptionsFlow()


class WetterOnlineOptionsFlow(OptionsFlow):
    """Allow tuning the polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MIN,
                            max=MAX_SCAN_INTERVAL_MIN,
                            step=5,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    )
                }
            ),
        )
