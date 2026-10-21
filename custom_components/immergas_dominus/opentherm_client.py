"""Experimental OpenTherm-over-TCP client for Immergas boilers (e.g. VICTRIX).

The Dominus Wi-Fi module speaks two local protocols, chosen by the boiler's config:

* boilers with a Modbus config (``*_MBUS_*``, Magis Combo/Pro) use the 7-byte
  Modbus-PDU protocol handled by :mod:`.dominus_client`;
* boilers **without** the ``modbus`` flag (VICTRIX ZEUS / AVIO, STAR, …) tunnel
  **standard OpenTherm** frames over the same authenticated TCP channel: a 6-byte
  frame = the 4-byte OpenTherm frame (parity + 3-bit msg-type + 8-bit Data-ID +
  16-bit value) + a 2-byte Dominus CRC (CRC-16/CCITT 0x1021 / 0xFFFF, identical to
  the Modbus mode).

This client is **read-only and experimental** — it issues OpenTherm READ-DATA
requests only and has not been verified on real hardware yet.  The AUTH and CRC are
reused from the Modbus client so the two modes stay byte-for-byte compatible.
"""
from __future__ import annotations

import asyncio
import logging
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
_OT_MSGTYPE_READ_DATA = 0b000
_OT_MSGTYPE_READ_ACK = 0b100
_OT_MSGTYPE_DATA_INVALID = 0b010
_OT_MSGTYPE_UNKNOWN_DATAID = 0b011

_READ_GAP_SECONDS = 0.6
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


class DominusOpenThermClient:
    """Async facade over the blocking OpenTherm-over-Dominus-TCP read client."""

    def __init__(self, config: DominusConfig) -> None:
        self._config = config
        self._lock = threading.RLock()

    async def async_test_connection(self) -> None:
        """Authenticate and read at least one known OpenTherm Data-ID."""
        await asyncio.to_thread(self._test_connection_blocking)

    async def async_read_many(self, data_ids: tuple[int, ...]) -> dict[int, int]:
        """Read several OpenTherm Data-IDs; returns raw 16-bit data values."""
        return await asyncio.to_thread(self._read_many_blocking, data_ids)

    # -- blocking implementation ------------------------------------------------

    def _test_connection_blocking(self) -> None:
        last_error: Exception | None = None
        with self._lock:
            for data_id in _TEST_DATA_IDS:
                try:
                    self._read_data_id_blocking(data_id)
                    return
                except Exception as err:  # noqa: BLE001
                    last_error = err
        raise DominusAuthError(
            "Failed to authenticate or read an OpenTherm Data-ID"
        ) from last_error

    def _read_many_blocking(self, data_ids: tuple[int, ...]) -> dict[int, int]:
        values: dict[int, int] = {}
        last_error: Exception | None = None
        with self._lock:
            for index, data_id in enumerate(data_ids):
                try:
                    values[data_id] = self._read_data_id_blocking(data_id)
                except DominusOpenThermUnsupported:
                    _LOGGER.debug("OpenTherm Data-ID %s not supported by boiler", data_id)
                except Exception as err:  # noqa: BLE001
                    last_error = err
                    _LOGGER.debug("OpenTherm read failed for Data-ID %s: %s", data_id, err)
                if index + 1 < len(data_ids):
                    time.sleep(_READ_GAP_SECONDS)
        if not values:
            raise DominusAuthError("Failed to read any OpenTherm Data-ID") from last_error
        return values

    def _read_data_id_blocking(self, data_id: int) -> int:
        with self._auth_connect() as sock:
            frame = self._build_read_frame(data_id)
            sock.sendall(frame)
            return self._recv_reply_for_id(sock, data_id)

    # -- framing ---------------------------------------------------------------

    @staticmethod
    def _build_read_frame(data_id: int) -> bytes:
        byte0 = _even_parity_byte0(0x00, data_id, 0x00, 0x00)  # READ-DATA, value 0
        body = bytes([byte0, data_id & 0xFF, 0x00, 0x00])
        crc = DominusClient._crc16_dominus(body)
        return body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])

    @staticmethod
    def _decode_reply(reply: bytes, expected_id: int) -> int:
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
        if msg_type != _OT_MSGTYPE_READ_ACK:
            raise DominusProtocolError(f"Unexpected OpenTherm msg-type {msg_type}")
        return (reply[2] << 8) | reply[3]

    def _recv_reply_for_id(self, sock: socket.socket, expected_id: int) -> int:
        deadline = time.monotonic() + float(sock.gettimeout() or 2.0)
        buffer = bytearray()
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            for start in range(0, max(0, len(buffer) - 5)):
                try:
                    return self._decode_reply(bytes(buffer[start:start + 6]), expected_id)
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
            except OSError as err:
                raise DominusAuthError("OpenTherm TCP RX error") from err
            finally:
                try:
                    sock.settimeout(old_timeout)
                except OSError:
                    pass
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > 512:
                del buffer[:-64]
        if buffer:
            raise DominusProtocolError("No valid OpenTherm reply found") from last_error
        raise DominusAuthError("OpenTherm TCP RX timeout")

    # -- connection (mirrors the Modbus client's authenticated connect) --------

    def _auth_connect(self) -> socket.socket:
        # Warm-up connect/close, like the Modbus client, to wake flaky modules.
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
