"""USB helper utilities built on top of PyUSB."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any, Optional

import usb.core
import usb.util
from usb.core import NoBackendError


class USBError(RuntimeError):
    """Raised when the USB layer encounters a fatal condition."""


def _is_resource_busy_error(exc: usb.core.USBError) -> bool:
    """Return True when libusb reports that an interface is still claimed."""

    errno = getattr(exc, "errno", None)
    if errno == 16:
        return True
    message = str(exc).lower()
    return "resource busy" in message or "busy" in message


@dataclass
class USBEndpoints:
    """Holds the OUT and IN endpoints for a claimed USB interface."""

    out: Any
    inn: Any


class USBEndpointDevice:
    """Convenience wrapper to claim a single-interface HID/WinUSB device."""

    def __init__(
        self,
        vendor_id: int,
        product_id: int,
        *,
        write_endpoint: Optional[int] = 0x01,
        read_endpoint: Optional[int] = 0x81,
        interface: Optional[int] = 0,
        configuration: Optional[int] = None,
        timeout_ms: int = 1000,
        serial_number: Optional[str] = None,
        location_id: Optional[int] = None,
    ) -> None:
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.timeout_ms = timeout_ms
        self._serial_number = serial_number
        self._location_id = location_id
        self._device = self._open_device(configuration)
        self._interface, self._endpoints = self._claim_interface(
            interface, write_endpoint, read_endpoint
        )

    @property
    def device(self) -> usb.core.Device:
        return self._device

    def _open_device(self, configuration: Optional[int]) -> usb.core.Device:
        try:
            if self._serial_number is not None or self._location_id is not None:
                dev = usb.core.find(
                    idVendor=self.vendor_id,
                    idProduct=self.product_id,
                    custom_match=self._match_device,
                )
            else:
                dev = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        except NoBackendError as exc:
            raise USBError(
                "PyUSB could not locate a usable libusb backend. Install libusb-1.0 and ensure it is discoverable.",
            ) from exc
        if dev is None:
            location_hint = ""
            if self._location_id is not None:
                location_hint = f" at location 0x{self._location_id:04x}"
            raise USBError(
                f"USB device {self.vendor_id:04x}:{self.product_id:04x} not found{location_hint}",
            )
        if configuration is not None:
            dev.set_configuration(configuration)
        else:
            try:
                dev.get_active_configuration()
            except usb.core.USBError:
                dev.set_configuration()
        return dev

    def _match_device(self, dev: usb.core.Device) -> bool:
        if dev.idVendor != self.vendor_id or dev.idProduct != self.product_id:
            return False
        if self._location_id is not None:
            bus = getattr(dev, "bus", None)
            address = getattr(dev, "address", None)
            if bus is None or address is None:
                return False
            if ((bus << 8) | address) != self._location_id:
                return False
        if self._serial_number is not None:
            try:
                serial = (
                    usb.util.get_string(dev, dev.iSerialNumber)
                    if dev.iSerialNumber
                    else None
                )
            except usb.core.USBError:
                serial = None
            if serial != self._serial_number:
                return False
        return True

    def _claim_interface(
        self,
        interface: Optional[int],
        write_ep: Optional[int],
        read_ep: Optional[int],
    ) -> tuple[int, USBEndpoints]:
        cfg = self._device.get_active_configuration()
        candidates = []
        if interface is not None:
            candidates.append(interface)
        else:
            for intf in cfg:
                if intf.bInterfaceClass in (0xFF, 0x03, 0):
                    candidates.append(intf.bInterfaceNumber)
        for intf_num in candidates:
            intf = cfg[(intf_num, 0)]
            # Detach kernel driver if possible (Linux)
            with contextlib.suppress(NotImplementedError, usb.core.USBError):
                if self._device.is_kernel_driver_active(intf_num):
                    self._device.detach_kernel_driver(intf_num)
            claimed = False
            last_error: Optional[usb.core.USBError] = None
            for attempt in range(5):
                try:
                    usb.util.claim_interface(self._device, intf_num)
                except (
                    usb.core.USBError
                ) as exc:  # pragma: no branch - error handling path
                    last_error = exc
                    if not _is_resource_busy_error(exc) or attempt == 4:
                        if _is_resource_busy_error(exc):
                            raise USBError(
                                "USB interface is busy; ensure no other process is accessing the device.",
                            ) from exc
                        raise
                    time.sleep(0.05 * (attempt + 1))
                else:
                    claimed = True
                    break
            if not claimed:
                if last_error is not None:
                    raise last_error
                continue
            ep_out = None
            ep_in = None
            for ep in intf:
                addr = ep.bEndpointAddress
                if usb.util.endpoint_direction(addr) == usb.util.ENDPOINT_OUT:
                    if write_ep is None or addr == write_ep:
                        ep_out = ep
                elif usb.util.endpoint_direction(addr) == usb.util.ENDPOINT_IN:
                    if read_ep is None or addr == read_ep:
                        ep_in = ep
            if ep_out is None and write_ep is None:
                ep_out = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(
                        e.bEndpointAddress
                    )
                    == usb.util.ENDPOINT_OUT,
                )
            if ep_in is None and read_ep is None:
                ep_in = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(
                        e.bEndpointAddress
                    )
                    == usb.util.ENDPOINT_IN,
                )
            if ep_out is not None and ep_in is not None:
                return intf_num, USBEndpoints(out=ep_out, inn=ep_in)
            usb.util.release_interface(self._device, intf_num)
        raise USBError("Could not locate suitable interface/endpoints for device")

    def write(self, payload: bytes) -> int:
        try:
            return self._endpoints.out.write(payload, self.timeout_ms)
        except usb.core.USBError as exc:
            raise USBError(f"USB write failed: {exc}") from exc

    def read(self, size: int, timeout_ms: Optional[int] = None) -> bytes:
        try:
            timeout = self.timeout_ms if timeout_ms is None else timeout_ms
            data = self._endpoints.inn.read(size, timeout)
        except usb.core.USBError as exc:
            raise USBError(f"USB read failed: {exc}") from exc
        return bytes(data)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            usb.util.release_interface(self._device, self._interface)
            with contextlib.suppress(NotImplementedError, usb.core.USBError):
                self._device.attach_kernel_driver(self._interface)
            usb.util.dispose_resources(self._device)

    def __enter__(self) -> "USBEndpointDevice":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
