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
    OT_FAULT_HISTORY_ENTRY_ID,
    OT_FAULT_HISTORY_MAX,
    OT_FAULT_HISTORY_SIZE_ID,
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
from .stats_entities import STAT_SPECS, ImmergasStatSensor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_PROTOCOL) == PROTOCOL_OPENTHERM:
        from .ot_diagnostics import OtLastWriteSensor, OtScanSensor
        from .ot_programs import ot_sensors
        from .ot_stats import ot_stat_sensors
        async_add_entities([*ot_sensors(coordinator), OtScanSensor(coordinator), OtLastWriteSensor(coordinator),
                            ImmergasOpenThermFaultHistorySensor(coordinator), ImmergasOpenThermFaultDescriptionSensor(coordinator),
                            *ot_stat_sensors(coordinator)])
        if getattr(coordinator, "ot_computed", None) is not None:
            from .ot_computed import ot_computed_sensors
            async_add_entities(ot_computed_sensors(coordinator))
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
    entities += [ImmergasStatSensor(coordinator, spec) for spec in STAT_SPECS]
    if getattr(coordinator, "stats_extra", None) is not None:
        from .stats_extra import stats_extra_sensors
        entities += stats_extra_sensors(coordinator)
    if coordinator.dhw is not None:
        entities.append(ImmergasDhwPhaseSensor(coordinator))
    if getattr(coordinator, "pdu_scan", None) is not None:
        from .pdu_scan import pdu_scan_sensors
        entities += pdu_scan_sensors(coordinator)
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
        lang = self.coordinator.fault_language
        return anomalies.describe(int(raw), self.hass.config.language if lang == "auto" else lang)


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
        if decode == "f88_pos":  # f8.8, negative = not available
            return None if raw & 0x8000 else round(raw / 256, 1)
        if decode == "f88_probe":  # f8.8, 0x7300 (115.0) = no probe connected
            if raw == 0x7300:
                return None
            signed = raw - 0x10000 if raw & 0x8000 else raw
            return round(signed / 256, 1)
        if decode == "dow_time":  # HH:MM; the day of week in the attributes
            return f"{(raw >> 8) & 0x1F:02d}:{raw & 0xFF:02d}"
        if decode == "lb_u8":
            return raw & 0xFF
        if decode == "hb_u8":
            return raw >> 8
        if decode == "lb_rpm":
            return (raw & 0xFF) * 60
        if decode == "hb_rpm":
            return (raw >> 8) * 60
        return raw  # u16

    @property
    def extra_state_attributes(self) -> dict[str, int | None] | None:
        if self.entity_description.decode != "dow_time" or self.raw_value is None:
            return None
        day = (int(self.raw_value) >> 13) & 0x07
        return {"weekday": day or None}  # 1 = Monday ... 7 = Sunday, 0 = not set


class ImmergasOpenThermFaultDescriptionSensor(ImmergasDominusEntity, SensorEntity):
    """1.6.9: description of the boiler fault code (Data-ID 5 low byte = the Immergas code, e.g. 31 = E31) in the Home
    Assistant language, like the Modbus mode's fault description (same translation key, so the cards find it)."""

    _attr_translation_key = "fault_description"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_fault_description", 5, DEVICE_MAIN)

    @property
    def native_value(self) -> str | None:
        raw = self.raw_value
        if raw is None:
            return None
        lang = self.coordinator.fault_language
        return anomalies.describe(int(raw) & 0xFF, self.hass.config.language if lang == "auto" else lang)


class ImmergasOpenThermFaultHistorySensor(ImmergasDominusEntity, SensorEntity):
    """Boiler fault history (Data-ID 12 = number of entries, Data-ID 13 indexed = the fault code of each entry).

    The state is the number of entries; the attributes list the codes in the boiler's order (entry 1 = index 0)
    with the integration's own description. The entries are polled only once the boiler reports how many it holds.
    """

    _attr_translation_key = "ot_fault_history"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False  # not every boiler answers it (a timeout per cycle otherwise)
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_fault_history", OT_FAULT_HISTORY_SIZE_ID, DEVICE_MAIN)
        self._entries = 0  # entry keys currently registered for polling

    def _entry_keys(self, count: int) -> tuple[int, ...]:
        from .opentherm_client import ot_param_key
        return tuple(ot_param_key(OT_FAULT_HISTORY_ENTRY_ID, i) for i in range(count))

    def _poll_pdus(self) -> tuple[int, ...]:
        return (OT_FAULT_HISTORY_SIZE_ID, *self._entry_keys(self._entries))

    def _count(self) -> int | None:
        raw = self.raw_value
        return None if raw is None else min((int(raw) >> 8) & 0xFF, OT_FAULT_HISTORY_MAX)

    def _handle_coordinator_update(self) -> None:
        count = self._count()
        if count is not None and count != self._entries:
            # the buffer size became known (or changed): poll exactly that many entries
            self.coordinator.unregister_pdus(self._entry_keys(self._entries))
            self._entries = count
            if self.coordinator.register_pdus(self._entry_keys(count)):
                self.hass.async_create_task(self.coordinator.async_request_refresh())
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> int | None:
        return self._count()

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        data = self.coordinator.data or {}
        lang = self.coordinator.fault_language
        lang = self.hass.config.language if lang == "auto" else lang
        attrs: dict[str, str] = {}
        for i, key in enumerate(self._entry_keys(self._entries), start=1):
            code = data.get(key)
            if code is None:
                continue
            code = int(code) & 0xFF
            attrs[f"entry_{i}"] = anomalies.describe(code, lang) if code else "-"  # "E89: ..."
        return attrs
