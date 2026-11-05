"""Text platform for Immergas Dominus: the boiler model for the PDU / Data-ID map report."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ImmergasDominusCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the text entities."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    from .pdu_scan import pdu_scan_texts
    async_add_entities(pdu_scan_texts(coordinator))
    if getattr(coordinator, "ot_programs", None) is not None:
        from .ot_programs import ot_texts
        async_add_entities(ot_texts(coordinator))
