"""1.6.14: OpenTherm values computed in Home Assistant from what the Dominus module reads (no extra boiler settings).

* **Hydraulics** - delta T (flow - return), mean loop temperature, the control setpoint the module sends (Data-ID 1,
  read back) and the flow minus it, exhaust minus return, condensing operation (return below the flue gas dew point
  while burning) and its share of today's burner time.
* **Burner power and gas** - kW from the modulation (Data-ID 17) between the min. and max. output (Data-ID 15), gas
  today (heating / DHW) and a gas counter in m³ (useful heat of 1 m³), the gas price and today's cost - estimates.
* **Short cycling** - average / last burn, the last pause, short burns, average modulation and the share at the
  minimum (from the flame flag of every poll, ~45 s: a lower bound).
* **DHW** - draws, litres and heat today (combi boilers with Data-ID 19); cylinder cycles today, the last cycle's
  length and the cylinder rise (boilers with a cylinder, by the DHW active flag).
* **Operating state** - one text ("CH · flame 45 % · 52 °C", "DHW", "Fault E10", "Idle").
* **Diagnostics** - the system pressure drop over 24 h with a possible leak warning, the average flame current while
  burning with a low flame current warning, the fan speed minus its setpoint.
* **CH supervision** - is a CH demand really taken up by the boiler (see ot_supervision_state).
* **Room and building** - the room deviation from the target (1 h mean), the time to reach a raised target, degree
  days (base 18 °C) today / this month and heating hours per degree day.

Values are integrated between polls; a gap longer than MAX_GAP is not counted. The daily / monthly counters and the
gas counter are kept in a Store (they survive a restart); the rolling windows (1 h, 24 h) start empty after one.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
import time
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from datetime import timedelta

from .const import DEVICE_MAIN, DOMAIN
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

MAX_GAP = 600            # s: a longer gap between polls is not integrated
DEW_POINT = 55.0         # °C: flue gas dew point of natural gas
GAS_KWH_PER_M3 = 10.6    # useful heat of 1 m³ (calorific value ~10.9 kWh/m³ x boiler efficiency ~0.97)
SHORT_BURN_MIN = 5.0     # a burn shorter than this is a short burn
LEAK_BAR_DAY = 0.2       # pressure drop over 24 h that raises the leak warning
FLAME_LOW_UA = 2.0       # average flame current below this raises the warning
COLD_WATER = 10.0        # °C: cold water for the DHW heat from the flow
DD_BASE = 18.0           # °C: degree day base
SUP_NEAR_SETPOINT = 3.0  # K: with the flow this close to the control setpoint the boiler has a reason to wait
SUP_STATES = ["fault", "no_demand", "demand_unknown", "confirmed", "dhw", "reached", "waiting", "no_response"]

# Data-IDs the computations read (each entity polls what it needs, see OT_POLL)
ST, CTRL, CAP, ROOM_SET, MOD, PRESS, DHW_FLOW, ROOM, FLOW, DHW, OUT, RET, EXH, FAN, FLAME_I = (
    0, 1, 15, 16, 17, 18, 19, 24, 25, 26, 27, 28, 33, 35, 36)


def _f88(raw: Any, positive: bool = False, probe: bool = False) -> float | None:
    if raw is None:
        return None
    raw = int(raw) & 0xFFFF
    if probe and raw == 0x7300:
        return None
    if raw & 0x8000:
        return None if positive else (raw - 0x10000) / 256
    return raw / 256


def ot_supervision_state(status: int, ctrl: float | None, flow: float | None, room: float | None,
                         room_set: float | None, demand_visible: bool) -> str:
    """What the boiler is doing about central heating, from one poll. "waiting" = it should be heating and is not.

    The regulator is in the Dominus module, so a demand is only inferred: the CH enable bit (the master status echoed in
    the high byte of Data-ID 0) tells that the mode allows CH, the control setpoint (Data-ID 1) that the module asks
    for water, and the room (Data-ID 24 / 16) that it still needs heat. With a physical thermostat on the boiler
    contacts the demand cannot be seen at all, so nothing is counted. Diagnosis only - nothing is written."""
    if status & 0x01:
        return "fault"
    if not status & 0x0100:
        return "no_demand"
    if status & 0x02:
        return "confirmed"
    if status & 0x04:
        return "dhw"
    if not demand_visible:
        return "demand_unknown"
    if ctrl is None or ctrl <= 10 or (room is not None and room_set is not None and room >= room_set):
        return "no_demand"
    if flow is not None and ctrl - flow < SUP_NEAR_SETPOINT:
        return "reached"
    return "waiting"


class OtComputed:
    """Keeps the computed values; entities read them and listen for updates."""

    def __init__(self, hass: HomeAssistant, coordinator: ImmergasDominusCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.lang = "pl" if str(hass.config.language).startswith("pl") else "en"
        self._store: Store = Store(hass, 1, f"{DOMAIN}.ot_computed.{coordinator.config_entry.entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsub: list[Callable[[], None]] = []
        self._at: float | None = None
        self.gas_price: float = 3.86
        self.elec_price: float = 1.0           # per kWh, for the gas / electricity comparison
        self.tank_volume: float = 0.0          # L, 0 = no cylinder (combi boiler)
        self.sup_limit: float = 15.0           # min without a response before the CH alarm
        self._sup_idle = 0.0                   # s the boiler has ignored the CH demand
        self.v: dict[str, Any] = {}            # the published values
        self.d: dict[str, Any] = self._fresh_day()
        self.m: dict[str, Any] = {"month": dt_util.now().strftime("%Y-%m"), "dd": 0.0, "ch_h": 0.0}
        self.gas_total = 0.0
        # transient state
        self._flame: bool | None = None
        self._flame_on: float | None = None
        self._flame_off: float | None = None
        self._dhw: bool | None = None
        self._dhw_start: float | None = None
        self._dhw_t0: float | None = None
        self._dhw_tmax: float | None = None
        self._dhw_q = 0.0                      # kWh of the running DHW cycle
        self._draw: bool = False
        self._draw_start: float | None = None
        self._room_dev: deque[tuple[float, float]] = deque()
        self._p_hist: deque[tuple[float, float]] = deque()
        self._flame_i_ema: float | None = None
        self._set_prev: float | None = None
        self._reach_start: float | None = None

    @staticmethod
    def _fresh_day() -> dict[str, Any]:
        return {"day": dt_util.now().date().isoformat(), "q_ch": 0.0, "q_dhw": 0.0, "burn_s": 0.0, "cond_s": 0.0,
                "minmod_s": 0.0, "mod_sum": 0.0, "starts": 0, "short": 0, "burn_last": None, "pause_last": None,
                "draws": 0, "draw_last": None, "litres": 0.0, "q_draw": 0.0, "cycles": 0, "cyc_last": None,
                "cyc_rise": None, "cyc_gas": None, "dd": 0.0, "reach_last": None}

    # ------------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        today, month = dt_util.now().date().isoformat(), dt_util.now().strftime("%Y-%m")
        if data.get("d", {}).get("day") == today:
            self.d.update(data["d"])
        if data.get("m", {}).get("month") == month:
            self.m.update(data["m"])
        self.gas_total = float(data.get("gas_total", 0.0))
        self.gas_price = float(data.get("gas_price", self.gas_price))
        self.elec_price = float(data.get("elec_price", self.elec_price))
        self.tank_volume = float(data.get("tank_volume", self.tank_volume))
        self.sup_limit = float(data.get("sup_limit", self.sup_limit))
        self._unsub.append(self.coordinator.async_add_listener(self._update))
        self._unsub.append(async_track_time_interval(self.hass, self._save, timedelta(minutes=5)))
        self._publish()

    async def async_stop(self) -> None:
        for u in self._unsub:
            u()
        self._unsub.clear()
        await self._save()

    async def _save(self, *_: Any) -> None:
        await self._store.async_save({"d": self.d, "m": self.m, "gas_total": self.gas_total, "gas_price": self.gas_price,
                                      "elec_price": self.elec_price, "tank_volume": self.tank_volume, "sup_limit": self.sup_limit})

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def set_gas_price(self, value: float) -> None:
        self.gas_price = value
        self._publish()
        self.hass.async_create_task(self._save())

    def set_elec_price(self, value: float) -> None:
        self.elec_price = value
        self._publish()
        self.hass.async_create_task(self._save())

    def set_tank_volume(self, value: float) -> None:
        self.tank_volume = value
        self._publish()
        self.hass.async_create_task(self._save())

    def set_sup_limit(self, value: float) -> None:
        self.sup_limit = value
        self._publish()
        self.hass.async_create_task(self._save())

    # ------------------------------------------------------------------ the computation
    @callback
    def _update(self) -> None:
        data = self.coordinator.data or {}
        st = data.get(ST)
        if st is None:
            return
        st = int(st)
        fault, ch, dhw, flame = bool(st & 0x01), bool(st & 0x02), bool(st & 0x04), bool(st & 0x08)
        flow, ret = _f88(data.get(FLOW)), _f88(data.get(RET))
        out, room, room_set = _f88(data.get(OUT)), _f88(data.get(ROOM)), _f88(data.get(ROOM_SET))
        tdhw, exh, press = _f88(data.get(DHW)), _f88(data.get(EXH)), _f88(data.get(PRESS), positive=True)
        mod, ctrl = _f88(data.get(MOD), positive=True), _f88(data.get(CTRL))
        wflow, flame_i = _f88(data.get(DHW_FLOW), positive=True), _f88(data.get(FLAME_I), positive=True)
        cap_raw = data.get(CAP)
        cap = (int(cap_raw) >> 8) & 0xFF if cap_raw is not None else 0
        minmod = int(cap_raw) & 0xFF if cap_raw is not None else 0
        fan_raw = data.get(FAN)

        now = time.monotonic()
        dt = 0.0 if self._at is None or now - self._at > MAX_GAP else now - self._at
        self._at = now
        today, month = dt_util.now().date().isoformat(), dt_util.now().strftime("%Y-%m")
        if self.d["day"] != today:
            self.d = self._fresh_day()
        if self.m["month"] != month:
            self.m = {"month": month, "dd": 0.0, "ch_h": 0.0}
        d, v = self.d, self.v

        # ---- CH supervision: time counts only while the boiler has no reason of its own to stay idle
        programs = getattr(self.coordinator, "ot_programs", None)
        sup = ot_supervision_state(st, ctrl, flow, room, room_set, getattr(programs, "thermostat", "none") != "physical")
        self._sup_idle = self._sup_idle + dt if sup == "waiting" else 0.0
        alarm = self._sup_idle >= self.sup_limit * 60
        v["sup_state"] = "no_response" if alarm else sup
        v["sup_alarm"] = alarm
        v["sup_idle_min"] = int(self._sup_idle // 60)

        # ---- burner power (kW) and the heat / gas split by DHW / heating
        power = None
        if flame and mod is not None and cap > 0:
            mn = minmod if 0 < minmod < 90 else 20
            m = min(100.0, max(0.0, mod))
            power = cap * (mn + (100 - mn) * m / 100) / 100
        elif not flame:
            power = 0.0
        if flame and power and dt:
            q = power * dt / 3600
            d["q_dhw" if dhw else "q_ch"] += q
            if dhw:
                self._dhw_q += q
            self.gas_total += q / GAS_KWH_PER_M3
        # ---- burns and pauses (the flag of each poll)
        if self._flame is False and flame:
            d["starts"] += 1
            if self._flame_off is not None:
                d["pause_last"] = (now - self._flame_off) / 60
            self._flame_on = now
        if self._flame and not flame and self._flame_on is not None:
            length = (now - self._flame_on) / 60
            d["burn_last"] = length
            if length < SHORT_BURN_MIN:
                d["short"] += 1
            self._flame_off = now
        self._flame = flame
        if flame and dt:
            d["burn_s"] += dt
            if mod is not None:
                d["mod_sum"] += mod * dt
                if mod <= 2:
                    d["minmod_s"] += dt
            if ret is not None and ret < DEW_POINT:
                d["cond_s"] += dt
            if ch and not dhw:
                self.m["ch_h"] += dt / 3600
        # ---- DHW cylinder cycles (the DHW active flag)
        if dhw and not self._dhw:
            self._dhw_start, self._dhw_t0, self._dhw_tmax = now, tdhw, tdhw
            self._dhw_q = 0.0
        if dhw and tdhw is not None and (self._dhw_tmax is None or tdhw > self._dhw_tmax):
            self._dhw_tmax = tdhw
        if self._dhw and not dhw and self._dhw_start is not None:
            mins = (now - self._dhw_start) / 60
            if mins >= 1:
                d["cycles"] += 1
                d["cyc_last"] = mins
                d["cyc_rise"] = (self._dhw_tmax - self._dhw_t0) if self._dhw_t0 is not None and self._dhw_tmax is not None else None
                d["cyc_gas"] = self._dhw_q / GAS_KWH_PER_M3
        self._dhw = dhw
        # ---- DHW draws (combi: the DHW flow)
        draw = wflow is not None and wflow > 1
        if draw and not self._draw:
            d["draws"] += 1
            self._draw_start = now
        if self._draw and not draw and self._draw_start is not None:
            d["draw_last"] = (now - self._draw_start) / 60
        self._draw = draw
        if draw and dt:
            d["litres"] += wflow * dt / 60
            if tdhw is not None and tdhw > COLD_WATER:
                d["q_draw"] += wflow * dt / 60 * 4.186 * (tdhw - COLD_WATER) / 3600
        # ---- degree days
        if out is not None and dt:
            inc = max(0.0, DD_BASE - out) * dt / 86400
            d["dd"] += inc
            self.m["dd"] += inc
        # ---- room deviation (1 h) and the time to reach a raised target
        if room is not None and room_set is not None:
            self._room_dev.append((now, room - room_set))
            while self._room_dev and now - self._room_dev[0][0] > 3600:
                self._room_dev.popleft()
            if self._set_prev is not None and room_set - self._set_prev >= 0.5:
                self._reach_start = now
            if self._reach_start is not None and room >= room_set - 0.2:
                d["reach_last"] = (now - self._reach_start) / 60
                self._reach_start = None
            self._set_prev = room_set
        # ---- pressure history (24 h)
        if press is not None:
            if not self._p_hist or now - self._p_hist[-1][0] >= 3600:
                self._p_hist.append((now, press))
            while len(self._p_hist) > 25:
                self._p_hist.popleft()
        # ---- flame current while burning (exponential mean, ~10 min)
        if flame and flame_i is not None and flame_i > 0:
            k = min(1.0, dt / 600) if dt else 0.1
            self._flame_i_ema = flame_i if self._flame_i_ema is None else self._flame_i_ema + (flame_i - self._flame_i_ema) * k

        # ---- publish
        v["delta_t"] = None if flow is None or ret is None else flow - ret
        v["mean_loop"] = None if flow is None or ret is None else (flow + ret) / 2
        v["control_setpoint"] = ctrl
        v["setpoint_dev"] = flow - ctrl if flame and ch and not dhw and flow is not None and ctrl is not None else None
        v["exh_return"] = exh - ret if flame and exh is not None and ret is not None else None
        v["condensing"] = bool(flame and ret is not None and ret < DEW_POINT)
        v["power"] = power
        v["pressure_drop"] = (self._p_hist[0][1] - press) if press is not None and len(self._p_hist) >= 2 else None
        v["leak"] = v["pressure_drop"] is not None and v["pressure_drop"] >= LEAK_BAR_DAY
        v["flame_i_avg"] = self._flame_i_ema
        v["flame_low"] = self._flame_i_ema is not None and self._flame_i_ema < FLAME_LOW_UA
        if fan_raw is not None:
            fr = int(fan_raw)
            v["fan_dev"] = ((fr & 0xFF) - ((fr >> 8) & 0xFF)) * 60 if (fr >> 8) & 0xFF else None
        v["room_dev"] = sum(x for _, x in self._room_dev) / len(self._room_dev) if self._room_dev else None
        v["state"] = self._state_text(fault, ch, dhw, flame, mod, flow, data)
        self._publish()

    def _state_text(self, fault: bool, ch: bool, dhw: bool, flame: bool, mod: float | None, flow: float | None,
                    data: dict) -> str:
        pl = self.lang == "pl"
        if fault:
            code = int(data.get(5) or 0) & 0xFF
            return (f"Usterka E{code}" if pl else f"Fault E{code}") if code else ("Usterka" if pl else "Fault")
        if dhw:
            return ("CWU" if pl else "DHW") + ("" if flame else (" · bez płomienia" if pl else " · no flame"))
        if ch:
            s = "CO" if pl else "CH"
            s += (f" · {'płomień' if pl else 'flame'} {mod or 0:.0f} %") if flame else (" · bez płomienia" if pl else " · no flame")
            return s + (f" · {flow:.0f} °C" if flow is not None else "")
        return "Postój" if pl else "Idle"

    def _publish(self) -> None:
        d, v = self.d, self.v
        k = GAS_KWH_PER_M3
        bs = d["burn_s"]
        v["gas_today"] = (d["q_ch"] + d["q_dhw"]) / k
        v["gas_ch_today"] = d["q_ch"] / k
        v["gas_dhw_today"] = d["q_dhw"] / k
        v["gas_total"] = self.gas_total
        v["gas_cost_today"] = v["gas_today"] * self.gas_price
        v["heat_today"] = d["q_ch"] + d["q_dhw"]
        v["condensing_share"] = d["cond_s"] / bs * 100 if bs > 60 else None
        v["minmod_share"] = d["minmod_s"] / bs * 100 if bs > 60 else None
        v["mod_avg"] = d["mod_sum"] / bs if bs > 60 else None
        v["burn_avg"] = bs / 60 / d["starts"] if d["starts"] else None
        v["short_burns"] = d["short"]
        v["burn_last"] = d["burn_last"]
        v["pause_last"] = d["pause_last"]
        v["draws_today"] = d["draws"]
        v["draw_last"] = d["draw_last"]
        v["dhw_litres"] = d["litres"]
        v["dhw_heat"] = d["q_draw"]
        v["dhw_cycles"] = d["cycles"]
        v["dhw_cycle_last"] = d["cyc_last"]
        v["dhw_cycle_rise"] = d["cyc_rise"]
        v["dhw_cycle_gas"] = d.get("cyc_gas")
        v["dd_today"] = d["dd"]
        v["dd_month"] = self.m["dd"]
        v["h_per_dd"] = self.m["ch_h"] / self.m["dd"] if self.m["dd"] > 0.5 else None
        v["reach_last"] = d["reach_last"]
        v["gas_price"] = self.gas_price
        for cb in list(self._listeners):
            cb()


# key: (unit, device_class, state_class, icon, precision, Data-IDs to poll, enabled by default)
_T, _K = UnitOfTemperature.CELSIUS, UnitOfTemperature.KELVIN
SENSORS: dict[str, tuple] = {
    "ot_delta_t": (_K, None, "m", "mdi:delta", 1, (FLOW, RET), True),
    "ot_mean_loop": (_T, SensorDeviceClass.TEMPERATURE, "m", "mdi:approximately-equal", 1, (FLOW, RET), True),
    "ot_control_setpoint": (_T, SensorDeviceClass.TEMPERATURE, "m", "mdi:thermometer-water", 1, (CTRL,), True),
    "ot_setpoint_dev": (_K, None, "m", "mdi:target", 1, (FLOW, CTRL), True),
    "ot_exh_return": (_K, None, "m", "mdi:smoke", 1, (EXH, RET), True),
    "ot_power": (UnitOfPower.KILO_WATT, SensorDeviceClass.POWER, "m", "mdi:fire", 1, (MOD, CAP), True),
    "ot_gas_today": (UnitOfVolume.CUBIC_METERS, SensorDeviceClass.GAS, None, "mdi:meter-gas", 2, (MOD, CAP), True),
    "ot_gas_ch_today": (UnitOfVolume.CUBIC_METERS, SensorDeviceClass.GAS, None, "mdi:radiator", 2, (MOD, CAP), True),
    "ot_gas_dhw_today": (UnitOfVolume.CUBIC_METERS, SensorDeviceClass.GAS, None, "mdi:water-boiler", 2, (MOD, CAP), True),
    "ot_gas_total": (UnitOfVolume.CUBIC_METERS, SensorDeviceClass.GAS, "t", "mdi:meter-gas-outline", 2, (MOD, CAP), True),
    "ot_gas_cost_today": (None, None, None, "mdi:cash", 2, (MOD, CAP), True),
    "ot_heat_today": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, None, "mdi:fire", 1, (MOD, CAP), True),
    "ot_condensing_share": ("%", None, "m", "mdi:water-percent", 0, (RET,), True),
    "ot_minmod_share": ("%", None, "m", "mdi:percent-outline", 0, (MOD,), True),
    "ot_mod_avg": ("%", None, "m", "mdi:fire-circle", 0, (MOD,), True),
    "ot_burn_avg": (UnitOfTime.MINUTES, None, "m", "mdi:timer-sync-outline", 1, (), True),
    "ot_short_burns": (None, None, "m", "mdi:timer-alert-outline", 0, (), True),
    "ot_burn_last": (UnitOfTime.MINUTES, None, None, "mdi:timer-outline", 1, (), True),
    "ot_pause_last": (UnitOfTime.MINUTES, None, None, "mdi:timer-pause-outline", 1, (), True),
    "ot_draws_today": (None, None, "m", "mdi:water-pump", 0, (DHW_FLOW, DHW), False),
    "ot_draw_last": (UnitOfTime.MINUTES, None, None, "mdi:timer-outline", 1, (DHW_FLOW,), False),
    "ot_dhw_litres": (UnitOfVolume.LITERS, SensorDeviceClass.WATER, None, "mdi:water", 0, (DHW_FLOW,), False),
    "ot_dhw_heat": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, None, "mdi:water-thermometer", 2, (DHW_FLOW, DHW), False),
    "ot_dhw_cycles": (None, None, "m", "mdi:water-boiler", 0, (DHW,), True),
    "ot_dhw_cycle_last": (UnitOfTime.MINUTES, None, None, "mdi:timer-outline", 0, (DHW,), True),
    "ot_dhw_cycle_rise": (_K, None, None, "mdi:thermometer-chevron-up", 1, (DHW,), True),
    "ot_dhw_cycle_gas": (UnitOfVolume.CUBIC_METERS, None, None, "mdi:meter-gas", 3, (DHW, MOD, CAP), True),
    "ot_pressure_drop": ("bar", None, "m", "mdi:gauge-low", 2, (PRESS,), True),
    "ot_flame_i_avg": ("µA", None, "m", "mdi:fire-circle", 1, (FLAME_I,), False),
    "ot_fan_dev": ("rpm", None, "m", "mdi:fan-alert", 0, (FAN,), False),
    "ot_room_dev": (_K, None, "m", "mdi:home-thermometer-outline", 1, (ROOM, ROOM_SET), True),
    "ot_reach_last": (UnitOfTime.MINUTES, None, None, "mdi:timer-play-outline", 0, (ROOM, ROOM_SET), True),
    "ot_dd_today": (None, None, "m", "mdi:thermometer-minus", 1, (OUT,), True),
    "ot_dd_month": (None, None, "m", "mdi:calendar-month", 1, (OUT,), True),
    "ot_h_per_dd": (UnitOfTime.HOURS, None, "m", "mdi:home-clock", 2, (OUT,), True),
}
BINARY: dict[str, tuple] = {   # key: (value key, device class, icon, Data-IDs, enabled)
    "ot_condensing": ("condensing", None, "mdi:water-outline", (RET,), True),
    "ot_leak_warning": ("leak", BinarySensorDeviceClass.PROBLEM, None, (PRESS,), True),
    "ot_flame_low": ("flame_low", BinarySensorDeviceClass.PROBLEM, None, (FLAME_I,), False),
    "ot_sup_alarm": ("sup_alarm", BinarySensorDeviceClass.PROBLEM, "mdi:shield-alert-outline", (CTRL, FLOW, ROOM, ROOM_SET), True),
}


class _CalcEntity(ImmergasDominusEntity):
    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, polls: tuple[int, ...], enabled: bool) -> None:
        super().__init__(coordinator, key, ST, DEVICE_MAIN)
        self._polls = (ST, *polls)
        self._attr_translation_key = key
        self._attr_entity_registry_enabled_default = enabled
        self._vk = key[3:]

    def _poll_pdus(self) -> tuple[int, ...]:
        return self._polls

    @property
    def calc(self) -> OtComputed:
        return self.coordinator.ot_computed

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.calc.add_listener(self.async_write_ha_state))


class OtCalcSensor(_CalcEntity, SensorEntity):
    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, spec: tuple) -> None:
        unit, dc, sc, icon, prec, polls, enabled = spec
        super().__init__(coordinator, key, polls, enabled)
        if key == "ot_gas_cost_today":
            unit = coordinator.hass.config.currency
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = dc
        self._attr_state_class = SensorStateClass.MEASUREMENT if sc == "m" else SensorStateClass.TOTAL_INCREASING if sc == "t" else None
        self._attr_icon = icon
        self._attr_suggested_display_precision = prec

    @property
    def native_value(self) -> float | int | None:
        x = self.calc.v.get(self._vk)
        return None if x is None else round(x, 3) if isinstance(x, float) else x


class OtStateSensor(_CalcEntity, SensorEntity):
    _attr_icon = "mdi:state-machine"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_op_state", (FLOW, MOD, 5), True)
        self._vk = "state"

    @property
    def native_value(self) -> str | None:
        return self.calc.v.get("state")


class OtSupervisionSensor(_CalcEntity, SensorEntity):
    _attr_icon = "mdi:shield-search"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = SUP_STATES
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_sup_state", (CTRL, FLOW, ROOM, ROOM_SET), True)

    @property
    def native_value(self) -> str | None:
        return self.calc.v.get("sup_state")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"minutes_without_response": self.calc.v.get("sup_idle_min", 0)}


class OtCalcBinary(_CalcEntity, BinarySensorEntity):
    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str, spec: tuple) -> None:
        vk, dc, icon, polls, enabled = spec
        super().__init__(coordinator, key, polls, enabled)
        self._vk = vk
        self._attr_device_class = dc
        if icon:
            self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        return bool(self.calc.v.get(self._vk))


class OtGasPriceNumber(ImmergasDominusEntity, RestoreNumber):
    """Gas price per m³ for today's gas cost (kept in the computed store)."""

    _attr_translation_key = "ot_gas_price"
    _attr_icon = "mdi:fire"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 50
    _attr_native_step = 0.01
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_gas_price", ST, DEVICE_MAIN)
        self._attr_native_unit_of_measurement = f"{coordinator.hass.config.currency}/m³"

    @property
    def native_value(self) -> float:
        return self.coordinator.ot_computed.gas_price

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.ot_computed.set_gas_price(value)
        self.async_write_ha_state()


class OtElecPriceNumber(ImmergasDominusEntity, RestoreNumber):
    """Electricity price per kWh for the gas / electricity comparison (kept in the computed store)."""

    _attr_translation_key = "ot_elec_price"
    _attr_icon = "mdi:flash"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 50
    _attr_native_step = 0.001
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_elec_price", ST, DEVICE_MAIN)
        self._attr_native_unit_of_measurement = f"{coordinator.hass.config.currency}/kWh"

    @property
    def native_value(self) -> float:
        return self.coordinator.ot_computed.elec_price

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.ot_computed.set_elec_price(value)
        self.async_write_ha_state()


class OtTankVolumeNumber(ImmergasDominusEntity, RestoreNumber):
    """DHW cylinder volume in litres, 0 = no cylinder (OpenTherm does not report it)."""

    _attr_translation_key = "ot_tank_volume"
    _attr_icon = "mdi:water-boiler"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 1000
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "L"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_tank_volume", ST, DEVICE_MAIN)

    @property
    def native_value(self) -> float:
        return self.coordinator.ot_computed.tank_volume

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.ot_computed.set_tank_volume(value)
        self.async_write_ha_state()


class OtSupLimitNumber(ImmergasDominusEntity, RestoreNumber):
    """Minutes without a response before the CH alarm (longer than the boiler's own CH timer)."""

    _attr_translation_key = "ot_sup_limit"
    _attr_icon = "mdi:timer-alert-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 5
    _attr_native_max_value = 120
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_sup_limit", ST, DEVICE_MAIN)

    @property
    def native_value(self) -> float:
        return self.coordinator.ot_computed.sup_limit

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.ot_computed.set_sup_limit(value)
        self.async_write_ha_state()


def ot_computed_sensors(coordinator: ImmergasDominusCoordinator) -> list:
    return [OtStateSensor(coordinator), OtSupervisionSensor(coordinator), *(OtCalcSensor(coordinator, k, s) for k, s in SENSORS.items())]


def ot_computed_binary_sensors(coordinator: ImmergasDominusCoordinator) -> list:
    return [OtCalcBinary(coordinator, k, s) for k, s in BINARY.items()]
