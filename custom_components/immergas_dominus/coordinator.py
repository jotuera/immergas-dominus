"""Data coordinator for Immergas Dominus."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .dominus_client import DominusClient, DominusError

_LOGGER = logging.getLogger(__name__)


class ImmergasDominusCoordinator(DataUpdateCoordinator[dict[int, int]]):
    """Fetches confirmed Dominus PDU values.

    Dominus local TCP is not perfectly stable: an individual read can time out
    even though the next one succeeds.  Home Assistant should not briefly blank
    a value only because one confirmed PDU was missed in one polling cycle, so
    the coordinator keeps a last-known-good cache per PDU and merges every
    successful partial read into it.

    Only PDUs that belong to a currently enabled entity are polled.  Entities
    register their PDUs when added to Home Assistant and unregister on removal,
    so disabled-by-default entities (e.g. inactive Zone 2/3) cost nothing until
    the user enables them.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: DominusClient,
    ) -> None:
        self.client = client
        self._last_good_data: dict[int, int] = {}
        self._poll_refcounts: dict[int, int] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def poll_pdus(self) -> tuple[int, ...]:
        """PDUs currently requested by enabled entities, ascending."""
        return tuple(sorted(self._poll_refcounts))

    def register_pdus(self, pdus: tuple[int, ...]) -> bool:
        """Add entity PDUs to the poll set. Return True if any PDU is new."""
        added = False
        for pdu in pdus:
            count = self._poll_refcounts.get(pdu, 0)
            self._poll_refcounts[pdu] = count + 1
            if count == 0:
                added = True
        return added

    def unregister_pdus(self, pdus: tuple[int, ...]) -> None:
        """Remove entity PDUs from the poll set when an entity is removed."""
        for pdu in pdus:
            count = self._poll_refcounts.get(pdu, 0)
            if count <= 1:
                self._poll_refcounts.pop(pdu, None)
            else:
                self._poll_refcounts[pdu] = count - 1

    async def _async_update_data(self) -> dict[int, int]:
        """Read current PDU values and keep previous values for missed PDU.

        If at least one PDU is read, merge it into the cache and return the
        whole cache.  If the full cycle fails but we already have previous
        values, keep returning them instead of marking all entities unavailable.
        Entities only become unavailable before the first successful read.
        """
        pdus = self.poll_pdus
        if not pdus:
            # No enabled entity yet (entities register their PDUs on add).
            return dict(self._last_good_data)
        try:
            values = await self.client.async_read_many(pdus)
        except DominusError as err:
            if self._last_good_data:
                _LOGGER.debug(
                    "Dominus poll failed; keeping last-known-good values: %s", err
                )
                return dict(self._last_good_data)
            raise UpdateFailed(str(err)) from err

        if values:
            self._last_good_data.update(values)
        return dict(self._last_good_data)

    def set_local_value(self, pdu: int, value: int) -> None:
        """Update local cache after a confirmed write ACK."""
        self._last_good_data[pdu] = int(value)
        current = dict(self.data or {})
        current[pdu] = int(value)
        self.async_set_updated_data(current)
