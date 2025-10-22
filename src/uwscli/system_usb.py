"""Lightweight USB enumeration helpers for common POSIX targets."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class USBRecord:
    vendor_id: int
    product_id: int
    product: Optional[str] = None
    vendor: Optional[str] = None
    serial: Optional[str] = None
    location_id: Optional[int] = None


_VENDOR_RE = re.compile(r'"idVendor"\s*=\s*(\d+)')
_PRODUCT_RE = re.compile(r'"idProduct"\s*=\s*(\d+)')
_LOCATION_RE = re.compile(r'"locationID"\s*=\s*(\d+)')
_STRING_RE = re.compile(
    r'"(kUSBProductString|USB Product Name|kUSBVendorString|USB Vendor Name|USB Serial Number|kUSBSerialNumberString)"\s*=\s*"([^"]*)"'
)


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _parse_int(value: Optional[str], base: int = 10) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value, base)
    except ValueError:
        return None


def _parse_ioreg(text: str) -> List[USBRecord]:
    devices: List[USBRecord] = []
    current: Dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        vid = current.get("vendor_id")
        pid = current.get("product_id")
        if isinstance(vid, int) and isinstance(pid, int):
            product = current.get("product")
            vendor = current.get("vendor")
            serial = current.get("serial")
            location_raw = current.get("location_id")
            devices.append(
                USBRecord(
                    vendor_id=vid,
                    product_id=pid,
                    product=product if isinstance(product, str) else None,
                    vendor=vendor if isinstance(vendor, str) else None,
                    serial=serial if isinstance(serial, str) else None,
                    location_id=location_raw if isinstance(location_raw, int) else None,
                ),
            )
        current = None

    for raw_line in text.splitlines():
        if "+-o " in raw_line:
            flush()
            current = {}
            continue
        if current is None:
            continue
        line = raw_line.strip()
        match = _VENDOR_RE.search(line)
        if match:
            current["vendor_id"] = int(match.group(1))
            continue
        match = _PRODUCT_RE.search(line)
        if match:
            current["product_id"] = int(match.group(1))
            continue
        match = _LOCATION_RE.search(line)
        if match:
            current["location_id"] = int(match.group(1))
            continue
        match = _STRING_RE.search(line)
        if match:
            key, value = match.groups()
            if "Product" in key:
                current["product"] = value
            elif "Vendor" in key:
                current["vendor"] = value
            elif "Serial" in key:
                current["serial"] = value
    flush()
    return devices


def _scan_linux_sysfs() -> List[USBRecord]:
    root = Path("/sys/bus/usb/devices")
    if not root.exists():
        return []
    devices: List[USBRecord] = []
    for entry in root.iterdir():
        if ":" in entry.name or not entry.is_dir():
            continue
        vid_str = _read_text(entry / "idVendor")
        pid_str = _read_text(entry / "idProduct")
        vendor_id = _parse_int(vid_str, base=16)
        product_id = _parse_int(pid_str, base=16)
        if vendor_id is None or product_id is None:
            continue
        product = _read_text(entry / "product")
        vendor = _read_text(entry / "manufacturer")
        serial = _read_text(entry / "serial")
        busnum = _parse_int(_read_text(entry / "busnum"))
        devnum = _parse_int(_read_text(entry / "devnum"))
        location_id = None
        if busnum is not None and devnum is not None:
            location_id = (busnum << 8) | devnum
        devices.append(
            USBRecord(
                vendor_id=vendor_id,
                product_id=product_id,
                product=product,
                vendor=vendor,
                serial=serial,
                location_id=location_id,
            ),
        )
    return devices


def scan_usb_devices() -> List[USBRecord]:
    if os.name != "posix":
        return []
    if sys.platform.startswith("linux"):
        return _scan_linux_sysfs()
    try:
        result = subprocess.run(
            ["ioreg", "-p", "IOUSB", "-l", "-w0"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return _parse_ioreg(result.stdout)


def find_devices_by_vid_pid(vendor_id: int, product_id: int) -> List[USBRecord]:
    return [
        rec
        for rec in scan_usb_devices()
        if rec.vendor_id == vendor_id and rec.product_id == product_id
    ]
