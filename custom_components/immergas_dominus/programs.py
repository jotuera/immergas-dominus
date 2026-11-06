"""Boiler settings declared by the user: night function U11, anti-legionella P15, heating curve R02-R05, DHW
thermostat T02, CH start timer T05, the gas boiler integration (I01, I02, I04, I10), cooling curve R10-R13, room
control A31, the outdoor probe correction P07 and the underfloor screed type.

These settings live in the boiler menu and are not readable over TCP, so the user declares them here: a switch says
"set on the boiler" and the values are copied from the boiler menu once.  They start empty (unknown) on a fresh
install - a wrong guess would be worse than nothing; the attribute "suggested" carries a typical value the dashboard
offers as the starting point.  Nothing is written to the boiler - the dashboard uses them for the reminder rows, the
timer bars, the curve and the hints.
"""
from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEVICE_MAIN
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

# option 0 = every day, 1-7 = Monday-Sunday (same order as the hub's P17 select)
LEGIONELLA_DAY_OPTIONS = ["daily", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class _Declared(ImmergasDominusEntity):
    """Base: a value kept in Home Assistant, no PDU, always available."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, icon: str, suggested: Any = None) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)
        self._attr_translation_key = key
        self._attr_icon = icon
        # typical value offered by the dashboard as the starting point; the entity itself starts empty
        if suggested is not None:
            self._attr_extra_state_attributes = {"suggested": suggested}

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
        if last is not None and last.state in ("on", "off"):
            self._attr_is_on = last.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class ImmergasDeclaredTime(_Declared, TimeEntity, RestoreEntity):
    """Time of day of a declared program (U12 / U13 / P16)."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, icon: str, suggested: time) -> None:
        super().__init__(coordinator, key, icon, suggested.strftime("%H:%M:%S"))
        self._attr_native_value = None

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
        super().__init__(coordinator, "legionella_day", "mdi:calendar-week", "sunday")
        self._attr_current_option = None

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
        super().__init__(coordinator, "legionella_hours", "mdi:timer-sand", 3)
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = float(last.native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = float(value)
        self.async_write_ha_state()


class ImmergasDeclaredNumber(_Declared, RestoreNumber):
    """A boiler menu value declared by the user (curve point, thermostat, timer, integration threshold)."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        key: str,
        icon: str,
        suggested: float,
        low: float,
        high: float,
        unit: str,
        step: float = 1,
    ) -> None:
        super().__init__(coordinator, key, icon, suggested)
        self._attr_native_value = None
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

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
        # gas boiler integration (Magis Combo): CH (I02) and DHW (I01)
        ImmergasDeclaredSwitch(coordinator, "boiler_integration", "mdi:fire"),
        ImmergasDeclaredSwitch(coordinator, "dhw_integration", "mdi:water-boiler"),
    ]


def declared_numbers(coordinator: ImmergasDominusCoordinator) -> list[RestoreNumber]:
    c = UnitOfTemperature.CELSIUS
    return [
        ImmergasLegionellaHours(coordinator),
        # heating curve of zone 1: outdoor R02 -> flow R04 (max), outdoor R03 -> flow R05 (min)
        ImmergasDeclaredNumber(coordinator, "curve_r02", "mdi:thermometer-low", -12, -30, 10, c),
        ImmergasDeclaredNumber(coordinator, "curve_r03", "mdi:thermometer-high", 20, 0, 30, c),
        ImmergasDeclaredNumber(coordinator, "curve_r04", "mdi:thermometer-chevron-up", 32, 20, 80, c),
        ImmergasDeclaredNumber(coordinator, "curve_r05", "mdi:thermometer-chevron-down", 23, 20, 80, c),
        # T02: DHW starts when the cylinder drops this many K below the setpoint
        ImmergasDeclaredNumber(coordinator, "dhw_hysteresis", "mdi:water-thermometer", 4, 1, 20, UnitOfTemperature.KELVIN),
        # T05: minimum pause between two CH starts
        ImmergasDeclaredNumber(coordinator, "ch_restart_minutes", "mdi:timer-lock-outline", 15, 0, 60, UnitOfTime.MINUTES),
        # I04: how long the heat pump heats alone before the boiler may join; I10: below it the boiler heats
        ImmergasDeclaredNumber(coordinator, "integration_ch_wait", "mdi:timer-play-outline", 60, 1, 255, UnitOfTime.MINUTES),
        ImmergasDeclaredNumber(coordinator, "integration_activation_temp", "mdi:snowflake-thermometer", -5, -30, 35, c),
        # cooling curve of zone 1: outdoor R10 -> flow R12 (min), outdoor R11 -> flow R13 (max)
        ImmergasDeclaredNumber(coordinator, "curve_r10", "mdi:thermometer-high", 35, 15, 50, c),
        ImmergasDeclaredNumber(coordinator, "curve_r11", "mdi:thermometer-low", 25, 10, 45, c),
        ImmergasDeclaredNumber(coordinator, "curve_r12", "mdi:snowflake-thermometer", 17, 5, 25, c),
        ImmergasDeclaredNumber(coordinator, "curve_r13", "mdi:snowflake", 20, 5, 25, c),
        # P07: outdoor probe correction (the temperature read over TCP already includes it)
        ImmergasDeclaredNumber(coordinator, "outdoor_probe_correction", "mdi:thermometer-plus", 0, -9, 9, c),
        # heated floor area of the house (m2): the dashboard shows the heat loss per m2
        ImmergasDeclaredNumber(coordinator, "heated_area", "mdi:floor-plan", 150, 20, 2000, "m²"),
    ]


class ImmergasRoomControlMode(_Declared, SelectEntity, RestoreEntity):
    """A31 room control: RP panel only, RPT panel + room thermostat, RT room thermostat only."""

    _attr_options = ["rp", "rpt", "rt"]

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "room_control_mode", "mdi:home-thermometer-outline", "rpt")
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class ImmergasFloorType(_Declared, SelectEntity, RestoreEntity):
    """Underfloor screed type (same option order as the hub's select): how fast the floor takes and gives back heat -
    the dashboard uses it for the floor limit, setbacks, the CH schedule and I04."""

    _attr_options = ["cement", "anhydrite", "dry"]

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "floor_type", "mdi:layers-triple-outline", "cement")
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class ImmergasDeclaredSelect(_Declared, SelectEntity, RestoreEntity):
    """A boiler menu choice declared by the user (starts empty)."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, icon: str, options: list[str], suggested: str) -> None:
        super().__init__(coordinator, key, icon, suggested)
        self._attr_options = options
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


# 1.6.9: OpenTherm boilers (VICTRIX ZEUS ...) - the P / t / A menu of the boiler, copied once from the boiler; Immergas
# does not publish which transparent slave parameter (Data-ID 11) is which, so they cannot be read yet
def ot_declared_numbers(coordinator: ImmergasDominusCoordinator) -> list[RestoreNumber]:
    c, s, pct = UnitOfTemperature.CELSIUS, UnitOfTime.SECONDS, "%"
    return [
        ImmergasDeclaredNumber(coordinator, "ot_t0", "mdi:thermometer-low", 25, 20, 50, c),        # CH min. flow
        ImmergasDeclaredNumber(coordinator, "ot_t1", "mdi:thermometer-high", 85, 25, 85, c),       # CH max. flow
        ImmergasDeclaredNumber(coordinator, "ot_t4", "mdi:timer-sand", 20, 0, 100, s, 10),         # DHW priority timing
        ImmergasDeclaredNumber(coordinator, "ot_t5", "mdi:timer-lock-outline", 180, 0, 600, s, 10),  # CH ignitions timer
        ImmergasDeclaredNumber(coordinator, "ot_t6", "mdi:chart-line-variant", 180, 0, 840, s, 10),  # CH ramp timer
        ImmergasDeclaredNumber(coordinator, "ot_t7", "mdi:timer-play-outline", 0, 0, 600, s, 10),  # CH ignition delay
        ImmergasDeclaredNumber(coordinator, "ot_p0", "mdi:water-boiler", 99, 0, 99, pct),          # DHW max. output
        ImmergasDeclaredNumber(coordinator, "ot_p1", "mdi:fire-circle", 0, 0, 99, pct),            # min. output
        ImmergasDeclaredNumber(coordinator, "ot_p2", "mdi:fire", 80, 0, 99, pct),                  # CH max. output
        ImmergasDeclaredNumber(coordinator, "ot_p7", "mdi:thermometer-plus", 0, -10, 10, UnitOfTemperature.KELVIN),
        ImmergasDeclaredNumber(coordinator, "ot_a3", "mdi:pump", 9, 1, 9, None),                   # pump max. speed
        ImmergasDeclaredNumber(coordinator, "ot_a4", "mdi:pump-off", 6, 1, 9, None),               # pump min. speed
        ImmergasDeclaredNumber(coordinator, "ot_a5", "mdi:delta", 15, 0, 25, UnitOfTemperature.KELVIN),  # pump mode / delta T
        # VICTRIX ZEUS Superior (menu M5 / M1): the climatic curve P66/C-D, the outputs as fan speeds (P57 / P62 / P64 /
        # P65) and the information menu counters (operating hours, burner ignitions) - no factory value is suggested
        ImmergasDeclaredNumber(coordinator, "ot_sup_out_min", "mdi:snowflake-thermometer", None, -20, 0, c),
        ImmergasDeclaredNumber(coordinator, "ot_sup_out_max", "mdi:sun-thermometer", None, 5, 25, c),
        ImmergasDeclaredNumber(coordinator, "ot_sup_dhw_max_rpm", "mdi:fan-chevron-up", None, 1000, 7000, "rpm", 50),
        ImmergasDeclaredNumber(coordinator, "ot_sup_dhw_min_rpm", "mdi:fan-chevron-down", None, 1000, 7000, "rpm", 50),
        ImmergasDeclaredNumber(coordinator, "ot_sup_ch_max_rpm", "mdi:fan-plus", None, 1000, 7000, "rpm", 50),
        ImmergasDeclaredNumber(coordinator, "ot_sup_ch_min_rpm", "mdi:fan-minus", None, 1000, 7000, "rpm", 50),
        ImmergasDeclaredNumber(coordinator, "ot_sup_hours", "mdi:timer-outline", None, 0, 500000, UnitOfTime.HOURS),
        ImmergasDeclaredNumber(coordinator, "ot_sup_ignitions", "mdi:fire-circle", None, 0, 5000000, None),
    ]


def ot_declared_selects(coordinator: ImmergasDominusCoordinator) -> list[SelectEntity]:
    return [
        ImmergasDeclaredSelect(coordinator, "ot_t2", "mdi:water-thermometer", ["0", "1", "2", "3"], "1"),
        ImmergasDeclaredSelect(coordinator, "ot_p6", "mdi:pump", ["intermittent", "continuous", "flow_probe"], "intermittent"),
        # which menu the boiler has: the dashboard shows the codes, ranges and units of that model
        ImmergasDeclaredSelect(coordinator, "ot_menu_profile", "mdi:book-cog-outline", ["zeus25", "superior", "generic"], None),
        ImmergasDeclaredSelect(coordinator, "ot_sup_pump_speed", "mdi:pump", ["1", "2", "3", "auto"], None),
        ImmergasDeclaredSelect(coordinator, "ot_sup_dhw_restart", "mdi:water-thermometer", ["3", "10"], "3"),
    ]


def declared_times(coordinator: ImmergasDominusCoordinator) -> list[TimeEntity]:
    return [
        ImmergasDeclaredTime(coordinator, "night_start", "mdi:weather-sunset-down", time(21, 0)),
        ImmergasDeclaredTime(coordinator, "night_stop", "mdi:weather-sunset-up", time(0, 0)),
        ImmergasDeclaredTime(coordinator, "legionella_start", "mdi:clock-start", time(2, 0)),
    ]
