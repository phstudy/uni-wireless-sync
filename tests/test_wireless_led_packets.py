"""RF packets of wireless commands, checked against the vendor app's layout."""

import pytest

from uwscli import tinyuz, wireless

MAC = "aa:bb:cc:dd:ee:01"
MASTER = "11:22:33:44:55:66"
INDEX = bytes([1, 2, 3, 4])


def _packets(compressed, **kw):
    args = {"led_count": 78, "total_frames": 10, "interval_ms": 50}
    args.update(kw)
    return wireless.build_led_packets(MAC, MASTER, INDEX, compressed, **args)


def test_packet_zero_is_header_only():
    data = bytes(range(256)) * 3  # 768 bytes -> 4 data packets
    packets = _packets(data)
    head = packets[0]
    assert len(head) == wireless.RF_PAYLOAD_SIZE
    assert head[0:2] == b"\x12\x20"
    assert head[2:8] == bytes.fromhex("aabbccddee01")
    assert head[8:14] == bytes.fromhex("112233445566")
    assert head[14:18] == INDEX
    assert head[18] == 0 and head[19] == 1 + 4 == len(packets)
    assert int.from_bytes(head[20:24], "big") == len(data)
    assert head[24] == 0
    assert int.from_bytes(head[25:27], "big") == 10
    assert head[27] == 78
    assert int.from_bytes(head[32:34], "big") == 50 and head[34] == 0
    assert head[35:] == bytes(len(head) - 35)  # no effect data in packet 0


def test_data_packets_carry_220_bytes_from_byte_20():
    data = bytes((i * 7) & 0xFF for i in range(500))
    packets = _packets(data)
    assert len(packets) == 1 + 3
    joined = b""
    for number, packet in enumerate(packets[1:], start=1):
        assert packet[18] == number and packet[19] == len(packets)
        assert packet[14:18] == INDEX
        joined += packet[20:240]
    assert joined[: len(data)] == data and joined[len(data) :] == bytes(
        len(joined) - len(data)
    )


def test_fractional_interval():
    head = _packets(b"x", interval_ms=33.33)[0]
    assert int.from_bytes(head[32:34], "big") == 33 and head[34] == 33


def test_effect_index_never_repeats_the_running_one():
    first = wireless._generate_effect_index()
    assert len(first) == 4 and first != bytes(4)
    assert wireless._generate_effect_index(avoid=first) != first


class FakeTx(wireless.WirelessTransceiver):
    """Transceiver without USB: records RF payloads, serves scripted device lists."""

    def __init__(self, devices, echo_effect=True):
        self._local_master = wireless.LocalMaster(MASTER, 8)
        self.sent = []
        self.devices = devices
        self.echo_effect = echo_effect

    def close(self):
        pass

    def list_devices(self):
        return wireless.WirelessSnapshot(devices=list(self.devices), raw=b"")

    def _send_rf_data(self, channel, rx, payload):
        self.sent.append((channel, rx, bytes(payload)))
        if payload[1] == wireless.RF_CMD_LED_EFFECT and self.echo_effect:
            dev = self.devices[0]
            self.devices[0] = wireless.WirelessDeviceInfo(
                **{**dev.__dict__, "effect_index": bytes(payload[14:18])}
            )
        if payload[1] == wireless.RF_CMD_BIND_PWM:
            target = payload[2:8].hex(":")
            for i, dev in enumerate(self.devices):
                if dev.mac == target:
                    self.devices[i] = wireless.WirelessDeviceInfo(
                        **{
                            **dev.__dict__,
                            "master_mac": payload[8:14].hex(":"),
                            "rx_type": payload[14],
                            "pwm_values": tuple(payload[17:21]),
                            "channel": payload[15],
                        }
                    )
        if payload[1] in (wireless.RF_CMD_IDENTIFY, wireless.RF_CMD_REBOOT_LCD):
            dev = self.devices[0]
            self.devices[0] = wireless.WirelessDeviceInfo(
                **{**dev.__dict__, "command_sequence": payload[17]}
            )


def _device(mac=MAC, master=MASTER, rx=3, channel=8, seq=254):
    return wireless.WirelessDeviceInfo(
        mac=mac,
        master_mac=master,
        channel=channel,
        rx_type=rx,
        device_type=0,
        fan_count=3,
        pwm_values=(100, 100, 100, 100),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=seq,
        raw=bytes(42),
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(wireless.time, "sleep", lambda s: None)


def test_led_effect_is_sent_then_saved(monkeypatch):
    tx = FakeTx([_device()])
    tx.set_led_static(MAC, (255, 0, 0))
    led = [p for _, _, p in tx.sent if p[1] == wireless.RF_CMD_LED_EFFECT]
    assert [p[18] for p in led[:4]] == [0, 0, 0, 0]  # header sent 4 times
    compressed = b"".join(p[20:240] for p in led[4:])[
        : int.from_bytes(led[0][20:24], "big")
    ]
    assert tinyuz.decompress(compressed) == bytes([255, 0, 0]) * 78
    channel, rx, save = tx.sent[-1]
    assert save[0:2] == b"\x12\x15" and save[2:8] == b"\xff" * 6 and save[14] == 0xFF
    assert (channel, rx) == (8, 0xFF)


def test_led_effect_resent_until_reported_then_fails(monkeypatch):
    monkeypatch.setattr(wireless, "LED_APPLY_WAIT", 0)
    tx = FakeTx([_device()], echo_effect=False)
    with pytest.raises(wireless.WirelessError, match="did not take"):
        tx.set_led_static(MAC, (0, 0, 255))
    headers = [
        p for _, _, p in tx.sent if p[1] == wireless.RF_CMD_LED_EFFECT and p[18] == 0
    ]
    assert len(headers) == 4 * wireless.LED_APPLY_ATTEMPTS
    assert not any(p[1] == wireless.RF_CMD_SAVE_CONFIG for _, _, p in tx.sent)


def test_effect_too_large_is_refused(monkeypatch):
    monkeypatch.setattr(wireless, "LED_MAX_COMPRESSED", 10)
    tx = FakeTx([_device()])
    with pytest.raises(wireless.WirelessError, match="too large"):
        tx.set_led_rainbow(MAC, frames=4)
    assert tx.sent == []


def test_device_of_another_master_is_driven_with_its_master_mac():
    other = "99:99:99:99:99:99"
    tx = FakeTx([_device(master=other)])
    tx.set_led_static(MAC, (1, 2, 3))
    led = [p for _, _, p in tx.sent if p[1] == wireless.RF_CMD_LED_EFFECT]
    assert led and all(p[8:14] == bytes.fromhex("999999999999") for p in led)
    # the attached master saves only its own devices
    assert not any(p[1] == wireless.RF_CMD_SAVE_CONFIG for _, _, p in tx.sent)


def test_unbound_device_is_refused():
    tx = FakeTx([_device(master="00:00:00:00:00:00")])
    with pytest.raises(wireless.WirelessError, match="not bound"):
        tx.set_led_static(MAC, (1, 2, 3))


def test_pwm_packet_uses_master_channel_and_device_number():
    other = _device(mac="aa:bb:cc:dd:ee:00", rx=1)
    tx = FakeTx([other, _device(channel=8)])
    tx.set_pwm(MAC, [10, 20, 30, 40])
    channel, rx, p = tx.sent[-1]
    assert p[0:2] == b"\x12\x10" and p[8:14] == bytes.fromhex("112233445566")
    assert (
        p[14] == 3 and p[15] == 8 and p[16] == 2 and p[17:21] == bytes([10, 20, 30, 40])
    )
    assert (channel, rx) == (8, 3)


def test_bind_picks_free_rx_and_numbers_the_device():
    bound = _device(mac="aa:bb:cc:dd:ee:00", rx=1)
    new = _device(master="00:00:00:00:00:00", rx=0, channel=4)
    tx = FakeTx([bound, new])
    tx.bind_device(MAC)
    channel, rx, p = tx.sent[0]
    assert p[1] == wireless.RF_CMD_BIND_PWM and p[8:14] == bytes.fromhex("112233445566")
    assert p[14] == 2 and p[15] == 8 and p[16] == 2
    assert (channel, rx) == (4, 0)  # sent where the device listens now


def test_identify_uses_next_sequence_and_wraps():
    tx = FakeTx([_device(seq=254)])
    assert tx.identify(MAC) is True
    _, _, p = tx.sent[0]
    assert p[0:2] == b"\x12\x12" and p[16] == 1 and p[17] == 1  # 255 wraps to 1


def test_reboot_lcd_packet():
    tx = FakeTx([_device(seq=7)])
    assert tx.reboot_lcd(MAC) is True
    _, _, p = tx.sent[0]
    assert p[0:2] == b"\x12\x16" and p[17] == 8


def test_parse_record_masks_flags_and_reads_versions():
    record = bytearray(42)
    record[0:6] = bytes.fromhex("aabbccddee01")
    record[6:12] = bytes.fromhex("112233445566")
    record[12], record[13], record[18], record[19] = (
        8,
        3,
        0,
        13,
    )  # 13 -> 3 fans, right attach
    record[20:24] = INDEX
    record[24:28] = bytes([40, 40, 40, 0])
    record[28:36] = bytes([0xC3, 0xE8, 0x23, 0xE8, 0x13, 0xE8, 0x23, 0xE8])
    record[36:40] = bytes([100, 100, 100, 0])
    record[40] = 9
    record[41] = 28
    page = bytes(4) + bytes(record)
    (dev,) = wireless.parse_device_records(1, page)
    assert dev.fan_count == 3
    assert dev.fan_rpm == (1000, 1000, 1000, 1000)
    assert dev.sync_line and dev.mb_light_sync and not dev.pwm_line and not dev.fg_line
    assert dev.rf_version == 0x12
    assert dev.effect_index == INDEX and dev.fans_type == (40, 40, 40, 0)
    assert dev.command_sequence == 9


def test_masters_are_listed_apart():
    master = bytearray(42)
    master[0:6] = bytes.fromhex("112233445566")
    master[12] = 12
    master[18] = 0xFF
    master[41] = 28
    device = bytearray(42)
    device[0:6] = bytes.fromhex("aabbccddee01")
    device[41] = 28
    records = wireless.parse_device_records(2, bytes(4) + bytes(master) + bytes(device))
    assert [d.is_master for d in records] == [True, False]


def test_bind_keeps_a_motherboard_synced_device_following_the_motherboard():
    new = _device(mac="aa:bb:cc:dd:01:e1", master="00:00:00:00:00:00", rx=0)
    new = wireless.WirelessDeviceInfo(**{**new.__dict__, "pwm_values": (0, 0, 0, 0)})
    tx = FakeTx([new])
    tx.bind_device("aa:bb:cc:dd:01:e1")
    _, _, p = tx.sent[0]
    assert p[17:21] == bytes([6, 6, 6, 6])


def test_resends_repeat_each_data_packet_more(monkeypatch):
    monkeypatch.setattr(wireless, "LED_APPLY_WAIT", 0)
    tx = FakeTx([_device()], echo_effect=False)
    with pytest.raises(wireless.WirelessError):
        tx.set_led_rainbow(MAC, frames=4)
    data = [
        p for _, _, p in tx.sent if p[1] == wireless.RF_CMD_LED_EFFECT and p[18] == 1
    ]
    assert len(data) == sum(wireless.LED_PACKET_COPIES)


def test_unbind_keeps_motherboard_sync_and_retries_until_unbound():
    dev = wireless.WirelessDeviceInfo(
        **{**_device(mac="aa:bb:cc:dd:01:e1").__dict__, "pwm_values": (0, 0, 0, 0)}
    )
    tx = FakeTx([dev])
    result = tx.unbind_device("aa:bb:cc:dd:01:e1")
    assert not result.is_bound and result.pwm_values == (6, 6, 6, 6)


def test_set_channel_moves_devices_of_the_attached_master_only():
    mine = _device(channel=8)
    other = _device(mac="aa:bb:cc:dd:ee:02", master="99:99:99:99:99:99", channel=8)
    tx = FakeTx([mine, other])
    assert tx.set_channel(7) == {MAC: True}
    bind = [p for _, _, p in tx.sent if p[1] == wireless.RF_CMD_BIND_PWM]
    assert bind[0][15] == 7 and bind[0][8:14] == bytes.fromhex("112233445566")
    assert tx.devices[1].channel == 8
    assert any(p[1] == wireless.RF_CMD_SAVE_CONFIG for _, _, p in tx.sent)


def test_set_channel_rejects_channels_the_app_does_not_offer():
    tx = FakeTx([_device()])
    with pytest.raises(wireless.WirelessError):
        tx.set_channel(2)


def test_interval_hundredths_carry_into_whole_ms():
    head = _packets(b"x", interval_ms=12.996)[0]
    assert int.from_bytes(head[32:34], "big") == 13 and head[34] == 0


class NoMasterReplyTx(FakeTx):
    """The controller does not answer the master MAC query."""

    def __init__(self, devices, echo_effect=True):
        super().__init__(devices, echo_effect)
        self._local_master = None

    def local_master(self, snapshot=None):
        raise wireless.WirelessError(
            "The wireless controller did not report its MAC address"
        )


def test_effect_that_was_taken_is_not_an_error_when_the_master_query_fails():
    tx = NoMasterReplyTx([_device()])
    tx.set_led_static(MAC, (255, 0, 0))  # no exception
    assert not any(p[1] == 0x15 for _, _, p in tx.sent), "not saved without the master"


def test_effect_failure_is_reported_even_when_the_master_query_fails(monkeypatch):
    monkeypatch.setattr(wireless, "LED_APPLY_WAIT", 0)
    tx = NoMasterReplyTx([_device()], echo_effect=False)
    with pytest.raises(wireless.WirelessError, match="did not take the LED effect"):
        tx.set_led_static(MAC, (255, 0, 0))


def test_unbind_that_worked_is_not_an_error_when_the_master_query_fails():
    tx = NoMasterReplyTx([_device()])
    after = tx.unbind_device(MAC)
    assert not after.is_bound


def test_bind_reaches_a_device_listed_on_channel_0_on_the_masters_channel():
    new = _device(master="00:00:00:00:00:00", rx=0, channel=0)
    tx = FakeTx([new])
    tx.bind_device(MAC)
    assert {channel for channel, _, _ in tx.sent} == {8}
