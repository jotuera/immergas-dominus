"""Number platform for Immergas Dominus."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_PROTOCOL,
    DEVICE_MAIN,
    DOMAIN,
    NUMBER_DESCRIPTIONS,
    OT_NUMBER_DESCRIPTIONS,
    PROTOCOL_OPENTHERM,
    DominusNumberEntityDescription,
    DominusOpenThermNumberDescription,
)
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_PROTOCOL) == PROTOCOL_OPENTHERM:
        async_add_entities(
            ImmergasOpenThermNumber(coordinator, description)
            for description in OT_NUMBER_DESCRIPTIONS
        )
        return
    async_add_entities(
        ImmergasDominusNumber(coordinator, description)
        for description in NUMBER_DESCRIPTIONS
    )


class ImmergasDominusNumber(ImmergasDominusEntity, NumberEntity):
    """Writable Dominus PDU as a Home Assistant number."""

    entity_description: DominusNumberEntityDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusNumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.pdu, description.device_key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        raw = self.raw_value
        if raw is None:
            return None
        return raw / self.entity_description.raw_scale

    async def async_set_native_value(self, value: float) -> None:
        raw_value = round(value * self.entity_description.raw_scale)
        ack_value = await self.coordinator.client.async_write_pdu(self._pdu, raw_value)
        self.coordinator.set_local_value(self._pdu, ack_value)
        await self.coordinator.async_request_refresh()


class ImmergasOpenThermNumber(ImmergasDominusEntity, NumberEntity):
    """Writable OpenTherm setpoint (f8.8 fixed-point, °C)."""

    entity_description: DominusOpenThermNumberDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusOpenThermNumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.data_id, DEVICE_MAIN)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        raw = self.raw_value
        if raw is None:
            return None
        raw = int(raw) & 0xFFFF
        signed = raw - 0x10000 if raw & 0x8000 else raw
        return round(signed / 256, 1)

    async def async_set_native_value(self, value: float) -> None:
        raw_value = round(float(value) * 256) & 0xFFFF
        ack_value = await self.coordinator.client.async_write_data_id(self._pdu, raw_value)
        self.coordinator.set_local_value(self._pdu, ack_value)
        await self.coordinator.async_request_refresh()
