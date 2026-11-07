"""1.6.14: more values computed in Home Assistant from the PDUs the Dominus module reads (Modbus mode).

* **Room comfort** - time in comfort today (room within ±0.5 °C of the target), minutes too cold / too warm, room min /
  max today.
* **Building** - heating rate (°C/h while the zone calls for heat) and cooling rate (°C/h without), the heat loss
  coefficient (cooling rate / (room - outdoor), 1/h) and a suggested heating curve offset change (+1 / 0 / -1 °C) from
  the mean room deviation in the Comfort phase over the last days - a hint, nothing is written.
* **Phases** - Comfort / Eco time today, the mean room deviation in each, phase changes today.
* **DHW** - DHW heat used today (cylinder temperature drops outside the heating cycles x the cylinder volume) and the
  litres it means, the standing loss of the cylinder (°C/h at night without heating), the cylinder minimum today, the
  average DHW cycle today.
* **Operating state** - one text ("Heating · Comfort · 20.6 / 21 °C", "DHW · cylinder 46 °C", "Idle · Eco", "Fault E10").
* **Weather and link** - outdoor min / max today and the 24 h mean, the module availability today and the link breaks.
* **Zones 2 / 3** - heating time and starts today, the room deviation (entities of the zone devices, disabled with them).

Values are taken once per successful poll (~45 s); a gap longer than MAX_GAP is not integrated. The day values and the
history of the curve hint are kept in a Store (they survive a restart).
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DEVICE_MAIN,
    DEVICE_ZONE_2,
    DEVICE_ZONE_3,
    DHW_REQUEST_MASK,
    DOMAIN,
    FAULT_CODE_PDU,
    STATUS_FLAGS_PDU,
    ZONE_HEAT_DEMAND_MASK,
    ZONE_PHASE_COMFORT_MASK,
    ZONE_PHASE_ECONOMY_MASK,
    ZONE_STATUS_PDU,
)
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

MAX_GAP = 600
COMFORT_BAND = 0.5          # K around the target
MIN_SEGMENT = 1800          # s: a heating / cooling stretch shorter than this gives no rate
NIGHT = (1, 5)              # hours of the standing loss window
COLD_WATER = 10.0
MODE_PDU, ROOM_PDU, TARGET_PDU, OUTDOOR_PDU, TANK_PDU = 2000, 2011, 2015, 3002, 3016
BASE_PDUS = (MODE_PDU, STATUS_FLAGS_PDU, ZONE_STATUS_PDU, ROOM_PDU, TARGET_PDU, OUTDOOR_PDU, TANK_PDU, FAULT_CODE_PDU)


def _temp(raw: Any, invalid: tuple[int, ...] = ()) -> float | None:
    if raw is None or int(raw) in invalid:
        return None
    v = int(raw)
    if v >= 0x8000:
        v -= 0x10000
    return v / 10


def _zone_pdus(zone: int) -> tuple[int, ...]:
    off = (zone - 1) * 10
    return (ZONE_STATUS_PDU + off, ROOM_PDU + off, TARGET_PDU + off)


class DominusStatsExtra:
    """Keeps the extra statistics; entities read them and listen for updates."""

    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.lang = "pl" if str(hass.config.language).startswith("pl") else "en"
        self._store: Store = Store(hass, 1, f"{DOMAIN}.stats_extra.{coordinator.config_entry.entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsub: list[Callable[[], None]] = []
        self.tank_volume = 200.0
        self.d: dict[str, Any] = self._fresh_day()
        self.hist: list[list] = []            # [[day, mean Comfort deviation, Comfort seconds], ...] (last 7 days)
        self.v: dict[str, Any] = {}
        self._last_at = None
        self._prev: dict[str, Any] | None = None
        self._seg_ch: bool | None = None
        self._seg: deque[tuple[float, float, float | None]] = deque()   # (t, room, outdoor) of the current stretch
        self._out24: deque[tuple[float, float, float]] = deque()
        self._night: list[tuple[float, float]] = []
        self._dhw_on_at: float | None = None
        self._avail_prev = True
        self._zone_prev: dict[int, bool | None] = {2: None, 3: None}

    @staticmethod
    def _fresh_day() -> dict[str, Any]:
        return {"day": dt_util.now().date().isoformat(), "comfort_s": 0.0, "known_s": 0.0, "under_s": 0.0, "over_s": 0.0,
                "room_min": None, "room_max": None, "ph_comfort_s": 0.0, "ph_eco_s": 0.0, "dev_comfort": 0.0, "dev_eco": 0.0,
                "phase_changes": 0, "dhw_drop": 0.0, "dhw_litres": 0.0, "tank_min": None, "dhw_cyc_s": 0.0, "dhw_cycles": 0,
                "out_min": None, "out_max": None, "avail_s": 0.0, "tick_s": 0.0, "breaks": 0,
                "heat_rate": None, "cool_rate": None, "loss_coef": None, "standing_loss": None,
                "z2_ch_s": 0.0, "z2_starts": 0, "z3_ch_s": 0.0, "z3_starts": 0}

    # ------------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        if data.get("d", {}).get("day") == self.d["day"]:
            self.d.update(data["d"])
        else:
            # keep yesterday's rates (they change slowly) for the new day
            for k in ("heat_rate", "cool_rate", "loss_coef", "standing_loss"):
                if data.get("d", {}).get(k) is not None:
                    self.d[k] = data["d"][k]
        self.hist = data.get("hist", [])[-7:]
        self.tank_volume = float(data.get("tank_volume", self.tank_volume))
        self._unsub.append(self.coordinator.async_add_listener(self._on_data))
        self._unsub.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=60)))
        self._unsub.append(async_track_time_interval(self.hass, self._save, timedelta(minutes=5)))
        self._publish()

    async def async_stop(self) -> None:
        for u in self._unsub:
            u()
        self._unsub.clear()
        await self._save()

    async def _save(self, *_: Any) -> None:
        await self._store.async_save({"d": self.d, "hist": self.hist, "tank_volume": self.tank_volume})

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def set_tank_volume(self, value: float) -> None:
        self.tank_volume = value
        self._publish()
        self.hass.async_create_task(self._save())

    def _rollover(self) -> None:
        today = dt_util.now().date().isoformat()
        if self.d["day"] == today:
            return
        if self.d["ph_comfort_s"] > 3600:   # the finished day goes to the curve hint history
            self.hist = (self.hist + [[self.d["day"], self.d["dev_comfort"] / self.d["ph_comfort_s"], self.d["ph_comfort_s"]]])[-7:]
        keep = {k: self.d[k] for k in ("heat_rate", "cool_rate", "loss_coef", "standing_loss")}
        self.d = self._fresh_day()
        self.d.update(keep)

    # ------------------------------------------------------------------ availability (every minute)
    @callback
    def _tick(self, *_: Any) -> None:
        self._rollover()
        last = self.coordinator.last_success
        ok = last is not None and (dt_util.utcnow() - last).total_seconds() < 180
        self.d["tick_s"] += 60
        if ok:
            self.d["avail_s"] += 60
        if self._avail_prev and not ok:
            self.d["breaks"] += 1
        self._avail_prev = ok
        self._publish()

    # ------------------------------------------------------------------ one successful poll
    def _sample(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        zone, flags = data.get(ZONE_STATUS_PDU), data.get(STATUS_FLAGS_PDU)
        phase = None
        if zone is not None:
            z = int(zone)
            phase = "eco" if z & ZONE_PHASE_ECONOMY_MASK else "comfort" if z & ZONE_PHASE_COMFORT_MASK else "manual"
        s = {"ch": None if zone is None else bool(int(zone) & ZONE_HEAT_DEMAND_MASK),
             "dhw": None if flags is None else bool(int(flags) & DHW_REQUEST_MASK),
             "room": _temp(data.get(ROOM_PDU), (32767,)), "target": _temp(data.get(TARGET_PDU)),
             "outdoor": _temp(data.get(OUTDOOR_PDU), (255,)), "tank": _temp(data.get(TANK_PDU)), "phase": phase,
             "mode": None if data.get(MODE_PDU) is None else int(data[MODE_PDU]),
             "fault": int(data.get(FAULT_CODE_PDU) or 0)}
        for zn in (2, 3):
            st, rm, tg = (data.get(p) for p in _zone_pdus(zn))
            s[f"z{zn}_ch"] = None if st is None else bool(int(st) & ZONE_HEAT_DEMAND_MASK)
            s[f"z{zn}_dev"] = None if rm is None or tg is None or int(rm) == 32767 else _temp(rm) - _temp(tg)
        return s

    @callback
    def _on_data(self) -> None:
        at = self.coordinator.last_success
        if at is None or at == self._last_at:
            return
        self._rollover()
        cur, prev, last = self._sample(), self._prev, self._last_at
        dt = (at - last).total_seconds() if last else 0.0
        t = at.timestamp()
        d = self.d
        if prev and 0 < dt <= MAX_GAP:
            room, target, phase = prev["room"], prev["target"], prev["phase"]
            # A: comfort
            if room is not None and target is not None:
                dev = room - target
                d["known_s"] += dt
                if abs(dev) <= COMFORT_BAND:
                    d["comfort_s"] += dt
                elif dev < 0:
                    d["under_s"] += dt
                else:
                    d["over_s"] += dt
                # C: phases
                if phase == "comfort":
                    d["ph_comfort_s"] += dt
                    d["dev_comfort"] += dev * dt
                elif phase == "eco":
                    d["ph_eco_s"] += dt
                    d["dev_eco"] += dev * dt
            # G: zones 2 / 3
            for zn in (2, 3):
                if prev.get(f"z{zn}_ch"):
                    d[f"z{zn}_ch_s"] += dt
            if prev.get("dhw"):
                d["dhw_cyc_s"] += dt
            # D: DHW heat used = cylinder drops outside heating (and outside the night standing loss window)
            if prev["tank"] is not None and cur["tank"] is not None and not prev.get("dhw") and not cur.get("dhw"):
                drop = prev["tank"] - cur["tank"]
                hour = dt_util.now().hour
                if drop > 0 and not (NIGHT[0] <= hour < NIGHT[1]):
                    d["dhw_drop"] += drop
                    if cur["tank"] > COLD_WATER:
                        d["dhw_litres"] += self.tank_volume * drop / (cur["tank"] - COLD_WATER)
        # edges
        if prev:
            if prev.get("phase") and cur["phase"] and prev["phase"] != cur["phase"]:
                d["phase_changes"] += 1
            for zn in (2, 3):
                if cur[f"z{zn}_ch"] and prev.get(f"z{zn}_ch") is False:
                    d[f"z{zn}_starts"] += 1
            if cur["dhw"] and prev.get("dhw") is False:
                d["dhw_cycles"] += 1
        # min / max
        for key, val in (("room", cur["room"]), ("tank", cur["tank"]), ("out", cur["outdoor"])):
            if val is None:
                continue
            if key in ("room", "out"):
                d[f"{key}_min"] = val if d[f"{key}_min"] is None else min(d[f"{key}_min"], val)
                d[f"{key}_max"] = val if d[f"{key}_max"] is None else max(d[f"{key}_max"], val)
            else:
                d["tank_min"] = val if d["tank_min"] is None else min(d["tank_min"], val)
        if cur["outdoor"] is not None:
            self._out24.append((t, cur["outdoor"], dt))
            while self._out24 and self._out24[0][0] < t - 86400:
                self._out24.popleft()
        # B: heating / cooling stretches (the room slope over at least 30 min of one state)
        if cur["ch"] is not None and cur["room"] is not None:
            if cur["ch"] != self._seg_ch or (dt and dt > MAX_GAP):
                self._close_segment()
                self._seg_ch, self._seg = cur["ch"], deque()
            self._seg.append((t, cur["room"], cur["outdoor"]))
            self._close_segment()   # the ongoing stretch updates the rate once it is long enough
        # D: standing loss at night (the cylinder without heating, 01-05)
        hour = dt_util.now().hour
        if NIGHT[0] <= hour < NIGHT[1] and cur["tank"] is not None and not cur.get("dhw"):
            self._night.append((t, cur["tank"]))
        elif self._night:
            if len(self._night) > 10 and self._night[-1][0] - self._night[0][0] > 7200:
                rate = (self._night[0][1] - self._night[-1][1]) / ((self._night[-1][0] - self._night[0][0]) / 3600)
                if rate >= 0:
                    d["standing_loss"] = rate
            self._night = []
        self._prev, self._last_at = cur, at
        self._publish()

    def _close_segment(self) -> None:
        seg = self._seg
        if self._seg_ch is None or len(seg) < 5 or seg[-1][0] - seg[0][0] < MIN_SEGMENT:
            return
        hours = (seg[-1][0] - seg[0][0]) / 3600
        rate = (seg[-1][1] - seg[0][1]) / hours
        if self._seg_ch:
            self.d["heat_rate"] = rate
        else:
            self.d["cool_rate"] = -rate
            outs = [o for _, _, o in seg if o is not None]
            if outs:
                gap = sum(r for _, r, _ in seg) / len(seg) - sum(outs) / len(outs)
                if gap > 5 and rate < 0:
                    self.d["loss_coef"] = -rate / gap

    def _state_text(self, s: dict[str, Any] | None) -> str | None:
        if not s:
            return None
        pl = self.lang == "pl"
        if s["fault"]:
            return f"{'Usterka' if pl else 'Fault'} E{s['fault']}"
        if s["mode"] == 0:
            return "Stand-by"
        tank = f"{s['tank']:.0f} °C" if s["tank"] is not None else ""
        if s["dhw"]:
            return ("CWU" if pl else "DHW") + (f" · {'zasobnik' if pl else 'cylinder'} {tank}" if tank else "")
        phase = {"comfort": "Komfort" if pl else "Comfort", "eco": "Eko" if pl else "Eco", "manual": "Manual"}.get(s["phase"] or "", "")
        room = f"{s['room']:.1f} / {s['target']:.1f} °C" if s["room"] is not None and s["target"] is not None else ""
        if s["mode"] == 1:
            return ("Lato" if pl else "Summer") + (f" · {'zasobnik' if pl else 'cylinder'} {tank}" if tank else "")
        if s["ch"]:
            head = ("Chłodzenie" if pl else "Cooling") if s["mode"] == 2 else ("Grzanie" if pl else "Heating")
        else:
            head = "Postój" if pl else "Idle"
        return " · ".join(x for x in (head, phase, room) if x)

    def _publish(self) -> None:
        d, v = self.d, self.v
        v["comfort_share"] = d["comfort_s"] / d["known_s"] * 100 if d["known_s"] > 600 else None
        v["too_cold_min"] = d["under_s"] / 60
        v["too_warm_min"] = d["over_s"] / 60
        v["room_min"], v["room_max"] = d["room_min"], d["room_max"]
        v["heat_rate"], v["cool_rate"], v["loss_coef"] = d["heat_rate"], d["cool_rate"], d["loss_coef"]
        days = [h for h in self.hist if h[2] > 3600][-5:]
        if len(days) >= 3:
            mean = sum(h[1] for h in days) / len(days)
            v["curve_hint"] = 1 if mean < -COMFORT_BAND else -1 if mean > COMFORT_BAND else 0
            v["curve_hint_dev"] = mean
        else:
            v["curve_hint"], v["curve_hint_dev"] = None, None
        v["comfort_hours"] = d["ph_comfort_s"] / 3600
        v["eco_hours"] = d["ph_eco_s"] / 3600
        v["dev_comfort"] = d["dev_comfort"] / d["ph_comfort_s"] if d["ph_comfort_s"] > 600 else None
        v["dev_eco"] = d["dev_eco"] / d["ph_eco_s"] if d["ph_eco_s"] > 600 else None
        v["phase_changes"] = d["phase_changes"]
        v["dhw_heat_used"] = self.tank_volume * 4.186 * d["dhw_drop"] / 3600
        v["dhw_litres_used"] = d["dhw_litres"]
        v["standing_loss"] = d["standing_loss"]
        v["tank_min"] = d["tank_min"]
        v["dhw_cycle_avg"] = d["dhw_cyc_s"] / 60 / d["dhw_cycles"] if d["dhw_cycles"] else None
        v["out_min"], v["out_max"] = d["out_min"], d["out_max"]
        w = sum(x[2] for x in self._out24)
        v["out_mean_24h"] = sum(x[1] * x[2] for x in self._out24) / w if w > 3600 else None
        v["availability"] = d["avail_s"] / d["tick_s"] * 100 if d["tick_s"] >= 600 else None
        v["link_breaks"] = d["breaks"]
        v["state"] = self._state_text(self._prev)
        for zn in (2, 3):
            v[f"z{zn}_ch_hours"] = d[f"z{zn}_ch_s"] / 3600
            v[f"z{zn}_starts"] = d[f"z{zn}_starts"]
            v[f"z{zn}_dev"] = (self._prev or {}).get(f"z{zn}_dev")
        v["tank_volume"] = self.tank_volume
        for cb in list(self._listeners):
            cb()


# key: (value key, unit, device class, state class, icon, precision, device, Data PDUs)
_K, _T = UnitOfTemperature.KELVIN, UnitOfTemperature.CELSIUS
SPECS: dict[str, tuple] = {
    "comfort_share_today": ("comfort_share", "%", None, "m", "mdi:sofa-outline", 0),
    "too_cold_minutes_today": ("too_cold_min", UnitOfTime.MINUTES, None, "m", "mdi:snowflake-thermometer", 0),
    "too_warm_minutes_today": ("too_warm_min", UnitOfTime.MINUTES, None, "m", "mdi:sun-thermometer", 0),
    "room_min_today": ("room_min", _T, SensorDeviceClass.TEMPERATURE, "m", "mdi:thermometer-low", 1),
    "room_max_today": ("room_max", _T, SensorDeviceClass.TEMPERATURE, "m", "mdi:thermometer-high", 1),
    "room_heating_rate": ("heat_rate", "°C/h", None, "m", "mdi:home-thermometer", 2),
    "room_cooling_rate": ("cool_rate", "°C/h", None, "m", "mdi:home-thermometer-outline", 2),
    "building_loss_coefficient": ("loss_coef", "1/h", None, "m", "mdi:home-export-outline", 3),
    "curve_offset_hint": ("curve_hint", _K, None, None, "mdi:tune-vertical", 0),
    "comfort_hours_today": ("comfort_hours", UnitOfTime.HOURS, None, "m", "mdi:sofa", 2),
    "eco_hours_today": ("eco_hours", UnitOfTime.HOURS, None, "m", "mdi:leaf", 2),
    "comfort_deviation_today": ("dev_comfort", _K, None, "m", "mdi:delta", 1),
    "eco_deviation_today": ("dev_eco", _K, None, "m", "mdi:delta", 1),
    "phase_changes_today": ("phase_changes", None, None, "m", "mdi:swap-horizontal", 0),
    "dhw_heat_used_today": ("dhw_heat_used", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, None, "mdi:water-thermometer", 2),
    "dhw_litres_used_today": ("dhw_litres_used", UnitOfVolume.LITERS, SensorDeviceClass.WATER, None, "mdi:water", 0),
    "dhw_standing_loss": ("standing_loss", "°C/h", None, "m", "mdi:thermometer-minus", 2),
    "tank_min_today": ("tank_min", _T, SensorDeviceClass.TEMPERATURE, "m", "mdi:water-boiler-alert", 1),
    "dhw_cycle_average_today": ("dhw_cycle_avg", UnitOfTime.MINUTES, None, "m", "mdi:timer-sync-outline", 0),
    "outdoor_min_today": ("out_min", _T, SensorDeviceClass.TEMPERATURE, "m", "mdi:thermometer-chevron-down", 1),
    "outdoor_max_today": ("out_max", _T, SensorDeviceClass.TEMPERATURE, "m", "mdi:thermometer-chevron-up", 1),
    "outdoor_mean_24h": ("out_mean_24h", _T, SensorDeviceClass.TEMPERATURE, "m", "mdi:thermometer-auto", 1),
    "module_availability_today": ("availability", "%", None, "m", "mdi:lan-check", 1),
    "link_breaks_today": ("link_breaks", None, None, "m", "mdi:lan-disconnect", 0),
}
ZONE_SPECS: dict[str, tuple] = {
    "ch_hours_today": ("ch_hours", UnitOfTime.HOURS, None, "m", "mdi:radiator", 2),
    "ch_starts_today_zone": ("starts", None, None, "m", "mdi:fire-circle", 0),
    "room_deviation_zone": ("dev", _K, None, "m", "mdi:delta", 1),
}


class _ExtraEntity(ImmergasDominusEntity):
    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, polls: tuple[int, ...], device: str = DEVICE_MAIN) -> None:
        super().__init__(coordinator, key, polls[0], device)
        self._polls = polls
        self._attr_translation_key = key.split("__")[0]

    def _poll_pdus(self) -> tuple[int, ...]:
        return self._polls

    @property
    def extra(self) -> DominusStatsExtra:
        return self.coordinator.stats_extra

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.extra.add_listener(self.async_write_ha_state))


class DominusExtraSensor(_ExtraEntity, SensorEntity):
    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, spec: tuple, vk: str | None = None,
                 device: str = DEVICE_MAIN, polls: tuple[int, ...] = BASE_PDUS) -> None:
        val, unit, dc, sc, icon, prec = spec
        super().__init__(coordinator, key, polls, device)
        self._vk = vk or val
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = dc
        self._attr_state_class = SensorStateClass.MEASUREMENT if sc == "m" else None
        self._attr_icon = icon
        self._attr_suggested_display_precision = prec

    @property
    def native_value(self) -> float | int | None:
        x = self.extra.v.get(self._vk)
        return None if x is None else round(x, 3) if isinstance(x, float) else x

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._vk != "curve_hint":
            return None
        dev = self.extra.v.get("curve_hint_dev")
        return {"mean_comfort_deviation": None if dev is None else round(dev, 2), "days": len(self.extra.hist)}


class DominusStateSensor(_ExtraEntity, SensorEntity):
    _attr_icon = "mdi:state-machine"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "operating_state", BASE_PDUS)

    @property
    def native_value(self) -> str | None:
        return self.extra.v.get("state")


class DominusTankVolumeNumber(ImmergasDominusEntity, RestoreNumber):
    """DHW cylinder volume for the DHW heat used (kept in the extra statistics store)."""

    _attr_translation_key = "dhw_tank_volume"
    _attr_icon = "mdi:storage-tank"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 30
    _attr_native_max_value = 1000
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "dhw_tank_volume", TANK_PDU, DEVICE_MAIN)

    @property
    def native_value(self) -> float:
        return self.coordinator.stats_extra.tank_volume

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.stats_extra.set_tank_volume(value)
        self.async_write_ha_state()


def stats_extra_sensors(coordinator: ImmergasDominusCoordinator) -> list:
    out: list = [DominusStateSensor(coordinator), *(DominusExtraSensor(coordinator, k, s) for k, s in SPECS.items())]
    for zn, dev in ((2, DEVICE_ZONE_2), (3, DEVICE_ZONE_3)):
        for k, s in ZONE_SPECS.items():
            out.append(DominusExtraSensor(coordinator, f"{k}__zone{zn}", s, vk=f"z{zn}_{s[0]}", device=dev, polls=_zone_pdus(zn)))
    return out
