"""2.4 GHz wireless fan controller helpers."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing_extensions import Self


from . import tinyuz, tl_merge
from .structs import WirelessDeviceInfo, clamp_pwm_values
from .system_usb import find_devices_by_vid_pid
from .tl_effects import (
    DEFAULT_SPEED,
    EFFECT_DEFAULT_COLOURS,
    TLEffectGenerator,
    TLEffects,
    effect_interval,
    flip_sides,
    merge_sides,
)
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
LED_MAX_COMPRESSED = 12288  # the vendor app refuses larger effects
LED_APPLY_ATTEMPTS = 5
LED_PACKET_COPIES = (1, 3, 4, 4, 5)  # copies of each data packet per attempt
LED_APPLY_WAIT = 3.0  # seconds to wait for the device to report the new effect

# Second byte of an RF payload (the first is 0x12).
RF_CMD_BIND_PWM = 0x10
RF_CMD_IDENTIFY = 0x12
RF_CMD_SAVE_CONFIG = 0x15
RF_CMD_REBOOT_LCD = 0x16
RF_CMD_LED_EFFECT = 0x20

MASTER_DEVICE_TYPE = 0xFF
DEFAULT_MASTER_CHANNEL = 8
# Channels the vendor app offers (it accepts only odd ones; 8 is its automatic default).
CHANNELS = (1, 7, 11, 15, 17, 21, 25, 29, 31, 33, 35, 39)
MAX_RX_TYPE = 13
COMMAND_RETRIES = 10  # the vendor app repeats a sequenced command up to 10 times
BROADCAST_MAC = b"\xff" * 6

_DEFAULT_DICT_SIZE = 4096


class WirelessError(RuntimeError):
    """Raised when an RF dongle interaction fails."""


@dataclass
class WirelessSnapshot:
    devices: list[WirelessDeviceInfo]
    raw: bytes
    masters: list[WirelessDeviceInfo] = field(default_factory=list)

    def motherboard_pwm(self) -> int | None:
        return _extract_motherboard_pwm(self.raw)

    def receiver_version(self) -> int | None:
        """Firmware version of the RF receiver, when the header carries it instead of PWM."""
        if len(self.raw) < 4 or not self.raw[2] >> 7:
            return None
        return ((self.raw[2] & 0x7F) << 8) | self.raw[3]

    def find(self, mac: str) -> WirelessDeviceInfo | None:
        return next((d for d in self.devices if d.mac.lower() == mac.lower()), None)


@dataclass(frozen=True)
class EffectJob:
    """One device's LED effect: raw RGB per LED, frame by frame."""

    target: WirelessDeviceInfo
    raw_rgb: bytes
    led_count: int
    total_frames: int
    interval_ms: float | None


@dataclass(frozen=True)
class LocalMaster:
    """The master controller (RF sender) attached to this computer."""

    mac: str
    channel: int


def bound_to(
    snapshot: WirelessSnapshot, master: LocalMaster
) -> list[WirelessDeviceInfo]:
    """Devices bound to this master, in list order (the vendor app numbers them 1, 2, ...)."""
    return [d for d in snapshot.devices if d.master_mac.lower() == master.mac.lower()]


def master_of(target: WirelessDeviceInfo) -> LocalMaster:
    """The master a device is bound to. Devices check only the master MAC in a packet, so
    the attached controller can drive devices bound to any master."""
    return LocalMaster(mac=target.master_mac, channel=target.channel)


def ordinal_of(snapshot: WirelessSnapshot, master: LocalMaster, mac: str) -> int:
    bound = bound_to(snapshot, master)
    for index, dev in enumerate(bound, start=1):
        if dev.mac.lower() == mac.lower():
            return index
    return len(bound) + 1


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

        self._local_master: LocalMaster | None = None
        logger.debug("Opened wireless transceiver (timeout=%sms)", timeout_ms)

    def close(self) -> None:
        self._sender.close()
        self._receiver.close()
        logger.debug("Closed wireless transceiver")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def list_devices(self) -> WirelessSnapshot:
        return _list_devices(self._receiver)

    def local_master(self, snapshot: WirelessSnapshot | None = None) -> LocalMaster:
        """MAC of the attached master and the channel it uses (its own list record)."""
        if self._local_master is not None:
            return self._local_master
        snapshot = snapshot or self.list_devices()
        query_channel = DEFAULT_MASTER_CHANNEL
        if len(snapshot.masters) == 1 and snapshot.masters[0].channel:
            query_channel = snapshot.masters[0].channel
        found = self.query_master_mac(channel=query_channel)
        if not found:
            raise WirelessError(
                "The wireless controller did not report its MAC address"
            )
        mac = found[0]
        record = next(
            (m for m in snapshot.masters if m.mac.lower() == mac.lower()), None
        )
        channel = record.channel if record and record.channel else query_channel
        self._local_master = LocalMaster(mac=mac, channel=channel)
        return self._local_master

    def _bound_target(self, snapshot: WirelessSnapshot, mac: str) -> WirelessDeviceInfo:
        target = snapshot.find(mac)
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        if not target.is_bound:
            raise WirelessError(f"Device {mac} is not bound to a master controller")
        return target

    def _local_master_mac(self) -> str | None:
        """The attached master's MAC, or None (logged) if it does not answer the query.

        Used after a command already worked: a failed query must not turn that into an error.
        """
        try:
            return self.local_master().mac.lower()
        except WirelessError as exc:
            logger.warning("Could not read the attached master's MAC: %s", exc)
            return None

    def _save_if_local(self, target: WirelessDeviceInfo) -> None:
        """Ask the attached master to save its configuration when it owns the device."""
        local = self._local_master_mac()
        if local is None:
            logger.warning(
                "Configuration not saved; the device keeps the change until power off"
            )
        elif target.master_mac.lower() == local:
            self.save_config()

    def query_master_mac(
        self, *, channel: int | None = None
    ) -> tuple[str, int | None] | None:
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
        sequence_index: int | None = None,
    ) -> None:
        snapshot = self.list_devices()
        target = self._bound_target(snapshot, mac)
        self.set_pwm_direct(
            target,
            pwm_values,
            sequence_index=sequence_index,
            label=mac,
            snapshot=snapshot,
        )

    def set_pwm_direct(
        self,
        target: WirelessDeviceInfo,
        pwm_values: Sequence[int],
        *,
        sequence_index: int | None = None,
        label: str | None = None,
        snapshot: WirelessSnapshot | None = None,
    ) -> None:
        """Send the bind/PWM packet; sequence_index defaults to the vendor's device number."""
        if not target.is_bound:
            raise WirelessError(
                "Device is not bound to a master controller; cannot send PWM"
            )
        master = master_of(target)
        if sequence_index is None:
            sequence_index = ordinal_of(
                snapshot or self.list_devices(), master, target.mac
            )
        payload = _rf_payload(RF_CMD_BIND_PWM, target.mac, master.mac)
        payload[14] = target.rx_type
        payload[15] = master.channel
        payload[16] = sequence_index & 0xFF
        pwm_tuple = clamp_pwm_values(pwm_values)
        payload[17:21] = bytes(pwm_tuple)
        logger.info(
            "Sending PWM command to %s (channel=%s rx=%s): %s index=%d",
            label or target.mac,
            target.channel,
            target.rx_type,
            pwm_tuple,
            sequence_index,
        )
        self._send_rf_data(target.channel, target.rx_type, payload)

    def _led_target(self, mac: str) -> tuple[WirelessSnapshot, WirelessDeviceInfo]:
        snapshot = self.list_devices()
        return snapshot, self._bound_target(snapshot, mac)

    def set_led_static(
        self,
        mac: str,
        color: tuple[int, int, int] | None,
        *,
        color_list: Sequence[tuple[int, int, int]] | None = None,
    ) -> None:
        snapshot, target = self._led_target(mac)
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
            interval_ms=None,
        )

    def set_led_rainbow(
        self,
        mac: str,
        *,
        frames: int = 24,
        interval_ms: int = 50,
    ) -> None:
        snapshot, target = self._led_target(mac)
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
            interval_ms=interval_ms,
        )

    def set_led_effect(
        self,
        mac: str,
        effect: TLEffects,
        *,
        tb: int | None = 0,
        brightness: int = 255,
        direction: int = 0,
        interval_ms: int | None = None,
        speed: int = DEFAULT_SPEED,
        colours: list[list[int]] | None = None,
        flip: bool = False,
    ) -> None:
        """Render a TL effect as the app does. interval_ms defaults to the app's interval
        for the speed level (1-5); colours are the effect's colours (default: the app's).
        """
        _, target = self._led_target(mac)
        job = self._effect_job(
            target,
            effect,
            tb=tb,
            brightness=brightness,
            direction=direction,
            interval_ms=interval_ms,
            speed=speed,
            colours=colours,
            flip=flip,
        )
        self._transmit_led_effects([job])

    def _effect_job(
        self,
        target: WirelessDeviceInfo,
        effect: TLEffects,
        *,
        tb: int | None,
        brightness: int,
        direction: int,
        interval_ms: int | None,
        speed: int,
        colours: list[list[int]] | None,
        flip: bool,
    ) -> EffectJob:
        try:
            generator = TLEffectGenerator(colours)
            interval = interval_ms or effect_interval(effect, speed)
        except ValueError as exc:
            raise WirelessError(str(exc)) from exc
        fan_slots = max(0, target.fan_count)
        if fan_slots <= 0:
            fan_slots = max(
                1, _infer_led_count(target) // TLEffectGenerator.LEDS_PER_FAN
            )
        fan_slots = max(1, min(4, fan_slots))
        brightness = max(0, min(255, int(brightness)))
        direction = 0 if direction < 0 else (1 if direction > 1 else int(direction))
        try:
            if tb is None:
                frames = merge_sides(
                    generator.generate(effect, 0, fan_slots, brightness, direction),
                    generator.generate(effect, 1, fan_slots, brightness, direction),
                    interval,
                )
            else:
                frames = generator.generate(
                    effect, tb, fan_slots, brightness, direction
                )
        except ValueError as exc:
            raise WirelessError(str(exc)) from exc
        if not frames:
            raise WirelessError("Generated TL effect produced no frames")
        if flip:
            frames = flip_sides(frames)
        leds = len(frames[0][0])
        buffer = bytearray()
        for frame in frames:
            if len(frame[0]) != leds:
                raise WirelessError("Inconsistent frame lengths in TL effect output")
            for led in range(leds):
                buffer.extend((frame[0][led], frame[1][led], frame[2][led]))
        return EffectJob(target, bytes(buffer), leds, len(frames), interval)

    def set_led_merge(
        self,
        effect: TLEffects,
        order: list[str],
        *,
        reversed_macs: Sequence[str] = (),
        brightness: int = 255,
        direction: int = 0,
        speed: int = DEFAULT_SPEED,
        colours: list[list[int]] | None = None,
        interval_ms: int | None = None,
    ) -> list[str]:
        """Run one effect across fan groups in `order`, as the vendor app's merge mode.
        Rainbow morph and twinkle are not merged by the app: each group runs them alone.
        Returns the MACs in order."""
        if not order:
            raise WirelessError("No fan groups to merge")
        if effect in tl_merge.PER_GROUP_EFFECTS:
            snapshot = self.list_devices()
            targets = [self._bound_target(snapshot, mac) for mac in order]
            jobs = [
                self._effect_job(
                    target,
                    effect,
                    tb=None,
                    brightness=brightness,
                    direction=direction,
                    interval_ms=interval_ms,
                    speed=speed,
                    colours=colours,
                    flip=False,
                )
                for target in targets
            ]
            self._transmit_led_effects(jobs, shared_index=True)
            return [t.mac for t in targets]
        if effect not in tl_merge.MERGE_EFFECTS:
            names = ", ".join(
                e.name.lower()
                for e in (*tl_merge.MERGE_EFFECTS, *tl_merge.PER_GROUP_EFFECTS)
            )
            raise WirelessError(
                f"{effect.name.lower()} cannot be merged; choose one of {names}"
            )
        snapshot = self.list_devices()
        targets = [self._bound_target(snapshot, mac) for mac in order]
        fans = [max(1, min(4, t.fan_count)) for t in targets]
        reversed_set = {m.lower() for m in reversed_macs}
        try:
            interval = interval_ms or tl_merge.merge_interval(speed)
        except ValueError as exc:
            raise WirelessError(str(exc)) from exc
        chosen = EFFECT_DEFAULT_COLOURS[effect] if colours is None else colours
        frames = tl_merge.merge_frames(
            effect,
            fans,
            bright=max(0, min(255, int(brightness))),
            direction=direction,
            colours=chosen,
            reversed_groups=[t.mac.lower() in reversed_set for t in targets],
        )
        jobs = []
        for target, count, group in zip(targets, fans, frames):
            leds = count * TLEffectGenerator.LEDS_PER_FAN
            raw = bytes(
                frame[c][led]
                for frame in group
                for led in range(leds)
                for c in range(3)
            )
            jobs.append(EffectJob(target, raw, leds, len(group), interval))
        self._transmit_led_effects(jobs, shared_index=True)
        return [t.mac for t in targets]

    def set_led_frames(
        self,
        mac: str,
        frames: Sequence[Sequence[tuple[int, int, int]]],
        *,
        interval_ms: int = 50,
    ) -> None:
        if not frames:
            raise WirelessError("Frames sequence cannot be empty")
        snapshot, target = self._led_target(mac)
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
        interval_ms: float | None,
    ) -> None:
        """Send an LED effect as the vendor app does, then wait until the device runs it.

        Packet 0 is a header only (sent 4 times); data follows in 220-byte packets.
        The device reports the running effect's index in its list record; the effect
        is resent until it does, then the master is told to save its configuration.
        """
        self._transmit_led_effects(
            [EffectJob(target, raw_rgb, led_count, total_frames, interval_ms)]
        )

    def _transmit_led_effects(
        self, jobs: list[EffectJob], *, shared_index: bool = False
    ) -> None:
        """Send effects to several devices: all of them first, then resend to those that
        have not reported theirs (so merged effects start close together). With
        shared_index every device gets the same effect index."""
        prepared: list[tuple[WirelessDeviceInfo, bytes, list[bytes]]] = []
        index = _generate_effect_index(
            avoid=jobs[0].target.effect_index if jobs else b""
        )
        for job in jobs:
            job_index, packets = self._effect_packets(
                job, index if shared_index else None
            )
            prepared.append((job.target, job_index, packets))
        pending = list(prepared)
        for attempt in range(1, LED_APPLY_ATTEMPTS + 1):
            # Some receivers lose many packets; later attempts send each data packet several
            # times (the device keeps one copy of each packet number).
            copies = LED_PACKET_COPIES[attempt - 1]
            for target, _, packets in pending:
                for number, packet in enumerate(packets):
                    for _ in range(copies if number else 1):
                        self._send_rf_data(target.channel, target.rx_type, packet)
                    if number == 0:
                        for _ in range(3):
                            time.sleep(0.02)
                            self._send_rf_data(target.channel, target.rx_type, packet)
            pending = self._wait_for_effects(pending)
            if not pending:
                break
            for target, _, _ in pending:
                logger.info(
                    "Effect not reported by %s yet (attempt %d)", target.mac, attempt
                )
        done = [entry[0] for entry in prepared if entry not in pending]
        local = self._local_master_mac() if done or pending else None
        if done and local is None:
            logger.warning("Configuration not saved; the effect stays until power off")
        elif any(t.master_mac.lower() == local for t in done):
            time.sleep(0.01)
            self.save_config()
        if pending:
            failed = [target for target, _, _ in pending]
            hint = ""
            if local is not None and any(t.master_mac.lower() != local for t in failed):
                hint = (
                    "; some are bound to another controller than the attached one "
                    f"({local}), and longer effects rarely reach such "
                    "devices. Rebinding them (fan unbind, then fan bind) fixes that"
                )
            names = ", ".join(t.mac for t in failed)
            raise WirelessError(
                f"{names} did not take the LED effect after {LED_APPLY_ATTEMPTS} attempts{hint}"
            )

    def _effect_packets(
        self, job: EffectJob, effect_index: bytes | None
    ) -> tuple[bytes, list[bytes]]:
        if job.led_count <= 0:
            raise WirelessError("LED count must be positive")
        if job.total_frames <= 0:
            raise WirelessError("Frame count must be positive")
        expected_len = job.led_count * job.total_frames * 3
        if len(job.raw_rgb) != expected_len:
            raise WirelessError(
                f"LED data length mismatch (expected {expected_len} bytes, got {len(job.raw_rgb)})",
            )
        compressed = tinyuz.compress_led_payload(job.raw_rgb)
        if len(compressed) > LED_MAX_COMPRESSED:
            raise WirelessError(
                f"LED effect too large after compression ({len(compressed)} > {LED_MAX_COMPRESSED} bytes); "
                "use fewer frames"
            )
        index = effect_index or _generate_effect_index(avoid=job.target.effect_index)
        packets = build_led_packets(
            job.target.mac,
            master_of(job.target).mac,
            index,
            compressed,
            led_count=job.led_count,
            total_frames=job.total_frames,
            interval_ms=50 if job.interval_ms is None else job.interval_ms,
        )
        logger.info(
            "Transmitting LED effect to %s (leds=%d frames=%d compressed=%d packets=%d)",
            job.target.mac,
            job.led_count,
            job.total_frames,
            len(compressed),
            len(packets),
        )
        return index, packets

    def _wait_for_effects(
        self, pending: list[tuple[WirelessDeviceInfo, bytes, list[bytes]]]
    ) -> list[tuple[WirelessDeviceInfo, bytes, list[bytes]]]:
        """Poll the list until every device reports its effect index or time runs out;
        returns the ones that did not."""
        remaining = list(pending)
        deadline = time.monotonic() + LED_APPLY_WAIT
        while remaining and time.monotonic() < deadline:
            time.sleep(0.2)
            snapshot = self.list_devices()
            remaining = [
                entry
                for entry in remaining
                if not (
                    (current := snapshot.find(entry[0].mac)) is not None
                    and current.effect_index == entry[1]
                )
            ]
        return remaining

    def save_config(self) -> None:
        """Ask the master to store its configuration (bindings, effects)."""
        master = self.local_master()
        payload = _rf_payload(RF_CMD_SAVE_CONFIG, None, master.mac)
        payload[2:8] = BROADCAST_MAC
        payload[14] = 0xFF
        self._send_rf_data(master.channel, 0xFF, payload)

    def bind_device(
        self,
        mac: str,
        *,
        master_mac: str | None = None,
        rx_type: int | None = None,
    ) -> WirelessDeviceInfo:
        """Bind a device to this master: the vendor bind/PWM packet with the new master's MAC."""
        snapshot = self.list_devices()
        target = snapshot.find(mac)
        if target is None:
            raise WirelessError(f"Device with MAC {mac} not found")
        master = self.local_master(snapshot)
        if target.master_mac.lower() == master.mac.lower():
            raise WirelessError("Device is already bound to this master")
        if target.is_bound:
            raise WirelessError(
                f"Device is bound to another master ({target.master_mac}); unbind it there first"
            )
        if master_mac is not None and master_mac.lower() != master.mac.lower():
            raise WirelessError(
                f"--master-mac {master_mac} is not the attached master ({master.mac})"
            )
        bound = bound_to(snapshot, master)
        if rx_type is None:
            used = {dev.rx_type for dev in bound}
            rx_type = next(
                (c for c in range(1, MAX_RX_TYPE + 1) if c not in used), None
            )
            if rx_type is None:
                raise WirelessError("No free RX type slots available")
        if not 1 <= rx_type <= MAX_RX_TYPE:
            raise WirelessError(f"rx_type must be in range 1-{MAX_RX_TYPE}")

        payload = _rf_payload(RF_CMD_BIND_PWM, target.mac, master.mac)
        payload[14] = rx_type
        payload[15] = master.channel
        payload[16] = len(bound) + 1
        payload[17:21] = bytes(_kept_pwm(target))
        refreshed = self._send_until(
            target,
            payload,
            lambda d: d.master_mac.lower() == master.mac.lower(),
            # An unbound device lists the channel it listens on; 0 (unknown) falls back
            # to the master's.
            channel=target.channel or master.channel,
        )
        logger.info(
            "Bind request sent for %s (channel=%s rx_type=%s master=%s)",
            mac,
            master.channel,
            rx_type,
            master.mac,
        )
        if refreshed is not None and refreshed.master_mac.lower() == master.mac.lower():
            self.save_config()
        return refreshed or target

    def unbind_device(self, mac: str) -> WirelessDeviceInfo:
        snapshot = self.list_devices()
        target = self._bound_target(snapshot, mac)
        master = master_of(target)
        payload = _rf_payload(RF_CMD_BIND_PWM, target.mac, None)
        payload[14] = 0
        payload[15] = master.channel
        payload[16] = 0
        payload[17:21] = bytes(_kept_pwm(target))
        refreshed = self._send_until(target, payload, lambda d: not d.is_bound)
        logger.info("Unbind request sent for %s", mac)
        if refreshed is not None and not refreshed.is_bound:
            self._save_if_local(target)
        return refreshed or target

    def _send_until(
        self,
        target: WirelessDeviceInfo,
        payload: bytearray,
        done: Callable[[WirelessDeviceInfo], bool],
        channel: int | None = None,
    ) -> WirelessDeviceInfo | None:
        """Send a packet until the device list shows it took effect (at most COMMAND_RETRIES
        times; packets to some devices get lost). Returns the device's last record."""
        current: WirelessDeviceInfo | None = None
        for _ in range(COMMAND_RETRIES):
            self._send_rf_data(
                target.channel if channel is None else channel, target.rx_type, payload
            )
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                time.sleep(0.2)
                current = self.list_devices().find(target.mac)
                if current is not None and done(current):
                    return current
        return current

    def identify(self, mac: str) -> bool:
        """Make a device flash so it can be found (the vendor app's "select")."""
        return self._send_sequenced(RF_CMD_IDENTIFY, mac)

    def reboot_lcd(self, mac: str) -> bool:
        """Restart the LCD panels of a TL Wireless LCD fan over RF."""
        return self._send_sequenced(RF_CMD_REBOOT_LCD, mac)

    def set_channel(self, channel: int) -> dict[str, bool]:
        """Move every device bound to the attached master to a channel (the bind packet with
        the new channel, as the vendor app does). Returns mac -> moved."""
        if channel not in CHANNELS and channel != DEFAULT_MASTER_CHANNEL:
            raise WirelessError(
                f"channel must be one of {', '.join(map(str, CHANNELS))} or {DEFAULT_MASTER_CHANNEL}"
            )
        snapshot = self.list_devices()
        master = self.local_master(snapshot)
        devices = bound_to(snapshot, master)
        if not devices:
            raise WirelessError("No devices are bound to the attached controller")
        result: dict[str, bool] = {}
        for number, dev in enumerate(devices, start=1):
            if dev.channel == channel:
                result[dev.mac] = True
                continue
            payload = _rf_payload(RF_CMD_BIND_PWM, dev.mac, master.mac)
            payload[14] = dev.rx_type
            payload[15] = channel
            payload[16] = number
            payload[17:21] = _kept_pwm(dev)
            moved = self._send_until(dev, payload, lambda d: d.channel == channel)
            result[dev.mac] = moved is not None and moved.channel == channel
        if any(result.values()):
            self.save_config()
        return result

    def _send_sequenced(
        self, command: int, mac: str, *, value: int | None = None
    ) -> bool:
        """Send a command numbered with the device's next command sequence, repeating it until
        the device reports that number (at most COMMAND_RETRIES times). True when confirmed.
        """
        snapshot = self.list_devices()
        target = self._bound_target(snapshot, mac)
        master = master_of(target)
        sequence = target.command_sequence + 1
        if sequence >= 255:
            sequence = 1
        payload = _rf_payload(command, target.mac, master.mac)
        payload[14] = target.rx_type
        payload[15] = master.channel
        payload[16] = ordinal_of(snapshot, master, target.mac)
        payload[17] = sequence
        if value is not None:
            payload[20] = value & 0xFF
        for _ in range(COMMAND_RETRIES):
            self._send_rf_data(target.channel, target.rx_type, payload)
            time.sleep(0.1)
            current = self.list_devices().find(mac)
            if current is not None and current.command_sequence == sequence:
                return True
        return False

    def set_pwm_sync(self, mac: str, enable: bool, fallback_pwm: int = 100) -> None:
        snapshot = self.list_devices()
        target = self._bound_target(snapshot, mac)
        if enable and not follows_motherboard_itself(mac):
            raise WirelessError(
                f"{mac} cannot follow the motherboard by itself; use the host sync loop"
            )
        if enable:
            pwm_values: tuple[int, int, int, int] = (6, 6, 6, 6)
        else:
            pwm_values = clamp_pwm_values([fallback_pwm] * 4)
        self.set_pwm_direct(target, pwm_values, label=mac, snapshot=snapshot)

    def _send_rf_data(self, channel: int, rx: int, payload: bytes | bytearray) -> None:
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


def _fetch_page(receiver: USBEndpointDevice, page_count: int) -> tuple[int, bytes]:
    command = bytearray(64)
    command[0] = RF_GET_DEV_CMD
    command[1] = page_count & 0xFF
    total_len = RF_PAGE_STRIDE * page_count
    buffer = bytearray()
    request_size = 512
    try:
        receiver.write(command)
        while len(buffer) < total_len:
            try:
                chunk = receiver.read(request_size)
            except USBError as exc:
                if "overflow" in str(exc).lower() and request_size < 2048:
                    request_size *= 2
                    continue
                raise
            if not chunk:
                break
            buffer.extend(chunk)
            if len(chunk) < request_size:
                break
    except USBError as exc:
        # A timeout or a receiver that stops answering mid-read is a wireless error too.
        raise WirelessError(f"RF receiver: {exc}") from exc
    if not buffer:
        raise WirelessError("RF receiver returned no data")
    buffer = buffer[:total_len]
    if buffer[0] != RF_GET_DEV_CMD:
        raise WirelessError(f"Unexpected RF response header 0x{buffer[0]:02x}")
    return buffer[1], bytes(buffer)


def _list_devices(receiver: USBEndpointDevice) -> WirelessSnapshot:
    """The device list from the RF receiver (fetching more pages when there are many)."""
    logger.debug("Requesting wireless device list")
    device_count, payload = _fetch_page(receiver, 1)
    pages = max(1, math.ceil(device_count / MAX_DEVICES_PER_PAGE))
    if pages != 1:
        device_count, payload = _fetch_page(receiver, pages)
    records = parse_device_records(device_count, payload)
    devices = [d for d in records if not d.is_master]
    masters = [d for d in records if d.is_master]
    logger.debug(
        "Discovered %d wireless device(s), %d master(s)", len(devices), len(masters)
    )
    return WirelessSnapshot(devices=devices, raw=payload, masters=masters)


def read_device_list(timeout_ms: int = 1000) -> WirelessSnapshot:
    """Read the device list through the RF receiver only (the controller stays free)."""
    try:
        receiver = USBEndpointDevice(
            RF_RECEIVER_VID, RF_RECEIVER_PID, timeout_ms=timeout_ms
        )
    except USBError as exc:
        raise WirelessError(str(exc)) from exc
    try:
        return _list_devices(receiver)
    finally:
        receiver.close()


def run_pwm_sync_loop(
    mac_addrs,
    *,
    interval: float = 1.0,
    max_cycles: int | None = None,
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
    last_sent: dict[str, int] = {}
    current_pwm: int | None = None
    missing_logged = False
    cycles = 0
    any_sent = False
    try:
        while True:
            try:
                with WirelessTransceiver() as tx:
                    snapshot = tx.list_devices()
                    pwm = snapshot.motherboard_pwm()
                    pwm_values: list[int] | None = None
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
                            try:
                                tx.set_pwm_direct(
                                    target,
                                    pwm_values,
                                    snapshot=snapshot,
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


def _extract_motherboard_pwm(raw: bytes) -> int | None:
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


def _generate_effect_index(avoid: bytes = b"") -> bytes:
    """Milliseconds since local midnight, as the vendor app numbers effects (never 0)."""
    now = time.localtime()
    midnight = time.mktime(
        (now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, now.tm_isdst)
    )
    value = int((time.time() - midnight) * 1000) & 0xFFFFFFFF or 1
    index = value.to_bytes(4, "big")
    if index == avoid:
        index = ((value + 1) & 0xFFFFFFFF or 1).to_bytes(4, "big")
    return index


def follows_motherboard_itself(mac: str) -> bool:
    """Devices that follow the motherboard PWM when sent PWM 6,6,6,6.

    The vendor app sends that only to MACs ending in e1; others are synced by the host loop.
    """
    return mac.lower().endswith(":e1")


def _kept_pwm(target: WirelessDeviceInfo) -> bytes:
    """PWM sent with bind/unbind. A device that follows the motherboard by itself (PWM 6, or
    reported as 0) keeps doing so; a plain 0 makes it run at its master's default speed.
    """
    pwm = tuple(target.pwm_values)
    if follows_motherboard_itself(target.mac) and (not any(pwm) or pwm == (6, 6, 6, 6)):
        pwm = (6, 6, 6, 6)
    return bytes(clamp_pwm_values(pwm))


def _rf_payload(command: int, mac: str | None, master_mac: str | None) -> bytearray:
    payload = bytearray(RF_PAYLOAD_SIZE)
    payload[0] = 0x12
    payload[1] = command
    if mac is not None:
        payload[2:8] = _mac_to_bytes(mac)
    if master_mac is not None:
        payload[8:14] = _mac_to_bytes(master_mac)
    return payload


def build_led_packets(
    mac: str,
    master_mac: str,
    effect_index: bytes,
    compressed: bytes,
    *,
    led_count: int,
    total_frames: int,
    interval_ms: float,
) -> list[bytes]:
    """RF payloads of an LED effect, in the vendor app's layout.

    Every packet: 12 20 | device MAC | master MAC | [14:18] effect index | [18] packet
    number | [19] packet count. Packet 0 carries only the header: [20:24] compressed
    length, [25:27] frame count, [27] LED count, [32:34] interval in ms, [34] its
    hundredths. Packets 1.. carry 220 bytes of compressed data each from byte 20.
    """
    if len(effect_index) != 4:
        raise WirelessError("effect index must be 4 bytes")
    data_packets = math.ceil(len(compressed) / LED_DATA_CHUNK)
    total = 1 + data_packets
    if total > 255:
        raise WirelessError("LED payload is too large to transmit")
    # Whole ms and hundredths from one rounding, so 12.996 ms is 13.00, not 12.00.
    whole, hundredths = divmod(round(max(0.0, float(interval_ms)) * 100), 100)
    whole = min(whole, 0xFFFF)

    def base(number: int) -> bytearray:
        payload = _rf_payload(RF_CMD_LED_EFFECT, mac, master_mac)
        payload[14:18] = effect_index
        payload[18] = number
        payload[19] = total
        return payload

    header = base(0)
    header[20:24] = len(compressed).to_bytes(4, "big")
    header[24] = 0
    header[25:27] = (total_frames & 0xFFFF).to_bytes(2, "big")
    header[27] = led_count & 0xFF
    header[32:34] = whole.to_bytes(2, "big")
    header[34] = hundredths
    packets = [bytes(header)]
    for number in range(1, total):
        chunk = compressed[(number - 1) * LED_DATA_CHUNK : number * LED_DATA_CHUNK]
        payload = base(number)
        payload[20 : 20 + len(chunk)] = chunk
        packets.append(bytes(payload))
    return packets


def parse_device_records(count: int, payload: bytes) -> list[WirelessDeviceInfo]:
    """Parse the receiver's device list: 42-byte records from byte 4, valid when byte 41 is 28."""
    devices: list[WirelessDeviceInfo] = []
    offset = 4
    for _ in range(count):
        if offset + 42 > len(payload):
            break
        record = payload[offset : offset + 42]
        offset += 42
        if record[41] != 28:
            continue
        fan_num = record[19] if record[19] < 10 else record[19] - 10
        speed = bytearray(record[28:36])
        flags = speed[0] >> 4
        speed[0] &= 0x0F
        speed[2] &= 0x0F  # high nibble: wireless theme / P28 gear
        rf_version = (speed[4] & 0xF0) + ((speed[6] & 0xF0) >> 4)
        speed[4] &= 0x0F
        speed[6] &= 0x0F
        fan_rpm = tuple((speed[i * 2] << 8) | speed[i * 2 + 1] for i in range(4))
        devices.append(
            WirelessDeviceInfo(
                mac=_bytes_to_mac(record[0:6]),
                master_mac=_bytes_to_mac(record[6:12]),
                channel=record[12],
                rx_type=record[13],
                device_type=record[18],
                fan_count=fan_num,
                pwm_values=cast(tuple[int, int, int, int], tuple(record[36:40])),
                fan_rpm=cast(tuple[int, int, int, int], fan_rpm),
                command_sequence=record[40],
                raw=bytes(record),
                effect_index=bytes(record[20:24]),
                fans_type=cast(tuple[int, int, int, int], tuple(record[24:28])),
                rf_version=rf_version,
                sync_line=bool(flags & 0x8),
                mb_light_sync=bool(flags & 0x4),
                pwm_line=bool(flags & 0x2),
                fg_line=bool(flags & 0x1),
            ),
        )
    return devices


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

    return led_count


def _expand_colors(
    colors: Sequence[tuple[int, int, int]],
    led_count: int,
    fan_count: int,
) -> bytes:
    if not colors:
        raise WirelessError("Color list cannot be empty")

    def to_bytes(color: tuple[int, int, int]) -> bytes:
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
