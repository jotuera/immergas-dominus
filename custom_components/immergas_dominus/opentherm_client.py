"""Experimental OpenTherm-over-TCP client for Immergas boilers (e.g. VICTRIX).

The Dominus Wi-Fi module speaks two local protocols, chosen by the boiler's config:

* boilers with a Modbus config (``*_MBUS_*``, Magis Combo/Pro) use the 7-byte
  Modbus-PDU protocol handled by :mod:`.dominus_client`;
* boilers **without** the ``modbus`` flag (VICTRIX ZEUS / AVIO, STAR, …) tunnel
  **standard OpenTherm** frames over the same authenticated TCP channel: a 6-byte
  frame = the 4-byte OpenTherm frame (parity + 3-bit msg-type + 8-bit Data-ID +
  16-bit value) + a 2-byte Dominus CRC (CRC-16/CCITT 0x1021 / 0xFFFF, identical to
  the Modbus mode).

Unlike the Modbus mode, this client runs a background loop that polls the registered
Data-IDs in an authenticated session and sends writes on a priority queue inside that
session.  The module accepts only one TCP client, so after every full polling cycle the
session is closed for ``_IDLE_BETWEEN_CYCLES`` seconds, leaving room for the official app.

Experimental: verified for reads on a VICTRIX ZEUS 25; writes are still unconfirmed.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import socket
import threading
import time

from .dominus_client import (
    DominusAuthError,
    DominusClient,
    DominusConfig,
    DominusProtocolError,
)

_LOGGER = logging.getLogger(__name__)

# OpenTherm message types (bits 6-4 of byte 0).
_OT_MSGTYPE_READ_ACK = 0b100
_OT_MSGTYPE_WRITE_ACK = 0b101
_OT_MSGTYPE_DATA_INVALID = 0b010
_OT_MSGTYPE_UNKNOWN_DATAID = 0b011
_OT_WRITE_TYPE_BIT = 0b001 << 4  # 0x10, WRITE-DATA in byte 0 bits 6-4

_MESSAGE_GAP = 0.3       # seconds between messages in the session loop
_WRITE_TIMEOUT = 12.0    # seconds to wait for a queued write to complete
_TEST_DATA_IDS = (0, 25, 27)  # status, boiler flow temp, outside temp
# The module serves a single TCP client: after each full polling cycle the session is
# released for this long so the official Dominus app can connect in between.
_IDLE_BETWEEN_CYCLES = 20.0
# A Data-ID the boiler answers DATA-INVALID / UNKNOWN-DATAID this many times in a row is skipped
# for _SUPPRESS_SECONDS (then tried again), so unsupported IDs do not slow every cycle down.
_SUPPRESS_AFTER = 3
_SUPPRESS_SECONDS = 3600.0
# Data-ID scan (diagnostics): the standard OpenTherm range
_SCAN_IDS = tuple(range(0, 128))
# 1.6.7: indexed tables read after the scan when the boiler reports their size - Data-ID 10 HB = number of transparent
# slave parameters (TSP, the boiler's own parameters, read with Data-ID 11 HB = index) and Data-ID 12 HB = number of
# fault history entries (read with Data-ID 13 HB = index)
_SCAN_TABLES = {10: 11, 12: 13}
_SCAN_TABLE_MAX = 128
# Writes that are commands, not values - nothing to read back
_NO_READBACK = (4,)
# 1.6.6: f8.8 setpoints may be stored slightly differently from what was sent (a VICTRIX stores 45.0 as 44.7 and
# 42.0 as 41.7), so they count as taken within half a degree
_F88_WRITE_IDS = (1, 8, 14, 16, 23, 56, 57, 71)
_F88_TOLERANCE = 0x80  # 0.5 in f8.8
# 1.6.6: right after a write the module may still answer the previous value, so a mismatch is read again a few
# seconds later (up to _RECHECKS times) before it is reported as "acknowledged, not taken"
_RECHECK_DELAY = 5.0
_RECHECKS = 3


def _write_taken(data_id: int, index: int | None, sent: int, back: int) -> bool:
    """Did the boiler take the written value? (``back`` = the value read back)."""
    if index is not None:
        return back == sent
    if data_id == 0:
        return (back >> 8) & 0x07 == (sent >> 8) & 0x07  # master enable bits
    if data_id in _F88_WRITE_IDS:
        s = lambda v: v - 0x10000 if v & 0x8000 else v  # noqa: E731 - signed f8.8
        return abs(s(back & 0xFFFF) - s(sent & 0xFFFF)) <= _F88_TOLERANCE
    return back == sent


def ot_param_key(data_id: int, index: int) -> int:
    """Poll / write key of an indexed module parameter (e.g. Data-ID 89, HB = parameter index).

    Plain keys (< 0x10000) are standard Data-IDs; an indexed key sends ``index`` in the request HB and keeps only the
    reply LB (the parameter value) - how the official app reads and writes the module parameters (89/17 = CH setpoint).
    """
    return 0x10000 | ((data_id & 0xFF) << 8) | (index & 0xFF)


def _split_key(key: int) -> tuple[int, int | None]:
    return ((key >> 8) & 0xFF, key & 0xFF) if key >= 0x10000 else (key, None)


class DominusOpenThermUnsupported(DominusProtocolError):
    """The boiler answered DATA-INVALID / UNKNOWN-DATAID for this Data-ID."""


def _even_parity_byte0(base0: int, data_id: int, hb: int, lb: int) -> int:
    """Return byte 0 with the OpenTherm even-parity bit (bit 7) set if needed."""
    ones = (
        bin(base0 & 0xFF).count("1")
        + bin(data_id & 0xFF).count("1")
        + bin(hb & 0xFF).count("1")
        + bin(lb & 0xFF).count("1")
    )
    return (base0 & 0x7F) | (0x80 if ones & 1 else 0x00)


class _WriteRequest:
    """A queued OpenTherm write, resolved by the session loop."""

    __slots__ = ("data_id", "value", "event", "ack", "error")

    def __init__(self, data_id: int, value: int) -> None:
        self.data_id = data_id
        self.value = value & 0xFFFF
        self.event = threading.Event()
        self.ack: int | None = None
        self.error: Exception | None = None


class DominusOpenThermClient:
    """Persistent-session OpenTherm client over the Dominus TCP channel."""

    def __init__(self, config: DominusConfig) -> None:
        self._config = config
        self._lock = threading.RLock()          # guards _values / _poll_ids
        self._values: dict[int, int] = {}
        self._poll_ids: tuple[int, ...] = ()
        self._write_queue: "queue.Queue[_WriteRequest]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        # diagnostics (see the "OpenTherm diagnostics" entities)
        # low byte added to every Data-ID 0 frame: None = standard (0), 0xCA = the "Immergas fix" of other
        # OpenTherm gateways (reported to unlock Data-ID 1 / 57 writes on Immergas boilers)
        self.status_lb: int | None = None
        self._unsupported: dict[int, int] = {}       # key -> consecutive unsupported replies
        self.suppressed: dict[int, float] = {}       # key -> monotonic time until it is polled again
        self._scan_queue: list[int] = []
        self.scan_running = False
        self.scan_result: dict[int, str] = {}        # Data-ID -> "ok" / "unsupported" / "error"
        self.scan_values: dict[int, int] = {}
        self.scan_tables: dict[int, dict[int, int | str]] = {}  # 11 / 13 -> index -> value (LB) or "unsupported" / "error"
        self.scan_finished: float | None = None      # time.time() of the last finished scan
        self.last_write: dict | None = None          # key, sent, ack, readback, result, rechecks
        self._recheck: tuple[int, float, int] | None = None  # (write key, monotonic due time, rechecks left)

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="dominus-opentherm", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_socket()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None
        self._fail_pending_writes(DominusAuthError("OpenTherm session stopped"))

    # -- coordinator / entity interface ---------------------------------------

    async def async_test_connection(self) -> None:
        """One-shot connect + read to validate auth (no persistent loop)."""
        await asyncio.to_thread(self._test_connection_blocking)

    async def async_read_many(self, data_ids: tuple[int, ...]) -> dict[int, int]:
        """Return the current cache snapshot; the session loop does the polling."""
        with self._lock:
            self._poll_ids = tuple(data_ids)
            snapshot = dict(self._values)
        self.start()
        # On the first cycle the cache is empty; give the freshly started session
        # loop a few seconds to populate so entities don't stay unknown until the
        # next coordinator interval.
        waited = 0.0
        while not snapshot and waited < 6.0:
            await asyncio.sleep(0.25)
            waited += 0.25
            with self._lock:
                snapshot = dict(self._values)
        return snapshot

    def start_scan(self) -> None:
        """Queue a read of every standard Data-ID; the session loop works through it between polls."""
        self._scan_queue = list(_SCAN_IDS)
        self.scan_result = {}
        self.scan_values = {}
        self.scan_tables = {}
        self.scan_running = True
        self.start()

    async def async_write_data_id(self, data_id: int, value: int) -> int:
        """Queue a write into the live session and wait for the ack."""
        self.start()
        request = _WriteRequest(data_id, value)
        self._write_queue.put(request)
        await asyncio.to_thread(request.event.wait, _WRITE_TIMEOUT)
        if not request.event.is_set():
            raise DominusAuthError(f"OpenTherm write to Data-ID {data_id} timed out")
        if request.error is not None:
            raise request.error
        if request.ack is None:
            raise DominusProtocolError(f"OpenTherm write to Data-ID {data_id} got no acknowledgement")
        return request.ack

    # -- background session loop ----------------------------------------------

    def _run(self) -> None:
        pos = 0
        backoff = 1.0
        while not self._stop.is_set():
            try:
                if self._sock is None:
                    self._sock = self._auth_connect()
                    backoff = 1.0

                request = self._next_write()
                if request is not None:
                    try:
                        request.ack = self._exchange_key(request.data_id, request.value, write=True)
                        with self._lock:
                            self._values[request.data_id] = request.ack
                        self._read_back(request)
                    except DominusOpenThermUnsupported as err:
                        request.error = err
                    except Exception as err:  # noqa: BLE001 - hand the cause to the waiting caller
                        request.error = err
                        raise
                    finally:
                        request.event.set()
                    self._stop.wait(_MESSAGE_GAP)
                    continue

                if self._recheck is not None and time.monotonic() >= self._recheck[1]:
                    self._recheck_step()
                    self._stop.wait(_MESSAGE_GAP)
                    continue

                if self._scan_queue:
                    self._scan_step()
                    self._stop.wait(_MESSAGE_GAP)
                    continue

                with self._lock:
                    ids = self._poll_ids
                if not ids:
                    self._stop.wait(0.3)
                    continue
                data_id = ids[pos % len(ids)]
                pos += 1
                until = self.suppressed.get(data_id)
                if until is not None and time.monotonic() < until:
                    pass  # unsupported by this boiler: skipped until the suppression ends
                else:
                    try:
                        value = self._exchange_key(data_id)
                        with self._lock:
                            self._values[data_id] = value
                        self._unsupported.pop(data_id, None)
                        self.suppressed.pop(data_id, None)
                    except DominusOpenThermUnsupported:
                        count = self._unsupported.get(data_id, 0) + 1
                        self._unsupported[data_id] = count
                        if count >= _SUPPRESS_AFTER:
                            self.suppressed[data_id] = time.monotonic() + _SUPPRESS_SECONDS
                            self._unsupported[data_id] = 0
                            _LOGGER.debug("OpenTherm key %s unsupported %s times, skipped for %.0f s",
                                          data_id, _SUPPRESS_AFTER, _SUPPRESS_SECONDS)
                if pos % len(ids) == 0 and self._write_queue.empty():
                    # full cycle done: free the module for the official app until the next one
                    self._close_socket()
                    idle_until = time.monotonic() + _IDLE_BETWEEN_CYCLES
                    while time.monotonic() < idle_until and self._write_queue.empty() and not self._recheck_due():
                        if self._stop.wait(0.25):
                            break
                    continue
                self._stop.wait(_MESSAGE_GAP)
            except (OSError, DominusProtocolError, DominusAuthError) as err:
                _LOGGER.debug("OpenTherm session error, reconnecting: %s", err)
                self._close_socket()
                self._fail_pending_writes(err)
                self._stop.wait(backoff)
                backoff = min(backoff * 2.0, 20.0)

    def _scan_step(self) -> None:
        key = self._scan_queue.pop(0)
        data_id, index = _split_key(key)
        if index is not None:  # an entry of an indexed table (TSP / fault history)
            table = self.scan_tables.setdefault(data_id, {})
            try:
                table[index] = self._exchange_key(key)
            except DominusOpenThermUnsupported:
                table[index] = "unsupported"
            except DominusProtocolError:
                table[index] = "error"
        else:
            try:
                self.scan_values[data_id] = self._exchange_key(data_id)
                self.scan_result[data_id] = "ok"
                entry_id = _SCAN_TABLES.get(data_id)
                if entry_id is not None:
                    size = min((self.scan_values[data_id] >> 8) & 0xFF, _SCAN_TABLE_MAX)
                    self.scan_tables[entry_id] = {}
                    self._scan_queue.extend(ot_param_key(entry_id, i) for i in range(size))
            except DominusOpenThermUnsupported:
                self.scan_result[data_id] = "unsupported"
            except DominusProtocolError:
                self.scan_result[data_id] = "error"  # no / invalid reply; the session itself is kept
        if not self._scan_queue:
            self.scan_running = False
            self.scan_finished = time.time()
            _LOGGER.info("OpenTherm Data-ID scan finished: %s supported", sum(1 for r in self.scan_result.values() if r == "ok"))

    def _read_back(self, request: _WriteRequest) -> None:
        """Read the written key again: did the boiler take the value, or only acknowledge it?"""
        data_id, index = _split_key(request.data_id)
        sent = request.value & (0xFF if index is not None else 0xFFFF)
        record = {"key": data_id if index is None else f"{data_id}/{index}", "sent": sent, "ack": request.ack,
                  "readback": None, "result": "no_readback", "at": time.time()}
        if data_id not in _NO_READBACK:
            self._stop.wait(_MESSAGE_GAP)
            try:
                back = self._exchange_key(request.data_id)
                record["readback"] = back
                record["result"] = "ok" if _write_taken(data_id, index, sent, back) else "mismatch"
                with self._lock:
                    self._values[request.data_id] = back
            except DominusOpenThermUnsupported:
                record["result"] = "unsupported"
            except DominusProtocolError as err:
                record["result"] = "error"
                _LOGGER.debug("OpenTherm read-back of %s failed: %s", record["key"], err)
        record["rechecks"] = 0
        self.last_write = record
        # a new write replaces the recheck of an older one
        self._recheck = (request.data_id, time.monotonic() + _RECHECK_DELAY, _RECHECKS) if record["result"] == "mismatch" else None

    def _recheck_due(self) -> bool:
        return self._recheck is not None and time.monotonic() >= self._recheck[1]

    def _recheck_step(self) -> None:
        """Read a mismatched write again: the module may have answered the previous value right after the write."""
        key, _due, left = self._recheck
        self._recheck = None
        record = self.last_write
        if record is None:
            return
        data_id, index = _split_key(key)
        try:
            back = self._exchange_key(key)
        except DominusOpenThermUnsupported:
            return
        except DominusProtocolError as err:
            _LOGGER.debug("OpenTherm recheck of %s failed: %s", record["key"], err)
            back = None
        if back is not None:
            with self._lock:
                self._values[key] = back
            record["readback"] = back
            record["rechecks"] = record.get("rechecks", 0) + 1
            if _write_taken(data_id, index, record["sent"], back):
                record["result"] = "ok"
                _LOGGER.debug("OpenTherm write %s taken on recheck %s", record["key"], record["rechecks"])
                return
        if left > 1:
            self._recheck = (key, time.monotonic() + _RECHECK_DELAY, left - 1)
        else:
            _LOGGER.info("OpenTherm write %s: sent %s, acknowledged %s, but reads back %s", record["key"],
                         record["sent"], record["ack"], record["readback"])

    def _next_write(self) -> _WriteRequest | None:
        try:
            return self._write_queue.get_nowait()
        except queue.Empty:
            return None

    def _fail_pending_writes(self, error: Exception) -> None:
        while True:
            try:
                request = self._write_queue.get_nowait()
            except queue.Empty:
                return
            request.error = error
            request.event.set()

    def _exchange_key(self, key: int, value: int = 0, write: bool = False) -> int:
        """Read or write a plain Data-ID or an indexed parameter (see :func:`ot_param_key`)."""
        data_id, index = _split_key(key)
        if index is None:
            if data_id == 0 and self.status_lb is not None:
                # status overlay: the master status (HB = the selected enable bits) with the configured low byte
                if not write:
                    with self._lock:
                        hb = (self._values.get(0, 0) >> 8) & 0xFF
                    value = hb << 8
                value = (value & 0xFF00) | (self.status_lb & 0xFF)
            frame = self._build_write_frame(data_id, value) if write else self._build_read_frame(data_id, value)
            return self._exchange(frame, data_id, expect_write=write)
        # indexed parameter: HB = index, LB = value (u8); the reply LB is the parameter value
        frame = self._build_write_frame(data_id, (index << 8) | (value & 0xFF)) if write else self._build_read_frame(data_id, index << 8)
        return self._exchange(frame, data_id, expect_write=write) & 0xFF

    def _exchange(self, frame: bytes, expected_id: int, expect_write: bool = False) -> int:
        """Send a frame on the live socket and return the decoded reply value."""
        sock = self._sock
        if sock is None:
            raise DominusAuthError("OpenTherm socket not connected")
        if expect_write:
            _LOGGER.debug("OpenTherm write TX Data-ID %s: %s", expected_id, frame.hex(" "))
        sock.sendall(frame)
        value = self._recv_reply(sock, expected_id, expect_write)
        if expect_write:
            _LOGGER.debug("OpenTherm write Data-ID %s acknowledged with %s", expected_id, value)
        return value

    # -- framing ---------------------------------------------------------------

    @staticmethod
    def _build_read_frame(data_id: int, value: int = 0) -> bytes:
        hb, lb = (value >> 8) & 0xFF, value & 0xFF
        byte0 = _even_parity_byte0(0x00, data_id, hb, lb)  # READ-DATA (value 0, or HB = parameter index)
        body = bytes([byte0, data_id & 0xFF, hb, lb])
        crc = DominusClient._crc16_dominus(body)
        return body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])

    @staticmethod
    def _build_write_frame(data_id: int, value: int) -> bytes:
        value &= 0xFFFF
        hb, lb = (value >> 8) & 0xFF, value & 0xFF
        byte0 = _even_parity_byte0(_OT_WRITE_TYPE_BIT, data_id, hb, lb)  # WRITE-DATA
        body = bytes([byte0, data_id & 0xFF, hb, lb])
        crc = DominusClient._crc16_dominus(body)
        return body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])

    @staticmethod
    def _decode_reply(reply: bytes, expected_id: int, expect_write: bool = False) -> int:
        if len(reply) != 6:
            raise DominusProtocolError(f"OpenTherm reply must be 6 bytes, got {len(reply)}")
        crc_recv = (reply[4] << 8) | reply[5]
        if crc_recv != DominusClient._crc16_dominus(reply[:4]):
            raise DominusProtocolError("Invalid OpenTherm CRC")
        if reply[1] != expected_id:
            raise DominusProtocolError("Unexpected OpenTherm Data-ID in reply")
        msg_type = (reply[0] >> 4) & 0x07
        if msg_type in (_OT_MSGTYPE_DATA_INVALID, _OT_MSGTYPE_UNKNOWN_DATAID):
            raise DominusOpenThermUnsupported(f"Data-ID {expected_id} unsupported")
        ack = _OT_MSGTYPE_WRITE_ACK if expect_write else _OT_MSGTYPE_READ_ACK
        if msg_type != ack:
            raise DominusProtocolError(f"Unexpected OpenTherm msg-type {msg_type}")
        return (reply[2] << 8) | reply[3]

    def _recv_reply(
        self, sock: socket.socket, expected_id: int, expect_write: bool = False
    ) -> int:
        deadline = time.monotonic() + float(self._config.timeout or 2.0)
        buffer = bytearray()
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            for start in range(0, max(0, len(buffer) - 5)):
                try:
                    return self._decode_reply(
                        bytes(buffer[start:start + 6]), expected_id, expect_write
                    )
                except DominusOpenThermUnsupported:
                    raise
                except DominusProtocolError as err:
                    last_error = err
            remaining = max(0.05, deadline - time.monotonic())
            old_timeout = sock.gettimeout()
            try:
                sock.settimeout(min(old_timeout or remaining, remaining))
                chunk = sock.recv(256)
            except socket.timeout:
                break
            finally:
                try:
                    sock.settimeout(old_timeout)
                except OSError:
                    pass
            if not chunk:
                raise DominusAuthError("OpenTherm connection closed")
            buffer.extend(chunk)
            if len(buffer) > 512:
                del buffer[:-64]
        if buffer:
            # the raw bytes tell what the module answered instead (another msg-type, Data-ID or frame shape)
            _LOGGER.debug("OpenTherm Data-ID %s (%s): no valid reply, RX %s (%s)", expected_id,
                          "write" if expect_write else "read", bytes(buffer).hex(" "), last_error)
            raise DominusProtocolError("No valid OpenTherm reply found") from last_error
        raise DominusProtocolError("OpenTherm RX timeout")

    # -- connection ------------------------------------------------------------

    def _test_connection_blocking(self) -> None:
        last_error: Exception | None = None
        sock = self._auth_connect()
        try:
            for data_id in _TEST_DATA_IDS:
                try:
                    sock.sendall(self._build_read_frame(data_id))
                    self._recv_reply(sock, data_id)
                    return
                except DominusOpenThermUnsupported:
                    return  # boiler answered (just not this Data-ID) → auth works
                except Exception as err:  # noqa: BLE001
                    last_error = err
        finally:
            try:
                sock.close()
            except OSError:
                pass
        raise DominusAuthError("Failed to authenticate or read an OpenTherm Data-ID") from last_error

    def _auth_connect(self) -> socket.socket:
        if self._config.warmup_connect:
            try:
                warm = socket.create_connection(
                    (self._config.host, int(self._config.port)),
                    timeout=float(self._config.timeout),
                )
                warm.close()
            except OSError:
                pass
        try:
            sock = socket.create_connection(
                (self._config.host, int(self._config.port)),
                timeout=float(self._config.timeout),
            )
            sock.settimeout(float(self._config.timeout))
        except OSError as err:
            raise DominusAuthError("Cannot open Dominus TCP connection") from err
        try:
            auth = DominusClient._make_auth(
                self._config.mac, self._config.password
            ).encode("ascii")
            sock.sendall(auth)
            self._drain_post_auth(sock)
            return sock
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
            raise

    def _close_socket(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _drain_post_auth(sock: socket.socket) -> None:
        time.sleep(0.2)
        old_timeout = sock.gettimeout()
        try:
            sock.settimeout(0.2)
            while True:
                try:
                    chunk = sock.recv(256)
                except socket.timeout:
                    break
                if not chunk or len(chunk) < 256:
                    break
        finally:
            try:
                sock.settimeout(old_timeout)
            except OSError:
                pass
