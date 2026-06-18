"""Weather platform for WetterOnline."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import WeatherData
from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import WetterOnlineConfigEntry, WetterOnlineCoordinator


def _localize(iso: str | None) -> str | None:
    """Return an ISO 8601 string with a timezone for HA's forecast parsing."""
    if not iso:
        return None
    dt = dt_util.parse_datetime(iso)
    if dt is None:
        day = dt_util.parse_date(iso)
        if day is None:
            return None
        dt = datetime(day.year, day.month, day.day)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt.isoformat()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the WetterOnline weather entity."""
    async_add_entities([WetterOnlineWeather(entry.runtime_data, entry)])


class WetterOnlineWeather(CoordinatorEntity[WetterOnlineCoordinator], WeatherEntity):
    """A weather entity backed by the wetteronline.de city page."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self,
        coordinator: WetterOnlineCoordinator,
        entry: WetterOnlineConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.location_name,
            manufacturer=MANUFACTURER,
            model="City forecast",
            configuration_url=f"https://www.wetteronline.de/wetter/{coordinator.slug}",
        )

    @property
    def _data(self) -> WeatherData:
        return self.coordinator.data

    @property
    def condition(self) -> str | None:
        return self._data.current.condition

    @property
    def native_temperature(self) -> float | None:
        return self._data.current.temperature

    @property
    def native_apparent_temperature(self) -> float | None:
        return self._data.current.apparent_temperature

    @property
    def native_dew_point(self) -> float | None:
        return self._data.current.dew_point

    @property
    def humidity(self) -> float | None:
        return self._data.current.humidity

    @property
    def native_pressure(self) -> float | None:
        return self._data.current.pressure

    @property
    def native_visibility(self) -> float | None:
        cur = self._data.current.visibility
        if cur is not None:
            return cur
        return self._data.hourly[0].visibility if self._data.hourly else None

    @property
    def wind_bearing(self) -> float | None:
        return self._data.current.wind_bearing

    @property
    def native_wind_speed(self) -> float | None:
        return self._data.current.wind_speed

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._data.current.wind_gust_speed

    @property
    def uv_index(self) -> float | None:
        # The current block has no UV value; expose today's daily UV index.
        return self._data.daily[0].uv_index if self._data.daily else None

    def _build_daily(self) -> list[Forecast]:
        out: list[Forecast] = []
        for d in self._data.daily:
            out.append(
                Forecast(
                    datetime=_localize(d.datetime),
                    condition=d.condition,
                    native_temperature=d.temperature,
                    native_templow=d.templow,
                    native_apparent_temperature=d.apparent_temperature,
                    humidity=d.humidity,
                    native_pressure=d.pressure,
                    uv_index=d.uv_index,
                    precipitation_probability=d.precipitation_probability,
                    native_precipitation=d.precipitation,
                    wind_bearing=d.wind_bearing,
                    native_wind_speed=d.wind_speed,
                    native_wind_gust_speed=d.wind_gust_speed,
                )
            )
        return out

    def _build_hourly(self) -> list[Forecast]:
        out: list[Forecast] = []
        for h in self._data.hourly:
            out.append(
                Forecast(
                    datetime=_localize(h.datetime),
                    condition=h.condition,
                    native_temperature=h.temperature,
                    native_apparent_temperature=h.apparent_temperature,
                    native_dew_point=h.dew_point,
                    humidity=h.humidity,
                    native_pressure=h.pressure,
                    precipitation_probability=h.precipitation_probability,
                    wind_bearing=h.wind_bearing,
                    native_wind_speed=h.wind_speed,
                    native_wind_gust_speed=h.wind_gust_speed,
                    native_visibility=h.visibility,
                )
            )
        return out

    async def async_forecast_daily(self) -> list[Forecast] | None:
        return self._build_daily()

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        return self._build_hourly()
