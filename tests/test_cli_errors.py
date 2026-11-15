import pytest

from uwscli import cli


def test_set_fan_requires_pwm():
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "fan",
                "set-fan",
                "--mac",
                "aa:bb:cc:dd:ee:ff",
            ]
        )
    assert "Either --pwm or --pwm-list must be provided" in str(exc.value)


class _EmptySnapshotTx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def list_devices(self):
        from uwscli.wireless import WirelessSnapshot

        return WirelessSnapshot(devices=[], raw=b"")

    def local_master(self, snapshot=None):
        from uwscli.wireless import LocalMaster

        return LocalMaster(mac="11:22:33:44:55:66", channel=8)


def test_pwm_sync_all_requires_bound_device(monkeypatch):
    monkeypatch.setattr(
        "uwscli.wireless.WirelessTransceiver",
        lambda *args, **kwargs: _EmptySnapshotTx(),
    )
    monkeypatch.setattr(
        "uwscli.tlcontroller.set_motherboard_rpm_sync", lambda enable: None
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "fan",
                "pwm-sync",
                "--all",
            ]
        )
    assert "No bound wireless devices found" in str(exc.value)


def test_set_fan_all_requires_bound_device(monkeypatch):
    monkeypatch.setattr(
        "uwscli.wireless.WirelessTransceiver",
        lambda *args, **kwargs: _EmptySnapshotTx(),
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "fan",
                "set-fan",
                "--all",
                "--pwm",
                "120",
            ]
        )
    assert "No bound wireless devices found" in str(exc.value)


def test_pwm_sync_receiver_once_invalid():
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "fan",
                "pwm-sync",
                "--mode",
                "receiver",
                "--mac",
                "aa:bb:cc:dd:ee:ff",
                "--once",
            ]
        )
    assert "--once is only valid when --mode controller" in str(exc.value)


def test_pwm_sync_receiver_interval_invalid():
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "fan",
                "pwm-sync",
                "--mode",
                "receiver",
                "--mac",
                "aa:bb:cc:dd:ee:ff",
                "--interval",
                "0.5",
            ]
        )
    assert "--interval is only valid when --mode controller" in str(exc.value)


MERGE = ["fan", "set-led", "--mode", "merge", "--effect", "breathing"]


def test_merge_takes_at_most_four_colours():
    colours = "255,0,0;0,255,0;0,0,255;255,255,0;255,0,255"
    with pytest.raises(SystemExit) as exc:
        cli.main([*MERGE, "--all", "--effect-colors", colours])
    assert "at most four colours" in str(exc.value)


def test_merge_refuses_flip():
    with pytest.raises(SystemExit) as exc:
        cli.main([*MERGE, "--all", "--flip"])
    assert "--flip does nothing in merge mode" in str(exc.value)


def test_set_led_needs_a_target_except_merge_with_order(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        cli.main(["fan", "set-led", "--mode", "effect", "--effect", "meteor"])
    assert "needs --mac or --all" in str(exc.value)
    calls = []
    monkeypatch.setattr(cli, "_set_led_merge", lambda args: calls.append(args.order))
    cli.main([*MERGE, "--order", "aa:bb:cc:dd:ee:01,aa:bb:cc:dd:ee:02"])
    assert calls == ["aa:bb:cc:dd:ee:01,aa:bb:cc:dd:ee:02"]
