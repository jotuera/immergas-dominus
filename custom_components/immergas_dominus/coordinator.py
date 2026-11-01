"""Data coordinator for Immergas Dominus."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .dominus_client import DominusClient, DominusError

_LOGGER = logging.getLogger(__name__)

# After a confirmed write the module can still answer with the value from before
# the write for a poll or two.  Such a read must not move the entity back.
WRITE_SETTLE_SECONDS = 30


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
        # pdu -> (written value, monotonic deadline) while a write settles
        self._settling: dict[int, tuple[int, float]] = {}
        # connection diagnostics (sensors "Last successful read" / "Failed polls")
        self.last_success: datetime | None = None
        self.failed_polls = 0
        self.missing_last_poll = 0
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
            self.failed_polls += 1
            if self._last_good_data:
                _LOGGER.debug(
                    "Dominus poll failed; keeping last-known-good values: %s", err
                )
                return dict(self._last_good_data)
            raise UpdateFailed(str(err)) from err

        self.missing_last_poll = len(pdus) - len(values)
        if not values:
            self.failed_polls += 1
            return dict(self._last_good_data)
        self.last_success = dt_util.utcnow()
        self._hold_settling(values)
        self._last_good_data.update(values)
        return dict(self._last_good_data)

    def _hold_settling(self, values: dict[int, int]) -> None:
        """Replace stale reads of just-written PDUs with the written value.

        A read equal to the written value ends the settle window early; after
        WRITE_SETTLE_SECONDS whatever the module reports wins again (e.g. a
        change made on the boiler itself).
        """
        now = time.monotonic()
        for pdu, (written, deadline) in list(self._settling.items()):
            if now >= deadline or values.get(pdu) == written:
                del self._settling[pdu]
            elif pdu in values:
                _LOGGER.debug("PDU %s still reads %s after writing %s; holding", pdu, values[pdu], written)
                values[pdu] = written

    def set_local_value(self, pdu: int, value: int) -> None:
        """Update local cache after a confirmed write ACK."""
        self._last_good_data[pdu] = int(value)
        self._settling[pdu] = (int(value), time.monotonic() + WRITE_SETTLE_SECONDS)
        current = dict(self.data or {})
        current[pdu] = int(value)
        self.async_set_updated_data(current)
