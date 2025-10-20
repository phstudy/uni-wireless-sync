import json
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1].parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from uwscli import cli, lcd, wireless  # noqa: E402


class StubTransceiver:
    """Context manager used to capture commands flowing through the CLI."""

    instances = []

    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.calls = []
        StubTransceiver.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    # Wireless CLI accesses list_devices for enumeration flows.
    def list_devices(self):  # pragma: no cover - exercised in tests
        if self.snapshot is None:
            raise AssertionError("list_devices() was called without a prepared snapshot")
        return self.snapshot

    def set_pwm_sync(self, mac, enable, fallback_pwm=100):  # pragma: no cover - exercised in tests
        self.calls.append({
            "mac": mac,
            "enable": enable,
            "fallback_pwm": fallback_pwm,
        })


def test_pwm_sync_enable_json(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    monkeypatch.setattr(wireless, "WirelessTransceiver", lambda *args, **kwargs: StubTransceiver())

    cli.main([
        "--output",
        "json",
        "fan",
        "pwm-sync",
        "--mac",
        "aa:bb:cc:dd:ee:ff",
        "--enable",
    ])

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload == {
        "targets": ["aa:bb:cc:dd:ee:ff"],
        "mode": "enable",
        "fallback_pwm": 100,
    }
    assert StubTransceiver.instances[-1].calls == [
        {"mac": "aa:bb:cc:dd:ee:ff", "enable": True, "fallback_pwm": 100},
    ]


def test_fan_list_json_output(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=7,
        fan_count=4,
        pwm_values=(10, 20, 30, 40),
        fan_rpm=(1000, 0, 0, 0),
        command_sequence=5,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["--output", "json", "fan", "list"])

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["devices"][0]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert payload["devices"][0]["channel"] == 3
    assert payload["devices"][0]["fan_pwm"] == [10, 20, 30, 40]
    assert payload["devices"][0]["fan_rpm"] == [1000, 0, 0, 0]


def test_lcd_list_includes_serial(monkeypatch, capsys):
    sample = lcd.HidDeviceInfo(
        path="usb:1cbe:0006:123",
        vendor_id=0x1CBE,
        product_id=0x0006,
        serial_number="abc123",
        manufacturer="LIANLI",
        product="TL-LCD Wireless",
        source="wireless",
        location_id=123,
    )

    monkeypatch.setattr(lcd, "enumerate_devices", lambda: [sample])

    cli.main(["lcd", "list"])

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines, "Expected list output"
    assert '"serial": "abc123"' in lines[0]


def test_lcd_info_uses_explicit_serial(monkeypatch, capsys):
    calls = []

    class DummyDevice:
        def __init__(self, serial):
            calls.append(serial)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def handshake(self):
            return {"mode": 1}

        def firmware_version(self):
            return {"version": "1.0"}

    monkeypatch.setattr(lcd, "TLLCDDevice", DummyDevice)

    cli.main(["--output", "json", "lcd", "info", "--serial", "abc123"])

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["handshake"]["mode"] == 1
    assert payload["firmware"]["version"] == "1.0"
    assert calls == ["abc123"]


def test_lcd_info_autodetects_single_serial(monkeypatch, capsys):
    sample = lcd.HidDeviceInfo(
        path="usb:1cbe:0006:321",
        vendor_id=0x1CBE,
        product_id=0x0006,
        serial_number="detected123",
        manufacturer="LIANLI",
        product="TL-LCD Wireless",
        source="wireless",
        location_id=0x321,
    )

    monkeypatch.setattr(lcd, "enumerate_devices", lambda: [sample])

    calls = []

    class DummyDevice:
        def __init__(self, serial):
            calls.append(serial)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def handshake(self):
            return {"mode": 2}

        def firmware_version(self):
            return {"version": "2.0"}

    monkeypatch.setattr(lcd, "TLLCDDevice", DummyDevice)

    cli.main(["--output", "json", "lcd", "info"])

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["handshake"]["mode"] == 2
    assert calls == ["detected123"]
