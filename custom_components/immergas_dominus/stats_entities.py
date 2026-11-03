"""Entities of the statistics and automations helper (stats.py): sensors, alerts, settings, switches, the vacation end.

They poll no PDU of their own (the helper registers what it needs) and update when the helper notifies them.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.datetime import DateTimeEntity
from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .anomalies import describe
from .const import DEVICE_MAIN, FAULT_CODE_PDU
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity
from .stats import DominusStats


class _StatsEntity(ImmergasDominusEntity):
    """Base: no PDU of its own, always available, refreshed by the helper."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, key: str) -> None:
        super().__init__(coordinator, key, 0, DEVICE_MAIN)
        self._key = key
        self._attr_translation_key = key

    @property
    def stats(self) -> DominusStats:
        return self.coordinator.stats

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.stats.add_listener(self.async_write_ha_state))


# --- statistics sensors ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class StatSpec:
    """One statistic: value, unit, classes; `period` = "day" / "month" for counters restored after a restart."""

    key: str
    value: Callable[[DominusStats], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    icon: str | None = None
    precision: int | None = None
    period: str | None = None  # "day" | "month" | "last" (kept, no period)
    attrs: Callable[[DominusStats], dict[str, Any]] | None = None


STAT_SPECS: tuple[StatSpec, ...] = (
    StatSpec(key="ch_heating_time_today", value=lambda s: round(s.ch_today_s / 3600, 2), unit=UnitOfTime.HOURS,
             device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.TOTAL_INCREASING,
             icon="mdi:radiator", precision=2, period="day"),
    StatSpec(key="ch_heating_share_24h", value=lambda s: s.ch_share_24h, unit=PERCENTAGE, icon="mdi:chart-donut",
             precision=1),
    StatSpec(key="dhw_cycles_today", value=lambda s: s.dhw_cycles_today, state_class=SensorStateClass.TOTAL_INCREASING,
             icon="mdi:water-boiler", period="day"),
    StatSpec(key="last_dhw_cycle_duration", value=lambda s: s.last_dhw_min, unit=UnitOfTime.MINUTES,
             device_class=SensorDeviceClass.DURATION, icon="mdi:timer-outline", precision=0, period="last"),
    StatSpec(key="last_dhw_cycle_rise", value=lambda s: s.last_dhw_rise, unit="K", icon="mdi:thermometer-chevron-up",
             precision=1, period="last"),
    StatSpec(key="ch_starts_per_hour", value=lambda s: s.starts_per_hour, unit="/h", icon="mdi:restart"),
    StatSpec(key="ch_starts_today", value=lambda s: s.ch_starts_today, state_class=SensorStateClass.TOTAL_INCREASING,
             icon="mdi:counter", period="day"),
    StatSpec(key="room_deviation", value=lambda s: s.room_deviation, unit="K", icon="mdi:thermometer-minus",
             precision=1, attrs=lambda s: {"now": s.room_deviation_now}),
    StatSpec(key="time_to_target", value=lambda s: s.time_to_target, unit=UnitOfTime.MINUTES,
             device_class=SensorDeviceClass.DURATION, icon="mdi:timer-sand", precision=0, period="last"),
    StatSpec(key="degree_days_today", value=lambda s: round(s.dd_today, 2), unit="°C·d",
             state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:snowflake-thermometer", precision=1, period="day"),
    StatSpec(key="degree_days_month", value=lambda s: round(s.dd_month, 2), unit="°C·d",
             state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:calendar-month", precision=1, period="month"),
    StatSpec(key="heating_hours_per_degree_day", value=lambda s: s.hours_per_degree_day, unit="h/°C·d",
             icon="mdi:speedometer", precision=2, period="month",
             attrs=lambda s: {"ch_hours_month": round(s.ch_month_s / 3600, 2)}),
)


class ImmergasStatSensor(_StatsEntity, RestoreSensor):
    """Statistic computed by the helper; day / month counters come back after a restart."""

    def __init__(self, coordinator: ImmergasDominusCoordinator, spec: StatSpec) -> None:
        super().__init__(coordinator, spec.key)
        self._spec = spec
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_icon = spec.icon
        self._attr_suggested_display_precision = spec.precision

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._spec.period is None:
            return
        last_data = await self.async_get_last_sensor_data()
        last_state = await self.async_get_last_state()
        period = last_state.attributes.get("period") if last_state else None
        if last_data is not None and last_data.native_value is not None:
            try:
                self.stats.restore(self._key, float(last_data.native_value), period)
            except (TypeError, ValueError):
                pass
        if self._key == "heating_hours_per_degree_day" and last_state is not None:
            hours = last_state.attributes.get("ch_hours_month")
            if hours is not None:
                self.stats.restore("ch_hours_month", float(hours), period)

    @property
    def native_value(self) -> Any:
        return self._spec.value(self.stats)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = dict(self._spec.attrs(self.stats)) if self._spec.attrs else {}
        if self._spec.period == "day":
            attrs["period"] = self.stats.day_key
        elif self._spec.period == "month":
            attrs["period"] = self.stats.month_key
        return attrs or None


# --- alerts ---------------------------------------------------------------------------------------------------------


class ImmergasFrostRiskBinarySensor(_StatsEntity, BinarySensorEntity):
    """On when the zone 1 room temperature is below the frost threshold."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:snowflake-alert"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "frost_risk")

    @property
    def is_on(self) -> bool | None:
        return self.stats.frost_risk


class ImmergasModuleOfflineBinarySensor(_StatsEntity, BinarySensorEntity):
    """On when the module has not answered for longer than the set number of minutes."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:lan-disconnect"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "module_offline")

    @property
    def is_on(self) -> bool:
        return self.stats.module_offline


# --- settings (numbers) ---------------------------------------------------------------------------------------------

# key, min, max, step, unit, icon
SETTING_SPECS: tuple[tuple[str, float, float, float, str, str], ...] = (
    ("vacation_temperature", 5, 25, 0.5, UnitOfTemperature.CELSIUS, "mdi:bag-suitcase"),
    ("season_winter_below", 0, 25, 0.5, UnitOfTemperature.CELSIUS, "mdi:snowflake"),
    ("season_summer_above", 0, 30, 0.5, UnitOfTemperature.CELSIUS, "mdi:white-balance-sunny"),
    ("frost_threshold", 3, 15, 0.5, UnitOfTemperature.CELSIUS, "mdi:snowflake-alert"),
    ("offline_minutes", 5, 240, 5, UnitOfTime.MINUTES, "mdi:timer-alert-outline"),
)


class ImmergasStatsSetting(_StatsEntity, RestoreNumber):
    """Setting of an automation or alert, kept in Home Assistant (not on the boiler)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImmergasDominusCoordinator, spec: tuple[str, float, float, float, str, str]) -> None:
        key, low, high, step, unit, icon = spec
        super().__init__(coordinator, key)
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        if unit == UnitOfTemperature.CELSIUS:
            self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_native_value = coordinator.stats.settings[key]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = float(last.native_value)
        self.stats.settings[self._key] = float(self._attr_native_value)

    @property
    def native_value(self) -> float:
        return self.stats.settings[self._key]

    async def async_set_native_value(self, value: float) -> None:
        self.stats.set_setting(self._key, value)


# --- automations (switches) and the vacation end (datetime) ---------------------------------------------------------


class ImmergasVacationSwitch(_StatsEntity, SwitchEntity, RestoreEntity):
    """On: zone 1 target = vacation temperature until "Vacation until" (or until switched off), then restored."""

    _attr_icon = "mdi:bag-suitcase"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "vacation_mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == "on":
            # the boiler already holds the vacation target: only bring back what to restore afterwards
            self.stats.vacation_on = True
            restore = last.attributes.get("restore_target")
            self.stats.vacation_restore = round(float(restore) * 10) if restore is not None else None

    @property
    def is_on(self) -> bool:
        return self.stats.vacation_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self.stats.vacation_restore
        return {"restore_target": None if r is None else r / 10}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.stats.async_set_vacation(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.stats.async_set_vacation(False)


class ImmergasAutoSeasonSwitch(_StatsEntity, SwitchEntity, RestoreEntity):
    """On: Summer / Winter follows the 24 h outdoor mean (never touches Standby or Cooling)."""

    _attr_icon = "mdi:sun-snowflake-variant"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "auto_season")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self.stats.auto_season = last is not None and last.state == "on"

    @property
    def is_on(self) -> bool:
        return self.stats.auto_season

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mean, hours = self.stats.outdoor_24h
        return {"outdoor_mean_24h": mean, "hours_of_data": hours}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.stats.auto_season = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.stats.auto_season = False
        self.async_write_ha_state()


class ImmergasAlertNotificationsSwitch(_StatsEntity, SwitchEntity, RestoreEntity):
    """On: frost risk, module offline and a boiler fault each raise a Home Assistant notification while active
    (dismissed when the alert clears)."""

    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "alert_notifications")
        self._on = True
        self._shown: set[str] = set()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._on = last is None or last.state != "off"
        self.async_on_remove(self.stats.add_listener(self._check))
        self._check()

    @property
    def is_on(self) -> bool:
        return self._on

    def _texts(self) -> dict[str, tuple[str, str] | None]:
        pl = (self.hass.config.language or "").startswith("pl")
        raw = self.coordinator.data.get(FAULT_CODE_PDU) if self.coordinator.data else None
        lang = self.hass.config.language
        return {
            "frost": (("Ryzyko zamarznięcia", f"Temperatura w strefie 1 spadła poniżej {self.stats.settings['frost_threshold']} °C.")
                      if pl else ("Frost risk", f"The zone 1 temperature is below {self.stats.settings['frost_threshold']} °C."))
            if self.stats.frost_risk else None,
            "offline": (("Moduł Dominus offline", f"Moduł nie odpowiada dłużej niż {int(self.stats.settings['offline_minutes'])} min.")
                        if pl else ("Dominus module offline", f"The module has not answered for over {int(self.stats.settings['offline_minutes'])} min."))
            if self.stats.module_offline else None,
            "fault": ((f"Błąd kotła E{raw}" if pl else f"Boiler fault E{raw}"), describe(int(raw), lang)) if raw else None,
        }

    def _check(self) -> None:
        if self.hass is None:
            return
        for key, text in self._texts().items():
            nid = f"immergas_dominus_{self.coordinator.config_entry.entry_id}_{key}"
            if self._on and text is not None and key not in self._shown:
                persistent_notification.async_create(self.hass, text[1], title=text[0], notification_id=nid)
                self._shown.add(key)
            elif (text is None or not self._on) and key in self._shown:
                persistent_notification.async_dismiss(self.hass, nid)
                self._shown.discard(key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._on = True
        self._check()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._on = False
        self._check()
        self.async_write_ha_state()


class ImmergasVacationUntil(_StatsEntity, DateTimeEntity, RestoreEntity):
    """End of the vacation (the zone 1 target is restored then); empty = until switched off."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-end"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "vacation_until")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "unknown", "unavailable"):
            until = dt_util.parse_datetime(last.state)
            if until is not None:
                self.stats.set_vacation_until(until)

    @property
    def native_value(self) -> datetime | None:
        return self.stats.vacation_until

    async def async_set_value(self, value: datetime) -> None:
        self.stats.set_vacation_until(value)
