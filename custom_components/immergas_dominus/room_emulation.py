"""Modbus mode: the room thermostat of zone 1 - what is connected, and an emulated one fed from Home Assistant.

The Dominus does not report the room thermostat, so the user says what is there: **none**, **physical** (with the
boiler's A31 room control RP / RPT / RT, the declared select) or **emulated**: Home Assistant sends the temperature of
an HA entity to the module as the zone 1 room temperature (PDU 2011, °C × 10) - the way the hub's ESP emulates the zone
panel on D+/D-. **Experimental:** PDU 2011 is the room temperature the zone panel gives the boiler; whether the module
accepts a write of it over TCP is judged by reading 2011 back on the next polls - NOT by the acknowledgement: a test on
a Magis Pro-Combo V2 (05.11.2026) got the written value echoed as the ACK while 2011 kept the zone panel's value, so the
module does not take it. Written on a change of 0.1 °C or every 5 minutes.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DEVICE_MAIN
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

_LOGGER = logging.getLogger(__name__)

ROOM_PDU = 2011
THERMOSTAT_OPTIONS = ["none", "physical", "emulated"]


class RoomEmulator:
    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.thermostat = "none"
        self.room_source = ""
        self.room_sent: float | None = None
        self.room_sent_at: datetime | None = None
        self.last_ack: float | None = None
        self.result: str | None = None  # taken / not_taken / error
        self._mono = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._unsub: Callable[[], None] | None = None

    def start(self) -> None:
        self._unsub = async_track_time_interval(self.hass, self._tick, timedelta(seconds=60))

    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def changed(self) -> None:
        self.room_sent = None
        for cb in list(self._listeners):
            cb()
        self.hass.async_create_task(self._tick(dt_util.now()))

    def source_value(self) -> float | None:
        if not self.room_source:
            return None
        st = self.hass.states.get(self.room_source)
        try:
            v = float(st.state) if st is not None else None
        except (TypeError, ValueError):
            return None
        return v if v is not None and -20 < v < 50 else None

    def _judge(self) -> None:
        """A minute after a write: did PDU 2011 (read by the normal polling) take the sent temperature?"""
        if self.result != "pending" or self.room_sent is None or time.monotonic() - self._mono < 60:
            return
        cur = (self.coordinator.data or {}).get(ROOM_PDU)
        if cur is None:
            return
        taken = abs(int(cur) / 10 - self.room_sent) <= 0.15
        self.result = "taken" if taken else "not_taken"
        if not taken:
            _LOGGER.info("Emulated thermostat: PDU %s reads back %.1f after writing %.1f - the module does not take it",
                         ROOM_PDU, int(cur) / 10, self.room_sent)
        for cb in list(self._listeners):
            cb()

    async def _tick(self, _now: datetime) -> None:
        if self.thermostat != "emulated":
            return
        self._judge()
        v = self.source_value()
        if v is None:
            return
        mono = time.monotonic()
        if self.room_sent is not None and abs(v - self.room_sent) < 0.05 and mono - self._mono < 300:
            return
        raw = int(round(v * 10))
        try:
            ack = await self.coordinator.client.async_write_pdu(ROOM_PDU, raw)
        except Exception as err:  # noqa: BLE001 - the next tick tries again
            _LOGGER.debug("Emulated thermostat: writing PDU %s failed: %s", ROOM_PDU, err)
            self.result, self.last_ack = "error", None
        else:
            self.last_ack = ack / 10
            # the ACK only echoes the request: "pending" until 2011 is read back on a later poll (_judge)
            self.result = "pending" if ack == raw else "not_taken"
            if ack != raw:
                _LOGGER.info("Emulated thermostat: PDU %s written %s, acknowledged %s", ROOM_PDU, raw, ack)
        self.room_sent, self.room_sent_at, self._mono = v, dt_util.now(), mono
        for cb in list(self._listeners):
            cb()


class _RoomEntity(ImmergasDominusEntity, RestoreEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)
        self.emu: RoomEmulator = coordinator.room_emulator

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.emu.add_listener(self.async_write_ha_state))
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "unknown", "unavailable"):
            self._restore(last.state)

    def _restore(self, state: str) -> None:
        raise NotImplementedError


class RoomThermostatSelect(_RoomEntity, SelectEntity):
    """Room thermostat of zone 1: none / physical / emulated (same translation key as the OpenTherm mode)."""

    _attr_translation_key = "ot_thermostat"
    _attr_options = THERMOSTAT_OPTIONS
    _attr_icon = "mdi:thermostat"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "room_thermostat")

    def _restore(self, state: str) -> None:
        if state in THERMOSTAT_OPTIONS:
            self.emu.thermostat = state

    @property
    def current_option(self) -> str:
        return self.emu.thermostat

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        e = self.emu
        return {"room_source": e.room_source or None, "room_source_value": e.source_value(), "room_sent": e.room_sent,
                "room_sent_at": e.room_sent_at.isoformat() if e.room_sent_at else None, "acknowledged": e.last_ack,
                "write_result": e.result, "pdu": ROOM_PDU}

    async def async_select_option(self, option: str) -> None:
        self.emu.thermostat = option
        self.emu.changed()


class RoomSourceText(_RoomEntity, TextEntity):
    """Entity id whose temperature the emulated thermostat sends as the zone 1 room temperature."""

    _attr_translation_key = "ot_room_source"
    _attr_icon = "mdi:home-thermometer-outline"
    _attr_native_max = 255

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "room_source")

    def _restore(self, state: str) -> None:
        self.emu.room_source = state

    @property
    def native_value(self) -> str:
        return self.emu.room_source

    async def async_set_value(self, value: str) -> None:
        self.emu.room_source = value.strip()
        self.emu.changed()
