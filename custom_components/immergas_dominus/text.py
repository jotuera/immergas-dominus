"""Text platform for Immergas Dominus: the boiler model for the PDU map report (Modbus mode)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ImmergasDominusCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the text entities."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if getattr(coordinator, "pdu_scan", None) is None:
        return
    from .pdu_scan import pdu_scan_texts
    async_add_entities(pdu_scan_texts(coordinator))
