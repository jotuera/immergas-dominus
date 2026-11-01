"""Sensor platform for Immergas Dominus."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import anomalies
from .const import (
    CONF_PROTOCOL,
    DEVICE_MAIN,
    DEVICE_ZONE_1,
    DOMAIN,
    FAULT_CODE_PDU,
    OT_SENSOR_DESCRIPTIONS,
    PROGRAM_PHASE_OPTIONS,
    PROTOCOL_OPENTHERM,
    SENSOR_DESCRIPTIONS,
    ZONE_PHASE_COMFORT_MASK,
    ZONE_PHASE_ECONOMY_MASK,
    ZONE_PHASE_MANUAL_MASK,
    ZONE_STATUS_PDU,
    DominusOpenThermSensorDescription,
    DominusSensorEntityDescription,
)
from .coordinator import ImmergasDominusCoordinator
from .dhw_schedule import DHW_TARGET_PDU
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_PROTOCOL) == PROTOCOL_OPENTHERM:
        async_add_entities(
            ImmergasOpenThermSensor(coordinator, description)
            for description in OT_SENSOR_DESCRIPTIONS
        )
        return
    entities: list[SensorEntity] = [
        ImmergasDominusSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(ImmergasDominusFaultCodeSensor(coordinator))
    entities.append(ImmergasDominusFaultDescriptionSensor(coordinator))
    entities.append(ImmergasDominusProgramPhaseSensor(coordinator))
    entities.append(ImmergasLastReadSensor(coordinator))
    entities.append(ImmergasFailedPollsSensor(coordinator))
    if coordinator.dhw is not None:
        entities.append(ImmergasDhwPhaseSensor(coordinator))
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
    """Boiler fault description in the Home Assistant language (the integration's own texts)."""

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
        return anomalies.describe(int(raw), self.hass.config.language)


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


class _ConnectionSensor(ImmergasDominusEntity, SensorEntity):
    """Local TCP connection diagnostics; reads coordinator counters, polls no PDU."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    @property
    def available(self) -> bool:
        return True


class ImmergasLastReadSensor(_ConnectionSensor):
    """Time of the last poll in which the module answered at least one PDU."""

    _attr_translation_key = "last_successful_read"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:lan-check"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "last_successful_read")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_success


class ImmergasFailedPollsSensor(_ConnectionSensor):
    """Polls since Home Assistant started in which the module answered nothing."""

    _attr_translation_key = "failed_polls"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lan-disconnect"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "failed_polls")

    @property
    def native_value(self) -> int:
        return self.coordinator.failed_polls

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"missing_in_last_poll": self.coordinator.missing_last_poll}


class ImmergasDhwPhaseSensor(ImmergasDominusEntity, SensorEntity):
    """Current DHW phase of "DHW Comfort-Eco by schedule" (empty while the switch is off)."""

    _attr_translation_key = "dhw_phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["comfort", "economy"]
    _attr_icon = "mdi:water-boiler-auto"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "dhw_phase", DHW_TARGET_PDU)

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.dhw.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str | None:
        return self.coordinator.dhw.phase


class ImmergasOpenThermSensor(ImmergasDominusEntity, SensorEntity):
    """Read-only OpenTherm Data-ID sensor (f8.8 / u16 / low byte)."""

    entity_description: DominusOpenThermSensorDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusOpenThermSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.data_id, DEVICE_MAIN)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        raw = self.raw_value
        if raw is None:
            return None
        raw = int(raw) & 0xFFFF
        decode = self.entity_description.decode
        if decode == "f88":  # OpenTherm f8.8 signed fixed-point
            signed = raw - 0x10000 if raw & 0x8000 else raw
            return round(signed / 256, 1)
        if decode == "lb_u8":
            return raw & 0xFF
        return raw  # u16
