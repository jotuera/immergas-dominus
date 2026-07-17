"""Number platform for Immergas Dominus."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUMBER_DESCRIPTIONS, DominusNumberEntityDescription
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
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
