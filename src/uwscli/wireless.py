"""2.4 GHz wireless fan controller helpers."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .structs import WirelessDeviceInfo, clamp_pwm_values
from .system_usb import find_devices_by_vid_pid
from .usbutil import USBEndpointDevice, USBError


logger = logging.getLogger(__name__)

RF_SENDER_VID = 0x0416
RF_SENDER_PID = 0x8040
RF_RECEIVER_VID = 0x0416
RF_RECEIVER_PID = 0x8041

RF_GET_DEV_CMD = 0x10
RF_PACKET_HEADER = 0x10
RF_CHUNK_SIZE = 60
RF_PAYLOAD_SIZE = 240
RF_PAGE_STRIDE = 434
MAX_DEVICES_PER_PAGE = 10


class WirelessError(RuntimeError):
    """Raised when an RF dongle interaction fails."""


@dataclass
class WirelessSnapshot:
    devices: List[WirelessDeviceInfo]
    raw: bytes


class WirelessTransceiver:
    """High level helper around the Uni Fan wireless USB dongle pair."""

    def __init__(self, timeout_ms: int = 1000) -> None:
        try:
            self._sender = USBEndpointDevice(
                RF_SENDER_VID,
                RF_SENDER_PID,
                timeout_ms=timeout_ms,
            )
        except USBError as exc:
            if find_devices_by_vid_pid(RF_SENDER_VID, RF_SENDER_PID):
                raise WirelessError(
                    "Wireless sender detected but libusb access failed. Install libusb (e.g. `brew install libusb`).",
                ) from exc
            raise WirelessError(str(exc)) from exc

        try:
            self._receiver = USBEndpointDevice(
                RF_RECEIVER_VID,
                RF_RECEIVER_PID,
                timeout_ms=timeout_ms,
            )
        except USBError as exc:
            self._sender.close()
            if find_devices_by_vid_pid(RF_RECEIVER_VID, RF_RECEIVER_PID):
                raise WirelessError(
                    "Wireless receiver detected but libusb access failed. Install libusb (e.g. `brew install libusb`).",
                ) from exc
            raise WirelessError(str(exc)) from exc

        logger.debug("Opened wireless transceiver (timeout=%sms)", timeout_ms)

    def close(self) -> None:
        self._sender.close()
        self._receiver.close()
        logger.debug("Closed wireless transceiver")

    def __enter__(self) -> "WirelessTransceiver":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def list_devices(self) -> WirelessSnapshot:
        logger.debug("Requesting wireless device list")
        page_count = 1
        snapshot = self._fetch_page(page_count)
        expected_pages = max(1, math.ceil(snapshot[0] / MAX_DEVICES_PER_PAGE))
        if expected_pages != page_count:
            snapshot = self._fetch_page(expected_pages)
        device_count, payload = snapshot
        devices = self._parse_devices(device_count, payload)
        logger.debug("Discovered %d wireless device(s)", len(devices))
        return WirelessSnapshot(devices=devices, raw=payload)

    def set_pwm(
        self,
        mac: str,
        pwm_values: Sequence[int],
        *,
        sequence_index: int = 1,
    ) -> None:
        snapshot = self.list_devices()
        target = next((dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None)
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError("Device is not bound to a master controller; cannot send PWM")
        payload = bytearray(RF_PAYLOAD_SIZE)
        payload[0] = 0x12
        payload[1] = 0x10
        payload[2:8] = _mac_to_bytes(target.mac)
        payload[8:14] = _mac_to_bytes(target.master_mac)
        payload[14] = target.rx_type
        payload[15] = target.channel
        payload[16] = sequence_index & 0xFF
        pwm_tuple = clamp_pwm_values(pwm_values)
        payload[17:21] = bytes(pwm_tuple)
        logger.info(
            "Sending PWM command to %s (channel=%s rx=%s): %s seq=%d",
            mac,
            target.channel,
            target.rx_type,
            pwm_tuple,
            sequence_index,
        )
        self._send_rf_data(target.channel, target.rx_type, payload)

    def bind_device(
        self,
        mac: str,
        *,
        master_mac: Optional[str] = None,
        rx_type: Optional[int] = None,
    ) -> WirelessDeviceInfo:
        snapshot = self.list_devices()
        target = next((dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None)
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if target.is_bound:
            raise WirelessError("Device is already bound")

        if master_mac is None:
            master_mac = next(
                (dev.master_mac for dev in snapshot.devices if dev.is_bound),
                None,
            )
            if not master_mac or set(master_mac.split(":")) == {"00"}:
                raise WirelessError(
                    "Unable to infer master MAC. Provide one with --master-mac (format aa:bb:cc:dd:ee:ff).",
                )

        if rx_type is None:
            used = {dev.rx_type for dev in snapshot.devices if dev.is_bound and dev.rx_type > 0}
            for candidate in range(1, 16):
                if candidate not in used:
                    rx_type = candidate
                    break
            else:
                raise WirelessError("No free RX type slots available")
        if not 0 < rx_type < 16:
            raise WirelessError("rx_type must be in range 1-15")

        channel = target.channel if target.channel else snapshot.devices[0].channel
        pwm_tuple = clamp_pwm_values(target.pwm_values)

        payload = bytearray(RF_PAYLOAD_SIZE)
        payload[0] = 0x12
        payload[1] = 0x10
        payload[2:8] = _mac_to_bytes(target.mac)
        payload[8:14] = _mac_to_bytes(master_mac)
        payload[14] = rx_type
        payload[15] = channel
        payload[16] = 1
        payload[17:21] = bytes(pwm_tuple)
        self._send_rf_data(channel, target.rx_type or 0, payload)
        time.sleep(0.1)
        refreshed = self.list_devices()
        updated = next((dev for dev in refreshed.devices if dev.mac.lower() == mac.lower()), None)
        logger.info(
            "Bind request sent for %s (channel=%s rx_type=%s master=%s)",
            mac,
            channel,
            rx_type,
            master_mac,
        )
        return updated or target

    def unbind_device(self, mac: str) -> WirelessDeviceInfo:
        snapshot = self.list_devices()
        target = next((dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None)
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError("Device is already unbound")

        channel = target.channel if target.channel else snapshot.devices[0].channel
        pwm_tuple = clamp_pwm_values(target.pwm_values)

        payload = bytearray(RF_PAYLOAD_SIZE)
        payload[0] = 0x12
        payload[1] = 0x10
        payload[2:8] = _mac_to_bytes(target.mac)
        payload[8:14] = bytes(6)
        payload[14] = 0
        payload[15] = channel
        payload[16] = 0
        payload[17:21] = bytes(pwm_tuple)
        self._send_rf_data(channel, target.rx_type, payload)
        time.sleep(0.1)
        refreshed = self.list_devices()
        updated = next((dev for dev in refreshed.devices if dev.mac.lower() == mac.lower()), None)
        logger.info("Unbind request sent for %s", mac)
        return updated or target

    def set_pwm_sync(self, mac: str, enable: bool, fallback_pwm: int = 100) -> None:
        snapshot = self.list_devices()
        target = next((dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None)
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError("Device is not bound")

        if enable:
            pwm_values = (6, 6, 6, 6)
        else:
            pwm_values = clamp_pwm_values([fallback_pwm] * 4)
        logger.debug(
            "Setting PWM sync for %s (mode=%s, fallback=%d)",
            mac,
            "enable" if enable else "disable",
            fallback_pwm,
        )
        self.set_pwm(mac, pwm_values)

    def _fetch_page(self, page_count: int) -> Tuple[int, bytes]:
        command = bytearray(64)
        command[0] = RF_GET_DEV_CMD
        command[1] = page_count & 0xFF
        self._receiver.write(command)
        total_len = RF_PAGE_STRIDE * page_count
        buffer = bytearray()
        request_size = 512
        while len(buffer) < total_len:
            try:
                chunk = self._receiver.read(request_size)
            except USBError as exc:
                message = str(exc).lower()
                if "overflow" in message and request_size < 2048:
                    request_size *= 2
                    continue
                raise
            if not chunk:
                break
            buffer.extend(chunk)
            if len(chunk) < request_size:
                break
        if not buffer:
            raise WirelessError("RF receiver returned no data")
        buffer = buffer[:total_len]
        if not buffer or buffer[0] != RF_GET_DEV_CMD:
            raise WirelessError(f"Unexpected RF response header 0x{buffer[0]:02x}")
        device_count = buffer[1]
        return device_count, bytes(buffer)

    def _parse_devices(self, count: int, payload: bytes) -> List[WirelessDeviceInfo]:
        devices: List[WirelessDeviceInfo] = []
        offset = 4
        for _ in range(count):
            if offset + 42 > len(payload):
                break
            record = payload[offset : offset + 42]
            if record[41] != 28:
                offset += 42
                continue
            mac = _bytes_to_mac(record[0:6])
            master_mac = _bytes_to_mac(record[6:12])
            channel = record[12]
            rx_type = record[13]
            dev_type = record[18]
            fan_num = record[19] if record[19] < 10 else record[19] - 10
            fan_pwm = tuple(record[36:40])
            fan_rpm = tuple(
                (record[28 + i * 2] << 8) | record[29 + i * 2]
                for i in range(4)
            )
            cmd_seq = record[40]
            devices.append(
                WirelessDeviceInfo(
                    mac=mac,
                    master_mac=master_mac,
                    channel=channel,
                    rx_type=rx_type,
                    device_type=dev_type,
                    fan_count=fan_num,
                    pwm_values=fan_pwm,
                    fan_rpm=fan_rpm,
                    command_sequence=cmd_seq,
                    raw=record,
                ),
            )
            offset += 42
        return devices

    def _send_rf_data(self, channel: int, rx: int, payload: bytes) -> None:
        if len(payload) != RF_PAYLOAD_SIZE:
            raise WirelessError(f"RF payload must be {RF_PAYLOAD_SIZE} bytes")
        chunk_index = 0
        sequence = 0
        while chunk_index < len(payload):
            chunk = payload[chunk_index : chunk_index + RF_CHUNK_SIZE]
            if len(chunk) < RF_CHUNK_SIZE:
                chunk = chunk + bytes(RF_CHUNK_SIZE - len(chunk))
            packet = bytearray(64)
            packet[0] = RF_PACKET_HEADER
            packet[1] = sequence & 0xFF
            packet[2] = channel & 0xFF
            packet[3] = rx & 0xFF
            packet[4 : 4 + RF_CHUNK_SIZE] = chunk
            self._sender.write(packet)
            chunk_index += RF_CHUNK_SIZE
            sequence = (sequence + 1) & 0xFF
            time.sleep(0.002)


def run_pwm_sync_loop(mac_addrs, *, enable: bool, fallback_pwm: int) -> None:
    macs = [m.lower() for m in mac_addrs]
    logger.info(
        "Starting PWM sync loop for %d device(s) (%s)",
        len(macs),
        "enable" if enable else f"disable fallback={fallback_pwm}",
    )
    try:
        while True:
            with WirelessTransceiver() as tx:
                snapshot = tx.list_devices()
                targets = [dev for dev in snapshot.devices if dev.mac.lower() in macs]
                if not targets:
                    logger.debug("PWM sync loop found no targets; sleeping")
                    time.sleep(1)
                    continue
                for dev in targets:
                    if enable:
                        tx.set_pwm_sync(dev.mac, enable=True)
                    else:
                        tx.set_pwm_sync(dev.mac, enable=False, fallback_pwm=fallback_pwm)
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("PWM sync loop interrupted by user")
        return


def _bytes_to_mac(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


def _mac_to_bytes(mac: str) -> bytes:
    parts = mac.split(":")
    if len(parts) != 6:
        raise WirelessError(f"Invalid MAC address '{mac}'")
    return bytes(int(part, 16) for part in parts)
