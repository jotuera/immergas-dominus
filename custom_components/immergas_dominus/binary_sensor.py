"""Binary sensor platform for Immergas Dominus (boiler fault state)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_PROTOCOL,
    DEVICE_MAIN,
    DEVICE_ZONE_1,
    DHW_REQUEST_MASK,
    DOMAIN,
    FAULT_CODE_PDU,
    FAULT_FLAGS_PDU,
    FAULT_RESET_AVAILABLE_MASK,
    OT_BINARY_DESCRIPTIONS,
    PROTOCOL_OPENTHERM,
    STATUS_FLAGS_PDU,
    ZONE_HEAT_DEMAND_MASK,
    ZONE_STATUS_PDU,
    DominusOpenThermBinaryDescription,
)
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_PROTOCOL) == PROTOCOL_OPENTHERM:
        async_add_entities(
            ImmergasOpenThermBinarySensor(coordinator, description)
            for description in OT_BINARY_DESCRIPTIONS
        )
        return
    async_add_entities(
        [
            ImmergasDominusFaultActiveBinarySensor(coordinator),
            ImmergasDominusResetAvailableBinarySensor(coordinator),
            ImmergasDominusDhwRequestBinarySensor(coordinator),
            ImmergasDominusHeatingDemandBinarySensor(coordinator),
        ]
    )


class ImmergasDominusFaultActiveBinarySensor(ImmergasDominusEntity, BinarySensorEntity):
    """On when the boiler reports a fault (PDU 2100 != 0)."""

    _attr_translation_key = "fault_active"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "fault_active", FAULT_CODE_PDU, DEVICE_MAIN)

    @property
    def is_on(self) -> bool | None:
        raw = self.raw_value
        if raw is None:
            return None
        return raw != 0


class ImmergasDominusResetAvailableBinarySensor(
    ImmergasDominusEntity, BinarySensorEntity
):
    """On when a boiler reset is available (PDU 2101 low-byte bit 1)."""

    _attr_translation_key = "reset_available"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "reset_available", FAULT_FLAGS_PDU, DEVICE_MAIN)

    @property
    def is_on(self) -> bool | None:
        raw = self.raw_value
        if raw is None:
            return None
        return bool(int(raw) & FAULT_RESET_AVAILABLE_MASK)


class ImmergasDominusDhwRequestBinarySensor(ImmergasDominusEntity, BinarySensorEntity):
    """On when a DHW cycle is pending (status flags PDU 2001, low-byte bit 0)."""

    _attr_translation_key = "dhw_request"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:water-boiler"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "dhw_request", STATUS_FLAGS_PDU, DEVICE_MAIN)

    @property
    def is_on(self) -> bool | None:
        raw = self.raw_value
        if raw is None:
            return None
        return bool(int(raw) & DHW_REQUEST_MASK)


class ImmergasDominusHeatingDemandBinarySensor(
    ImmergasDominusEntity, BinarySensorEntity
):
    """On when Zone 1 is calling for heat (zone status PDU 2010, bit 3)."""

    _attr_translation_key = "heating_demand"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "heating_demand", ZONE_STATUS_PDU, DEVICE_ZONE_1)

    @property
    def is_on(self) -> bool | None:
        raw = self.raw_value
        if raw is None:
            return None
        return bool(int(raw) & ZONE_HEAT_DEMAND_MASK)


class ImmergasOpenThermBinarySensor(ImmergasDominusEntity, BinarySensorEntity):
    """Read-only OpenTherm status flag (a bit of a Data-ID byte)."""

    entity_description: DominusOpenThermBinaryDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusOpenThermBinaryDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.data_id, DEVICE_MAIN)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        raw = self.raw_value
        if raw is None:
            return None
        raw = int(raw) & 0xFFFF
        byte = (raw >> 8) & 0xFF if self.entity_description.byte == "hb" else raw & 0xFF
        return bool(byte & self.entity_description.mask)
