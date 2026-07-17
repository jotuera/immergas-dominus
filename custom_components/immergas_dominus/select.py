"""Select platform for Immergas Dominus."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CHRONO_OPTION_TO_RAW,
    CHRONO_PROFILE_OPTIONS,
    CHRONO_RAW_TO_OPTION,
    DEVICE_SCHEDULE,
    DOMAIN,
    SELECT_DESCRIPTIONS,
    WEEKDAY_PROFILE_PDUS,
    DominusSelectEntityDescription,
)
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selects."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = [
        ImmergasDominusSelect(coordinator, description)
        for description in SELECT_DESCRIPTIONS
    ]
    entities.append(ImmergasDominusAllDaysProfileSelect(coordinator))
    async_add_entities(entities)


class ImmergasDominusSelect(ImmergasDominusEntity, SelectEntity):
    """Writable Dominus PDU as a Home Assistant select."""

    entity_description: DominusSelectEntityDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusSelectEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.pdu, description.device_key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """Return selected option."""
        raw = self.raw_value
        if raw is None:
            return None
        if self.entity_description.mask_low_byte:
            raw = int(raw) & 0xFF
        return self.entity_description.raw_to_option.get(raw)

    async def async_select_option(self, option: str) -> None:
        """Set operation mode."""
        raw_value = self.entity_description.option_to_raw[option]
        ack_value = await self.coordinator.client.async_write_pdu(self._pdu, raw_value)
        self.coordinator.set_local_value(self._pdu, ack_value)
        await self.coordinator.async_request_refresh()


class ImmergasDominusAllDaysProfileSelect(ImmergasDominusEntity, SelectEntity):
    """Shortcut: assign one profile (Cal 1-4) to every weekday at once.

    Writes the chosen profile to all seven weekday registers (2410-2416).
    Shows a value only when every day already uses the same profile.
    """

    _attr_translation_key = "all_days_profile"
    _attr_icon = "mdi:calendar-sync"
    _attr_options = list(CHRONO_PROFILE_OPTIONS)

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(
            coordinator, "all_days_profile", WEEKDAY_PROFILE_PDUS[0], DEVICE_SCHEDULE
        )

    def _poll_pdus(self) -> tuple[int, ...]:
        return WEEKDAY_PROFILE_PDUS

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        profiles = set()
        for pdu in WEEKDAY_PROFILE_PDUS:
            raw = data.get(pdu)
            if raw is None:
                return None
            profiles.add(int(raw) & 0xFF)
        if len(profiles) == 1:
            return CHRONO_RAW_TO_OPTION.get(next(iter(profiles)))
        return None

    async def async_select_option(self, option: str) -> None:
        raw_value = CHRONO_OPTION_TO_RAW[option]
        for pdu in WEEKDAY_PROFILE_PDUS:
            ack_value = await self.coordinator.client.async_write_pdu(pdu, raw_value)
            self.coordinator.set_local_value(pdu, ack_value)
        await self.coordinator.async_request_refresh()
