from uwscli import led, wireless
from uwscli.structs import WirelessDeviceInfo


def _make_device():
    return WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:ff",
        master_mac="11:22:33:44:55:66",
        channel=3,
        rx_type=2,
        device_type=1,
        fan_count=4,
        pwm_values=(0, 0, 0, 0),
        fan_rpm=(0, 0, 0, 0),
        command_sequence=1,
        raw=bytes([0] * 41 + [28]),
    )


def test_transmit_led_effect_streams_first_packet_payload(monkeypatch):
    device = _make_device()
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=b"")

    led_count = 120
    total_frames = 1
    raw_rgb = bytes((idx % 256) for idx in range(led_count * total_frames * 3))
    compressed = led.compress_led_payload(raw_rgb)

    assert len(compressed) > wireless.FIRST_LED_PACKET_DATA_MAX
    first_chunk_len = min(len(compressed), wireless.FIRST_LED_PACKET_DATA_MAX)

    tx = wireless.WirelessTransceiver.__new__(wireless.WirelessTransceiver)
    payloads = []

    def fake_send(channel, rx, payload):
        payloads.append(bytes(payload))

    monkeypatch.setattr(tx, "_send_rf_data", fake_send)
    monkeypatch.setattr(wireless.time, "sleep", lambda *args, **kwargs: None)

    tx._transmit_led_effect(
        device,
        snapshot,
        raw_rgb,
        led_count=led_count,
        total_frames=total_frames,
        dict_size=4096,
        broadcast=False,
        interval_ms=50,
    )

    assert payloads, "No LED packets were transmitted"

    packets_by_index = {}
    for payload in payloads:
        packets_by_index[payload[18]] = payload

    first_packet = packets_by_index[0]
    total_packets = first_packet[19]
    assert total_packets == len(packets_by_index)

    first_chunk = first_packet[
        wireless.FIRST_LED_PACKET_DATA_OFFSET : wireless.FIRST_LED_PACKET_DATA_OFFSET
        + first_chunk_len
    ]
    assert first_chunk == compressed[:first_chunk_len]

    collected = bytearray()
    for index in range(total_packets):
        payload = packets_by_index[index]
        if index == 0:
            chunk_len = min(
                len(compressed) - len(collected), wireless.FIRST_LED_PACKET_DATA_MAX
            )
            chunk = payload[
                wireless.FIRST_LED_PACKET_DATA_OFFSET : wireless.FIRST_LED_PACKET_DATA_OFFSET
                + chunk_len
            ]
        else:
            remaining = len(compressed) - len(collected)
            chunk_len = min(remaining, wireless.LED_DATA_CHUNK)
            chunk = payload[20 : 20 + chunk_len]
        collected.extend(chunk)

    assert bytes(collected) == compressed
