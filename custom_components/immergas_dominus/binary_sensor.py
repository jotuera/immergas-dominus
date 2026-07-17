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
    DEVICE_MAIN,
    DOMAIN,
    FAULT_CODE_PDU,
    FAULT_FLAGS_PDU,
    FAULT_RESET_AVAILABLE_MASK,
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
    async_add_entities(
        [
            ImmergasDominusFaultActiveBinarySensor(coordinator),
            ImmergasDominusResetAvailableBinarySensor(coordinator),
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
