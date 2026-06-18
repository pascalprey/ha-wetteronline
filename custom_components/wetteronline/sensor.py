"""Sensor platform for WetterOnline.

Surfaces the data that does not fit the single weather entity — current values,
today's aggregates, astronomy, the pollen forecast and severe-weather warnings —
as individual sensors so they can be graphed and used in automations.
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
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import POLLEN_ALLERGENS, POLLEN_LEVELS, WeatherData
from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import WetterOnlineConfigEntry, WetterOnlineCoordinator


def _day0(data: WeatherData):
    return data.daily[0] if data.daily else None


def _ts(iso: str | None) -> datetime | None:
    return dt_util.parse_datetime(iso) if iso else None


def _visibility(data: WeatherData) -> StateType:
    if data.current.visibility is not None:
        return data.current.visibility
    return data.hourly[0].visibility if data.hourly else None


@dataclass(frozen=True, kw_only=True)
class WoSensorDescription(SensorEntityDescription):
    """Describes a WetterOnline sensor."""

    value_fn: Callable[[WeatherData], StateType | datetime]
    attr_fn: Callable[[WeatherData], dict] | None = None


def _convection(data: WeatherData) -> StateType:
    return data.hourly[0].convection_probability if data.hourly else None


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
        key="apparent_temperature",
        name="Gefühlte Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.current.apparent_temperature,
    ),
    WoSensorDescription(
        key="dew_point",
        name="Taupunkt",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.current.dew_point,
    ),
    WoSensorDescription(
        key="humidity",
        name="Luftfeuchtigkeit",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.current.humidity,
    ),
    WoSensorDescription(
        key="pressure",
        name="Luftdruck",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.current.pressure,
    ),
    WoSensorDescription(
        key="wind_speed",
        name="Windgeschwindigkeit",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.current.wind_speed,
    ),
    WoSensorDescription(
        key="wind_gust",
        name="Windböen",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        value_fn=lambda d: d.current.wind_gust_speed,
    ),
    WoSensorDescription(
        key="wind_bearing",
        name="Windrichtung",
        native_unit_of_measurement=DEGREE,
        icon="mdi:compass-outline",
        value_fn=lambda d: d.current.wind_bearing,
    ),
    WoSensorDescription(
        key="precipitation_probability",
        name="Regenwahrscheinlichkeit",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:weather-rainy",
        value_fn=lambda d: d.current.precipitation_probability,
    ),
    WoSensorDescription(
        key="visibility",
        name="Sichtweite",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_fn=_visibility,
    ),
    WoSensorDescription(
        key="uv_index",
        name="UV-Index",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-sunny-alert",
        value_fn=lambda d: getattr(_day0(d), "uv_index", None),
        attr_fn=lambda d: {"description": getattr(_day0(d), "uv_description", None)},
    ),
    WoSensorDescription(
        key="water_temperature",
        name="Wassertemperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:pool-thermometer",
        value_fn=lambda d: d.water_temperature,
    ),
    WoSensorDescription(
        key="convection_probability",
        name="Gewitterneigung",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:weather-lightning",
        value_fn=_convection,
    ),
    WoSensorDescription(
        key="sunshine_hours",
        name="Sonnenstunden heute",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:weather-sunny",
        value_fn=lambda d: getattr(_day0(d), "sunshine_hours", None),
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
        key="sunrise",
        name="Sonnenaufgang",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-up",
        value_fn=lambda d: _ts(d.astro.sunrise),
    ),
    WoSensorDescription(
        key="sunset",
        name="Sonnenuntergang",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-sunset-down",
        value_fn=lambda d: _ts(d.astro.sunset),
    ),
    # --- niche sensors, disabled by default to avoid clutter -----------------
    WoSensorDescription(
        key="solar_elevation",
        name="Sonnenstand",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-sunny",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.current.solar_elevation,
    ),
    WoSensorDescription(
        key="pressure_tendency",
        name="Luftdrucktendenz",
        icon="mdi:gauge",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.current.pressure_tendency,
    ),
    WoSensorDescription(
        key="smog_level",
        name="Smog-Level",
        icon="mdi:smog",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.current.smog_level,
    ),
    WoSensorDescription(
        key="day_length",
        name="Tageslänge",
        icon="mdi:sun-clock",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.astro.day_length,
    ),
    WoSensorDescription(
        key="moon_phase_age",
        name="Mondphase",
        native_unit_of_measurement=UnitOfTime.DAYS,
        icon="mdi:moon-waning-crescent",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.astro.moon_phase_age,
    ),
    WoSensorDescription(
        key="moonrise",
        name="Mondaufgang",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-night",
        entity_registry_enabled_default=False,
        value_fn=lambda d: _ts(d.astro.moonrise),
    ),
    WoSensorDescription(
        key="moonset",
        name="Monduntergang",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:weather-night",
        entity_registry_enabled_default=False,
        value_fn=lambda d: _ts(d.astro.moonset),
    ),
    WoSensorDescription(
        key="precipitation_type",
        name="Niederschlagsart",
        icon="mdi:weather-pouring",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.current.precipitation_type,
    ),
    WoSensorDescription(
        key="significant_weather",
        name="Signifikantes Wetter",
        icon="mdi:weather-cloudy-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: getattr(_day0(d), "significant_weather", None),
    ),
    # Prose forecast text is WetterOnline's copyrighted editorial content; off by
    # default. The full text lives in the "full_text" attribute (state is capped
    # at HA's 255-char limit).
    WoSensorDescription(
        key="forecast_text",
        name="Wetterbericht heute",
        icon="mdi:text-long",
        entity_registry_enabled_default=False,
        value_fn=lambda d: (d.forecast_text or None) and d.forecast_text[:255],
        attr_fn=lambda d: {"full_text": d.forecast_text},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WetterOnline sensors."""
    coordinator = entry.runtime_data
    entities: list[CoordinatorEntity] = [
        WetterOnlineSensor(coordinator, entry, description) for description in SENSORS
    ]
    entities += [
        WetterOnlinePollenSensor(coordinator, entry, allergen)
        for allergen in POLLEN_ALLERGENS
    ]
    entities.append(WetterOnlineWarningsSensor(coordinator, entry))
    async_add_entities(entities)


class _WoBaseEntity(CoordinatorEntity[WetterOnlineCoordinator], SensorEntity):
    """Shared device wiring."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WetterOnlineCoordinator, entry: WetterOnlineConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.location_name,
            manufacturer=MANUFACTURER,
            model="City forecast",
            configuration_url=f"https://www.wetteronline.de/wetter/{coordinator.slug}",
        )


class WetterOnlineSensor(_WoBaseEntity):
    """A single scraped value from wetteronline.de."""

    entity_description: WoSensorDescription

    def __init__(
        self,
        coordinator: WetterOnlineCoordinator,
        entry: WetterOnlineConfigEntry,
        description: WoSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data)


class WetterOnlinePollenSensor(_WoBaseEntity):
    """Today's pollen burden (0-3) for one allergen, with a multi-day forecast."""

    _attr_icon = "mdi:flower-pollen"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: WetterOnlineCoordinator,
        entry: WetterOnlineConfigEntry,
        allergen: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._allergen = allergen
        slug = allergen.lower().translate(
            str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
        )
        self._attr_unique_id = f"{entry.entry_id}_pollen_{slug}"
        self._attr_name = f"Pollen {allergen}"

    @property
    def native_value(self) -> int | None:
        days = self.coordinator.data.pollen
        return days[0].levels.get(self._allergen) if days else None

    @property
    def extra_state_attributes(self) -> dict:
        days = self.coordinator.data.pollen
        level = days[0].levels.get(self._allergen) if days else None
        return {
            "level": POLLEN_LEVELS.get(level) if level is not None else None,
            "forecast": [
                {"date": d.date, "value": d.levels.get(self._allergen)}
                for d in days
            ],
        }


class WetterOnlineWarningsSensor(_WoBaseEntity):
    """Number of active severe-weather warnings, with details in attributes."""

    _attr_name = "Wetterwarnungen"
    _attr_icon = "mdi:alert"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: WetterOnlineCoordinator, entry: WetterOnlineConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_warnings"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.warnings)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "warnings": [
                {
                    "type": w.type,
                    "level": w.level,
                    "headline": w.headline,
                    "start": w.start,
                    "end": w.end,
                }
                for w in self.coordinator.data.warnings
            ]
        }
