"""Number platform for Immergas Dominus."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_PROTOCOL,
    DEVICE_MAIN,
    DOMAIN,
    NUMBER_DESCRIPTIONS,
    OT_NUMBER_DESCRIPTIONS,
    PROTOCOL_OPENTHERM,
    DominusNumberEntityDescription,
    DominusOpenThermNumberDescription,
)
from .coordinator import ImmergasDominusCoordinator
from .dhw_schedule import DEFAULT_COMFORT, DEFAULT_ECO, DHW_TARGET_PDU
from .entity import ImmergasDominusEntity
from .programs import declared_numbers
from .stats_entities import SETTING_SPECS, ImmergasStatsSetting


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_PROTOCOL) == PROTOCOL_OPENTHERM:
        async_add_entities(
            ImmergasOpenThermNumber(coordinator, description)
            for description in OT_NUMBER_DESCRIPTIONS
        )
        return
    entities: list[NumberEntity] = [
        ImmergasDominusNumber(coordinator, description)
        for description in NUMBER_DESCRIPTIONS
    ]
    if coordinator.dhw is not None:
        entities += [
            ImmergasDhwProfileNumber(coordinator, "comfort", DEFAULT_COMFORT, "mdi:sofa-outline"),
            ImmergasDhwProfileNumber(coordinator, "eco", DEFAULT_ECO, "mdi:leaf"),
        ]
    if coordinator.stats is not None:
        entities += [ImmergasStatsSetting(coordinator, spec) for spec in SETTING_SPECS]
        entities += declared_numbers(coordinator)
    async_add_entities(entities)


class ImmergasDominusNumber(ImmergasDominusEntity, NumberEntity):
    """Writable Dominus PDU as a Home Assistant number."""

    entity_description: DominusNumberEntityDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusNumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.pdu, description.device_key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        raw = self.raw_value
        if raw is None:
            return None
        return raw / self.entity_description.raw_scale

    async def async_set_native_value(self, value: float) -> None:
        raw_value = round(value * self.entity_description.raw_scale)
        ack_value = await self.coordinator.client.async_write_pdu(self._pdu, raw_value)
        self.coordinator.set_local_value(self._pdu, ack_value)
        await self.coordinator.async_request_refresh()


class ImmergasOpenThermNumber(ImmergasDominusEntity, NumberEntity):
    """Writable OpenTherm setpoint (f8.8 fixed-point, °C)."""

    entity_description: DominusOpenThermNumberDescription

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusOpenThermNumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.data_id, DEVICE_MAIN)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        raw = self.raw_value
        if raw is None:
            return None
        raw = int(raw) & 0xFFFF
        signed = raw - 0x10000 if raw & 0x8000 else raw
        return round(signed / 256, 1)

    async def async_set_native_value(self, value: float) -> None:
        raw_value = round(float(value) * 256) & 0xFFFF
        ack_value = await self.coordinator.client.async_write_data_id(self._pdu, raw_value)
        self.coordinator.set_local_value(self._pdu, ack_value)
        await self.coordinator.async_request_refresh()


class ImmergasDhwProfileNumber(ImmergasDominusEntity, RestoreNumber):
    """DHW Comfort / Eco value used by "DHW Comfort-Eco by schedule" (kept in Home Assistant, not on the boiler)."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_min_value = 30
    _attr_native_max_value = 60
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ImmergasDominusCoordinator, which: str, default: float, icon: str) -> None:
        super().__init__(coordinator, f"dhw_{which}", DHW_TARGET_PDU)
        self._which = which
        self._attr_translation_key = f"dhw_{which}"
        self._attr_icon = icon
        self._attr_native_value = default

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = float(last.native_value)
        self.coordinator.dhw.set_value(self._which, float(self._attr_native_value))

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = float(value)
        self.coordinator.dhw.set_value(self._which, float(value))
        self.async_write_ha_state()
