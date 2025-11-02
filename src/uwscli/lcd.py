"""Uni Fan LCD (TL) HID device access helpers."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import enum
import time
from typing import Any, Dict, Iterator, List, Optional

from .structs import LCDControlMode, LCDControlSetting, ScreenRotation
from .system_usb import find_devices_by_vid_pid
from .usbutil import USBEndpointDevice, USBError

import hid

DES: Any
Padding: Any

try:  # Prefer the namespace-safe module
    from Cryptodome.Cipher import DES as _CryptodomeDES
    from Cryptodome.Util import Padding as _CryptodomePadding

    DES = _CryptodomeDES
    Padding = _CryptodomePadding
except ImportError:  # pragma: no cover - fallback for alternative install
    try:
        from Crypto.Cipher import DES as _CryptoDES
        from Crypto.Util import Padding as _CryptoPadding

        DES = _CryptoDES
        Padding = _CryptoPadding
    except ImportError:  # pragma: no cover - handled at runtime
        DES = None
        Padding = None


LCD_REPORT_ID = 0x02
OUTPUT_PACKET_SIZE = 512
INPUT_PACKET_SIZE = 64
USB_INPUT_PACKET_SIZE = OUTPUT_PACKET_SIZE
MAX_CHUNK = 501

# Known Uni Fan LCD VID/PID combinations (original and TL V2 wireless receiver)
KNOWN_LCD_IDS = (
    (0x04FC, 0x7393),
    (0x1CBE, 0x0006),
)


class LCDDeviceError(RuntimeError):
    """Raised when HID operations fail."""


@dataclasses.dataclass
class HidDeviceInfo:
    path: str
    vendor_id: int
    product_id: int
    serial_number: Optional[str]
    manufacturer: Optional[str]
    product: Optional[str]
    source: str = "hid"
    location_id: Optional[int] = None


def enumerate_devices() -> List[HidDeviceInfo]:
    devices: List[HidDeviceInfo] = []
    for vendor_id, product_id in KNOWN_LCD_IDS:
        found_for_pair = False
        for entry in hid.enumerate(vendor_id, product_id):
            devices.append(
                HidDeviceInfo(
                    path=entry["path"],
                    vendor_id=entry["vendor_id"],
                    product_id=entry["product_id"],
                    serial_number=entry.get("serial_number"),
                    manufacturer=entry.get("manufacturer_string"),
                    product=entry.get("product_string"),
                    source="hid",
                    location_id=entry.get("location_id"),
                ),
            )
            found_for_pair = True
        if not found_for_pair:
            for record in find_devices_by_vid_pid(vendor_id, product_id):
                source = "usb"
                if (record.vendor_id, record.product_id) == (0x1CBE, 0x0006):
                    source = "wireless"
                devices.append(
                    HidDeviceInfo(
                        path=f"usb:{record.vendor_id:04x}:{record.product_id:04x}:{record.location_id or 0}",
                        vendor_id=record.vendor_id,
                        product_id=record.product_id,
                        serial_number=record.serial,
                        manufacturer=record.vendor,
                        product=record.product,
                        source=source,
                        location_id=record.location_id,
                    ),
                )
    unique: List[HidDeviceInfo] = []
    seen = set()
    for dev in devices:
        key = (dev.path, dev.serial_number, dev.vendor_id, dev.product_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(dev)
    return unique


class WirelessCommand(enum.IntEnum):
    GET_VER = 10
    REBOOT = 11
    ROTATE = 13
    BRIGHTNESS = 14
    SET_FRAME_RATE = 15
    UPDATE_FIRMWARE = 40
    STOP_CLOCK = 41
    PUSH_JPG = 101
    START_PLAY = 121
    QUERY_BLOCK = 122
    STOP_PLAY = 123
    GET_POS_INDEX = 201
    FACTORY_H264_TEST = 253


class WirelessUSBTransport:
    """Implements the wireless receiver WinUSB protocol used by Uni Fan LCD devices."""

    _KEY = b"slv3tuzx"
    _HEADER_SIZE = 512
    _PAYLOAD_BUFFER = 102400

    def __init__(
        self,
        vendor_id: int,
        product_id: int,
        timeout_ms: int = 5000,
        *,
        serial_number: Optional[str] = None,
        location_id: Optional[int] = None,
    ) -> None:
        self._vendor_id = vendor_id
        self._product_id = product_id
        self._timeout_ms = timeout_ms
        self._serial_number = serial_number
        self._location_id = location_id
        self._device = USBEndpointDevice(
            vendor_id,
            product_id,
            write_endpoint=0x01,
            read_endpoint=0x81,
            interface=0,
            configuration=None,
            timeout_ms=timeout_ms,
            serial_number=serial_number,
            location_id=location_id,
        )
        utc_midnight = datetime.datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self._epoch = utc_midnight - datetime.timedelta(days=1)
        self._last_handshake = 0.0

    def close(self) -> None:
        self._device.close()
        self._last_handshake = 0.0

    def handshake(self) -> Dict[str, int]:
        response = self._send_command(WirelessCommand.GET_POS_INDEX, expect_reply=True)
        for _ in range(4):
            if response:
                command = response[0]
                if command == WirelessCommand.GET_POS_INDEX:
                    mode = response[8] if len(response) > 8 else 0
                    frame_index = response[9] if len(response) > 9 else 0
                    self._last_handshake = time.monotonic()
                    return {"mode": mode, "frame_index": frame_index}
                if command == WirelessCommand.GET_VER:
                    self._parse_version(response)
                    self._last_handshake = time.monotonic()
                    return {"mode": 0, "frame_index": 0}
            response = self._read_next()
        raise LCDDeviceError("No valid handshake response from wireless LCD")

    def firmware_version(self) -> Dict[str, str]:
        response = self._send_command(WirelessCommand.GET_VER, expect_reply=True)
        for _ in range(4):
            if response and response[0] == WirelessCommand.GET_VER:
                version = self._parse_version(response)
                self._last_handshake = time.monotonic()
                return {"version": version or "unknown", "build": ""}
            response = self._read_next()
        raise LCDDeviceError("Firmware request did not return expected data")

    def _ensure_awake(self) -> None:
        now = time.monotonic()
        if self._last_handshake and now - self._last_handshake <= 2.0:
            return
        self.handshake()

    def control(self, setting: LCDControlSetting) -> None:
        self._ensure_awake()
        brightness = max(0, min(100, setting.brightness))
        self._send_command(
            WirelessCommand.BRIGHTNESS,
            single_byte=brightness,
            drain_response=True,
        )
        self._send_command(
            WirelessCommand.ROTATE,
            single_byte=setting.rotation.value,
            drain_response=True,
        )

    def send_jpg(self, payload: bytes) -> None:
        self._ensure_awake()
        self._send_command(
            WirelessCommand.PUSH_JPG,
            payload=payload,
            expect_reply=False,
            drain_response=True,
        )

    def send_sync_jpg(self, payload: bytes) -> None:
        self.send_jpg(payload)

    def send_boot_jpg(self, payload: bytes) -> None:
        self.send_jpg(payload)

    def send_boot_video(self, payload: bytes) -> None:
        raise LCDDeviceError(
            "Boot video upload is not supported for wireless LCD devices"
        )

    def send_avi(self, payload: bytes) -> None:
        raise LCDDeviceError("AVI streaming is not supported for wireless LCD devices")

    def reboot(self) -> None:
        self._ensure_awake()
        self._send_command(
            WirelessCommand.REBOOT, expect_reply=False, drain_response=True
        )

    def _timestamp_ms(self) -> int:
        delta = datetime.datetime.utcnow() - self._epoch
        return int(delta.total_seconds() * 1000) & 0xFFFFFFFF

    def _send_command(
        self,
        command: WirelessCommand,
        *,
        payload: Optional[bytes] = None,
        single_byte: Optional[int] = None,
        expect_reply: bool = False,
        drain_response: bool = False,
    ) -> bytes:
        packet = self._build_packet(command, payload=payload, single_byte=single_byte)
        written = self._write_with_recovery(packet)
        if written != len(packet):
            raise LCDDeviceError(
                f"Incomplete wireless USB write ({written}/{len(packet)})"
            )
        if expect_reply:
            return self._device.read(self._HEADER_SIZE)
        if drain_response:
            self._drain_optional_response()
        return b""

    def _write_with_recovery(self, packet: bytes) -> int:
        try:
            return self._device.write(packet)
        except USBError as exc:
            if not self._should_retry(exc):
                raise
            self._reset_connection()
            return self._device.write(packet)

    def _should_retry(self, exc: USBError) -> bool:
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return True
        cause = exc.__cause__
        errno = getattr(cause, "errno", None)
        return errno == 110

    def _reset_connection(self) -> None:
        with contextlib.suppress(Exception):
            self._device.close()
        self._device = USBEndpointDevice(
            self._vendor_id,
            self._product_id,
            write_endpoint=0x01,
            read_endpoint=0x81,
            interface=0,
            configuration=None,
            timeout_ms=self._timeout_ms,
            serial_number=self._serial_number,
            location_id=self._location_id,
        )
        self._last_handshake = 0.0
        time.sleep(0.05)

    def _build_packet(
        self,
        command: WirelessCommand,
        *,
        payload: Optional[bytes],
        single_byte: Optional[int],
    ) -> bytes:
        header = bytearray(504)
        header[0] = command & 0xFF
        header[2] = 26
        header[3] = 109
        header[4:8] = self._timestamp_ms().to_bytes(4, "little", signed=False)
        if payload is not None:
            if len(payload) > self._PAYLOAD_BUFFER - self._HEADER_SIZE:
                raise LCDDeviceError("Payload too large for wireless LCD transfer")
            header[8:12] = len(payload).to_bytes(4, "big", signed=False)
        elif single_byte is not None:
            header[8] = single_byte & 0xFF
        encrypted_header = self._encrypt(bytes(header))
        if payload is None:
            packet = bytearray(self._HEADER_SIZE)
            packet[: len(encrypted_header)] = encrypted_header
            return bytes(packet)

        packet_length = max(self._PAYLOAD_BUFFER, self._HEADER_SIZE + len(payload))
        packet = bytearray(packet_length)
        packet[: len(encrypted_header)] = encrypted_header
        packet[self._HEADER_SIZE : self._HEADER_SIZE + len(payload)] = payload
        return bytes(packet)

    def _encrypt(self, data: bytes) -> bytes:
        if DES is None or Padding is None:  # pragma: no cover - dependency missing
            raise LCDDeviceError(
                "PyCryptodome is required for wireless LCD support. Install with 'pip install pycryptodomex'.",
            )
        padded = Padding.pad(data, 8, style="pkcs7")
        cipher = DES.new(self._KEY, DES.MODE_CBC, iv=self._KEY)
        return cipher.encrypt(padded)

    def _parse_version(self, packet: bytes) -> str:
        raw = packet[8 : 8 + 32]
        value = raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
        return value

    def _drain_optional_response(self, timeout_ms: int = 200) -> None:
        try:
            self._device.read(self._HEADER_SIZE, timeout_ms=timeout_ms)
        except USBError:
            # Some operations do not produce an acknowledgement; ignore timeouts.
            return

    def _read_next(self) -> bytes:
        try:
            return self._device.read(self._HEADER_SIZE)
        except USBError:
            return b""


class TLLCDDevice:
    """Control a TL LCD panel resolved by its USB serial number."""

    def __init__(self, serial: str) -> None:
        self._backend = "hid"
        self._hid: Optional[hid.Device] = None
        self._usb: Optional[USBEndpointDevice] = None
        self._wireless: Optional[WirelessUSBTransport] = None
        normalized = serial.strip()
        if not normalized:
            raise LCDDeviceError("Serial selector cannot be empty")
        if normalized.startswith("serial:"):
            normalized = normalized.split(":", 1)[1].strip()
        if not normalized:
            raise LCDDeviceError("Serial selector cannot be empty")

        matches = [
            dev for dev in enumerate_devices() if dev.serial_number == normalized
        ]
        if not matches:
            raise LCDDeviceError(f"No LCD device found with serial {normalized}")
        if len(matches) > 1:
            raise LCDDeviceError(
                f"Multiple LCD devices share serial {normalized}; specify a unique serial",
            )

        resolved = matches[0]
        if resolved.source == "hid":
            try:
                self._hid = hid.Device(path=resolved.path)
            except OSError as exc:
                raise LCDDeviceError(f"Unable to open HID device: {exc}") from exc
            self._hid.nonblocking = False
            return

        if resolved.location_id is None:
            raise LCDDeviceError(
                f"Device serial {normalized} is missing a location id; replug the device and try again",
            )

        try:
            if (resolved.vendor_id, resolved.product_id) == (0x1CBE, 0x0006):
                self._backend = "wireless"
                self._wireless = WirelessUSBTransport(
                    resolved.vendor_id,
                    resolved.product_id,
                    timeout_ms=5000,
                    location_id=resolved.location_id,
                )
            else:
                self._backend = "usb"
                self._usb = USBEndpointDevice(
                    resolved.vendor_id,
                    resolved.product_id,
                    write_endpoint=None,
                    read_endpoint=None,
                    interface=None,
                    timeout_ms=5000,
                    location_id=resolved.location_id,
                )
        except USBError as exc:
            raise LCDDeviceError(str(exc)) from exc

    def close(self) -> None:
        if self._backend == "hid" and self._hid is not None:
            with contextlib.suppress(Exception):
                self._hid.close()
            self._hid = None
        elif self._backend == "usb" and self._usb is not None:
            self._usb.close()
            self._usb = None
        elif self._backend == "wireless" and self._wireless is not None:
            self._wireless.close()
            self._wireless = None

    def __enter__(self) -> "TLLCDDevice":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _build_packets(self, command: int, data: bytes) -> Iterator[bytes]:
        data_length = len(data)
        if data_length == 0:
            packet = bytearray(OUTPUT_PACKET_SIZE)
            packet[0] = LCD_REPORT_ID
            packet[1] = command
            return iter([bytes(packet)])
        packets: List[bytes] = []
        packet_number = 0
        offset = 0
        while offset < data_length:
            chunk = data[offset : offset + MAX_CHUNK]
            packet = bytearray(OUTPUT_PACKET_SIZE)
            packet[0] = LCD_REPORT_ID
            packet[1] = command
            packet[2:6] = data_length.to_bytes(4, "big")
            packet[6:9] = packet_number.to_bytes(3, "big")
            packet[9:11] = len(chunk).to_bytes(2, "big")
            packet[11 : 11 + len(chunk)] = chunk
            packets.append(bytes(packet))
            offset += len(chunk)
            packet_number += 1
        return iter(packets)

    def _write(self, command: int, data: bytes, expect_reply: bool) -> List[bytes]:
        if self._backend == "wireless":
            raise LCDDeviceError("Wireless LCD backend does not support HID framing")
        responses: List[bytes] = []
        packets = list(self._build_packets(command, data))
        if not packets:
            packets = [
                bytes(
                    bytearray([LCD_REPORT_ID, command] + [0] * (OUTPUT_PACKET_SIZE - 2))
                )
            ]
        for packet in packets:
            written = self._write_packet(packet)
            if written != len(packet):
                raise LCDDeviceError(
                    f"Incomplete HID write ({written}/{len(packet)})",
                )
            if expect_reply:
                response = self._read_packet()
                if not response:
                    raise LCDDeviceError("Timeout waiting for LCD response")
                if response[1] != command:
                    raise LCDDeviceError(
                        f"Unexpected response command 0x{response[1]:02x} for 0x{command:02x}",
                    )
                responses.append(bytes(response))
        return responses

    def _write_packet(self, packet: bytes) -> int:
        if self._backend == "hid" and self._hid is not None:
            return self._hid.write(packet)
        if self._backend == "usb" and self._usb is not None:
            try:
                return self._usb.write(packet)
            except USBError as exc:
                raise LCDDeviceError(f"USB write failed: {exc}") from exc
        if self._backend == "wireless":
            raise LCDDeviceError(
                "Wireless LCD backend does not support HID packet writes"
            )
        raise LCDDeviceError("LCD device is not open")

    def _read_packet(self) -> bytes:
        if self._backend == "hid" and self._hid is not None:
            return bytes(self._hid.read(INPUT_PACKET_SIZE, timeout=1000))
        if self._backend == "usb" and self._usb is not None:
            try:
                return self._usb.read(USB_INPUT_PACKET_SIZE)
            except USBError as exc:
                raise LCDDeviceError(f"USB read failed: {exc}") from exc
        if self._backend == "wireless":
            raise LCDDeviceError(
                "Wireless LCD backend does not support HID packet reads"
            )
        raise LCDDeviceError("LCD device is not open")

    def handshake(self) -> Dict[str, int]:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            return self._wireless.handshake()
        response = self._write(0x3C, b"", expect_reply=True)
        if not response:
            raise LCDDeviceError("No handshake response")
        payload = _extract_payload(response[0])
        if len(payload) < 3:
            raise LCDDeviceError("Handshake payload too short")
        mode = payload[0]
        frame_index = (payload[1] << 8) | payload[2]
        return {"mode": mode, "frame_index": frame_index}

    def firmware_version(self) -> Dict[str, str]:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            return self._wireless.firmware_version()
        responses = self._write(0x3D, b"", expect_reply=True)
        if len(responses) < 2:
            raise LCDDeviceError("Firmware request did not return two packets")
        version = (
            _extract_payload(responses[0])
            .split(b"\x00", 1)[0]
            .decode("ascii", errors="ignore")
        )
        build_date = (
            _extract_payload(responses[1])
            .split(b"\x00", 1)[0]
            .decode("ascii", errors="ignore")
        )
        return {"version": version, "build": build_date}

    def control(self, setting: LCDControlSetting) -> None:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            self._wireless.control(setting)
            return
        self._write(0x40, setting.to_bytes(), expect_reply=True)

    def send_jpg(self, payload: bytes) -> None:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            self._wireless.send_jpg(payload)
            return
        self._write(0x41, payload, expect_reply=True)

    def send_avi(self, payload: bytes) -> None:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            self._wireless.send_avi(payload)
            return
        self._write(0x45, payload, expect_reply=True)

    def send_sync_jpg(self, payload: bytes) -> None:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            self._wireless.send_sync_jpg(payload)
            return
        self._write(0x46, payload, expect_reply=False)

    def send_boot_jpg(self, payload: bytes) -> None:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            self._wireless.send_boot_jpg(payload)
            return
        self._write(0x48, payload, expect_reply=True)

    def send_boot_video(self, payload: bytes) -> None:
        if self._backend == "wireless":
            if not self._wireless:
                raise LCDDeviceError("Wireless transport is unavailable")
            self._wireless.send_boot_video(payload)
            return
        self._write(0x47, payload, expect_reply=True)


def rotation_from_arg(value: int) -> ScreenRotation:
    return ScreenRotation.from_degrees(value)


def mode_from_arg(value: str) -> LCDControlMode:
    value_upper = value.upper().replace("-", "_")
    try:
        return LCDControlMode[value_upper]
    except KeyError as exc:
        raise ValueError(
            f"Invalid LCD control mode '{value}'. Valid modes: "
            + ", ".join(m.name.lower() for m in LCDControlMode),
        ) from exc


def _extract_payload(packet: bytes) -> bytes:
    if len(packet) < 11 or packet[0] != LCD_REPORT_ID:
        raise LCDDeviceError("Malformed LCD input packet")
    length = (packet[9] << 8) | packet[10]
    length = min(length, max(0, len(packet) - 11))
    return bytes(packet[11 : 11 + length])
