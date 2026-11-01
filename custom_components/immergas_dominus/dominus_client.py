"""Low-level local TCP client for Immergas Dominus.

The TCP path is intentionally based on the working Dominus Gateway add-on,
with two additions useful inside Home Assistant:

* a short warm-up TCP connect/close before authenticated sessions.  The
  Gateway 0.3.15 code effectively did this by opening the socket twice;
  keeping it here makes the integration behave like the known-working path.
* robust reply scanning.  Some Dominus modules leave small handshake/echo
  bytes in the stream after AUTH.  The Gateway normally drained them, but HA's
  config flow should not fail just because a few bytes remain before the
  7-byte PDU reply.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import socket
import threading
import time
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

MAP1 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "
MAP2 = "0SFGLcTdjaxZPyeK9QhptB5v7zJH3Mq1VibDfCAN6EgYRwXlo8Wk4mun2rOsUI="

READ_REQUEST_TYPES = (0x00, 0x80)
WRITE_REQUEST_TYPE = 0x90
POST_AUTH_DRAIN_DELAY = 0.2
POST_AUTH_DRAIN_TIMEOUT = 0.2
READ_GAP_SECONDS = 0.6
TEST_RETRIES = 3
TEST_RETRY_DELAY = 1.0


class DominusError(Exception):
    """Base Dominus error."""


class DominusAuthError(DominusError):
    """Dominus authentication or connection failed."""


class DominusProtocolError(DominusError):
    """Unexpected Dominus TCP response."""


@dataclass(slots=True)
class DominusConfig:
    """Connection settings for a Dominus device."""

    host: str
    port: int
    mac: str
    password: str
    timeout: float = 2.0
    warmup_connect: bool = True


@dataclass(frozen=True, slots=True)
class TCPReply:
    """Decoded 7-byte Dominus TCP PDU reply."""

    reply_type: int
    pdu: int
    value_u16: int
    value_s16: int


class DominusClient:
    """Async facade over the blocking Dominus TCP AUTH client."""

    def __init__(self, config: DominusConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._read_request_types = READ_REQUEST_TYPES

    async def async_test_connection(self) -> None:
        """Open TCP AUTH and read a known safe PDU, with retries."""
        await asyncio.to_thread(self._test_connection_blocking)

    async def async_read_many(self, pdus: tuple[int, ...]) -> dict[int, int]:
        """Read many PDU values using short authenticated TCP sessions."""
        return await asyncio.to_thread(self._read_many_blocking, pdus)

    async def async_write_pdu(self, pdu: int, value: int) -> int:
        """Write a raw PDU value and return raw acknowledgement value."""
        reply = await asyncio.to_thread(self._write_pdu_blocking, pdu, value)
        return reply.value_s16

    def _test_connection_blocking(self) -> None:
        """Validate credentials using confirmed read-only PDU values.

        PDU 2011 is room temperature and proved stable in the Gateway tests.
        PDU 2000 is also confirmed, but if a module is slow just after closing
        another local client, room temperature tends to be a gentler test.
        """
        last_error: Exception | None = None
        test_pdus = (2011, 2000, 3002)
        with self._lock:
            for attempt in range(TEST_RETRIES):
                for pdu in test_pdus:
                    try:
                        self._read_pdu_blocking(pdu)
                        return
                    except Exception as err:  # noqa: BLE001
                        last_error = err
                if attempt + 1 < TEST_RETRIES:
                    time.sleep(TEST_RETRY_DELAY)
        raise DominusAuthError("Failed to authenticate or read a test PDU") from last_error

    def _read_many_blocking(self, pdus: tuple[int, ...]) -> dict[int, int]:
        """Read PDU values like the working Dominus Gateway poll loop.

        A single missing/slow PDU should not make the whole integration
        unavailable.  If at least one confirmed PDU is read successfully, HA can
        load the device and the next coordinator cycles can fill the rest.
        """
        values: dict[int, int] = {}
        last_error: Exception | None = None
        with self._lock:
            for index, pdu in enumerate(pdus):
                try:
                    reply = self._read_pdu_blocking(pdu)
                    values[pdu] = reply.value_s16
                except Exception as err:  # noqa: BLE001
                    last_error = err
                    _LOGGER.debug("Skipping failed Dominus PDU %s during polling: %s", pdu, err)
                if index + 1 < len(pdus):
                    time.sleep(READ_GAP_SECONDS)
        if not values:
            raise DominusAuthError("Failed to read any confirmed Dominus PDU") from last_error
        return values

    def _read_pdu_blocking(self, pdu: int) -> TCPReply:
        """Read one PDU; try the confirmed Dominus read request types."""
        last_error: Exception | None = None
        for request_type in self._read_request_types:
            try:
                with self._auth_connect() as sock:
                    frame = self._build_read_frame(pdu, request_type)
                    sock.sendall(frame)
                    return self._recv_reply_for_pdu(sock, expected_pdu=pdu)
            except Exception as err:  # noqa: BLE001 - converted below
                last_error = err
                _LOGGER.debug(
                    "Dominus read failed for PDU %s with request type 0x%02x: %s",
                    pdu,
                    request_type,
                    err,
                )
        raise DominusAuthError(f"Failed to read Dominus PDU {pdu}") from last_error

    def _write_pdu_blocking(self, pdu: int, value: int) -> TCPReply:
        """Write one PDU through an authenticated TCP session."""
        with self._lock:
            try:
                with self._auth_connect() as sock:
                    frame = self._build_write_frame(pdu, value, WRITE_REQUEST_TYPE)
                    sock.sendall(frame)
                    return self._recv_reply_for_pdu(sock, expected_pdu=pdu)
            except DominusError:
                raise
            except Exception as err:  # noqa: BLE001
                raise DominusAuthError(f"Failed to write Dominus PDU {pdu}") from err

    def _warmup_connect(self) -> None:
        """Replicate the Gateway 0.3.15 double-connect behaviour safely."""
        if not self._config.warmup_connect:
            return
        sock: socket.socket | None = None
        try:
            sock = socket.create_connection(
                (self._config.host, int(self._config.port)),
                timeout=float(self._config.timeout),
            )
        except OSError:
            return
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _auth_connect(self) -> socket.socket:
        """Open TCP socket, send Dominus AUTH and drain immediate echo."""
        self._warmup_connect()
        try:
            sock = socket.create_connection(
                (self._config.host, int(self._config.port)),
                timeout=float(self._config.timeout),
            )
            sock.settimeout(float(self._config.timeout))
        except OSError as err:
            raise DominusAuthError("Cannot open Dominus TCP connection") from err

        try:
            auth = self._make_auth(self._config.mac, self._config.password).encode("ascii")
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
    def _normalize_mac(mac: str) -> str:
        """Return a 12-character lowercase hex MAC."""
        normalized = str(mac or "").replace(":", "").replace("-", "").strip().lower()
        if len(normalized) != 12 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise DominusAuthError("Invalid MAC address")
        return normalized

    @classmethod
    def _make_auth(cls, mac: str, password: str) -> str:
        """Build the Immergas local TCP AUTH string."""
        mac12 = cls._normalize_mac(mac)
        md5_12 = hashlib.md5(str(password).encode("utf-8")).hexdigest()[:12]
        plain = f"{mac12} {md5_12}"

        encoded: list[str] = []
        map_len = len(MAP1)
        for char in plain:
            idx = MAP1.find(char)
            if idx == -1:
                encoded.append(char)
            else:
                encoded.append(MAP2[(idx + 2) % map_len])
        return "#D" + "".join(encoded)

    @staticmethod
    def _crc16_dominus(data: bytes) -> int:
        """CRC used by Dominus 7-byte TCP frames."""
        crc = 0xFFFF
        poly = 0x1021
        for byte in data:
            for bit_index in range(8):
                bit = (byte >> bit_index) & 1
                lsb = crc & 1
                crc >>= 1
                if lsb ^ bit:
                    crc ^= poly
        return crc & 0xFFFF

    @classmethod
    def _build_read_frame(cls, pdu: int, request_type: int) -> bytes:
        """Build one 7-byte PDU read frame."""
        body = bytes([
            request_type & 0xFF,
            (pdu >> 8) & 0xFF,
            pdu & 0xFF,
            0x00,
            0x00,
        ])
        crc = cls._crc16_dominus(body)
        return body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])

    @classmethod
    def _build_write_frame(cls, pdu: int, value: int, request_type: int = WRITE_REQUEST_TYPE) -> bytes:
        """Build one 7-byte PDU write frame."""
        value_u16 = int(value) & 0xFFFF
        body = bytes([
            request_type & 0xFF,
            (pdu >> 8) & 0xFF,
            pdu & 0xFF,
            (value_u16 >> 8) & 0xFF,
            value_u16 & 0xFF,
        ])
        crc = cls._crc16_dominus(body)
        return body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])

    @classmethod
    def _decode_reply(cls, reply: bytes, expected_pdu: int) -> TCPReply:
        """Decode and validate a 7-byte Dominus TCP PDU reply."""
        if len(reply) != 7:
            raise DominusProtocolError(f"Reply must be 7 bytes, got {len(reply)}")
        crc_recv = (reply[5] << 8) | reply[6]
        crc_calc = cls._crc16_dominus(reply[:5])
        if crc_recv != crc_calc:
            raise DominusProtocolError("Invalid Dominus PDU CRC")

        pdu = (reply[1] << 8) | reply[2]
        if pdu != expected_pdu:
            raise DominusProtocolError("Unexpected Dominus PDU reply")

        value_u16 = (reply[3] << 8) | reply[4]
        value_s16 = value_u16 - 0x10000 if value_u16 & 0x8000 else value_u16
        return TCPReply(
            reply_type=reply[0],
            pdu=pdu,
            value_u16=value_u16,
            value_s16=value_s16,
        )

    @classmethod
    def _recv_reply_for_pdu(cls, sock: socket.socket, expected_pdu: int) -> TCPReply:
        """Receive and scan for a valid 7-byte reply for the expected PDU."""
        deadline = time.monotonic() + float(sock.gettimeout() or 2.0)
        buffer = bytearray()
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            # Try every 7-byte window currently buffered.  This tolerates a few
            # leftover AUTH echo/handshake bytes before the actual frame.
            for start in range(0, max(0, len(buffer) - 6)):
                candidate = bytes(buffer[start:start + 7])
                try:
                    return cls._decode_reply(candidate, expected_pdu=expected_pdu)
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
                raise DominusAuthError("Dominus TCP RX error") from err
            finally:
                try:
                    sock.settimeout(old_timeout)
                except OSError:
                    pass

            if not chunk:
                break
            buffer.extend(chunk)
            # Avoid unbounded growth if the peer sends unexpected data.
            if len(buffer) > 512:
                del buffer[:-64]

        if buffer:
            raise DominusProtocolError("No valid Dominus PDU reply found") from last_error
        raise DominusAuthError("Dominus TCP RX timeout")

    @staticmethod
    def _drain_post_auth(sock: socket.socket) -> bytes:
        """Drain the immediate ASCII AUTH echo returned after AUTH."""
        if POST_AUTH_DRAIN_DELAY:
            time.sleep(POST_AUTH_DRAIN_DELAY)
        old_timeout = sock.gettimeout()
        drained = bytearray()
        try:
            sock.settimeout(POST_AUTH_DRAIN_TIMEOUT)
            while True:
                try:
                    chunk = sock.recv(256)
                except socket.timeout:
                    break
                if not chunk:
                    break
                drained.extend(chunk)
                if len(chunk) < 256:
                    break
        finally:
            try:
                sock.settimeout(old_timeout)
            except OSError:
                pass
        return bytes(drained)
