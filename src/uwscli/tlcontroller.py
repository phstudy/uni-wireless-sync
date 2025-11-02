"""Helpers for interacting with TL-series fan controllers over HID."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised implicitly when hidapi is available
    import hid as _hid
except ImportError:  # pragma: no cover - fallback when hidapi is missing
    hid: Any | None = None
else:
    hid = _hid


CANDIDATE_VID_PID = ((0x0416, 0x7372),)  # TL fan controller
TL_CONTROLLER_REPORT_ID = 0x01
LED_PACKET_HEADER_LEN = 6
LED_PACKET_LENGTH = 64
LED_PACKET_MAX_PAYLOAD = LED_PACKET_LENGTH - LED_PACKET_HEADER_LEN

CMD_SET_MB_PWM_SYNC = 0xB1

DEFAULT_PORTS = range(4)
DEFAULT_FANS_PER_PORT = range(4)


def _build_led_packet(command: int, payload: bytes = b"") -> bytes:
    report = bytearray(LED_PACKET_LENGTH)
    report[0] = TL_CONTROLLER_REPORT_ID
    report[1] = command & 0xFF
    length = min(len(payload), LED_PACKET_MAX_PAYLOAD)
    report[5] = length
    if length:
        report[LED_PACKET_HEADER_LEN : LED_PACKET_HEADER_LEN + length] = payload[
            :length
        ]
    return bytes(report)


def set_motherboard_rpm_sync(enable: bool) -> None:
    """Toggle motherboard RPM sync flag on all connected TL controllers."""

    if hid is None or not hasattr(hid, "device"):
        logger.debug("hidapi not available; skipping TL controller sync toggle")
        return
    active = 0
    payloads = [
        bytes([((1 if enable else 0) << 7) | ((port & 0x3) << 4) | (fan & 0xF)])
        for port in DEFAULT_PORTS
        for fan in DEFAULT_FANS_PER_PORT
    ]

    packet_cache = [
        _build_led_packet(CMD_SET_MB_PWM_SYNC, payload) for payload in payloads
    ]

    for label, device in _iterate_candidate_devices():
        try:
            for packet in packet_cache:
                try:
                    device.write(packet)
                except Exception as exc:  # pragma: no cover - hardware dependent
                    logger.warning(
                        "TL controller %s write failed: %s",
                        label,
                        exc,
                    )
                    break
                try:
                    device.read(LED_PACKET_LENGTH, timeout=50)
                except Exception:
                    pass
            else:
                active += 1
        finally:
            try:
                device.close()
            except Exception:
                pass

    if active:
        logger.debug(
            "Updated motherboard RPM sync=%s on %d TL controller(s)", enable, active
        )
    else:
        logger.debug("No TL controllers updated; enable=%s", enable)


def _iterate_candidate_devices():
    if hid is None or not hasattr(hid, "device"):
        return
    seen = set()
    for vid, pid in CANDIDATE_VID_PID:
        descriptors = []
        try:
            descriptors = hid.enumerate(vid, pid) or []
        except Exception as exc:  # pragma: no cover - hardware dependent
            logger.debug("Enumerate %04x:%04x failed: %s", vid, pid, exc)
        for info in descriptors:
            path = info.get("path")
            if not path:
                continue
            if isinstance(path, str):
                path_bytes = path.encode("utf-8", "ignore")
            else:
                path_bytes = path
            key = (vid, pid, path_bytes)
            if key in seen:
                continue
            seen.add(key)
            device = hid.device()
            try:
                device.open_path(path_bytes)
            except Exception:
                continue
            yield f"{vid:04x}:{pid:04x}@{path_bytes!r}", device
        key = (vid, pid, None)
        if key in seen:
            continue
        device = hid.device()
        try:
            device.open(vid, pid)
        except Exception:
            continue
        seen.add(key)
        yield f"{vid:04x}:{pid:04x}", device
