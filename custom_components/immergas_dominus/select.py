"""Select platform for Immergas Dominus."""
from __future__ import annotations

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
    DOMAIN,
    OT_MODE_OPTIONS,
    OT_MODE_PDU,
    OT_MODE_TO_STATUS,
    OT_STATUS_CH_ACTIVE_MASK,
    OT_STATUS_DHW_ACTIVE_MASK,
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
        async_add_entities([ImmergasOpenThermModeSelect(coordinator)])
        return
    entities: list[SelectEntity] = [
        ImmergasDominusSelect(coordinator, description)
        for description in SELECT_DESCRIPTIONS
    ]
    entities.append(ImmergasDominusAllDaysProfileSelect(coordinator))
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
        lb = int(raw) & 0xFF
        ch = bool(lb & OT_STATUS_CH_ACTIVE_MASK)
        dhw = bool(lb & OT_STATUS_DHW_ACTIVE_MASK)
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
