"""Switch platform for Immergas Dominus: DHW Comfort / Eco by the DHW schedule."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import ImmergasDominusCoordinator
from .dhw_schedule import DHW_TARGET_PDU
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.dhw is not None:
        async_add_entities([ImmergasDhwScheduleSwitch(coordinator)])


class ImmergasDhwScheduleSwitch(ImmergasDominusEntity, SwitchEntity, RestoreEntity):
    """On: the DHW target follows the DHW schedule - Comfort inside the calendar ranges, Eco outside."""

    _attr_translation_key = "dhw_comfort_eco"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "dhw_comfort_eco", DHW_TARGET_PDU)

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()  # the scheduler registers its own PDUs while it is on

    @property
    def is_on(self) -> bool:
        return self.coordinator.dhw.enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == "on":
            self.coordinator.dhw.set_enabled(True)

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.dhw.set_enabled(False)
        await super().async_will_remove_from_hass()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.dhw.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.dhw.set_enabled(False)
        self.async_write_ha_state()
