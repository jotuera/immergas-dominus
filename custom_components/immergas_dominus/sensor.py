"""Sensor platform for Immergas Dominus."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import anomalies
from .const import (
    DEVICE_MAIN,
    DEVICE_ZONE_1,
    DOMAIN,
    FAULT_CODE_PDU,
    PROGRAM_PHASE_OPTIONS,
    SENSOR_DESCRIPTIONS,
    ZONE_PHASE_COMFORT_MASK,
    ZONE_PHASE_ECONOMY_MASK,
    ZONE_PHASE_MANUAL_MASK,
    ZONE_STATUS_PDU,
    DominusSensorEntityDescription,
)
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        ImmergasDominusSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(ImmergasDominusFaultCodeSensor(coordinator))
    entities.append(ImmergasDominusFaultDescriptionSensor(coordinator))
    entities.append(ImmergasDominusProgramPhaseSensor(coordinator))
    async_add_entities(entities)


class ImmergasDominusSensor(ImmergasDominusEntity, SensorEntity):
    """Dominus read-only PDU sensor."""

    entity_description: DominusSensorEntityDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.pdu, description.device_key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | None:
        """Return converted PDU value."""
        raw = self.raw_value
        if raw is None:
            return None
        if raw in self.entity_description.invalid_raw_values:
            # Sentinel value (e.g. 3002 = 255 = no outdoor probe); report as unknown.
            return None
        value = raw * self.entity_description.value_scale
        precision = self.entity_description.suggested_display_precision
        if precision is not None:
            return round(value, precision)
        return value


class ImmergasDominusFaultCodeSensor(ImmergasDominusEntity, SensorEntity):
    """Boiler fault code (PDU 2100): 'OK' when no fault, otherwise 'E<code>'."""

    _attr_translation_key = "fault_code"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "fault_code", FAULT_CODE_PDU, DEVICE_MAIN)

    @property
    def native_value(self) -> str | None:
        raw = self.raw_value
        if raw is None:
            return None
        return "OK" if raw == 0 else f"E{int(raw)}"


class ImmergasDominusFaultDescriptionSensor(ImmergasDominusEntity, SensorEntity):
    """Boiler fault description in Polish (from the Dominus anomalies table)."""

    _attr_translation_key = "fault_description"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "fault_description", FAULT_CODE_PDU, DEVICE_MAIN)

    @property
    def native_value(self) -> str | None:
        raw = self.raw_value
        if raw is None:
            return None
        return anomalies.describe(int(raw))


class ImmergasDominusProgramPhaseSensor(ImmergasDominusEntity, SensorEntity):
    """Zone 1 time-program phase from the zone-status register (PDU 2010).

    bit 2 = manual, bit 6 = comfort, bit 7 = economy (confirmed on the D+/D- bus).
    """

    _attr_translation_key = "program_phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PROGRAM_PHASE_OPTIONS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "program_phase", ZONE_STATUS_PDU, DEVICE_ZONE_1)

    @property
    def native_value(self) -> str | None:
        raw = self.raw_value
        if raw is None:
            return None
        raw = int(raw)
        if raw & ZONE_PHASE_ECONOMY_MASK:
            return "economy"
        if raw & ZONE_PHASE_COMFORT_MASK:
            return "comfort"
        if raw & ZONE_PHASE_MANUAL_MASK:
            return "manual"
        return None
