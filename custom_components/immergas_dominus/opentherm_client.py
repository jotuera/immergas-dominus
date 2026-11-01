"""Experimental OpenTherm-over-TCP client for Immergas boilers (e.g. VICTRIX).

The Dominus Wi-Fi module speaks two local protocols, chosen by the boiler's config:

* boilers with a Modbus config (``*_MBUS_*``, Magis Combo/Pro) use the 7-byte
  Modbus-PDU protocol handled by :mod:`.dominus_client`;
* boilers **without** the ``modbus`` flag (VICTRIX ZEUS / AVIO, STAR, …) tunnel
  **standard OpenTherm** frames over the same authenticated TCP channel: a 6-byte
  frame = the 4-byte OpenTherm frame (parity + 3-bit msg-type + 8-bit Data-ID +
  16-bit value) + a 2-byte Dominus CRC (CRC-16/CCITT 0x1021 / 0xFFFF, identical to
  the Modbus mode).

Unlike the Modbus mode, this client keeps **one persistent authenticated session**
and runs a background loop that polls the registered Data-IDs continuously and sends
writes on a priority queue inside that session.  The module resets a fresh connection
on a WRITE-DATA frame (reads work on a fresh connection, writes do not), so the live
session is required for writes — mirroring the official Dominus app.

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
        assert request.ack is not None
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
                        request.ack = self._exchange(
                            self._build_write_frame(request.data_id, request.value),
                            request.data_id,
                            expect_write=True,
                        )
                        with self._lock:
                            self._values[request.data_id] = request.ack
                    except DominusOpenThermUnsupported as err:
                        request.error = err
                    finally:
                        request.event.set()
                    self._stop.wait(_MESSAGE_GAP)
                    continue

                with self._lock:
                    ids = self._poll_ids
                if not ids:
                    self._stop.wait(0.3)
                    continue
                data_id = ids[pos % len(ids)]
                pos += 1
                try:
                    value = self._exchange(self._build_read_frame(data_id), data_id)
                    with self._lock:
                        self._values[data_id] = value
                except DominusOpenThermUnsupported:
                    pass  # boiler doesn't support this Data-ID; keep polling others
                self._stop.wait(_MESSAGE_GAP)
            except (OSError, DominusProtocolError, DominusAuthError) as err:
                _LOGGER.debug("OpenTherm session error, reconnecting: %s", err)
                self._close_socket()
                self._fail_pending_writes(err)
                self._stop.wait(backoff)
                backoff = min(backoff * 2.0, 20.0)

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

    def _exchange(self, frame: bytes, expected_id: int, expect_write: bool = False) -> int:
        """Send a frame on the live socket and return the decoded reply value."""
        sock = self._sock
        if sock is None:
            raise DominusAuthError("OpenTherm socket not connected")
        sock.sendall(frame)
        return self._recv_reply(sock, expected_id, expect_write)

    # -- framing ---------------------------------------------------------------

    @staticmethod
    def _build_read_frame(data_id: int) -> bytes:
        byte0 = _even_parity_byte0(0x00, data_id, 0x00, 0x00)  # READ-DATA, value 0
        body = bytes([byte0, data_id & 0xFF, 0x00, 0x00])
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
