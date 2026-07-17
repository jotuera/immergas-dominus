"""Climate platform for Immergas Dominus."""
from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CLIMATE_DESCRIPTIONS,
    DOMAIN,
    OPERATION_MODE_TO_RAW,
    RAW_TO_OPERATION_MODE,
    DominusClimateEntityDescription,
    OperationMode,
)
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity

OPERATION_PDU = 2000

SPACE_MODE_TO_OPERATION: dict[HVACMode, OperationMode] = {
    HVACMode.OFF: OperationMode.SUMMER,
    HVACMode.HEAT: OperationMode.WINTER,
    HVACMode.COOL: OperationMode.COOLING,
}
DHW_MODE_TO_OPERATION: dict[HVACMode, OperationMode] = {
    HVACMode.OFF: OperationMode.STANDBY,
    HVACMode.HEAT: OperationMode.SUMMER,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ImmergasDominusClimate(coordinator, description)
        for description in CLIMATE_DESCRIPTIONS
    )


class ImmergasDominusClimate(ImmergasDominusEntity, ClimateEntity):
    """Dominus thermostat entity built from confirmed PDU."""

    entity_description: DominusClimateEntityDescription
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        description: DominusClimateEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.target_pdu, description.device_key)
        self.entity_description = description
        self._attr_min_temp = description.native_min_temp
        self._attr_max_temp = description.native_max_temp
        self._attr_target_temperature_step = description.native_step

    def _poll_pdus(self) -> tuple[int, ...]:
        """A thermostat needs its current, target and the global mode PDU."""
        return (
            self.entity_description.current_pdu,
            self.entity_description.target_pdu,
            OPERATION_PDU,
        )

    def _raw(self, pdu: int) -> int | None:
        """Return raw PDU value from coordinator."""
        return self.coordinator.data.get(pdu) if self.coordinator.data else None

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature."""
        raw = self._raw(self.entity_description.current_pdu)
        if raw is None:
            return None
        return round(raw / 10, 1)

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        raw = self._raw(self.entity_description.target_pdu)
        if raw is None:
            return None
        return round(raw / self.entity_description.target_raw_scale, 1)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return supported HVAC modes."""
        if self.entity_description.climate_kind == "dhw":
            return [HVACMode.OFF, HVACMode.HEAT]
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current HVAC mode based on Dominus operation mode."""
        raw = self._raw(OPERATION_PDU)
        if raw is None:
            return None
        operation = RAW_TO_OPERATION_MODE.get(raw)

        if self.entity_description.climate_kind == "dhw":
            if operation == OperationMode.STANDBY:
                return HVACMode.OFF
            return HVACMode.HEAT

        if operation == OperationMode.WINTER:
            return HVACMode.HEAT
        if operation == OperationMode.COOLING:
            return HVACMode.COOL
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return a best-effort action from current and target temperature."""
        mode = self.hvac_mode
        current = self.current_temperature
        target = self.target_temperature
        if mode is None or current is None or target is None:
            return None
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        if mode == HVACMode.HEAT:
            return HVACAction.HEATING if current < target else HVACAction.IDLE
        if mode == HVACMode.COOL:
            return HVACAction.COOLING if current > target else HVACAction.IDLE
        return None

    async def async_set_temperature(self, **kwargs: float) -> None:
        """Set target temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            return
        temperature = kwargs[ATTR_TEMPERATURE]
        if temperature is None:
            return
        raw_value = round(float(temperature) * self.entity_description.target_raw_scale)
        ack_value = await self.coordinator.client.async_write_pdu(
            self.entity_description.target_pdu,
            raw_value,
        )
        self.coordinator.set_local_value(self.entity_description.target_pdu, ack_value)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set Dominus operation mode from the thermostat.

        Space heating/cooling thermostat:
        - OFF maps to Summer, so central heating/cooling is disabled but DHW can remain active.
        - HEAT maps to Winter.
        - COOL maps to Cooling.

        DHW thermostat:
        - OFF maps to Standby.
        - HEAT maps to Summer only when the boiler is currently in Standby; if the system is
          already in Winter or Cooling, DHW is already available and we keep the global mode.
        """
        current_raw = self._raw(OPERATION_PDU)
        current_operation = RAW_TO_OPERATION_MODE.get(current_raw) if current_raw is not None else None

        if self.entity_description.climate_kind == "dhw":
            if hvac_mode not in DHW_MODE_TO_OPERATION:
                raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")
            if hvac_mode == HVACMode.HEAT and current_operation in (
                OperationMode.SUMMER,
                OperationMode.WINTER,
                OperationMode.COOLING,
            ):
                # DHW is already available in every non-standby Dominus mode.
                return
            operation = DHW_MODE_TO_OPERATION[hvac_mode]
        else:
            if hvac_mode not in SPACE_MODE_TO_OPERATION:
                raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")
            operation = SPACE_MODE_TO_OPERATION[hvac_mode]

        raw_value = OPERATION_MODE_TO_RAW[operation]
        ack_value = await self.coordinator.client.async_write_pdu(OPERATION_PDU, raw_value)
        self.coordinator.set_local_value(OPERATION_PDU, ack_value)
        await self.coordinator.async_request_refresh()
