"""Sensor platform for WetterOnline.

Exposes the extra data points that do not fit the single weather entity
(astronomy, today's aggregates) as individual sensors so they can be graphed
and used in automations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    UnitOfPrecipitationDepth,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import WeatherData
from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import WetterOnlineConfigEntry, WetterOnlineCoordinator


def _time_today(hhmm: str | None) -> datetime | None:
    """Combine 'HH:MM' with today's local date into an aware datetime."""
    if not hhmm:
        return None
    try:
        hour, minute = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return None
    now = dt_util.now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _day0(data: WeatherData):
    return data.daily[0] if data.daily else None


@dataclass(frozen=True, kw_only=True)
class WoSensorDescription(SensorEntityDescription):
    """Describes a WetterOnline sensor."""

    value_fn: Callable[[WeatherData], StateType | datetime]


SENSORS: tuple[WoSensorDescription, ...] = (
    WoSensorDescription(
        key="current_temperature",
        name="Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.current.temperature,
    ),
    WoSensorDescription(
        key="current_wind_bearing",
        name="Windrichtung",
        native_unit_of_measurement=DEGREE,
        icon="mdi:compass-outline",
        value_fn=lambda d: d.current.wind_bearing,
    ),
    WoSensorDescription(
        key="sunrise",
        name="Sonnenaufgang",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-up",
        value_fn=lambda d: _time_today(d.astro.sunrise),
    ),
    WoSensorDescription(
        key="sunset",
        name="Sonnenuntergang",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-down",
        value_fn=lambda d: _time_today(d.astro.sunset),
    ),
    WoSensorDescription(
        key="sun_elevation",
        name="Sonnenstand",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-sunny",
        value_fn=lambda d: d.astro.sun_elevation,
    ),
    WoSensorDescription(
        key="today_temp_max",
        name="Höchsttemperatur heute",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: getattr(_day0(d), "temperature", None),
    ),
    WoSensorDescription(
        key="today_temp_min",
        name="Tiefsttemperatur heute",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: getattr(_day0(d), "templow", None),
    ),
    WoSensorDescription(
        key="today_precipitation",
        name="Niederschlag heute",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: getattr(_day0(d), "precipitation", None),
    ),
    WoSensorDescription(
        key="today_precipitation_probability",
        name="Regenwahrscheinlichkeit heute",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-rainy",
        value_fn=lambda d: getattr(_day0(d), "precipitation_probability", None),
    ),
    WoSensorDescription(
        key="today_sun_hours",
        name="Sonnenstunden heute",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:weather-sunny",
        value_fn=lambda d: getattr(_day0(d), "sun_hours", None),
    ),
    WoSensorDescription(
        key="today_wind_gust",
        name="Windböen heute",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        value_fn=lambda d: getattr(_day0(d), "wind_gust_speed", None),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WetterOnline sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        WetterOnlineSensor(coordinator, entry, description) for description in SENSORS
    )


class WetterOnlineSensor(
    CoordinatorEntity[WetterOnlineCoordinator], SensorEntity
):
    """A single scraped value from wetteronline.de."""

    entity_description: WoSensorDescription
    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WetterOnlineCoordinator,
        entry: WetterOnlineConfigEntry,
        description: WoSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.location_name,
            manufacturer=MANUFACTURER,
            model="City forecast",
            configuration_url=f"https://www.wetteronline.de/wetter/{coordinator.slug}",
        )

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)
