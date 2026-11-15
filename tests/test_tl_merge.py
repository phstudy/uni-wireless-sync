"""Merged lighting across fan groups (the vendor app's merge mode)."""

import hashlib
import json
from pathlib import Path

import pytest

from uwscli import tl_merge, wireless
from uwscli.tl_effects import TLEffects

DATA = Path(__file__).parent / "data"
COLOUR_SETS = [
    [[255, 0, 0], [0, 0, 255], [0, 128, 0], [255, 255, 0]],
    [
        [0xFF, 0, 0x96],
        [0, 0xD7, 0xFF],
        [0, 0xFF, 0],
        [0xFF, 0xD7, 0],
        [10, 20, 30],
        [200, 100, 50],
    ],
]


def test_strips_and_slices_match_the_vendor_app():
    """Hashes of the app's strip renders, sliced for a group, for the 9 merge effects."""
    by_mode = {v: k for k, v in tl_merge.MERGE_EFFECTS.items()}
    for key, digest in json.loads((DATA / "tl_merge_strip.json").read_text()).items():
        mode, dots, bright, direction, cs, start, stop, gdir, frames = map(
            int, key.split("/")
        )
        strip = tl_merge.render_strip(
            by_mode[mode], dots, bright, direction, COLOUR_SETS[cs]
        )
        assert len(strip) == frames, key
        sliced = tl_merge.group_slice(strip, start, stop, gdir)
        data = bytes(v for f in sliced for c in f for v in c)
        assert hashlib.sha256(data).hexdigest()[:16].upper() == digest, key


def test_groups_get_consecutive_slices():
    frames = tl_merge.merge_frames(
        TLEffects.STATIC_COLOR, [2, 1], bright=255, direction=0, colours=[[255, 0, 0]]
    )
    assert [len(g[0][0]) for g in frames] == [52, 26]
    assert frames[0][0][0][0] == 254


def test_interval_is_speed_times_12ms():
    assert tl_merge.merge_interval(4) == 48 and tl_merge.merge_interval(1) == 84


def _device(mac, fans):
    return wireless.WirelessDeviceInfo(
        mac=mac,
        master_mac="11:22:33:44:55:66",
        channel=8,
        rx_type=1,
        device_type=0,
        fan_count=fans,
        pwm_values=(6, 6, 6, 6),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=0,
        raw=bytes(42),
    )


class FakeTx(wireless.WirelessTransceiver):
    def __init__(self, devices):
        self._local_master = wireless.LocalMaster("11:22:33:44:55:66", 8)
        self.devices = devices
        self.events = []

    def close(self):
        pass

    def list_devices(self):
        self.events.append("list")
        return wireless.WirelessSnapshot(devices=list(self.devices), raw=b"")

    def _send_rf_data(self, channel, rx, payload):
        if payload[1] == wireless.RF_CMD_LED_EFFECT:
            mac = payload[2:8].hex(":")
            self.events.append(("send", mac))
            for i, dev in enumerate(self.devices):
                if dev.mac == mac:
                    self.devices[i] = wireless.WirelessDeviceInfo(
                        **{**dev.__dict__, "effect_index": bytes(payload[14:18])}
                    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(wireless.time, "sleep", lambda s: None)


def test_merge_sends_every_group_before_waiting_with_one_index():
    a, b = "aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"
    tx = FakeTx([_device(a, 2), _device(b, 3)])
    assert tx.set_led_merge(TLEffects.WAVE, [b, a], reversed_macs=[a]) == [b, a]
    sends = [e for e in tx.events if e != "list"]
    first_list_after_send = tx.events.index("list", tx.events.index(sends[0]))
    sent_before_waiting = {
        e[1] for e in tx.events[:first_list_after_send] if e != "list"
    }
    assert sent_before_waiting == {a, b}
    assert tx.devices[0].effect_index == tx.devices[1].effect_index != bytes(4)


def test_per_group_effects_are_not_merged_but_sent_to_each_group():
    a, b = "aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"
    tx = FakeTx([_device(a, 1), _device(b, 1)])
    tx.set_led_merge(TLEffects.TWINKLE, [a, b])
    assert {e[1] for e in tx.events if e != "list"} == {a, b}


def test_effects_the_app_does_not_merge_are_refused():
    tx = FakeTx([_device("aa:bb:cc:dd:ee:01", 1)])
    with pytest.raises(wireless.WirelessError, match="cannot be merged"):
        tx.set_led_merge(TLEffects.COLLIDE, ["aa:bb:cc:dd:ee:01"])
