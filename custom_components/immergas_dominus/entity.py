"""Base entities for Immergas Dominus."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_INFO, DEVICE_MAIN, DOMAIN
from .coordinator import ImmergasDominusCoordinator


class ImmergasDominusEntity(CoordinatorEntity[ImmergasDominusCoordinator]):
    """Base Dominus entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ImmergasDominusCoordinator,
        key: str,
        pdu: int,
        device_key: str = DEVICE_MAIN,
    ) -> None:
        super().__init__(coordinator)
        self._pdu = pdu
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = _device_info(coordinator, device_key)

    def _poll_pdus(self) -> tuple[int, ...]:
        """PDUs this entity needs the coordinator to poll while it is enabled."""
        return (self._pdu,)

    async def async_added_to_hass(self) -> None:
        """Register this entity's PDUs so only enabled entities are polled."""
        await super().async_added_to_hass()
        if self.coordinator.register_pdus(self._poll_pdus()):
            # A newly needed PDU appeared; refresh soon instead of waiting a cycle.
            await self.coordinator.async_request_refresh()

    async def async_will_remove_from_hass(self) -> None:
        """Stop polling PDUs that no enabled entity needs anymore."""
        self.coordinator.unregister_pdus(self._poll_pdus())
        await super().async_will_remove_from_hass()

    @property
    def raw_value(self) -> int | None:
        """Return raw PDU value from coordinator."""
        return self.coordinator.data.get(self._pdu) if self.coordinator.data else None


def _device_info(
    coordinator: ImmergasDominusCoordinator,
    device_key: str,
) -> DeviceInfo:
    """Return Home Assistant device info for a logical Dominus sub-device."""
    info = DEVICE_INFO[device_key]
    if device_key == DEVICE_MAIN:
        identifiers = {(DOMAIN, coordinator.config_entry.entry_id)}
    else:
        identifiers = {(DOMAIN, f"{coordinator.config_entry.entry_id}_{device_key}")}

    device_info = DeviceInfo(
        identifiers=identifiers,
        manufacturer="Immergas",
        name=info["name"],
        model=info["model"],
    )

    if device_key != DEVICE_MAIN:
        device_info["via_device"] = (DOMAIN, coordinator.config_entry.entry_id)

    return device_info
