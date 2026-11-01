"""Time platform for Immergas Dominus (CO heating schedule)."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCHEDULE_TIME_DESCRIPTIONS, DominusTimeEntityDescription
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the CO schedule time entities."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ImmergasDominusScheduleTime(coordinator, description)
        for description in SCHEDULE_TIME_DESCRIPTIONS
    )


class ImmergasDominusScheduleTime(ImmergasDominusEntity, TimeEntity):
    """One schedule time-of-day PDU (high byte = hour, low byte = minute)."""

    entity_description: DominusTimeEntityDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusTimeEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.pdu, description.device_key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        if description.translation_placeholders:
            self._attr_translation_placeholders = description.translation_placeholders

    @property
    def native_value(self) -> time | None:
        raw = self.raw_value
        if raw is None:
            return None
        raw = int(raw) & 0xFFFF
        hour = (raw >> 8) & 0xFF
        minute = raw & 0xFF
        # The bus uses 24:00 as "end of day"; clamp to 23:59 for a valid HA time.
        if hour >= 24:
            return time(23, 59)
        if minute > 59:
            minute = 59
        return time(hour, minute)

    async def async_set_value(self, value: time) -> None:
        raw_value = (value.hour << 8) | value.minute
        ack_value = await self.coordinator.client.async_write_pdu(self._pdu, raw_value)
        self.coordinator.set_local_value(self._pdu, ack_value)
        await self.coordinator.async_request_refresh()
