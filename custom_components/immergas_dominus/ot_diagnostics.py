"""OpenTherm diagnostics: what does this boiler support and does it really take a written value.

* **Status overlay** - the low byte sent with every Data-ID 0 frame.  Standard OpenTherm sends 0; other OpenTherm
  gateways send 0xCA for Immergas boilers ("Immergas fix"), reported to unlock writes to Data-ID 1 / 57.
* **Data-ID scan** - reads every standard Data-ID once and lists what the boiler answers.
* **Last write** - after every write the value is read back: "ok" (taken), "mismatch" (acknowledged, but the boiler
  keeps another value), "no_readback" (a command such as the reset).
* Data-IDs the boiler answers as unsupported three times in a row are skipped for an hour (listed in the scan sensor).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEVICE_MAIN
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

STATUS_OVERLAYS = {"standard": None, "immergas": 0xCA}
WRITE_RESULTS = ["ok", "mismatch", "no_readback", "unsupported", "error"]


def _table(table: dict | None) -> dict[int, int | str] | None:
    """An indexed scan table for the attributes / the report: index -> value (decimal) or the failure."""
    return None if table is None else dict(sorted(table.items()))


def _table_text(table: dict | None) -> str:
    if table is None:
        return "-"
    return ", ".join(f"{i}={v}" for i, v in sorted(table.items())) or "(0 entries)"


class _DiagEntity(ImmergasDominusEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)
        self._attr_translation_key = key

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    @property
    def client(self):
        return self.coordinator.client


class OtStatusOverlaySelect(_DiagEntity, SelectEntity, RestoreEntity):
    """Low byte of the Data-ID 0 frames: standard (0) or the Immergas 0xCA."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(STATUS_OVERLAYS)
    _attr_icon = "mdi:code-brackets"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_status_overlay")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in STATUS_OVERLAYS:
            self.client.status_lb = STATUS_OVERLAYS[last.state]

    @property
    def current_option(self) -> str:
        return next((k for k, v in STATUS_OVERLAYS.items() if v == self.client.status_lb), "standard")

    async def async_select_option(self, option: str) -> None:
        self.client.status_lb = STATUS_OVERLAYS[option]
        self.async_write_ha_state()


class OtReadOnlySwitch(_DiagEntity, SwitchEntity, RestoreEntity):
    """On: Home Assistant only reads - every write (controls, programs, reset) is refused before it reaches the
    Dominus. For a boiler controlled by its remote (CAR V2 / Super Amico): a value written once is kept by the module
    and sent to the boiler over the remote's own until the module is power-cycled."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:lock-outline"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_read_only")

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.client.read_only = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self.client.read_only

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.client.read_only = True
        self._changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.client.read_only = False
        self._changed()

    def _changed(self) -> None:
        self.async_write_ha_state()
        programs = getattr(self.coordinator, "ot_programs", None)
        if programs is not None:  # program entities show "blocked_by_remote"; MANUAL / AUTO write their phase again
            programs._ch_written = programs._dhw_written = None
            programs.changed()


class OtScanButton(_DiagEntity, ButtonEntity):
    """Read every standard Data-ID once (takes about a minute; polling pauses meanwhile)."""

    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_scan")

    async def async_press(self) -> None:
        self.client.start_scan()


class OtScanSensor(_DiagEntity, SensorEntity):
    """Number of Data-IDs the boiler answered in the last scan; the lists in the attributes."""

    _attr_icon = "mdi:format-list-checks"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_supported_ids")

    @property
    def native_value(self) -> int | None:
        res = self.client.scan_result
        return sum(1 for r in res.values() if r == "ok") if res else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c, res = self.client, self.client.scan_result
        pick = lambda what: [i for i, r in sorted(res.items()) if r == what]  # noqa: E731
        finished = c.scan_finished
        return {
            "running": c.scan_running,
            "supported": pick("ok"),
            "unsupported": pick("unsupported"),
            "no_reply": pick("error"),
            "values": {i: f"0x{v:04X}" for i, v in sorted(c.scan_values.items())},
            # 1.6.7: the boiler's own parameters (TSP, Data-ID 11) and the fault history (Data-ID 13), index: value
            "boiler_parameters": _table(c.scan_tables.get(11)),
            "fault_history": _table(c.scan_tables.get(13)),
            "suppressed_now": sorted(f"{(k >> 8) & 0xFF}/{k & 0xFF}" if k >= 0x10000 else k for k in c.suppressed),
            "finished": datetime.fromtimestamp(finished, timezone.utc).isoformat() if finished else None,
        }


class OtReportButton(_DiagEntity, ButtonEntity):
    """Prepare the GitHub report of the Data-ID scan: a notification with a link to a pre-filled issue (nothing is
    sent automatically)."""

    _attr_icon = "mdi:github"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_scan_report")

    def map_text(self) -> str:
        c, res = self.client, self.client.scan_result
        pick = lambda what: [i for i, r in sorted(res.items()) if r == what]  # noqa: E731
        sup = pick("ok")
        lines = [
            f"supported: {len(sup)}, unsupported: {len(pick('unsupported'))}, no reply: {len(pick('error'))}",
            "",
            "values (Data-ID=raw hex, HB/LB):",
            ", ".join(f"{i}=0x{c.scan_values[i]:04X}" for i in sup if i in c.scan_values),
            "",
            f"unsupported: {', '.join(map(str, pick('unsupported'))) or '-'}",
            f"no reply: {', '.join(map(str, pick('error'))) or '-'}",
            "",
            "boiler parameters (TSP, Data-ID 11 index=value):",
            _table_text(c.scan_tables.get(11)),
            "fault history (Data-ID 13 index=code):",
            _table_text(c.scan_tables.get(13)),
            f"status low byte sent: {'0xCA (Immergas)' if c.status_lb == 0xCA else '0x00 (standard)'}",
        ]
        return "\n".join(lines)

    async def async_press(self) -> None:
        from urllib.parse import urlencode

        from homeassistant.components import persistent_notification
        from homeassistant.loader import async_get_integration

        from .const import DOMAIN
        c = self.client
        nid, title = f"{DOMAIN}_ot_report", "Immergas Dominus – OpenTherm Data-ID map"
        if not c.scan_result or c.scan_running:
            persistent_notification.async_create(
                self.hass, "Run **Scan Data-IDs** first and wait until it finishes (about a minute).",
                title=title, notification_id=nid)
            return
        integration = await async_get_integration(self.hass, DOMAIN)
        version = str(integration.version) if integration.version else ""
        model = getattr(self.coordinator, "boiler_model", "")
        query = urlencode({"template": "opentherm-map.yml", "title": f"OpenTherm map: {model or 'boiler model?'}",
                           "model": model, "version": version, "map": self.map_text()})
        url = f"https://github.com/jotuera/immergas-dominus/issues/new?{query}"
        sup = sum(1 for r in c.scan_result.values() if r == "ok")
        msg = (
            f"Data-ID scan: {sup} supported of {len(c.scan_result)}. Boiler model: "
            f"**{model or '(not set – fill in “Boiler model”)'}**.\n\n"
            f"**[Open the pre-filled GitHub issue]({url})**\n\n"
            "Nothing is sent automatically: the link opens GitHub with the report filled in (boiler model, integration "
            "version, the Data-ID values – no host, MAC or password). Check it there and press *Create* to send it, or "
            "just close the page. A GitHub account is needed."
        )
        persistent_notification.async_create(self.hass, msg, title=title, notification_id=nid)


class OtLastWriteSensor(_DiagEntity, SensorEntity):
    """Result of the last write, checked by reading the value back."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = WRITE_RESULTS
    _attr_icon = "mdi:check-network-outline"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_last_write")

    @property
    def native_value(self) -> str | None:
        last = self.client.last_write
        return last["result"] if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        last = self.client.last_write
        if not last:
            return None
        hexv = lambda v: None if v is None else f"0x{int(v):04X}"  # noqa: E731
        return {"data_id": last["key"], "sent": hexv(last["sent"]), "acknowledged": hexv(last["ack"]),
                "read_back": hexv(last["readback"]), "rechecks": last.get("rechecks", 0),
                "at": datetime.fromtimestamp(last["at"], timezone.utc).isoformat()}
