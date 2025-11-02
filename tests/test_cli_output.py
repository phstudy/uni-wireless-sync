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

    def __init__(self, snapshot=None, *, master_mac=None, master_channel=8):
        self.snapshot = snapshot
        self.calls = []
        self.led_static_calls = []
        self.led_rainbow_calls = []
        self.led_effect_calls = []
        self.pwm_calls = []
        self.master_mac = master_mac
        self.master_channel = master_channel
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

    def query_master_mac(self, channel=None):
        if self.master_mac is None:
            return None
        requested_channel = 8 if channel is None else channel
        channel_to_return = (
            self.master_channel if self.master_channel is not None else requested_channel
        )
        return self.master_mac, channel_to_return

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

    def set_pwm(self, mac, pwm_values, sequence_index=1):
        self.pwm_calls.append(
            {
                "type": "set_pwm",
                "mac": mac,
                "pwm": list(pwm_values),
                "sequence_index": sequence_index,
            }
        )

    def set_pwm_direct(
        self,
        target,
        pwm_values,
        *,
        sequence_index=1,
        label=None,
    ):
        self.pwm_calls.append(
            {
                "type": "set_pwm_direct",
                "mac": getattr(target, "mac", label),
                "pwm": list(pwm_values),
                "sequence_index": sequence_index,
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
            "--mode",
            "controller",
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
        "mode": "controller",
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
            "--mode",
            "controller",
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
        "mode": "controller",
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
        return StubTransceiver(
            snapshot=snapshot,
            master_mac="11:22:33:44:55:66",
            master_channel=8,
        )

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
            "--mode",
            "controller",
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
        return StubTransceiver(
            snapshot=snapshot,
            master_mac="11:22:33:44:55:66",
            master_channel=8,
        )

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["--output", "json", "fan", "list"])

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["devices"][0]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert payload["devices"][0]["channel"] == 3
    assert payload["devices"][0]["fan_pwm"] == [10, 20, 30, 40]
    assert payload["devices"][0]["fan_rpm"] == [1000, 0, 0, 0]


def test_fan_list_masters_json_output(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    master = wireless.WirelessDeviceInfo(
        mac="11:22:33:44:55:66",
        master_mac="11:22:33:44:55:66",
        channel=8,
        rx_type=255,
        device_type=255,
        fan_count=1,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    device_a = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:01",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=1,
        device_type=7,
        fan_count=4,
        pwm_values=(10, 20, 30, 40),
        fan_rpm=(1000, 0, 0, 0),
        command_sequence=5,
        raw=bytes(42),
    )
    device_b = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:02",
        master_mac="11:22:33:44:55:66",
        channel=4,
        rx_type=2,
        device_type=6,
        fan_count=2,
        pwm_values=(20, 20, 20, 20),
        fan_rpm=(900, 0, 0, 0),
        command_sequence=6,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(
        devices=[device_b, device_a, master], raw=b""
    )

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["--output", "json", "fan", "list-masters"])

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {
        "masters": [
            {
                "master_mac": "11:22:33:44:55:66",
                "channel": 8,
                "device_count": 2,
                "channels": [3, 4, 8],
                "rx_types": [1, 2],
                "devices": [
                    {
                        "mac": "aa:bb:cc:dd:ee:01",
                        "channel": 3,
                        "rx_type": 1,
                        "device_type": 7,
                        "fan_count": 4,
                    },
                    {
                        "mac": "aa:bb:cc:dd:ee:02",
                        "channel": 4,
                        "rx_type": 2,
                        "device_type": 6,
                        "fan_count": 2,
                    },
                ],
            }
        ]
    }


def test_fan_list_masters_master_only_text(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    master = wireless.WirelessDeviceInfo(
        mac="11:22:33:44:55:66",
        master_mac="00:00:00:00:00:00",
        channel=8,
        rx_type=255,
        device_type=255,
        fan_count=1,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[master], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(
            snapshot=snapshot,
            master_mac="11:22:33:44:55:66",
            master_channel=8,
        )

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["fan", "list-masters"])

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload == {
        "master_mac": "11:22:33:44:55:66",
        "channel": 8,
        "device_count": 0,
        "channels": [8],
        "rx_types": [],
        "devices": [],
    }


def test_fan_list_masters_query_only(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    receiver = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="00:00:00:00:00:00",
        channel=8,
        rx_type=254,
        device_type=0,
        fan_count=3,
        pwm_values=(130, 130, 130, 130),
        fan_rpm=(1100, 0, 0, 0),
        command_sequence=2,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(devices=[receiver], raw=b"")

    def factory(*args, **kwargs):
        return StubTransceiver(
            snapshot=snapshot,
            master_mac="11:22:33:44:55:66",
            master_channel=8,
        )

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["--output", "json", "fan", "list-masters"])

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {
        "masters": [
            {
                "master_mac": "11:22:33:44:55:66",
                "channel": 8,
                "device_count": 0,
                "channels": [8],
                "rx_types": [],
                "devices": [],
            }
        ]
    }


def test_fan_set_fan_all_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device_bound_a = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:01",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=1,
        device_type=7,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=2,
        raw=bytes(42),
    )
    device_bound_b = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:02",
        master_mac="11:22:33:44:55:66",
        channel=4,
        rx_type=2,
        device_type=6,
        fan_count=3,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=3,
        raw=bytes(42),
    )
    device_unbound = wireless.WirelessDeviceInfo(
        mac="de:ad:be:ef:00:01",
        master_mac="00:00:00:00:00:00",
        channel=5,
        rx_type=3,
        device_type=7,
        fan_count=2,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=4,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(
        devices=[device_unbound, device_bound_a, device_bound_b], raw=b""
    )

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["fan", "set-fan", "--all", "--pwm", "150"])

    out = capsys.readouterr().out.strip()
    assert "Applied PWM [150, 150, 150, 150]" in out
    assert "aa:bb:cc:dd:ee:01" in out
    assert "aa:bb:cc:dd:ee:02" in out
    stub = StubTransceiver.instances[-1]
    macs = [call["mac"] for call in stub.pwm_calls]
    assert macs == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    for call in stub.pwm_calls:
        assert call["pwm"] == [150, 150, 150, 150]
        assert call["sequence_index"] == 1


def test_fan_set_fan_sync_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=7,
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

    cli.main(["fan", "pwm-sync", "--mode", "receiver", "--mac", "aa:bb:cc:dd:ee:ff"])

    out = capsys.readouterr().out.strip()
    assert "Enabled motherboard PWM sync (receiver mode)" in out
    stub = StubTransceiver.instances[-1]
    assert stub.pwm_calls == [
        {
            "type": "set_pwm",
            "mac": "aa:bb:cc:dd:ee:ff",
            "pwm": [6, 6, 6, 6],
            "sequence_index": 1,
        }
    ]


def test_fan_set_fan_custom_sequence_index(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=7,
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
            "set-fan",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--pwm",
            "90",
            "--sequence-index",
            "7",
        ]
    )

    capsys.readouterr()
    stub = StubTransceiver.instances[-1]
    assert stub.pwm_calls == [
        {
            "type": "set_pwm",
            "mac": "aa:bb:cc:dd:ee:ff",
            "pwm": [90, 90, 90, 90],
            "sequence_index": 7,
        }
    ]


def test_fan_set_fan_all_sync_cli(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device_bound_a = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:01",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=1,
        device_type=7,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=2,
        raw=bytes(42),
    )
    device_bound_b = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:02",
        master_mac="11:22:33:44:55:66",
        channel=4,
        rx_type=2,
        device_type=6,
        fan_count=3,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=3,
        raw=bytes(42),
    )
    snapshot = wireless.WirelessSnapshot(
        devices=[device_bound_a, device_bound_b], raw=b""
    )

    def factory(*args, **kwargs):
        return StubTransceiver(snapshot=snapshot)

    monkeypatch.setattr(wireless, "WirelessTransceiver", factory)

    cli.main(["fan", "pwm-sync", "--mode", "receiver", "--all"])

    out = capsys.readouterr().out.strip()
    assert "Enabled motherboard PWM sync (receiver mode)" in out
    stub = StubTransceiver.instances[-1]
    macs = [call["mac"] for call in stub.pwm_calls]
    assert macs == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    for call in stub.pwm_calls:
        assert call["pwm"] == [6, 6, 6, 6]
        assert call["sequence_index"] == 1


def test_fan_pwm_sync_receiver_sequence_index(monkeypatch, capsys):
    StubTransceiver.instances.clear()
    device = wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=7,
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
            "pwm-sync",
            "--mode",
            "receiver",
            "--mac",
            "aa:bb:cc:dd:ee:ff",
            "--sequence-index",
            "5",
        ]
    )

    capsys.readouterr()
    stub = StubTransceiver.instances[-1]
    assert stub.pwm_calls == [
        {
            "type": "set_pwm",
            "mac": "aa:bb:cc:dd:ee:ff",
            "pwm": [6, 6, 6, 6],
            "sequence_index": 5,
        }
    ]


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
