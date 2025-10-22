import json
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1].parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from uwscli import cli, lcd, tl_effects, tlcontroller, wireless  # noqa: E402


class StubTransceiver:
    """Context manager used to capture commands flowing through the CLI."""

    instances: list["StubTransceiver"] = []

    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.calls = []
        self.led_static_calls = []
        self.led_rainbow_calls = []
        self.led_effect_calls = []
        StubTransceiver.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    # Wireless CLI accesses list_devices for enumeration flows.
    def list_devices(self):  # pragma: no cover - exercised in tests
        if self.snapshot is None:
            raise AssertionError(
                "list_devices() was called without a prepared snapshot"
            )
        return self.snapshot

    def set_led_static(self, mac, color, color_list=None, **kwargs):
        self.led_static_calls.append(
            {
                "mac": mac,
                "color": color,
                "color_list": color_list,
            }
        )

    def set_led_rainbow(self, mac, frames=24, interval_ms=50, **kwargs):
        self.led_rainbow_calls.append(
            {
                "mac": mac,
                "frames": frames,
                "interval_ms": interval_ms,
            }
        )

    def set_led_frames(self, mac, frames, interval_ms=50, **kwargs):
        self.led_rainbow_calls.append(
            {
                "mac": mac,
                "frames": frames,
                "interval_ms": interval_ms,
                "mode": "frames",
            }
        )

    def set_led_effect(
        self,
        mac,
        effect,
        tb=0,
        brightness=255,
        direction=1,
        interval_ms=50,
        **kwargs,
    ):
        self.led_effect_calls.append(
            {
                "mac": mac,
                "effect": getattr(effect, "name", str(effect)),
                "tb": tb,
                "brightness": brightness,
                "direction": direction,
                "interval_ms": interval_ms,
            }
        )


def test_pwm_sync_mac_json(monkeypatch, capsys):
    run_calls = []

    def fake_run_pwm_sync_loop(
        targets, *, interval=1.0, max_cycles=None, stop_after_first_send=False
    ):
        run_calls.append(
            {
                "targets": targets,
                "interval": interval,
                "max_cycles": max_cycles,
                "stop_after_first_send": stop_after_first_send,
            }
        )

    monkeypatch.setattr(wireless, "run_pwm_sync_loop", fake_run_pwm_sync_loop)
    toggles = []
    monkeypatch.setattr(tlcontroller, "set_motherboard_rpm_sync", toggles.append)

    cli.main(
        [
            "--output",
            "json",
            "fan",
            "pwm-sync",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--interval",
            "0.5",
        ]
    )

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload == {
        "targets": ["aa:bb:cc:dd:ee:ff"],
        "interval": 0.5,
        "status": "running",
    }
    assert toggles == [True]
    assert run_calls == [
        {
            "targets": ["aa:bb:cc:dd:ee:ff"],
            "interval": 0.5,
            "max_cycles": None,
            "stop_after_first_send": False,
        },
    ]


def test_pwm_sync_mac_once(monkeypatch, capsys):
    run_calls = []

    def fake_run_pwm_sync_loop(
        targets, *, interval=1.0, max_cycles=None, stop_after_first_send=False
    ):
        run_calls.append(
            {
                "targets": targets,
                "interval": interval,
                "max_cycles": max_cycles,
                "stop_after_first_send": stop_after_first_send,
            }
        )

    monkeypatch.setattr(wireless, "run_pwm_sync_loop", fake_run_pwm_sync_loop)
    toggles = []
    monkeypatch.setattr(tlcontroller, "set_motherboard_rpm_sync", toggles.append)

    cli.main(
        [
            "--output",
            "json",
            "fan",
            "pwm-sync",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--once",
        ]
    )

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload == {
        "targets": ["aa:bb:cc:dd:ee:ff"],
        "interval": 1.0,
        "status": "once",
    }
    assert toggles == [True]
    assert run_calls == [
        {
            "targets": ["aa:bb:cc:dd:ee:ff"],
            "interval": 1.0,
            "max_cycles": None,
            "stop_after_first_send": True,
        },
    ]


def test_pwm_sync_all_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device_bound = wireless.WirelessDeviceInfo(
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
    device_unbound = wireless.WirelessDeviceInfo(
        mac="de:ad:be:ef:00:01",
        master_mac="00:00:00:00:00:00",
        channel=3,
        rx_type=2,
        device_type=7,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(
        devices=[device_bound, device_unbound], raw=b""
    )

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    run_calls = []

    def fake_run_pwm_sync_loop(
        targets, *, interval=1.0, max_cycles=None, stop_after_first_send=False
    ):
        run_calls.append(
            {
                "targets": targets,
                "interval": interval,
                "max_cycles": max_cycles,
                "stop_after_first_send": stop_after_first_send,
            }
        )

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)
    monkeypatch.setattr(wireless, "run_pwm_sync_loop", fake_run_pwm_sync_loop)
    toggles = []
    monkeypatch.setattr(tlcontroller, "set_motherboard_rpm_sync", toggles.append)

    cli.main(
        [
            "fan",
            "pwm-sync",
            "--all",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert "Syncing motherboard PWM" in out
    assert toggles == [True]
    assert run_calls == [
        {
            "targets": ["aa:bb:cc:dd:ee:ff"],
            "interval": 1.0,
            "max_cycles": None,
            "stop_after_first_send": False,
        },
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


def test_fan_set_led_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["fan", "set-led", "--mac", "aa:bb:cc:dd:ee:ff", "--color", "255,128,0"])

    out = capsys.readouterr().out.strip()
    assert "Applied static LED effect" in out
    stub = StubTransceiver.instances[-1]
    record = stub.led_static_calls[-1]
    assert record["mac"] == "aa:bb:cc:dd:ee:ff"
    assert record["color"] == (255, 128, 0)
    assert record["color_list"] is None


def test_fan_set_led_color_list_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(
        [
            "fan",
            "set-led",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--color-list",
            "255,0,0;0,0,255",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert "Applied static LED effect" in out
    record = StubTransceiver.instances[-1].led_static_calls[-1]
    assert record["color"] is None
    assert record["color_list"] == [(255, 0, 0), (0, 0, 255)]


def test_fan_set_led_effect_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(
        [
            "fan",
            "set-led",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--mode",
            "effect",
            "--effect",
            "twinkle",
            "--effect-brightness",
            "128",
            "--effect-direction",
            "0",
            "--effect-scope",
            "behind",
            "--interval-ms",
            "60",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert "Applied TL effect TWINKLE" in out
    record = StubTransceiver.instances[-1].led_effect_calls[-1]
    assert record["mac"] == "aa:bb:cc:dd:ee:ff"
    assert record["effect"] == "TWINKLE"
    assert record["tb"] == 1
    assert record["brightness"] == 128
    assert record["direction"] == 0
    assert record["interval_ms"] == 60


def test_fan_set_led_effect_both_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(
        [
            "fan",
            "set-led",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--mode",
            "effect",
            "--effect",
            "ripple",
            "--effect-scope",
            "both",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert "Applied TL effect RIPPLE" in out
    record = StubTransceiver.instances[-1].led_effect_calls[-1]
    assert record["mac"] == "aa:bb:cc:dd:ee:ff"
    assert record["effect"] == "RIPPLE"
    assert record["tb"] is None


def test_fan_set_led_random_effect_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)
    monkeypatch.setattr(cli.random, "choice", lambda seq: tl_effects.TLEffects.RIPPLE)

    cli.main(
        [
            "fan",
            "set-led",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--mode",
            "random-effect",
            "--effect-brightness",
            "200",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert "Applied random TL effect RIPPLE" in out
    record = StubTransceiver.instances[-1].led_effect_calls[-1]
    assert record["mac"] == "aa:bb:cc:dd:ee:ff"
    assert record["effect"] == "RIPPLE"
    assert record["tb"] is None
    assert record["brightness"] == 200


def test_fan_set_led_random_effect_all_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device_a = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    device_b = wireless.WirelessDeviceInfo(
        mac="de:ad:be:ef:00:01",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=3,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=2,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device_a, device_b], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)
    monkeypatch.setattr(
        cli.random, "choice", lambda seq: tl_effects.TLEffects.STAGGERED
    )

    cli.main(
        [
            "fan",
            "set-led",
            "--all",
            "--mode",
            "random-effect",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert '"effect": "STAGGERED"' in out
    # The last stub is the one used for sends (after enumeration)
    record_calls = StubTransceiver.instances[-1].led_effect_calls
    assert len(record_calls) == 2
    assert {call["effect"] for call in record_calls} == {"STAGGERED"}


def test_fan_set_led_rainbow_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(
        [
            "fan",
            "set-led",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--mode",
            "rainbow",
            "--frames",
            "12",
            "--interval-ms",
            "80",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert "Applied rainbow LED effect" in out
    stub = StubTransceiver.instances[-1]
    record = stub.led_rainbow_calls[-1]
    assert record["mac"] == "aa:bb:cc:dd:ee:ff"
    assert record["frames"] == 12
    assert record["interval_ms"] == 80
    assert "mode" not in record


def test_fan_set_led_frames_cli(monkeypatch, tmp_path, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    frames_path = tmp_path / "frames.json"
    frames_path.write_text(
        json.dumps(
            [
                [[255, 0, 0], [0, 255, 0]],
                [[0, 0, 255], [255, 255, 0]],
            ]
        )
    )

    cli.main(
        [
            "fan",
            "set-led",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--mode",
            "frames",
            "--frames-file",
            str(frames_path),
            "--interval-ms",
            "90",
        ]
    )

    out = capsys.readouterr().out.strip()
    assert "Applied custom LED frames" in out
    record = StubTransceiver.instances[-1].led_rainbow_calls[-1]
    assert record["mac"] == "aa:bb:cc:dd:ee:ff"
    assert record["frames"] == [
        [(255, 0, 0), (0, 255, 0)],
        [(0, 0, 255), (255, 255, 0)],
    ]
    assert record["interval_ms"] == 90
    assert record["mode"] == "frames"


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
