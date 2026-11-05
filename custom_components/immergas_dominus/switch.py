"""Switch platform for Immergas Dominus: DHW Comfort / Eco by the DHW schedule, vacation mode, auto Summer / Winter."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEVICE_MAIN, DOMAIN, OT_PARAM_SWITCH_DESCRIPTIONS, DominusOpenThermParamSwitchDescription
from .coordinator import ImmergasDominusCoordinator
from .dhw_schedule import DHW_TARGET_PDU
from .entity import ImmergasDominusEntity
from .programs import declared_switches
from .stats_entities import ImmergasAlertNotificationsSwitch, ImmergasAutoSeasonSwitch, ImmergasVacationSwitch


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if getattr(coordinator, "ot_programs", None) is not None:
        from .ot_programs import ot_switches
        async_add_entities([ImmergasOpenThermParamSwitch(coordinator, d) for d in OT_PARAM_SWITCH_DESCRIPTIONS])
        async_add_entities(ot_switches(coordinator))
        from .ot_diagnostics import OtReadOnlySwitch
        async_add_entities([OtReadOnlySwitch(coordinator)])
        return
    if coordinator.dhw is not None:
        async_add_entities([ImmergasDhwScheduleSwitch(coordinator)])
    if coordinator.stats is not None:
        async_add_entities([ImmergasVacationSwitch(coordinator), ImmergasAutoSeasonSwitch(coordinator),
                            ImmergasAlertNotificationsSwitch(coordinator)])
        # boiler programs declared by the user (not readable over TCP)
        async_add_entities(declared_switches(coordinator))


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


class ImmergasOpenThermParamSwitch(ImmergasDominusEntity, SwitchEntity):
    """On / off parameter of the Dominus regulator (OpenTherm mode, Data-ID 89, HB = index, LB = 0 / 1)."""

    entity_description: DominusOpenThermParamSwitchDescription

    def __init__(self, coordinator: ImmergasDominusCoordinator, description: DominusOpenThermParamSwitchDescription) -> None:
        from .opentherm_client import ot_param_key
        super().__init__(coordinator, description.key, ot_param_key(89, description.index), DEVICE_MAIN)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        raw = self.raw_value
        return None if raw is None else bool(int(raw) & 0xFF)

    async def _async_write(self, on: bool) -> None:
        ack = await self.coordinator.client.async_write_data_id(self._pdu, 1 if on else 0)
        self.coordinator.set_local_value(self._pdu, ack)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)
