import pytest
import usb.core
import usb.util

from uwscli import usbutil


class _FakeEndpoint:
    def __init__(self, address: int) -> None:
        self.bEndpointAddress = address


class _FakeInterface:
    bInterfaceClass = 0xFF
    bInterfaceNumber = 0

    def __iter__(self):
        yield _FakeEndpoint(0x01)
        yield _FakeEndpoint(0x81)


class _FakeConfiguration:
    def __init__(self) -> None:
        self._interface = _FakeInterface()

    def __iter__(self):
        yield self._interface

    def __getitem__(self, key):  # pragma: no cover - defensive
        return self._interface


class _FakeDevice:
    def __init__(self) -> None:
        self._config = _FakeConfiguration()

    def is_kernel_driver_active(self, intf_num):
        return False

    def detach_kernel_driver(self, intf_num):  # pragma: no cover - API parity
        return None

    def get_active_configuration(self):
        return self._config

    def set_configuration(self):  # pragma: no cover - not exercised
        return None

    def attach_kernel_driver(self, intf_num):  # pragma: no cover - API parity
        return None


@pytest.fixture
def fake_device(monkeypatch):
    device = _FakeDevice()

    def fake_open(self, configuration):
        return device

    monkeypatch.setattr(usbutil.USBEndpointDevice, "_open_device", fake_open)
    monkeypatch.setattr(usbutil.time, "sleep", lambda _: None)
    return device


def test_claim_interface_retries_busy_then_succeeds(monkeypatch, fake_device):
    attempts = {"count": 0}

    def fake_claim(dev, intf):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise usb.core.USBError("Resource busy", 16)

    monkeypatch.setattr(usb.util, "claim_interface", fake_claim)

    usbutil.USBEndpointDevice(
        0x1234,
        0x5678,
        interface=0,
        write_endpoint=0x01,
        read_endpoint=0x81,
    )

    assert attempts["count"] == 3


def test_claim_interface_busy_exhaustion_raises_usb_error(monkeypatch, fake_device):
    def fake_claim(dev, intf):
        raise usb.core.USBError("Resource busy", 16)

    monkeypatch.setattr(usb.util, "claim_interface", fake_claim)

    with pytest.raises(usbutil.USBError, match="interface is busy"):
        usbutil.USBEndpointDevice(
            0x1234,
            0x5678,
            interface=0,
            write_endpoint=0x01,
            read_endpoint=0x81,
        )
