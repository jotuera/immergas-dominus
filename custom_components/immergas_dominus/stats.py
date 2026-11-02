"""Statistics and simple automations computed in Home Assistant from the PDUs the Dominus module reads.

Statistics (read-only sensors): CH heating time today and its 24 h share, DHW cycles today with the last cycle's
length and cylinder rise, CH starts (last 60 min / today), room deviation from the target (1 h mean) and the time to
reach a raised target, degree days (base 18 °C) today and this month with heating hours per degree day.

Automations (all off by default): vacation mode (zone 1 target lowered until a date, then restored), automatic
Summer / Winter from the 24 h outdoor mean, and two alerts (frost risk, module offline).

Values are integrated between polls (~45 s); a gap longer than MAX_GAP is not counted (module offline, HA restart).
Daily and monthly counters survive a restart through their sensors; the rolling 24 h / 60 min windows start empty
after a restart.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    DHW_REQUEST_MASK,
    STATUS_FLAGS_PDU,
    ZONE_HEAT_DEMAND_MASK,
    ZONE_PHASE_COMFORT_MASK,
    ZONE_PHASE_ECONOMY_MASK,
    ZONE_STATUS_PDU,
)
from .coordinator import ImmergasDominusCoordinator
from .dominus_client import DominusError

_LOGGER = logging.getLogger(__name__)

MODE_PDU = 2000
ROOM_PDU = 2011
TARGET_PDU = 2015
OUTDOOR_PDU = 3002
TANK_PDU = 3016
STATS_PDUS = (MODE_PDU, STATUS_FLAGS_PDU, ZONE_STATUS_PDU, ROOM_PDU, TARGET_PDU, OUTDOOR_PDU, TANK_PDU)

MAX_GAP = 600  # s: longer gaps between polls are not integrated
DAY = 86400
DD_BASE = 18.0  # °C, degree-day base temperature
MODE_SUMMER, MODE_WINTER = 1, 3
SEASON_MIN_HOURS = 12  # hours of outdoor data needed before Summer / Winter is switched
SEASON_MIN_INTERVAL = 3600  # s between two automatic mode changes
TICK = timedelta(seconds=60)

# settings (numbers) with their defaults
DEFAULTS = {
    "vacation_temperature": 16.0,
    "season_winter_below": 15.0,
    "season_summer_above": 18.0,
    "frost_threshold": 8.0,
    "offline_minutes": 15.0,
}


def _temp(raw: int | None, invalid: tuple[int, ...] = ()) -> float | None:
    """Raw °C x 10 -> °C (None for a missing value or a sentinel)."""
    if raw is None or int(raw) in invalid:
        return None
    return int(raw) / 10


class DominusStats:
    """Keeps the statistics and runs the optional automations; entities read it and register as listeners."""

    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.settings = dict(DEFAULTS)
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._started = dt_util.utcnow()
        # last sample (previous poll) used for the integration
        self._last_at: datetime | None = None
        self._prev: dict[str, float | bool | None] = {}
        # daily / monthly counters (restored by their sensors)
        self.day = dt_util.now().date()
        self.month = (self.day.year, self.day.month)
        self.ch_today_s = 0.0
        self.ch_month_s = 0.0
        self.dhw_cycles_today = 0
        self.ch_starts_today = 0
        self.dd_today = 0.0
        self.dd_month = 0.0
        # last DHW cycle / last time to target (kept until replaced)
        self.last_dhw_min: float | None = None
        self.last_dhw_rise: float | None = None
        self.time_to_target: float | None = None
        self._dhw_start: tuple[datetime, float | None] | None = None
        self._ttt_since: datetime | None = None
        # rolling windows: CH on segments (24 h), CH starts (60 min), deviation (1 h), outdoor (24 h)
        self._ch_segments: deque[tuple[float, float]] = deque()
        self._starts: deque[float] = deque()
        self._dev: deque[tuple[float, float, float]] = deque()
        self._outdoor: deque[tuple[float, float, float]] = deque()
        # automations
        self.vacation_on = False
        self.vacation_until: datetime | None = None
        self.vacation_restore: int | None = None  # zone 1 target (raw) to restore after the vacation
        self.auto_season = False
        self._season_changed: datetime | None = None

    # --- lifecycle -------------------------------------------------------------------------------------------------

    @callback
    def start(self) -> None:
        """Poll the PDUs the statistics need (even when their own entities are disabled) and follow the data."""
        self.coordinator.register_pdus(STATS_PDUS)
        self._unsubs.append(self.coordinator.async_add_listener(self._on_data))
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick, TICK))

    @callback
    def stop(self) -> None:
        self.coordinator.unregister_pdus(STATS_PDUS)
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Entities showing a statistic register here."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    # --- restore (called by the sensors after a restart) ----------------------------------------------------------

    @callback
    def restore(self, key: str, value: float, period: str | None) -> None:
        """Restore a counter if its period (day "YYYY-MM-DD" / month "YYYY-MM") is still the current one."""
        if key in ("ch_heating_time_today", "dhw_cycles_today", "ch_starts_today", "degree_days_today"):
            if period != self.day.isoformat():
                return
        elif key in ("degree_days_month", "ch_hours_month"):
            if period != "%04d-%02d" % self.month:
                return
        if key == "ch_heating_time_today":
            self.ch_today_s = value * 3600
        elif key == "dhw_cycles_today":
            self.dhw_cycles_today = int(value)
        elif key == "ch_starts_today":
            self.ch_starts_today = int(value)
        elif key == "degree_days_today":
            self.dd_today = value
        elif key == "degree_days_month":
            self.dd_month = value
        elif key == "ch_hours_month":
            self.ch_month_s = value * 3600
        elif key == "last_dhw_cycle_duration":
            self.last_dhw_min = value
        elif key == "last_dhw_cycle_rise":
            self.last_dhw_rise = value
        elif key == "time_to_target":
            self.time_to_target = value

    @property
    def day_key(self) -> str:
        return self.day.isoformat()

    @property
    def month_key(self) -> str:
        return "%04d-%02d" % self.month

    # --- statistics --------------------------------------------------------------------------------------------------

    def _rollover(self) -> None:
        today = dt_util.now().date()
        if today != self.day:
            self.day = today
            self.ch_today_s = self.dd_today = 0.0
            self.dhw_cycles_today = self.ch_starts_today = 0
        if (today.year, today.month) != self.month:
            self.month = (today.year, today.month)
            self.ch_month_s = self.dd_month = 0.0

    def _sample(self) -> dict[str, float | bool | None]:
        data = self.coordinator.data or {}
        zone, flags = data.get(ZONE_STATUS_PDU), data.get(STATUS_FLAGS_PDU)
        phase = None
        if zone is not None:
            phase = "eco" if int(zone) & ZONE_PHASE_ECONOMY_MASK else "comfort" if int(zone) & ZONE_PHASE_COMFORT_MASK else "manual"
        return {
            "ch": None if zone is None else bool(int(zone) & ZONE_HEAT_DEMAND_MASK),
            "dhw": None if flags is None else bool(int(flags) & DHW_REQUEST_MASK),
            "room": _temp(data.get(ROOM_PDU), (32767,)),
            "target": _temp(data.get(TARGET_PDU)),
            "outdoor": _temp(data.get(OUTDOOR_PDU), (255,)),
            "tank": _temp(data.get(TANK_PDU)),
            "phase": phase,
        }

    @callback
    def _on_data(self) -> None:
        """A coordinator update: integrate once per new successful poll (writes also notify the coordinator)."""
        at = self.coordinator.last_success
        if at is None or at == self._last_at:
            return
        self._rollover()
        cur = self._sample()
        prev, last = self._prev, self._last_at
        dt = (at - last).total_seconds() if last else 0.0
        if 0 < dt <= MAX_GAP and prev:
            t0, t1 = last.timestamp(), at.timestamp()
            if prev.get("ch"):
                self.ch_today_s += dt
                self.ch_month_s += dt
                if self._ch_segments and abs(self._ch_segments[-1][1] - t0) < 1:
                    self._ch_segments[-1] = (self._ch_segments[-1][0], t1)
                else:
                    self._ch_segments.append((t0, t1))
            out = prev.get("outdoor")
            if out is not None:
                self.dd_today += max(0.0, DD_BASE - out) * dt / DAY
                self.dd_month += max(0.0, DD_BASE - out) * dt / DAY
                self._outdoor.append((t1, out, dt))
            if prev.get("room") is not None and prev.get("target") is not None:
                self._dev.append((t1, prev["room"] - prev["target"], dt))
        self._edges(prev, cur, at)
        self._prev, self._last_at = cur, at
        self._prune(at.timestamp())
        self._notify()

    def _edges(self, prev: dict, cur: dict, at: datetime) -> None:
        # CH starts
        if cur["ch"] and prev.get("ch") is False:
            self.ch_starts_today += 1
            self._starts.append(at.timestamp())
        # DHW cycles: request on -> off
        if cur["dhw"] and prev.get("dhw") is False:
            self.dhw_cycles_today += 1
            self._dhw_start = (at, cur["tank"])
        elif cur["dhw"] is False and prev.get("dhw") and self._dhw_start:
            start, tank0 = self._dhw_start
            self.last_dhw_min = round((at - start).total_seconds() / 60, 1)
            if tank0 is not None and cur["tank"] is not None:
                self.last_dhw_rise = round(cur["tank"] - tank0, 1)
            self._dhw_start = None
        # time to target: after the target goes up by >= 0.5 K or the phase switches Eco -> Comfort
        pt, ct = prev.get("target"), cur["target"]
        if (pt is not None and ct is not None and ct - pt >= 0.5) or (prev.get("phase") == "eco" and cur["phase"] == "comfort"):
            self._ttt_since = at
        if self._ttt_since and cur["room"] is not None and ct is not None and cur["room"] >= ct - 0.2:
            self.time_to_target = round((at - self._ttt_since).total_seconds() / 60, 1)
            self._ttt_since = None

    def _prune(self, now: float) -> None:
        while self._ch_segments and self._ch_segments[0][1] < now - DAY:
            self._ch_segments.popleft()
        while self._starts and self._starts[0] < now - 3600:
            self._starts.popleft()
        while self._dev and self._dev[0][0] < now - 3600:
            self._dev.popleft()
        while self._outdoor and self._outdoor[0][0] < now - DAY:
            self._outdoor.popleft()

    @property
    def ch_share_24h(self) -> float:
        now = dt_util.utcnow().timestamp()
        on = sum(max(0.0, b - max(a, now - DAY)) for a, b in self._ch_segments)
        return round(100 * on / DAY, 1)

    @property
    def starts_per_hour(self) -> int:
        return len(self._starts)

    @property
    def room_deviation(self) -> float | None:
        w = sum(d for _, _, d in self._dev)
        return round(sum(v * d for _, v, d in self._dev) / w, 2) if w else None

    @property
    def room_deviation_now(self) -> float | None:
        room, target = self._prev.get("room"), self._prev.get("target")
        return None if room is None or target is None else round(room - target, 1)

    @property
    def outdoor_24h(self) -> tuple[float | None, float]:
        """Time-weighted 24 h outdoor mean and the hours of data behind it."""
        w = sum(d for _, _, d in self._outdoor)
        return (round(sum(v * d for _, v, d in self._outdoor) / w, 1) if w else None), round(w / 3600, 1)

    @property
    def hours_per_degree_day(self) -> float | None:
        return round(self.ch_month_s / 3600 / self.dd_month, 2) if self.dd_month >= 0.5 else None

    # --- alerts ------------------------------------------------------------------------------------------------------

    @property
    def frost_risk(self) -> bool | None:
        room = self._prev.get("room")
        return None if room is None else room < self.settings["frost_threshold"]

    @property
    def module_offline(self) -> bool:
        last = self.coordinator.last_success or self._started
        return (dt_util.utcnow() - last).total_seconds() > self.settings["offline_minutes"] * 60

    # --- automations -------------------------------------------------------------------------------------------------

    @callback
    def set_setting(self, key: str, value: float) -> None:
        self.settings[key] = float(value)
        if key == "vacation_temperature" and self.vacation_on:
            self.hass.async_create_task(self._async_write(TARGET_PDU, round(value * 10), "vacation target"))
        self._notify()

    async def async_set_vacation(self, on: bool) -> None:
        """On: remember the zone 1 target and lower it; off: restore it."""
        if on == self.vacation_on:
            return
        if on:
            current = (self.coordinator.data or {}).get(TARGET_PDU)
            self.vacation_restore = int(current) if current is not None else None
            self.vacation_on = True
            await self._async_write(TARGET_PDU, round(self.settings["vacation_temperature"] * 10), "vacation target")
        else:
            self.vacation_on = False
            if self.vacation_restore is not None:
                await self._async_write(TARGET_PDU, self.vacation_restore, "target after the vacation")
            self.vacation_restore = None
        self._notify()

    @callback
    def set_vacation_until(self, until: datetime | None) -> None:
        self.vacation_until = until
        self._notify()

    async def _async_write(self, pdu: int, raw: int, what: str) -> bool:
        try:
            ack = await self.coordinator.client.async_write_pdu(pdu, raw)
        except DominusError as err:
            _LOGGER.warning("Writing the %s (%s) failed: %s", what, raw, err)
            return False
        _LOGGER.info("Wrote the %s: PDU %s = %s", what, pdu, ack)
        self.coordinator.set_local_value(pdu, ack)
        return True

    async def _async_tick(self, _now: datetime) -> None:
        self._rollover()
        if self.vacation_on and self.vacation_until and dt_util.utcnow() >= self.vacation_until:
            _LOGGER.info("Vacation ended (%s)", self.vacation_until)
            await self.async_set_vacation(False)
            self.vacation_until = None
        if self.auto_season:
            await self._async_season()
        self._notify()  # alerts (module offline) change with time alone

    async def _async_season(self) -> None:
        mean, hours = self.outdoor_24h
        mode = (self.coordinator.data or {}).get(MODE_PDU)
        if mean is None or hours < SEASON_MIN_HOURS or mode is None:
            return
        if self._season_changed and (dt_util.utcnow() - self._season_changed).total_seconds() < SEASON_MIN_INTERVAL:
            return
        target = None
        if int(mode) == MODE_SUMMER and mean < self.settings["season_winter_below"]:
            target = MODE_WINTER
        elif int(mode) == MODE_WINTER and mean > self.settings["season_summer_above"]:
            target = MODE_SUMMER
        if target is None:
            return  # Standby / Cooling or inside the band: never touched
        _LOGGER.info("Auto season: outdoor 24 h mean %.1f °C -> %s", mean, "Winter" if target == MODE_WINTER else "Summer")
        if await self._async_write(MODE_PDU, target, "operating mode (auto season)"):
            self._season_changed = dt_util.utcnow()
