"""Boiler programs declared by the user: night function U11 and anti-legionella P15.

These settings live in the boiler menu and are not readable over TCP, so the user declares them here: a switch says
"set on the boiler" and the times say when.  Nothing is written to the boiler - the dashboard uses them for the
reminder rows and the timer bars.
"""
from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEVICE_MAIN
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

# option 0 = every day, 1-7 = Monday-Sunday (same order as the hub's P17 select)
LEGIONELLA_DAY_OPTIONS = ["daily", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class _Declared(ImmergasDominusEntity):
    """Base: a value kept in Home Assistant, no PDU, always available."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, icon: str) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)
        self._attr_translation_key = key
        self._attr_icon = icon

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    @property
    def available(self) -> bool:
        return True


class ImmergasDeclaredSwitch(_Declared, SwitchEntity, RestoreEntity):
    """On: the program is set on the boiler (declared by the user)."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, icon: str) -> None:
        super().__init__(coordinator, key, icon)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._attr_is_on = last is not None and last.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class ImmergasDeclaredTime(_Declared, TimeEntity, RestoreEntity):
    """Time of day of a declared program (U12 / U13 / P16)."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, icon: str, default: time) -> None:
        super().__init__(coordinator, key, icon)
        self._attr_native_value = default

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = time.fromisoformat(last.state)
            except ValueError:
                pass

    async def async_set_value(self, value: time) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


class ImmergasLegionellaDay(_Declared, SelectEntity, RestoreEntity):
    """Anti-legionella day (P17): every day or one weekday."""

    _attr_options = LEGIONELLA_DAY_OPTIONS

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "legionella_day", "mdi:calendar-week")
        self._attr_current_option = "sunday"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class ImmergasLegionellaHours(_Declared, RestoreNumber):
    """Anti-legionella maximum cycle duration (P13), hours."""

    _attr_native_min_value = 1
    _attr_native_max_value = 24
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "legionella_hours", "mdi:timer-sand")
        self._attr_native_value = 3.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = float(last.native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = float(value)
        self.async_write_ha_state()


def declared_switches(coordinator: ImmergasDominusCoordinator) -> list[SwitchEntity]:
    return [
        ImmergasDeclaredSwitch(coordinator, "night_mode", "mdi:weather-night"),
        ImmergasDeclaredSwitch(coordinator, "legionella", "mdi:bacteria-outline"),
    ]


def declared_times(coordinator: ImmergasDominusCoordinator) -> list[TimeEntity]:
    return [
        ImmergasDeclaredTime(coordinator, "night_start", "mdi:weather-sunset-down", time(21, 0)),
        ImmergasDeclaredTime(coordinator, "night_stop", "mdi:weather-sunset-up", time(0, 0)),
        ImmergasDeclaredTime(coordinator, "legionella_start", "mdi:clock-start", time(2, 0)),
    ]
