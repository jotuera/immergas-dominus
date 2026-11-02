"""Datetime platform for Immergas Dominus: the end of the vacation mode."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ImmergasDominusCoordinator
from .stats_entities import ImmergasVacationUntil


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the datetime entities."""
    coordinator: ImmergasDominusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.stats is not None:
        async_add_entities([ImmergasVacationUntil(coordinator)])
