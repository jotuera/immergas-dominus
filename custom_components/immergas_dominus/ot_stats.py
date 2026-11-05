"""OpenTherm burner statistics computed in Home Assistant from the flame flag (Data-ID 0, slave status bit 3).

* **Burner starts today** and **in the last 60 min** - a start is a change from flame off to flame on between two polls.
* **Burner hours today** - the flame-on time integrated between polls.

The flame flag is read once per polling cycle (about every 45 s), so a burner run shorter than that may be missed:
the numbers are a lower bound, good for spotting short cycling, not an exact count. A gap longer than MAX_GAP
(module offline, Home Assistant restart) is not integrated. The daily values survive a restart (restored sensors).
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
import time

from homeassistant.components.sensor import RestoreSensor, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DEVICE_MAIN
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

STATUS_ID = 0
FLAME_MASK = 0x08
MAX_GAP = 600  # s
HOUR = 3600


class OtBurnerStats:
    """Counts burner starts and the flame-on time from the coordinator data."""

    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.day = dt_util.now().date().isoformat()
        self.starts_today = 0
        self.hours_today = 0.0
        self._recent: deque[float] = deque()  # monotonic times of the starts in the last hour
        self._flame: bool | None = None
        self._at: float | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsub: Callable[[], None] | None = None

    def start(self) -> None:
        self._unsub = self.coordinator.async_add_listener(self._update)

    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def restore(self, day: str | None, starts: float | None = None, hours: float | None = None) -> None:
        """Daily values from the restored sensors (only when they belong to today)."""
        if day != self.day:
            return
        if starts is not None:
            self.starts_today = max(self.starts_today, int(starts))
        if hours is not None:
            self.hours_today = max(self.hours_today, float(hours))

    @property
    def starts_hour(self) -> int:
        self._trim(time.monotonic())
        return len(self._recent)

    def _trim(self, now: float) -> None:
        while self._recent and now - self._recent[0] > HOUR:
            self._recent.popleft()

    @callback
    def _update(self) -> None:
        data = self.coordinator.data or {}
        raw = data.get(STATUS_ID)
        if raw is None:
            return
        flame = bool(int(raw) & FLAME_MASK)
        now = time.monotonic()
        today = dt_util.now().date().isoformat()
        if today != self.day:
            self.day, self.starts_today, self.hours_today = today, 0, 0.0
        if self._at is not None and self._flame and now - self._at <= MAX_GAP:
            self.hours_today += (now - self._at) / HOUR
        if self._flame is False and flame:
            self.starts_today += 1
            self._recent.append(now)
        self._trim(now)
        self._flame, self._at = flame, now
        for cb in list(self._listeners):
            cb()


class _OtStatSensor(ImmergasDominusEntity, RestoreSensor):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, icon: str) -> None:
        super().__init__(coordinator, key, STATUS_ID, DEVICE_MAIN)
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def stats(self) -> OtBurnerStats:
        return self.coordinator.ot_stats

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.stats.add_listener(self.async_write_ha_state))
        last = await self.async_get_last_state()
        data = await self.async_get_last_sensor_data()
        if last is not None and data is not None and data.native_value is not None:
            self._restore(last.attributes.get("day"), float(data.native_value))

    def _restore(self, day: str | None, value: float) -> None:
        raise NotImplementedError

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"day": self.stats.day}


class OtBurnerStartsTodaySensor(_OtStatSensor):
    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_burner_starts_today", "mdi:fire-circle")

    def _restore(self, day: str | None, value: float) -> None:
        self.stats.restore(day, starts=value)

    @property
    def native_value(self) -> int:
        return self.stats.starts_today


class OtBurnerHoursTodaySensor(_OtStatSensor):
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_burner_hours_today", "mdi:timer-outline")

    def _restore(self, day: str | None, value: float) -> None:
        self.stats.restore(day, hours=value)

    @property
    def native_value(self) -> float:
        return round(self.stats.hours_today, 3)


class OtBurnerStartsHourSensor(ImmergasDominusEntity, SensorEntity):
    """Burner starts in the last 60 minutes (rolling; starts empty after a restart)."""

    _attr_translation_key = "ot_burner_starts_hour"
    _attr_icon = "mdi:fire-alert"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "/h"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_burner_starts_hour", STATUS_ID, DEVICE_MAIN)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.ot_stats.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return self.coordinator.ot_stats.starts_hour


def ot_stat_sensors(coordinator: ImmergasDominusCoordinator) -> list:
    return [OtBurnerStartsTodaySensor(coordinator), OtBurnerStartsHourSensor(coordinator),
            OtBurnerHoursTodaySensor(coordinator)]
