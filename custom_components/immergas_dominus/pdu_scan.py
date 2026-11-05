"""PDU scanner (Modbus mode): read a range of PDUs through the Dominus TCP and prepare a map report.

The Dominus module answers every PDU it is asked for; a PDU the boiler does not provide usually reads 0, so a scan
cannot tell "unsupported" from a real 0 - the report lists the zeros separately.  Every read is its own authenticated
TCP session (about a second per PDU); the normal polling runs in between, so a scan of 1000 PDUs takes 15-20 minutes.

The report is never sent automatically: the "Report PDU map" button creates a notification with a link to a
pre-filled GitHub issue (boiler model, integration version, the map).  The user opens it, checks the content and
submits it on GitHub.  The report holds no host, MAC or password.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEVICE_MAIN, DOMAIN
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

_LOGGER = logging.getLogger(__name__)

REPO_ISSUES = "https://github.com/jotuera/immergas-dominus/issues/new"
MAX_RANGE = 2000          # PDUs per scan
READ_PAUSE = 0.3          # s between two reads, lets the normal polling in
URL_BUDGET = 7000         # GitHub refuses very long pre-filled URLs
DEFAULT_FROM, DEFAULT_TO = 2000, 2999


def _ranges(pdus: list[int]) -> str:
    """[1, 2, 3, 7] -> "1-3, 7"."""
    out: list[str] = []
    start = prev = None
    for p in sorted(pdus):
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            out.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = p
    if start is not None:
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(out)


class PduScanner:
    """Scan state of one Dominus entry."""

    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.from_pdu = DEFAULT_FROM
        self.to_pdu = DEFAULT_TO
        self.running = False
        self.current: int | None = None
        self.values: dict[int, int] = {}
        self.no_reply: list[int] = []
        self.scanned_range: tuple[int, int] | None = None
        self.started: float | None = None
        self.finished: float | None = None
        self._stop = False
        self._task: asyncio.Task | None = None
        self._listeners: list[Any] = []

    @property
    def model(self) -> str:
        return getattr(self.coordinator, "boiler_model", "")

    # --- listeners (the entities) ---
    def add_listener(self, cb) -> Any:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # --- scan ---
    def start(self) -> None:
        if self.running:
            self._stop = True
            return
        lo, hi = sorted((int(self.from_pdu), int(self.to_pdu)))
        hi = min(hi, lo + MAX_RANGE - 1)
        self.values, self.no_reply = {}, []
        self.scanned_range = (lo, hi)
        self.running, self._stop = True, False
        self.started, self.finished, self.current = time.time(), None, lo
        self._notify()
        self._task = self.hass.async_create_background_task(self._run(lo, hi), f"{DOMAIN} PDU scan")

    def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()

    def _read(self, pdu: int) -> int:
        client = self.coordinator.client
        with client._lock:  # noqa: SLF001 - one TCP client at a time, shared with the polling
            return client._read_pdu_blocking(pdu).value_s16  # noqa: SLF001

    async def _run(self, lo: int, hi: int) -> None:
        try:
            for pdu in range(lo, hi + 1):
                if self._stop:
                    break
                self.current = pdu
                try:
                    self.values[pdu] = await asyncio.to_thread(self._read, pdu)
                except Exception as err:  # noqa: BLE001
                    self.no_reply.append(pdu)
                    _LOGGER.debug("PDU scan: no reply for %s: %s", pdu, err)
                if (pdu - lo) % 10 == 0:
                    self._notify()
                await asyncio.sleep(READ_PAUSE)
        finally:
            self.running, self.finished, self.current = False, time.time(), None
            self._notify()

    # --- results ---
    @property
    def nonzero(self) -> dict[int, int]:
        return {p: v for p, v in sorted(self.values.items()) if v != 0}

    @property
    def zero(self) -> list[int]:
        return [p for p, v in sorted(self.values.items()) if v == 0]

    def map_text(self, limit: int | None = None) -> str:
        rng = self.scanned_range
        nz = self.nonzero
        lines = [
            f"range: {rng[0]}-{rng[1]}" if rng else "range: -",
            f"read: {len(self.values)}, non-zero: {len(nz)}, zero: {len(self.zero)}, no reply: {len(self.no_reply)}",
            "",
            "non-zero (PDU=value, signed 16 bit):",
        ]
        pairs = [f"{p}={v}" for p, v in nz.items()]
        tail = [
            "",
            f"zero: {_ranges(self.zero) or '-'}",
            f"no reply: {_ranges(self.no_reply) or '-'}",
        ]
        text = "\n".join(lines + [", ".join(pairs)] + tail)
        if limit is not None and len(text) > limit:
            # keep the non-zero values (the interesting part), shorten the zero list
            tail = ["", f"zero: {len(self.zero)} PDUs (list too long for the link, see the sensor attributes)",
                    f"no reply: {_ranges(self.no_reply) or '-'}"]
            text = "\n".join(lines + [", ".join(pairs)] + tail)
            if len(text) > limit:
                text = text[: limit - 40] + "\n... (cut, see the sensor attributes)"
        return text

    def report_url(self, version: str | None) -> str:
        rng = self.scanned_range
        title = f"PDU map: {self.model or 'boiler model?'}" + (f" ({rng[0]}-{rng[1]})" if rng else "")
        base = {"template": "pdu-map.yml", "title": title, "model": self.model,
                "version": version or "", "range": f"{rng[0]}-{rng[1]}" if rng else ""}
        budget = URL_BUDGET - len(REPO_ISSUES) - len(urlencode(base)) - 10
        text = self.map_text()
        # the URL-encoded text is longer than the text; shrink until it fits
        limit = len(text)
        while len(urlencode({"map": text})) > budget and limit > 200:
            limit = int(limit * 0.8)
            text = self.map_text(limit)
        return f"{REPO_ISSUES}?{urlencode({**base, 'map': text})}"


# ------------------------------------------------------------------------------------------------ entities
class _ScanEntity(ImmergasDominusEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)
        self._attr_translation_key = key

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    @property
    def scanner(self) -> PduScanner:
        return self.coordinator.pdu_scan

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.scanner.add_listener(self.async_write_ha_state))


class PduScanRangeNumber(_ScanEntity, RestoreNumber):
    """First / last PDU of the scan."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 65535
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:numeric"

    def __init__(self, coordinator: ImmergasDominusCoordinator, which: str) -> None:
        super().__init__(coordinator, f"pdu_scan_{which}")
        self._which = which

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            setattr(self.scanner, f"{self._which}_pdu", int(last.native_value))

    @property
    def native_value(self) -> float:
        return float(getattr(self.scanner, f"{self._which}_pdu"))

    async def async_set_native_value(self, value: float) -> None:
        setattr(self.scanner, f"{self._which}_pdu", int(value))
        self.async_write_ha_state()


class BoilerModelText(ImmergasDominusEntity, TextEntity, RestoreEntity):
    """Boiler model typed by the user, goes into the PDU / Data-ID map report (both modes)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_max = 80
    _attr_icon = "mdi:water-boiler"
    _attr_translation_key = "boiler_model"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "boiler_model", 0, DEVICE_MAIN)

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "unknown", "unavailable"):
            self.coordinator.boiler_model = last.state

    @property
    def native_value(self) -> str:
        return getattr(self.coordinator, "boiler_model", "")

    async def async_set_value(self, value: str) -> None:
        self.coordinator.boiler_model = value.strip()
        self.async_write_ha_state()


class PduScanButton(_ScanEntity, ButtonEntity):
    """Start the scan of the range (pressed again while running: stop)."""

    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "pdu_scan")

    async def async_press(self) -> None:
        self.scanner.start()


class PduReportButton(_ScanEntity, ButtonEntity):
    """Prepare the GitHub report: a notification with a link to a pre-filled issue (nothing is sent automatically)."""

    _attr_icon = "mdi:github"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "pdu_scan_report")

    async def async_press(self) -> None:
        s = self.scanner
        if not s.values:
            persistent_notification.async_create(
                self.hass, "Run **Scan PDUs** first (Dominus device → Diagnostic).",
                title="Immergas Dominus – PDU map", notification_id=f"{DOMAIN}_pdu_report")
            return
        from homeassistant.loader import async_get_integration
        integration = await async_get_integration(self.hass, DOMAIN)
        url = s.report_url(str(integration.version) if integration.version else None)
        rng = s.scanned_range
        msg = (
            f"Scan {rng[0]}–{rng[1]}: {len(s.values)} PDUs read, {len(s.nonzero)} non-zero, {len(s.zero)} zero, "
            f"{len(s.no_reply)} no reply. Boiler model: **{s.model or '(not set – fill in “Boiler model”)'}**.\n\n"
            f"**[Open the pre-filled GitHub issue]({url})**\n\n"
            "Nothing is sent automatically: the link opens GitHub with the report filled in (boiler model, integration "
            "version, the PDU map – no host, MAC or password). Check it there and press *Create* to send it, or just "
            "close the page. A GitHub account is needed."
        )
        persistent_notification.async_create(
            self.hass, msg, title="Immergas Dominus – PDU map", notification_id=f"{DOMAIN}_pdu_report")


class PduScanSensor(_ScanEntity, SensorEntity):
    """Number of non-zero PDUs of the last scan; the map in the attributes."""

    _attr_icon = "mdi:map-search-outline"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "pdu_scan_result")

    @property
    def native_value(self) -> int | None:
        return len(self.scanner.nonzero) if self.scanner.values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.scanner
        rng = s.scanned_range
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None  # noqa: E731
        return {
            "running": s.running,
            "current": s.current,
            "range": f"{rng[0]}-{rng[1]}" if rng else None,
            "read": len(s.values),
            "non_zero": {str(p): v for p, v in s.nonzero.items()},
            "zero": _ranges(s.zero),
            "no_reply": _ranges(s.no_reply),
            "started": iso(s.started),
            "finished": iso(s.finished),
        }


def pdu_scan_numbers(coordinator) -> list:
    return [PduScanRangeNumber(coordinator, "from"), PduScanRangeNumber(coordinator, "to")]


def pdu_scan_buttons(coordinator) -> list:
    return [PduScanButton(coordinator), PduReportButton(coordinator)]


def pdu_scan_sensors(coordinator) -> list:
    return [PduScanSensor(coordinator)]


def pdu_scan_texts(coordinator) -> list:
    return [BoilerModelText(coordinator)]
