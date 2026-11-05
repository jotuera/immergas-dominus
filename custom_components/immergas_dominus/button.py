"""Button platform for Immergas Dominus: boiler reset, Data-ID scan (OpenTherm), PDU scan and report (Modbus)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PROTOCOL, DEVICE_MAIN, DOMAIN, OT_RESET_DATA_ID, OT_RESET_VALUE, PROTOCOL_OPENTHERM
from .coordinator import ImmergasDominusCoordinator
from .entity import ImmergasDominusEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the buttons."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_PROTOCOL) == PROTOCOL_OPENTHERM:
        from .ot_diagnostics import OtReportButton, OtScanButton
        async_add_entities([ImmergasOpenThermResetButton(coordinator), OtScanButton(coordinator),
                            OtReportButton(coordinator)])
    elif getattr(coordinator, "pdu_scan", None) is not None:
        from .pdu_scan import pdu_scan_buttons
        async_add_entities(pdu_scan_buttons(coordinator))


class ImmergasOpenThermResetButton(ImmergasDominusEntity, ButtonEntity):
    """Unlock the boiler after a fault that needs a manual reset (Data-ID 4, HB 1 / LB 127, as the official app)."""

    _attr_translation_key = "ot_reset"
    _attr_icon = "mdi:restart-alert"

    def __init__(self, coordinator: ImmergasDominusCoordinator) -> None:
        super().__init__(coordinator, "ot_reset", OT_RESET_DATA_ID, DEVICE_MAIN)

    def _poll_pdus(self) -> tuple[int, ...]:
        return ()  # a command, nothing to read

    async def async_press(self) -> None:
        await self.coordinator.client.async_write_data_id(OT_RESET_DATA_ID, OT_RESET_VALUE)
        await self.coordinator.async_request_refresh()
