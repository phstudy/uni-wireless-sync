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
