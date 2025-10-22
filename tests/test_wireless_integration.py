import pytest

from uwscli import wireless


def _build_listing_page(
    *, mac: str, master_mac: str, channel: int, rx_type: int
) -> bytes:
    data = bytearray(wireless.RF_PAGE_STRIDE)
    data[0] = wireless.RF_GET_DEV_CMD
    data[1] = 1  # single device
    record = bytearray(42)
    record[0:6] = bytes(int(part, 16) for part in mac.split(":"))
    record[6:12] = bytes(int(part, 16) for part in master_mac.split(":"))
    record[12] = channel
    record[13] = rx_type
    record[18] = 7  # arbitrary device type
    record[19] = 4  # fan count
    record[28] = 0x03
    record[29] = 0xE8  # 1000 RPM on fan 0
    record[36:40] = bytes([10, 20, 30, 40])
    record[41] = 28
    data[4 : 4 + len(record)] = record
    return bytes(data)


class _FakeUSBDevice:
    def __init__(self, role: str, buffer: bytes | None = None):
        self.role = role
        self.buffer = buffer or b""
        self._read_consumed = False
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes | bytearray):
        if self.role == "sender":
            self.writes.append(bytes(data))
        elif self.role == "receiver":
            self._read_consumed = False
        self._last_write = bytes(data)

    def read(self, size: int) -> bytes:
        if self.role != "receiver" or self._read_consumed:
            return b""
        self._read_consumed = True
        return self.buffer

    def close(self):
        self.closed = True


@pytest.fixture
def fake_usb(monkeypatch):
    sender = _FakeUSBDevice("sender")
    receiver = _FakeUSBDevice(
        "receiver",
        buffer=_build_listing_page(
            mac="aa:bb:cc:dd:ee:ff",
            master_mac="11:22:33:44:55:66",
            channel=3,
            rx_type=2,
        ),
    )

    def factory(vid, pid, timeout_ms=None):
        if pid == wireless.RF_SENDER_PID:
            return sender
        return receiver

    monkeypatch.setattr(wireless, "USBEndpointDevice", factory)
    monkeypatch.setattr(wireless, "find_devices_by_vid_pid", lambda vid, pid: [])
    return sender, receiver


def test_set_pwm_uses_usb_sender(fake_usb):
    sender, _ = fake_usb
    with wireless.WirelessTransceiver() as tx:
        tx.set_pwm("aa:bb:cc:dd:ee:ff", [120, 121, 122, 123])

    # Four 60-byte chunks pushed through the sender
    assert len(sender.writes) == 4
    first_chunk = sender.writes[0]
    assert first_chunk[0] == wireless.RF_PACKET_HEADER
    pwm_bytes = first_chunk[4 + 17 : 4 + 21]
    assert pwm_bytes == bytes([120, 121, 122, 123])


def test_set_pwm_sync_enable_emits_sentinel(fake_usb):
    sender, _ = fake_usb
    with wireless.WirelessTransceiver() as tx:
        tx.set_pwm_sync("aa:bb:cc:dd:ee:ff", enable=True)

    pwm_bytes = sender.writes[0][4 + 17 : 4 + 21]
    assert pwm_bytes == bytes([6, 6, 6, 6])


def test_snapshot_motherboard_pwm_extracts_ratio():
    raw = bytes([wireless.RF_GET_DEV_CMD, 1, 2, 6])
    snapshot = wireless.WirelessSnapshot(devices=[], raw=raw)
    assert snapshot.motherboard_pwm() == int(255 * 6 / (6 + 2))


def test_run_pwm_sync_loop_sends_updates(monkeypatch):
    pwm_raw = bytes([wireless.RF_GET_DEV_CMD, 1, 2, 6])
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
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=pwm_raw)

    class LoopStub:
        instances = []

        def __init__(self):
            self.sent = []
            LoopStub.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_devices(self):
            return snapshot

        def set_pwm_direct(self, target, pwm_values, sequence_index=1, **kwargs):
            self.sent.append(
                {
                    "mac": target.mac,
                    "pwm": tuple(pwm_values),
                    "sequence": sequence_index,
                }
            )

    monkeypatch.setattr(
        wireless, "WirelessTransceiver", lambda *args, **kwargs: LoopStub()
    )

    wireless.run_pwm_sync_loop(["aa:bb:cc:dd:ee:ff"], interval=0.1, max_cycles=1)

    stub = LoopStub.instances[-1]
    assert stub.sent == [
        {
            "mac": "aa:bb:cc:dd:ee:ff",
            "pwm": (191, 191, 191, 191),
            "sequence": (device.command_sequence + 1) & 0xFF,
        }
    ]


def test_run_pwm_sync_loop_skips_when_no_pwm(monkeypatch):
    raw_missing = bytes([wireless.RF_GET_DEV_CMD, 1, 0x80, 0])
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
    snapshot = wireless.WirelessSnapshot(devices=[device], raw=raw_missing)

    class SkipStub:
        calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_devices(self):
            return snapshot

        def set_pwm_direct(self, *args, **kwargs):
            SkipStub.calls.append(kwargs)

    SkipStub.calls = []
    monkeypatch.setattr(
        wireless, "WirelessTransceiver", lambda *args, **kwargs: SkipStub()
    )

    wireless.run_pwm_sync_loop(["aa:bb:cc:dd:ee:ff"], interval=0.1, max_cycles=1)

    assert SkipStub.calls == []


def test_run_pwm_sync_loop_reuses_previous_pwm(monkeypatch):
    pwm_raw = bytes([wireless.RF_GET_DEV_CMD, 1, 2, 6])
    raw_missing = bytes([wireless.RF_GET_DEV_CMD, 1, 0x80, 0])
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
    snapshots = [
        wireless.WirelessSnapshot(devices=[device], raw=pwm_raw),
        wireless.WirelessSnapshot(devices=[device], raw=raw_missing),
    ]

    class ReuseStub:
        sent = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_devices(self):
            if snapshots:
                return snapshots.pop(0)
            return wireless.WirelessSnapshot(devices=[device], raw=raw_missing)

        def set_pwm_direct(self, target, pwm_values, sequence_index=1, **kwargs):
            ReuseStub.sent.append(
                {
                    "mac": target.mac,
                    "pwm": tuple(pwm_values),
                    "sequence": sequence_index,
                }
            )

    ReuseStub.sent = []
    monkeypatch.setattr(
        wireless, "WirelessTransceiver", lambda *args, **kwargs: ReuseStub()
    )

    wireless.run_pwm_sync_loop(["aa:bb:cc:dd:ee:ff"], interval=0.1, max_cycles=2)

    assert ReuseStub.sent == [
        {
            "mac": "aa:bb:cc:dd:ee:ff",
            "pwm": (191, 191, 191, 191),
            "sequence": (device.command_sequence + 1) & 0xFF,
        }
    ]


def test_run_pwm_sync_loop_stop_after_first(monkeypatch):
    pwm_raw = bytes([wireless.RF_GET_DEV_CMD, 1, 2, 6])
    pwm_raw2 = bytes([wireless.RF_GET_DEV_CMD, 1, 1, 6])
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

    snapshots = [
        wireless.WirelessSnapshot(devices=[device], raw=pwm_raw),
        wireless.WirelessSnapshot(devices=[device], raw=pwm_raw2),
    ]

    class StopStub:
        sent = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_devices(self):
            if snapshots:
                return snapshots.pop(0)
            return wireless.WirelessSnapshot(devices=[device], raw=pwm_raw2)

        def set_pwm_direct(self, target, pwm_values, sequence_index=1, **kwargs):
            StopStub.sent.append(
                {
                    "mac": target.mac,
                    "pwm": tuple(pwm_values),
                    "sequence": sequence_index,
                }
            )

    StopStub.sent = []
    monkeypatch.setattr(
        wireless, "WirelessTransceiver", lambda *args, **kwargs: StopStub()
    )

    wireless.run_pwm_sync_loop(
        ["aa:bb:cc:dd:ee:ff"],
        interval=0.1,
        stop_after_first_send=True,
    )

    assert StopStub.sent == [
        {
            "mac": "aa:bb:cc:dd:ee:ff",
            "pwm": (191, 191, 191, 191),
            "sequence": (device.command_sequence + 1) & 0xFF,
        }
    ]
