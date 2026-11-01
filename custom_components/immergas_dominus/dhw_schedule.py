"""DHW Comfort / Eco by the boiler's DHW schedule.

The boiler has a single DHW setpoint (PDU 2095) and its DHW schedule only enables or blocks DHW heating.  With the
switch "DHW Comfort/Eco by schedule" on, this helper writes the Comfort setpoint while the time is inside a range of
the calendar assigned to today (DHW weekday PDU 2490-2496 -> calendar 1-4, ranges 2310-2347) and the Eco setpoint
outside them.  It writes only when the phase or a Comfort / Eco value changes, so a manual change of the DHW target
holds until the next phase.  It works with the zone 1 time program in Manual too.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .coordinator import ImmergasDominusCoordinator
from .dominus_client import DominusError

_LOGGER = logging.getLogger(__name__)

DHW_TARGET_PDU = 2095
DHW_WEEKDAY_PDUS = tuple(range(2490, 2497))  # Monday .. Sunday
CALENDAR_PDUS = tuple(2310 + 10 * cal + i for cal in range(4) for i in range(8))
DEFAULT_COMFORT = 50.0
DEFAULT_ECO = 45.0
CHECK_INTERVAL = timedelta(seconds=60)


def _minutes(raw: int) -> int:
    """Range time -> minutes of the day (high byte = hour, low byte = minute; 0xE0 = panel 'modified' flag)."""
    raw = int(raw) & 0x1FFF
    hour, minute = raw >> 8, min(raw & 0xFF, 59)
    return 1440 if hour >= 24 else hour * 60 + minute


class DhwComfortEco:
    """Keeps the DHW target at Comfort inside today's DHW calendar ranges, Eco outside."""

    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.comfort = DEFAULT_COMFORT
        self.eco = DEFAULT_ECO
        self.enabled = False
        self.phase: str | None = None  # "comfort" | "economy" | None
        self._applied: tuple[str, int] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_coord: CALLBACK_TYPE | None = None

    @callback
    def add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Entities showing the phase / values register here."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def set_enabled(self, enabled: bool) -> None:
        if enabled == self.enabled:
            return
        self.enabled = enabled
        pdus = (DHW_TARGET_PDU, *DHW_WEEKDAY_PDUS, *CALENDAR_PDUS)
        if enabled:
            self._applied = None
            if self.coordinator.register_pdus(pdus):
                self.hass.async_create_task(self.coordinator.async_request_refresh())
            self._unsub_timer = async_track_time_interval(self.hass, self._async_tick, CHECK_INTERVAL)
            self._unsub_coord = self.coordinator.async_add_listener(self._on_data)
            self.hass.async_create_task(self.async_check())
        else:
            self.coordinator.unregister_pdus(pdus)
            for unsub in (self._unsub_timer, self._unsub_coord):
                if unsub:
                    unsub()
            self._unsub_timer = self._unsub_coord = None
            self.phase = None
        self._notify()

    @callback
    def set_value(self, which: str, value: float) -> None:
        if which == "comfort":
            self.comfort = value
        else:
            self.eco = value
        if self.enabled:
            self.hass.async_create_task(self.async_check())

    @callback
    def _on_data(self) -> None:
        self.hass.async_create_task(self.async_check())

    async def _async_tick(self, _now) -> None:
        await self.async_check()

    def _comfort_now(self) -> bool | None:
        """True inside a range of today's DHW calendar, None while the schedule is not read yet."""
        data = self.coordinator.data or {}
        now = dt_util.now()
        day = data.get(DHW_WEEKDAY_PDUS[now.weekday()])
        if day is None:
            return None
        cal = (int(day) & 0xFF) - 1
        if not 0 <= cal <= 3:
            return None
        m = now.hour * 60 + now.minute
        for rng in range(4):
            on, off = data.get(2310 + 10 * cal + 2 * rng), data.get(2311 + 10 * cal + 2 * rng)
            if on is None or off is None:
                return None
            a, b = _minutes(on), _minutes(off)
            if a == b:
                continue  # unused range
            if b == 0:
                b = 1440  # "until 00:00" = until midnight
            if (a <= m < b) if a < b else (m >= a or m < b):
                return True
        return False

    async def async_check(self) -> None:
        if not self.enabled:
            return
        comfort = self._comfort_now()
        if comfort is None:
            return
        phase = "comfort" if comfort else "economy"
        raw = round((self.comfort if comfort else self.eco) * 10)
        if phase != self.phase:
            self.phase = phase
            self._notify()
        if self._applied == (phase, raw):
            return
        self._applied = (phase, raw)
        current = (self.coordinator.data or {}).get(DHW_TARGET_PDU)
        if current is not None and int(current) == raw:
            return
        try:
            ack = await self.coordinator.client.async_write_pdu(DHW_TARGET_PDU, raw)
        except DominusError as err:
            _LOGGER.warning("DHW %s by schedule: writing %.1f °C failed: %s", phase, raw / 10, err)
            self._applied = None  # retry at the next check
            return
        _LOGGER.info("DHW %s by schedule: target %.1f °C", phase, raw / 10)
        self.coordinator.set_local_value(DHW_TARGET_PDU, ack)
