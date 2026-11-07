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
from .opentherm_client import ot_param_key
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
        from .ot_programs import ot_numbers
        async_add_entities(
            ImmergasOpenThermNumber(coordinator, description)
            for description in OT_NUMBER_DESCRIPTIONS
        )
        async_add_entities(ot_numbers(coordinator))
        from .programs import ot_declared_numbers
        async_add_entities(ot_declared_numbers(coordinator))
        if getattr(coordinator, "ot_computed", None) is not None:
            from .ot_computed import OtGasPriceNumber
            async_add_entities([OtGasPriceNumber(coordinator)])
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
    if getattr(coordinator, "stats_extra", None) is not None:
        from .stats_extra import DominusTankVolumeNumber
        entities.append(DominusTankVolumeNumber(coordinator))
    if getattr(coordinator, "pdu_scan", None) is not None:
        from .pdu_scan import pdu_scan_numbers
        entities += pdu_scan_numbers(coordinator)
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
        key = description.data_id if description.param is None else ot_param_key(description.data_id, description.param)
        super().__init__(coordinator, description.key, key, DEVICE_MAIN)
        self.entity_description = description

    def _poll_pdus(self) -> tuple[int, ...]:
        bounds = self.entity_description.bounds_id
        return (self._pdu,) if bounds is None else (self._pdu, bounds)

    def _bounds(self) -> tuple[int, int] | None:
        """The boiler's own limits (Data-ID 48 / 49: HB upper, LB lower, s8 °C), if it answers them sensibly."""
        bounds = self.entity_description.bounds_id
        data = self.coordinator.data
        if bounds is None or not data or data.get(bounds) is None:
            return None
        raw = int(data[bounds]) & 0xFFFF
        hi, lo = raw >> 8, raw & 0xFF
        hi, lo = (hi - 0x100 if hi & 0x80 else hi), (lo - 0x100 if lo & 0x80 else lo)
        if not 0 < lo < hi <= 100:
            return None
        return lo, hi

    @property
    def native_min_value(self) -> float:
        b = self._bounds()
        default = self.entity_description.native_min_value
        return float(max(b[0], default)) if b else default

    @property
    def native_max_value(self) -> float:
        b = self._bounds()
        default = self.entity_description.native_max_value
        return float(min(b[1], default)) if b else default

    @property
    def native_value(self) -> float | None:
        raw = self.raw_value
        if raw is None:
            return None
        d = self.entity_description
        if d.param is not None:
            # module parameter: the reply LB, signed (s8) or scaled down by the divisor (curve 1.0-9.0 = 10-90)
            lb = int(raw) & 0xFF
            if d.signed and lb & 0x80:
                lb -= 0x100
            return round(lb / d.divisor, 1) if d.divisor != 1 else float(lb)
        raw = int(raw) & 0xFFFF
        signed = raw - 0x10000 if raw & 0x8000 else raw
        return round(signed / 256, 1)

    async def async_set_native_value(self, value: float) -> None:
        d = self.entity_description
        if d.param is not None:
            raw_value = int(round(float(value) * d.divisor)) & 0xFF
        elif d.whole:
            # whole degrees, as the official app sends the DHW setpoint (f8.8 with LB = 0)
            raw_value = (int(round(float(value))) << 8) & 0xFFFF
        else:
            raw_value = int(round(float(value) * 256)) & 0xFFFF
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
