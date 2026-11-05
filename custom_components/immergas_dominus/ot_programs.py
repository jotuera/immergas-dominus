"""OpenTherm programs kept in Home Assistant - what the CAR V2 remote does on its own clock.

In the OpenTherm mode (VICTRIX ZEUS / AVIO, STAR …) the Dominus module has a regulator (room setpoint Data-ID 16, the
parameters of Data-ID 89) but no clock: no weekly program, no DHW program, no vacation or anti-legionella.  With the
CAR V2 removed (the Dominus is then the only controller) Home Assistant runs them here and writes the result to the
module, the same way the official app writes it:

* **CH program** (CAR V2 "PR RIS"): 4 calendars of up to 4 Comfort ranges and a calendar per weekday; AUTO writes the
  Comfort / Eco room setpoint (Data-ID 16) when the phase changes, so a manual change holds until the next change (the
  CAR V2 "temporary override").  The Eco action can instead switch heating off (CAR V2 "RIDOTT OFF").
* **DHW program** (CAR V2 "PR SAN"): DHW Comfort / Eco setpoint (Data-ID 56) by the DHW calendar per weekday.
* **Vacation**: heating off (mode Summer) until the end date, then the mode from before.
* **Automatic Summer / Winter** by the 24 h mean of the outdoor temperature (Data-ID 27).
* **Anti-legionella** (CAR V2 "LEGION"): daily or on Monday at 02:00 the DHW setpoint goes up until the DHW temperature
  held it for 15 minutes (at most 3 hours), then back.

Everything is kept in Home Assistant (restored after a restart); the entities reuse the keys of the Modbus mode
(calendars, weekdays, Comfort / Eco, vacation, automatic season), so the dashboard cards work with them as they are.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, time as dtime, timedelta
import logging
import time
from typing import Any, Callable

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import CHRONO_PROFILE_OPTIONS, DEVICE_MAIN, DEVICE_SCHEDULE, OT_MODE_PDU, OT_MODE_TO_STATUS, PROGRAM_PHASE_OPTIONS
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

_LOGGER = logging.getLogger(__name__)

ROOM_SETPOINT_ID = 16
DHW_SETPOINT_ID = 56
DHW_TEMP_ID = 26
OUTDOOR_ID = 27
_DAY = 24 * 60
_WATER = OT_MODE_TO_STATUS["water"]
_WINTER = OT_MODE_TO_STATUS["heating_water"]

# CAR V2 factory program: Mon-Fri Comfort 6-8, 11-13, 17-23, Sat-Sun 7-23; the DHW program Comfort all day
_DEFAULT_CALENDARS: dict[int, list[tuple[int, int]]] = {
    1: [(360, 480), (660, 780), (1020, 1380), (0, 0)],
    2: [(420, 1380), (0, 0), (0, 0), (0, 0)],
    3: [(0, _DAY), (0, 0), (0, 0), (0, 0)],
    4: [(0, 0), (0, 0), (0, 0), (0, 0)],
}
_DEFAULT_CH_DAYS = [1, 1, 1, 1, 1, 2, 2]
_DEFAULT_DHW_DAYS = [3] * 7

ECO_ACTIONS = ["setpoint", "ch_off"]
LEGIONELLA_OPTIONS = ["off", "daily", "weekly"]
_LEG_HOLD = 15 * 60
_LEG_TIMEOUT = 3 * 3600

# key -> (default, min, max, step, icon); numbers kept in Home Assistant
NUMBER_SPECS: dict[str, tuple[float, float, float, float, str]] = {
    "comfort_heat": (20.0, 10, 35, 0.5, "mdi:sofa-outline"),
    "eco_heat": (16.0, 10, 35, 0.5, "mdi:leaf"),
    "dhw_comfort": (50.0, 30, 60, 1, "mdi:sofa-outline"),
    "dhw_eco": (40.0, 30, 60, 1, "mdi:leaf"),
    "season_winter_below": (15.0, 0, 25, 0.5, "mdi:snowflake"),
    "season_summer_above": (18.0, 0, 30, 0.5, "mdi:white-balance-sunny"),
    "ot_legionella_temp": (60.0, 50, 65, 1, "mdi:bacteria-outline"),
}


class OtPrograms:
    """The programs; entities read and change the state here, a 1-minute tick writes the result to the module."""

    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.calendars = {p: list(r) for p, r in _DEFAULT_CALENDARS.items()}
        self.ch_days = list(_DEFAULT_CH_DAYS)
        self.dhw_days = list(_DEFAULT_DHW_DAYS)
        self.ch_program = "manual"
        self.eco_action = "setpoint"
        self.dhw_sched = False
        self.vacation = False
        self.vacation_until: datetime | None = None
        self.auto_season = False
        self.legionella = "off"
        self.numbers = {k: v[0] for k, v in NUMBER_SPECS.items()}
        self.phase: str | None = None        # comfort / economy / manual (shown by the phase sensor)
        self._ch_written: str | None = None  # last CH phase written to the module
        self._dhw_written: str | None = None
        self._vac_prev_mode: int | None = None
        self._ch_off_by_eco = False
        self._outdoor: deque[tuple[float, float]] = deque()
        self._leg_active = False
        self._leg_start = 0.0
        self._leg_since: float | None = None
        self._leg_restore: int | None = None
        self._leg_last_day: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsub: list[CALLBACK_TYPE] = []
        self._polls = (OT_MODE_PDU, OUTDOOR_ID, DHW_TEMP_ID, DHW_SETPOINT_ID, ROOM_SETPOINT_ID)

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        self.coordinator.register_pdus(self._polls)
        self._unsub.append(async_track_time_interval(self.hass, self._async_tick, timedelta(minutes=1)))
        self._unsub.append(self.coordinator.async_add_listener(self._on_data))

    def stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        self.coordinator.unregister_pdus(self._polls)

    def add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    def changed(self) -> None:
        """A setting changed: notify the entities and apply it at once."""
        for update in list(self._listeners):
            update()
        self.hass.async_create_task(self._async_tick(dt_util.now()))

    # -- values from the module --------------------------------------------------

    def _raw(self, key: int) -> int | None:
        value = (self.coordinator.data or {}).get(key)
        return None if value is None else int(value)

    @staticmethod
    def _f88(raw: int | None) -> float | None:
        if raw is None:
            return None
        raw &= 0xFFFF
        return (raw - 0x10000 if raw & 0x8000 else raw) / 256

    def mode_status(self) -> int | None:
        raw = self._raw(OT_MODE_PDU)
        return None if raw is None else (raw >> 8) & 0x03

    @callback
    def _on_data(self) -> None:
        out = self._f88(self._raw(OUTDOOR_ID))
        if out is None or not -50 < out < 60:
            return
        now = time.time()
        if not self._outdoor or now - self._outdoor[-1][0] >= 300:
            self._outdoor.append((now, out))
        while self._outdoor and now - self._outdoor[0][0] > 86400:
            self._outdoor.popleft()

    def outdoor_24h(self) -> tuple[float | None, float]:
        """Mean of the outdoor samples of the last 24 h and how many hours they cover."""
        if not self._outdoor:
            return None, 0.0
        hours = (self._outdoor[-1][0] - self._outdoor[0][0]) / 3600
        return round(sum(v for _, v in self._outdoor) / len(self._outdoor), 1), round(hours, 1)

    # -- schedule ----------------------------------------------------------------

    def in_comfort(self, calendar: int, minute: int) -> bool:
        return any(a <= minute < b for a, b in self.calendars.get(calendar, []) if a < b)

    def _now_minute(self, now: datetime) -> tuple[int, int]:
        local = dt_util.as_local(now)
        return local.weekday(), local.hour * 60 + local.minute

    # -- writes ------------------------------------------------------------------

    async def _write(self, key: int, value: int, what: str) -> bool:
        if getattr(self.coordinator.client, "read_only", False):
            _LOGGER.debug("OpenTherm program: %s not written (read-only mode)", what)
            return False
        try:
            ack = await self.coordinator.client.async_write_data_id(key, value)
        except Exception as err:  # noqa: BLE001 - the next tick tries again
            _LOGGER.warning("OpenTherm program: writing %s failed: %s", what, err)
            return False
        self.coordinator.set_local_value(key, ack)
        _LOGGER.debug("OpenTherm program: %s written", what)
        return True

    async def _set_mode(self, status: int, what: str) -> bool:
        return await self._write(OT_MODE_PDU, status << 8, f"mode {status} ({what})")

    async def _set_room(self, value: float, what: str) -> bool:
        return await self._write(ROOM_SETPOINT_ID, int(round(value * 256)) & 0xFFFF, f"room setpoint {value} ({what})")

    async def _set_dhw(self, value: float, what: str) -> bool:
        return await self._write(DHW_SETPOINT_ID, (int(round(value)) << 8) & 0xFFFF, f"DHW setpoint {value} ({what})")

    # -- vacation (called by the switch) ----------------------------------------

    async def async_set_vacation(self, on: bool) -> None:
        if on == self.vacation:
            return
        self.vacation = on
        mode = self.mode_status()
        if on:
            self._vac_prev_mode = mode if mode not in (None, _WATER) else None
            if mode is not None and mode & 0x01:
                await self._set_mode(_WATER, "vacation")
        else:
            prev, self._vac_prev_mode = self._vac_prev_mode, None
            if prev is not None:
                await self._set_mode(prev, "vacation end")
            self._ch_written = None  # the CH program writes its phase again
        self.changed()

    # -- the tick ----------------------------------------------------------------

    async def _async_tick(self, now: datetime) -> None:
        day, minute = self._now_minute(now)
        if self.vacation and self.vacation_until is not None and dt_util.utcnow() >= dt_util.as_utc(self.vacation_until):
            self.vacation_until = None
            await self.async_set_vacation(False)
            return
        await self._ch_program(day, minute)
        await self._dhw_program(day, minute)
        await self._season()
        await self._legionella(now, day, minute)

    async def _ch_program(self, day: int, minute: int) -> None:
        if self.ch_program != "auto":
            if self.phase != "manual":
                self.phase = "manual"
                self._notify()
            if self._ch_off_by_eco:  # back from AUTO with "Eco = heating off": heating on again
                self._ch_off_by_eco = False
                await self._set_mode(_WINTER, "program manual")
            self._ch_written = None
            return
        phase = "comfort" if self.in_comfort(self.ch_days[day], minute) else "economy"
        if phase != self.phase:
            self.phase = phase
            self._notify()
        if self.vacation or phase == self._ch_written:
            return
        ok = True
        if self.eco_action == "ch_off":
            mode = self.mode_status()
            if phase == "economy" and mode is not None and mode & 0x01:
                ok = await self._set_mode(_WATER, "Eco = heating off")
                self._ch_off_by_eco = ok or self._ch_off_by_eco
            elif phase == "comfort" and self._ch_off_by_eco:
                ok = await self._set_mode(_WINTER, "Comfort")
                self._ch_off_by_eco = not ok
            if phase == "comfort" and ok:
                ok = await self._set_room(self.numbers["comfort_heat"], "Comfort")
        else:
            ok = await self._set_room(self.numbers["comfort_heat" if phase == "comfort" else "eco_heat"], phase)
        if ok:
            self._ch_written = phase

    async def _dhw_program(self, day: int, minute: int) -> None:
        if not self.dhw_sched or self._leg_active:
            self._dhw_written = None if not self.dhw_sched else self._dhw_written
            return
        phase = "comfort" if self.in_comfort(self.dhw_days[day], minute) else "economy"
        if phase == self._dhw_written:
            return
        if await self._set_dhw(self.numbers["dhw_comfort" if phase == "comfort" else "dhw_eco"], f"DHW {phase}"):
            self._dhw_written = phase

    async def _season(self) -> None:
        if not self.auto_season or self.vacation:
            return
        mean, hours = self.outdoor_24h()
        mode = self.mode_status()
        if mean is None or hours < 12 or mode is None:
            return
        if mode == _WATER and mean < self.numbers["season_winter_below"]:
            _LOGGER.info("Auto season: outdoor 24 h mean %.1f °C -> Winter", mean)
            await self._set_mode(_WINTER, "auto season")
        elif mode == _WINTER and mean > self.numbers["season_summer_above"] and not self._ch_off_by_eco:
            _LOGGER.info("Auto season: outdoor 24 h mean %.1f °C -> Summer", mean)
            await self._set_mode(_WATER, "auto season")

    async def _legionella(self, now: datetime, day: int, minute: int) -> None:
        mono = time.monotonic()
        if self._leg_active:
            target = self.numbers["ot_legionella_temp"]
            temp = self._f88(self._raw(DHW_TEMP_ID))
            if temp is not None and temp >= target - 2:
                self._leg_since = self._leg_since or mono
            else:
                self._leg_since = None
            done = self._leg_since is not None and mono - self._leg_since >= _LEG_HOLD
            if done or mono - self._leg_start >= _LEG_TIMEOUT or self.legionella == "off":
                self._leg_active = False
                self._dhw_written = None  # the DHW program writes its phase again
                restore, self._leg_restore = self._leg_restore, None
                if restore is not None and not self.dhw_sched:
                    await self._write(DHW_SETPOINT_ID, restore, "DHW setpoint after anti-legionella")
                _LOGGER.info("Anti-legionella %s", "done" if done else "stopped")
                self._notify()
            return
        today = dt_util.as_local(now).date().isoformat()
        due = self.legionella == "daily" or (self.legionella == "weekly" and day == 0)
        if not due or not 120 <= minute < 130 or self._leg_last_day == today:
            return
        self._leg_last_day = today
        self._leg_restore = self._raw(DHW_SETPOINT_ID)
        if await self._set_dhw(self.numbers["ot_legionella_temp"], "anti-legionella"):
            self._leg_active, self._leg_start, self._leg_since = True, mono, None
            _LOGGER.info("Anti-legionella started (%s °C)", self.numbers["ot_legionella_temp"])
            self._notify()

    def _notify(self) -> None:
        for update in list(self._listeners):
            update()


# -- entities ---------------------------------------------------------------------


class _ProgramEntity(ImmergasDominusEntity, RestoreEntity):
    """A program setting kept in Home Assistant: reads / changes the OtPrograms state, polls nothing itself."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, device_key: str = DEVICE_MAIN) -> None:
        super().__init__(coordinator, key, 0, device_key)
        self.programs: OtPrograms = coordinator.ot_programs

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.programs.add_listener(self.async_write_ha_state))
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "unknown", "unavailable"):
            self._restore(last.state)

    def _restore(self, state: str) -> None:
        """Take the value from before the restart."""


def _minutes(value: dtime) -> int:
    m = value.hour * 60 + value.minute
    return _DAY if m >= 23 * 60 + 59 else m  # 23:59 = end of the day (24:00)


class OtCalendarTime(_ProgramEntity, TimeEntity):
    """Start / end of a Comfort range of a calendar (the end 23:59 means 24:00; start = end: range unused)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ImmergasDominusCoordinator, profile: int, fascia: int, edge: str) -> None:
        super().__init__(coordinator, f"profile{profile}_fascia{fascia}_{edge}", DEVICE_SCHEDULE)
        self._p, self._i, self._e = profile, fascia - 1, 0 if edge == "start" else 1
        self._attr_translation_key = f"fascia_{edge}"
        self._attr_translation_placeholders = {"profile": str(profile), "fascia": str(fascia)}

    def _restore(self, state: str) -> None:
        parsed = dt_util.parse_time(state)
        if parsed is not None:
            self._store(_minutes(parsed))

    def _store(self, minute: int) -> None:
        rng = list(self.programs.calendars[self._p][self._i])
        rng[self._e] = minute
        self.programs.calendars[self._p][self._i] = (rng[0], rng[1])

    @property
    def native_value(self) -> dtime:
        m = self.programs.calendars[self._p][self._i][self._e]
        return dtime(23, 59) if m >= _DAY else dtime(m // 60, m % 60)

    async def async_set_value(self, value: dtime) -> None:
        self._store(_minutes(value))
        self.programs.changed()


class OtWeekdaySelect(_ProgramEntity, SelectEntity):
    """Calendar of one weekday for the CH or the DHW program."""

    _attr_options = list(CHRONO_PROFILE_OPTIONS)
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ImmergasDominusCoordinator, dhw: bool, day: int) -> None:
        super().__init__(coordinator, f"{'dhw_' if dhw else ''}weekday_{day}_profile", DEVICE_SCHEDULE)
        self._dhw, self._d = dhw, day - 1
        self._attr_translation_key = f"weekday_{day}_profile"
        self._attr_translation_placeholders = {"target": "DHW" if dhw else "CH"}

    def _days(self) -> list[int]:
        return self.programs.dhw_days if self._dhw else self.programs.ch_days

    def _restore(self, state: str) -> None:
        if state in self._attr_options:
            self._days()[self._d] = self._attr_options.index(state) + 1

    @property
    def current_option(self) -> str:
        return self._attr_options[self._days()[self._d] - 1]

    async def async_select_option(self, option: str) -> None:
        self._days()[self._d] = self._attr_options.index(option) + 1
        self.programs.changed()


class OtChoiceSelect(_ProgramEntity, SelectEntity):
    """CH program AUTO / MANUAL, the Eco action, anti-legionella."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, attr: str, options: list[str], icon: str,
                 config: bool = True) -> None:
        super().__init__(coordinator, key)
        self._attr = attr
        self._attr_translation_key = key
        self._attr_options = options
        self._attr_icon = icon
        if config:
            self._attr_entity_category = EntityCategory.CONFIG

    def _restore(self, state: str) -> None:
        if state in self._attr_options:
            setattr(self.programs, self._attr, state)

    @property
    def current_option(self) -> str:
        return getattr(self.programs, self._attr)

    async def async_select_option(self, option: str) -> None:
        setattr(self.programs, self._attr, option)
        self.programs.changed()


class OtProgramNumber(ImmergasDominusEntity, RestoreNumber):
    """Comfort / Eco room and DHW temperatures, season thresholds, anti-legionella temperature."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = NumberDeviceClass.TEMPERATURE

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)
        self.programs: OtPrograms = coordinator.ot_programs
        self._key = key
        _, low, high, step, icon = NUMBER_SPECS[key]
        self._attr_translation_key = key
        self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = low, high, step
        self._attr_icon = icon

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.programs.numbers[self._key] = float(last.native_value)

    @property
    def native_value(self) -> float:
        return self.programs.numbers[self._key]

    async def async_set_native_value(self, value: float) -> None:
        self.programs.numbers[self._key] = float(value)
        # a new Comfort / Eco value is written at once when that phase is on
        if self._key in ("comfort_heat", "eco_heat"):
            self.programs._ch_written = None
        if self._key in ("dhw_comfort", "dhw_eco"):
            self.programs._dhw_written = None
        self.programs.changed()


class OtProgramSwitch(_ProgramEntity, SwitchEntity):
    """DHW Comfort / Eco by the DHW calendar, vacation, automatic Summer / Winter."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, attr: str, icon: str) -> None:
        super().__init__(coordinator, key)
        self._attr = attr
        self._attr_translation_key = key
        self._attr_icon = icon

    def _restore(self, state: str) -> None:
        if self._attr == "vacation":
            self.programs.vacation = state == "on"  # the mode from before is not known any more: no write
        else:
            setattr(self.programs, self._attr, state == "on")

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.programs, self._attr))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._attr != "auto_season":
            return None
        mean, hours = self.programs.outdoor_24h()
        return {"outdoor_mean_24h": mean, "hours_of_data": hours}

    async def _async_set(self, on: bool) -> None:
        if self._attr == "vacation":
            await self.programs.async_set_vacation(on)
            return
        setattr(self.programs, self._attr, on)
        if self._attr == "dhw_sched":
            self.programs._dhw_written = None
        self.programs.changed()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)


class OtVacationUntil(_ProgramEntity, DateTimeEntity):
    """End of the vacation; empty = until switched off."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-end"
    _attr_translation_key = "vacation_until"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "vacation_until")

    def _restore(self, state: str) -> None:
        self.programs.vacation_until = dt_util.parse_datetime(state)

    @property
    def native_value(self) -> datetime | None:
        return self.programs.vacation_until

    async def async_set_value(self, value: datetime) -> None:
        self.programs.vacation_until = value
        self.programs.changed()


class OtProgramPhase(_ProgramEntity, SensorEntity):
    """Phase of the CH program: Comfort / Eco (AUTO) or manual."""

    _attr_translation_key = "program_phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PROGRAM_PHASE_OPTIONS
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "program_phase")

    @property
    def native_value(self) -> str | None:
        return self.programs.phase

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"anti_legionella_running": self.programs._leg_active}


# -- per platform -------------------------------------------------------------------


def ot_times(coordinator: ImmergasDominusCoordinator) -> list:
    return [OtCalendarTime(coordinator, p, f, e) for p in range(1, 5) for f in range(1, 5) for e in ("start", "end")]


def ot_selects(coordinator: ImmergasDominusCoordinator) -> list:
    return [
        *(OtWeekdaySelect(coordinator, dhw, d) for dhw in (False, True) for d in range(1, 8)),
        OtChoiceSelect(coordinator, "zone1_time_program", "ch_program", ["manual", "auto"], "mdi:calendar-clock", config=False),
        OtChoiceSelect(coordinator, "ot_eco_action", "eco_action", ECO_ACTIONS, "mdi:leaf"),
        OtChoiceSelect(coordinator, "ot_legionella", "legionella", LEGIONELLA_OPTIONS, "mdi:bacteria-outline"),
    ]


def ot_numbers(coordinator: ImmergasDominusCoordinator) -> list:
    return [OtProgramNumber(coordinator, key) for key in NUMBER_SPECS]


def ot_switches(coordinator: ImmergasDominusCoordinator) -> list:
    return [
        OtProgramSwitch(coordinator, "dhw_comfort_eco", "dhw_sched", "mdi:calendar-clock"),
        OtProgramSwitch(coordinator, "vacation_mode", "vacation", "mdi:bag-suitcase"),
        OtProgramSwitch(coordinator, "auto_season", "auto_season", "mdi:sun-snowflake-variant"),
    ]


def ot_datetimes(coordinator: ImmergasDominusCoordinator) -> list:
    return [OtVacationUntil(coordinator)]


def ot_sensors(coordinator: ImmergasDominusCoordinator) -> list:
    return [OtProgramPhase(coordinator)]
