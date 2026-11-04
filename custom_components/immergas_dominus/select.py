"""Select platform for Immergas Dominus."""
from __future__ import annotations

import asyncio

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import anomalies
from .programs import ImmergasFloorType, ImmergasLegionellaDay, ImmergasRoomControlMode

from .const import (
    CHRONO_OPTION_TO_RAW,
    CHRONO_PROFILE_OPTIONS,
    CHRONO_RAW_TO_OPTION,
    CONF_PROTOCOL,
    DEVICE_MAIN,
    DEVICE_SCHEDULE,
    DEVICE_ZONE_1,
    ZONE_PHASE_MANUAL_MASK,
    ZONE_STATUS_PDU,
    DOMAIN,
    OT_MODE_OPTIONS,
    OT_MODE_PDU,
    OT_MODE_TO_STATUS,
    OT_MASTER_CH_ENABLE,
    OT_MASTER_DHW_ENABLE,
    OT_NTC_USE_INDEX,
    OT_NTC_USE_OPTIONS,
    PROTOCOL_OPENTHERM,
    SELECT_DESCRIPTIONS,
    WEEKDAY_PROFILE_PDUS,
    DominusSelectEntityDescription,
)
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selects."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_PROTOCOL) == PROTOCOL_OPENTHERM:
        from .ot_diagnostics import OtStatusOverlaySelect
        from .ot_programs import ot_selects
        async_add_entities([ImmergasOpenThermModeSelect(coordinator), ImmergasOpenThermNtcUseSelect(coordinator), *ot_selects(coordinator),
                            OtStatusOverlaySelect(coordinator)])
        return
    entities: list[SelectEntity] = [
        ImmergasDominusSelect(coordinator, description)
        for description in SELECT_DESCRIPTIONS
    ]
    entities.append(ImmergasDominusAllDaysProfileSelect(coordinator))
    entities.append(ImmergasZone1ProgramSelect(coordinator))
    entities.append(ImmergasFaultLanguageSelect(coordinator))
    if coordinator.stats is not None:
        entities.append(ImmergasLegionellaDay(coordinator))
        entities.append(ImmergasRoomControlMode(coordinator))
        entities.append(ImmergasFloorType(coordinator))
    async_add_entities(entities)


class ImmergasFaultLanguageSelect(ImmergasDominusEntity, SelectEntity, RestoreEntity):
    """Language of the boiler fault description; "auto" follows the Home Assistant language."""

    _attr_translation_key = "fault_language"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:translate"
    _attr_options = ["auto", *anomalies.ANOMALIES]

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "fault_language", 0, DEVICE_MAIN)

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    @property
    def available(self) -> bool:
        return True

    @property
    def current_option(self) -> str:
        return self.coordinator.fault_language

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self.coordinator.fault_language = last.state

    async def async_select_option(self, option: str) -> None:
        self.coordinator.fault_language = option
        # the fault description sensor re-renders in the new language
        self.coordinator.async_update_listeners()


class ImmergasDominusSelect(ImmergasDominusEntity, SelectEntity):
    """Writable Dominus PDU as a Home Assistant select."""

    entity_description: DominusSelectEntityDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusSelectEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.pdu, description.device_key)
        self.entity_description = description
        if description.translation_placeholders:
            self._attr_translation_placeholders = description.translation_placeholders

    @property
    def current_option(self) -> str | None:
        """Return selected option."""
        raw = self.raw_value
        if raw is None:
            return None
        if self.entity_description.mask_low_byte:
            raw = int(raw) & 0xFF
        return self.entity_description.raw_to_option.get(raw)

    async def async_select_option(self, option: str) -> None:
        """Set operation mode."""
        raw_value = self.entity_description.option_to_raw[option]
        ack_value = await self.coordinator.client.async_write_pdu(self._pdu, raw_value)
        self.coordinator.set_local_value(self._pdu, ack_value)
        await self.coordinator.async_request_refresh()


class ImmergasDominusAllDaysProfileSelect(ImmergasDominusEntity, SelectEntity):
    """Shortcut: assign one profile (Cal 1-4) to every weekday at once.

    Writes the chosen profile to all seven weekday registers (2410-2416).
    Shows a value only when every day already uses the same profile.
    """

    _attr_translation_key = "all_days_profile"
    _attr_icon = "mdi:calendar-sync"
    _attr_options = list(CHRONO_PROFILE_OPTIONS)

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(
            coordinator, "all_days_profile", WEEKDAY_PROFILE_PDUS[0], DEVICE_SCHEDULE
        )

    def _poll_pdus(self) -> tuple[int, ...]:
        return WEEKDAY_PROFILE_PDUS

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        profiles = set()
        for pdu in WEEKDAY_PROFILE_PDUS:
            raw = data.get(pdu)
            if raw is None:
                return None
            profiles.add(int(raw) & 0xFF)
        if len(profiles) == 1:
            return CHRONO_RAW_TO_OPTION.get(next(iter(profiles)))
        return None

    async def async_select_option(self, option: str) -> None:
        raw_value = CHRONO_OPTION_TO_RAW[option]
        for pdu in WEEKDAY_PROFILE_PDUS:
            ack_value = await self.coordinator.client.async_write_pdu(pdu, raw_value)
            self.coordinator.set_local_value(pdu, ack_value)
        await self.coordinator.async_request_refresh()


class ImmergasOpenThermModeSelect(ImmergasDominusEntity, SelectEntity):
    """Experimental boiler mode over OpenTherm (master status Data-ID 0 enable bits).

    Writing Data-ID 0 as WRITE-DATA may not persist through the module's own status
    loop; the shown state reflects the slave's current CH/DHW activity.
    """

    _attr_translation_key = "ot_mode"
    _attr_icon = "mdi:hvac"
    _attr_options = OT_MODE_OPTIONS

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_mode", OT_MODE_PDU, DEVICE_MAIN)

    @property
    def current_option(self) -> str | None:
        raw = self.raw_value
        if raw is None:
            return None
        # the selected mode = master status enable bits (reply HB), as the app reads it - not the current activity (LB)
        hb = (int(raw) >> 8) & 0xFF
        ch = bool(hb & OT_MASTER_CH_ENABLE)
        dhw = bool(hb & OT_MASTER_DHW_ENABLE)
        if ch and dhw:
            return "heating_water"
        if ch:
            return "heating"
        if dhw:
            return "water"
        return "off"

    async def async_select_option(self, option: str) -> None:
        status = OT_MODE_TO_STATUS[option]
        ack = await self.coordinator.client.async_write_data_id(OT_MODE_PDU, status << 8)
        self.coordinator.set_local_value(OT_MODE_PDU, ack)
        await self.coordinator.async_request_refresh()


class ImmergasOpenThermNtcUseSelect(ImmergasDominusEntity, SelectEntity):
    """What the probe of the Dominus kit measures: the room or the outdoor temperature (module parameter 11)."""

    _attr_translation_key = "ot_ntc_use"
    _attr_icon = "mdi:thermometer-probe"
    _attr_options = OT_NTC_USE_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        from .opentherm_client import ot_param_key
        super().__init__(coordinator, "ot_ntc_use", ot_param_key(89, OT_NTC_USE_INDEX), DEVICE_MAIN)

    @property
    def current_option(self) -> str | None:
        raw = self.raw_value
        if raw is None:
            return None
        lb = int(raw) & 0xFF
        return OT_NTC_USE_OPTIONS[lb] if lb < len(OT_NTC_USE_OPTIONS) else None

    async def async_select_option(self, option: str) -> None:
        ack = await self.coordinator.client.async_write_data_id(self._pdu, OT_NTC_USE_OPTIONS.index(option))
        self.coordinator.set_local_value(self._pdu, ack)
        await self.coordinator.async_request_refresh()


# Zone 1 CH time program AUTO / MANUAL.  The boiler keeps "time programs active" in the zone panel (0x29 2294), which
# the Dominus module does not expose over TCP, so the integration emulates it on the registers the app itself writes:
# MANUAL = every weekday on a calendar that covers the whole day (calendar 4 is set to 00:00-24:00 when none does) -
# a fixed setpoint 24 h; AUTO = the day assignment from before MANUAL, never on a whole-day calendar.  The state is read
# back from the boiler (all days on one whole-day calendar = MANUAL), so a change made in the app shows up here too.
_PROGRAM_OPTIONS = ["manual", "auto"]
_DAY_END = 24 * 60
_MANUAL_PROFILE = 4


def _profile_pdus(profile: int) -> list[tuple[int, int]]:
    base = 2300 + profile * 10
    return [(base + (f - 1) * 2, base + (f - 1) * 2 + 1) for f in range(1, 5)]


def _minutes(raw: int | None) -> int | None:
    if raw is None:
        return None
    hour, minute = (int(raw) >> 8) & 0xFF, int(raw) & 0xFF
    return _DAY_END if hour >= 24 or (hour == 23 and minute >= 59) else hour * 60 + min(minute, 59)


class ImmergasZone1ProgramSelect(ImmergasDominusEntity, SelectEntity, RestoreEntity):
    """Zone 1 CH time program: AUTO (by the calendars) / MANUAL (fixed setpoint 24 h), emulated on the calendars."""

    _attr_translation_key = "zone1_time_program"
    _attr_icon = "mdi:calendar-clock"
    _attr_options = _PROGRAM_OPTIONS

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "zone1_time_program", WEEKDAY_PROFILE_PDUS[0], DEVICE_ZONE_1)
        self._auto_days: list[int] | None = None

    def _poll_pdus(self) -> tuple[int, ...]:
        cal = tuple(pdu for p in range(1, 5) for pair in _profile_pdus(p) for pdu in pair)
        return WEEKDAY_PROFILE_PDUS + cal + (ZONE_STATUS_PDU,)

    def _panel_manual(self) -> bool:
        """The zone panel (or the hub emulating it) has its time programs off: the boiler flags the zone MANUAL."""
        raw = (self.coordinator.data or {}).get(ZONE_STATUS_PDU)
        return raw is not None and bool(int(raw) & ZONE_PHASE_MANUAL_MASK)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        days = last.attributes.get("auto_days") if last is not None else None
        if isinstance(days, list) and len(days) == 7:
            self._auto_days = [int(d) for d in days]

    def _days(self) -> list[int] | None:
        data = self.coordinator.data or {}
        raws = [data.get(pdu) for pdu in WEEKDAY_PROFILE_PDUS]
        return None if any(r is None for r in raws) else [int(r) & 0xFF for r in raws]

    def _whole_day(self, profile: int) -> bool | None:
        """True when the calendar's ranges together cover 00:00-24:00."""
        if profile not in (1, 2, 3, 4):
            return False
        data = self.coordinator.data or {}
        spans = []
        for start_pdu, end_pdu in _profile_pdus(profile):
            start, end = _minutes(data.get(start_pdu)), _minutes(data.get(end_pdu))
            if start is None or end is None:
                return None
            if end > start:
                spans.append((start, end))
        reach = 0
        for start, end in sorted(spans):
            if start > reach:
                break
            reach = max(reach, end)
        return reach >= _DAY_END

    @property
    def current_option(self) -> str | None:
        days = self._days()
        if days is None:
            return None
        if self._panel_manual():
            return "manual"
        if len(set(days)) == 1:
            whole = self._whole_day(days[0])
            if whole is None:
                return None
            if whole:
                return "manual"
        return "auto"

    @property
    def extra_state_attributes(self) -> dict:
        # panel_manual: MANUAL set on the zone panel / hub - AUTO from here cannot override it (the module has no access)
        return {"auto_days": self._auto_days, "panel_manual": self._panel_manual()}

    async def _write(self, pdu: int, value: int) -> None:
        # the module drops a frame now and then (one TCP client at a time): retry, so a switch never stops half-way
        for attempt in range(3):
            try:
                ack = await self.coordinator.client.async_write_pdu(pdu, value)
                break
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    raise
                await asyncio.sleep(1.5)
        self.coordinator.set_local_value(pdu, ack)

    async def async_select_option(self, option: str) -> None:
        days = self._days()
        if days is None:
            return
        if option == "manual":
            if self.current_option == "auto":
                self._auto_days = days
            whole = next((p for p in (1, 2, 3, 4) if self._whole_day(p)), None)
            if whole is None:
                whole = _MANUAL_PROFILE
                for i, (start_pdu, end_pdu) in enumerate(_profile_pdus(whole)):
                    await self._write(start_pdu, 0x0000)
                    await self._write(end_pdu, 0x1800 if i == 0 else 0x0000)
            for pdu in WEEKDAY_PROFILE_PDUS:
                await self._write(pdu, whole)
        else:
            # back to the days from before MANUAL, but never on a whole-day calendar (AUTO must follow a real schedule)
            fallback = next((p for p in (1, 2, 3, 4) if self._whole_day(p) is False), 1)
            target = [d if d in (1, 2, 3, 4) and self._whole_day(d) is False else fallback for d in (self._auto_days or days)]
            for pdu, profile in zip(WEEKDAY_PROFILE_PDUS, target):
                await self._write(pdu, profile)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
