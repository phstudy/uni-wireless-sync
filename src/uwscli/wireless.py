"""2.4 GHz wireless fan controller helpers."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, cast

from . import tinyuz
from .tl_effects import TLEffectGenerator, TLEffects
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
LED_DATA_CHUNK = 220
FIRST_LED_PACKET_DATA_OFFSET = 34
FIRST_LED_PACKET_DATA_MAX = RF_PAYLOAD_SIZE - FIRST_LED_PACKET_DATA_OFFSET

_DEFAULT_DICT_SIZE = 4096


class WirelessError(RuntimeError):
    """Raised when an RF dongle interaction fails."""


@dataclass
class WirelessSnapshot:
    devices: List[WirelessDeviceInfo]
    raw: bytes

    def motherboard_pwm(self) -> Optional[int]:
        return _extract_motherboard_pwm(self.raw)


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

    def query_master_mac(
        self, *, channel: Optional[int] = None
    ) -> Optional[Tuple[str, Optional[int]]]:
        """Query the transmitter for the currently active master MAC."""

        request_channel = 8 if channel is None else channel & 0xFF
        payload = bytearray(64)
        payload[0] = 0x11
        payload[1] = request_channel
        try:
            self._sender.write(payload)
            response = self._sender.read(64)
        except USBError as exc:
            raise WirelessError(str(exc)) from exc
        if not response or response[0] != 0x11:
            logger.debug(
                "Unexpected master query response header: %s",
                response[0] if response else None,
            )
            return None
        master_mac = _bytes_to_mac(response[1:7])
        if set(master_mac.split(":")) == {"00"}:
            return None
        return master_mac, request_channel

    def set_pwm(
        self,
        mac: str,
        pwm_values: Sequence[int],
        *,
        sequence_index: int = 1,
    ) -> None:
        snapshot = self.list_devices()
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        self.set_pwm_direct(
            target, pwm_values, sequence_index=sequence_index, label=mac
        )

    def set_pwm_direct(
        self,
        target: WirelessDeviceInfo,
        pwm_values: Sequence[int],
        *,
        sequence_index: int = 1,
        label: Optional[str] = None,
    ) -> None:
        self._send_pwm_command(
            target, pwm_values, sequence_index=sequence_index, label=label
        )

    def _send_pwm_command(
        self,
        target: WirelessDeviceInfo,
        pwm_values: Sequence[int],
        *,
        sequence_index: int,
        label: Optional[str],
    ) -> None:
        if not target.is_bound:
            raise WirelessError(
                "Device is not bound to a master controller; cannot send PWM"
            )
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
            label or target.mac,
            target.channel,
            target.rx_type,
            pwm_tuple,
            sequence_index,
        )
        self._send_rf_data(target.channel, target.rx_type, payload)

    def set_led_static(
        self,
        mac: str,
        color: Optional[Tuple[int, int, int]],
        *,
        color_list: Optional[Sequence[Tuple[int, int, int]]] = None,
        broadcast: bool = False,
    ) -> None:
        snapshot = self.list_devices()
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError(
                "Device is not bound to a master controller; cannot send LED data"
            )
        led_count = _infer_led_count(target)
        if led_count <= 0:
            raise WirelessError("Unable to infer LED count for target device")
        if color_list:
            rgb = _expand_colors(color_list, led_count, target.fan_count)
        else:
            if color is None:
                raise WirelessError(
                    "Color must be provided when color_list is not supplied"
                )
            rgb = _expand_colors([color], led_count, target.fan_count)
        self._transmit_led_effect(
            target,
            snapshot,
            rgb,
            led_count=led_count,
            total_frames=1,
            dict_size=_DEFAULT_DICT_SIZE,
            broadcast=broadcast,
            interval_ms=None,
        )

    def set_led_rainbow(
        self,
        mac: str,
        *,
        frames: int = 24,
        interval_ms: int = 50,
        broadcast: bool = False,
    ) -> None:
        snapshot = self.list_devices()
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError(
                "Device is not bound to a master controller; cannot send LED data"
            )
        led_count = _infer_led_count(target)
        if led_count <= 0:
            raise WirelessError("Unable to infer LED count for target device")
        data = tinyuz.generate_rainbow_frames(led_count, frame_count=frames)
        self._transmit_led_effect(
            target,
            snapshot,
            data,
            led_count=led_count,
            total_frames=frames,
            dict_size=_DEFAULT_DICT_SIZE,
            broadcast=broadcast,
            interval_ms=interval_ms,
        )

    def set_led_effect(
        self,
        mac: str,
        effect: TLEffects,
        *,
        tb: Optional[int] = 0,
        brightness: int = 255,
        direction: int = 1,
        interval_ms: Optional[int] = 50,
        broadcast: bool = False,
    ) -> None:
        snapshot = self.list_devices()
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError(
                "Device is not bound to a master controller; cannot send LED data"
            )

        generator = TLEffectGenerator()
        fan_slots = target.fan_count if target.fan_count > 0 else 0
        if fan_slots <= 0:
            hint_leds = _infer_led_count(target)
            fan_slots = max(1, hint_leds // TLEffectGenerator.LEDS_PER_FAN)
        fan_slots = max(1, min(4, fan_slots))

        brightness = max(0, min(255, int(brightness)))
        direction = 0 if direction < 0 else (1 if direction > 1 else int(direction))

        if tb is None:
            front_frames = generator.generate(
                effect, 0, fan_slots, brightness, direction
            )
            back_frames = generator.generate(
                effect, 1, fan_slots, brightness, direction
            )
            frames = self._merge_half_frames(front_frames, back_frames)
        else:
            frames = generator.generate(effect, tb, fan_slots, brightness, direction)
        if not frames:
            raise WirelessError("Generated TL effect produced no frames")

        leds_per_frame = len(frames[0][0])
        hint_leds = _infer_led_count(target)
        if leds_per_frame != hint_leds:
            logger.debug(
                "Generated TL effect length %s differs from inferred LED count %s for %s",
                leds_per_frame,
                hint_leds,
                mac,
            )

        buffer = bytearray()
        for frame in frames:
            if len(frame[0]) != leds_per_frame:
                raise WirelessError("Inconsistent frame lengths in TL effect output")
            for led in range(leds_per_frame):
                buffer.extend((frame[0][led], frame[1][led], frame[2][led]))

        interval = None if interval_ms is None else max(1, int(interval_ms))
        self._transmit_led_effect(
            target,
            snapshot,
            bytes(buffer),
            led_count=leds_per_frame,
            total_frames=len(frames),
            dict_size=_DEFAULT_DICT_SIZE,
            broadcast=broadcast,
            interval_ms=interval,
        )

    def set_led_frames(
        self,
        mac: str,
        frames: Sequence[Sequence[Tuple[int, int, int]]],
        *,
        interval_ms: int = 50,
        broadcast: bool = False,
    ) -> None:
        if not frames:
            raise WirelessError("Frames sequence cannot be empty")
        snapshot = self.list_devices()
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError(
                "Device is not bound to a master controller; cannot send LED data"
            )
        led_count = _infer_led_count(target)
        if led_count <= 0:
            raise WirelessError("Unable to infer LED count for target device")
        buffer = bytearray()
        for frame in frames:
            frame_bytes = _expand_colors(frame, led_count, target.fan_count)
            buffer.extend(frame_bytes)
        self._transmit_led_effect(
            target,
            snapshot,
            bytes(buffer),
            led_count=led_count,
            total_frames=len(frames),
            dict_size=_DEFAULT_DICT_SIZE,
            broadcast=broadcast,
            interval_ms=interval_ms,
        )

    def _transmit_led_effect(
        self,
        target: WirelessDeviceInfo,
        snapshot: WirelessSnapshot,
        raw_rgb: bytes,
        *,
        led_count: int,
        total_frames: int,
        dict_size: int,
        broadcast: bool,
        interval_ms: Optional[int],
    ) -> None:
        if led_count <= 0:
            raise WirelessError("LED count must be positive")
        if total_frames <= 0:
            raise WirelessError("Frame count must be positive")
        expected_len = led_count * total_frames * 3
        if len(raw_rgb) != expected_len:
            raise WirelessError(
                f"LED data length mismatch (expected {expected_len} bytes, got {len(raw_rgb)})",
            )

        if FIRST_LED_PACKET_DATA_MAX <= 0:
            raise WirelessError(
                "Invalid LED packet configuration (no space for payload data)"
            )

        compressed = tinyuz.compress_led_payload(raw_rgb, dict_size=dict_size)
        compressed_len = len(compressed)
        if not compressed_len:
            raise WirelessError("LED payload is empty after compression")
        data_packets = math.ceil(compressed_len / LED_DATA_CHUNK)
        total_packets = 1 + data_packets
        if total_packets > 255:
            raise WirelessError("LED payload is too large to transmit")

        mac_bytes = b"\xff" * 6 if broadcast else _mac_to_bytes(target.mac)
        master_mac = _mac_to_bytes(target.master_mac)
        effect_index = _generate_effect_index()
        channel = target.channel if target.channel else snapshot.devices[0].channel
        send_interval = interval_ms if interval_ms is not None else 50
        if send_interval < 0:
            send_interval = 0

        logger.info(
            "Transmitting LED effect to %s (leds=%d frames=%d packets=%d)",
            target.mac,
            led_count,
            total_frames,
            total_packets,
        )

        data_offset = 0
        for packet_index in range(total_packets):
            payload = bytearray(RF_PAYLOAD_SIZE)
            payload[0] = 0x12
            payload[1] = 0x20
            payload[2:8] = mac_bytes
            payload[8:14] = master_mac
            payload[14:18] = effect_index
            payload[18] = packet_index & 0xFF
            payload[19] = total_packets & 0xFF

            if packet_index == 0:
                data_len = len(compressed)
                payload[20] = (data_len >> 24) & 0xFF
                payload[21] = (data_len >> 16) & 0xFF
                payload[22] = (data_len >> 8) & 0xFF
                payload[23] = data_len & 0xFF
                payload[24] = 0
                payload[25] = (total_frames >> 8) & 0xFF
                payload[26] = total_frames & 0xFF
                payload[27] = led_count & 0xFF
                payload[32] = (send_interval >> 8) & 0xFF
                payload[33] = send_interval & 0xFF
                payload[34] = 0
                payload[35] = 0
                payload[36] = 0
                payload[37] = 0
                payload[38] = 0
                payload[39] = 0
                first_chunk_len = min(
                    FIRST_LED_PACKET_DATA_MAX, compressed_len - data_offset
                )
                if first_chunk_len:
                    chunk = compressed[data_offset : data_offset + first_chunk_len]
                    start = FIRST_LED_PACKET_DATA_OFFSET
                    payload[start : start + first_chunk_len] = chunk
                    data_offset += first_chunk_len
            else:
                chunk_len = min(LED_DATA_CHUNK, compressed_len - data_offset)
                if chunk_len:
                    chunk = compressed[data_offset : data_offset + chunk_len]
                    payload[20 : 20 + chunk_len] = chunk
                    data_offset += chunk_len

            self._send_rf_data(channel, target.rx_type, payload)
            if packet_index == 0:
                for _ in range(3):
                    time.sleep(0.02)
                    self._send_rf_data(channel, target.rx_type, payload)
            if packet_index < total_packets - 1:
                time.sleep(0.01)

    @staticmethod
    def _merge_half_frames(
        front: Sequence[Sequence[Sequence[int]]],
        back: Sequence[Sequence[Sequence[int]]],
    ) -> List[List[List[int]]]:
        if not front and not back:
            return []
        if not front:
            return [[list(channel) for channel in frame] for frame in back]
        if not back:
            return [[list(channel) for channel in frame] for frame in front]
        total = max(len(front), len(back))
        merged: List[List[List[int]]] = []
        for index in range(total):
            frame_front = front[index % len(front)]
            frame_back = back[index % len(back)]
            combined = [
                list(frame_front[0]),
                list(frame_front[1]),
                list(frame_front[2]),
            ]
            led_count = len(frame_back[0])
            for led in range(led_count):
                r = frame_back[0][led]
                g = frame_back[1][led]
                b = frame_back[2][led]
                if r or g or b:
                    combined[0][led] = r
                    combined[1][led] = g
                    combined[2][led] = b
            merged.append(combined)
        return merged

    def bind_device(
        self,
        mac: str,
        *,
        master_mac: Optional[str] = None,
        rx_type: Optional[int] = None,
    ) -> WirelessDeviceInfo:
        snapshot = self.list_devices()
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
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
            used = {
                dev.rx_type
                for dev in snapshot.devices
                if dev.is_bound and dev.rx_type > 0
            }
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
        updated = next(
            (dev for dev in refreshed.devices if dev.mac.lower() == mac.lower()), None
        )
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
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
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
        updated = next(
            (dev for dev in refreshed.devices if dev.mac.lower() == mac.lower()), None
        )
        logger.info("Unbind request sent for %s", mac)
        return updated or target

    def set_pwm_sync(self, mac: str, enable: bool, fallback_pwm: int = 100) -> None:
        snapshot = self.list_devices()
        target = next(
            (dev for dev in snapshot.devices if dev.mac.lower() == mac.lower()), None
        )
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
                (record[28 + i * 2] << 8) | record[29 + i * 2] for i in range(4)
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
                    pwm_values=cast(Tuple[int, int, int, int], fan_pwm),
                    fan_rpm=cast(Tuple[int, int, int, int], fan_rpm),
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


def run_pwm_sync_loop(
    mac_addrs,
    *,
    interval: float = 1.0,
    max_cycles: Optional[int] = None,
    stop_after_first_send: bool = False,
) -> None:
    macs = [m.lower() for m in mac_addrs]
    if not macs:
        logger.info("No targets provided to PWM sync loop; nothing to do")
        return
    interval = max(interval, 0.1)
    logger.info(
        "Starting motherboard PWM sync loop for %d device(s) (interval=%.2fs)",
        len(macs),
        interval,
    )
    last_sent: Dict[str, int] = {}
    current_pwm: Optional[int] = None
    missing_logged = False
    cycles = 0
    any_sent = False
    try:
        while True:
            try:
                with WirelessTransceiver() as tx:
                    snapshot = tx.list_devices()
                    pwm = snapshot.motherboard_pwm()
                    pwm_values: Optional[List[int]] = None
                    if pwm is None:
                        if current_pwm is None:
                            if not missing_logged:
                                logger.debug(
                                    "No motherboard PWM value detected; nothing to sync this cycle"
                                )
                                missing_logged = True
                        else:
                            pwm = current_pwm
                            pwm_values = [pwm] * 4
                            if not missing_logged:
                                logger.debug(
                                    "No new motherboard PWM value detected; reusing previous value %d",
                                    pwm,
                                )
                                missing_logged = True
                    else:
                        logger.debug(
                            "Extracted motherboard PWM raw=%s computed=%d",
                            _format_pwm_debug(snapshot.raw),
                            pwm,
                        )
                        current_pwm = pwm
                        pwm_values = [pwm] * 4
                        missing_logged = False
                    if pwm_values is not None:
                        pwm_int = pwm if pwm is not None else current_pwm
                        if pwm_int is None:
                            continue
                        available = {
                            dev.mac.lower(): dev
                            for dev in snapshot.devices
                            if dev.is_bound
                        }
                        for mac in macs:
                            target = available.get(mac)
                            if target is None:
                                logger.debug(
                                    "Target %s not bound or missing from snapshot", mac
                                )
                                continue
                            if last_sent.get(mac) == pwm_int:
                                continue
                            sequence_index = (target.command_sequence + 1) & 0xFF
                            try:
                                tx.set_pwm_direct(
                                    target,
                                    pwm_values,
                                    sequence_index=sequence_index,
                                )
                            except WirelessError as exc:
                                logger.warning(
                                    "Failed to send PWM to %s: %s", target.mac, exc
                                )
                                continue
                            last_sent[mac] = pwm_int
                            any_sent = True
                cycles += 1
            except WirelessError as exc:
                logger.warning("PWM sync iteration failed: %s", exc)
            if stop_after_first_send and any_sent:
                break
            if max_cycles is not None and cycles >= max_cycles:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("PWM sync loop interrupted by user")
        return


def _extract_motherboard_pwm(raw: bytes) -> Optional[int]:
    if not raw or len(raw) < 4:
        return None
    indicator = raw[2]
    value = raw[3]
    if indicator >> 7:
        return None
    denominator = (indicator & 0x7F) + value
    if denominator == 0:
        return None
    pwm = int(255.0 * (value / denominator))
    if pwm < 0:
        return 0
    if pwm > 255:
        return 255
    return pwm


def _format_pwm_debug(raw: bytes) -> str:
    if len(raw) < 4:
        return "N/A"
    return f"{raw[2]:02x}:{raw[3]:02x}"


def _bytes_to_mac(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


def _mac_to_bytes(mac: str) -> bytes:
    parts = mac.split(":")
    if len(parts) != 6:
        raise WirelessError(f"Invalid MAC address '{mac}'")
    return bytes(int(part, 16) for part in parts)


def _generate_effect_index() -> bytes:
    value = int(time.time() * 1000) & 0xFFFFFFFF
    return bytes(
        (
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ),
    )


def _infer_led_count(device: WirelessDeviceInfo) -> int:
    mapping = {
        1: 116,
        2: 132,
        3: 174,
        4: 88,
        65: 96,
    }
    if device.device_type in mapping:
        led_count = mapping[device.device_type]
    elif device.device_type == 10:
        led_count = 24 + max(device.fan_count, 0) * 24
    elif device.fan_count > 0:
        led_count = device.fan_count * 26
    else:
        led_count = 60

    hint = _extract_led_count_hint(device.raw)
    if hint and hint != led_count:
        if led_count == 60 or device.fan_count == 0:
            logger.debug(
                "Adopting LED count hint %s for device %s (prev=%s)",
                hint,
                device.mac,
                led_count,
            )
            led_count = hint
        else:
            logger.debug(
                "LED count hint %s for device %s differs from heuristic %s",
                hint,
                device.mac,
                led_count,
            )

    return led_count


def _expand_colors(
    colors: Sequence[Tuple[int, int, int]],
    led_count: int,
    fan_count: int,
) -> bytes:
    if not colors:
        raise WirelessError("Color list cannot be empty")

    def to_bytes(color: Tuple[int, int, int]) -> bytes:
        for component in color:
            if not 0 <= component <= 255:
                raise WirelessError("Color values must be between 0 and 255")
        return bytes(color)

    if len(colors) == led_count:
        return b"".join(to_bytes(color) for color in colors)
    if len(colors) == 1:
        return to_bytes(colors[0]) * led_count
    if fan_count > 0 and led_count % fan_count == 0 and len(colors) == fan_count:
        leds_per_fan = led_count // fan_count
        return b"".join(to_bytes(color) * leds_per_fan for color in colors)
    raise WirelessError(
        "Color list length must match LED count or fan count (with evenly divisible LEDs).",
    )


def _extract_led_count_hint(raw: bytes) -> Optional[int]:
    if not raw or len(raw) < 32:
        return None
    hint = raw[31]
    if hint == 0:
        return None
    return hint
