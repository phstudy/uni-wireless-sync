"""Packet-level tests of the TL Wireless LCD transport against the vendor app's layout."""

import io
import json

import pytest
from Cryptodome.Cipher import DES
from PIL import Image

from uwscli import cli, lcd
from uwscli.structs import LCDControlMode, LCDControlSetting, ScreenRotation

KEY = b"slv3tuzx"


def decrypt_header(packet: bytes) -> bytes:
    return DES.new(KEY, DES.MODE_CBC, iv=KEY).decrypt(packet[:512])[:504]


class FakeUSB:
    """Records writes; answers reads with a queued reply or a GetVer reply."""

    def __init__(self, *args, **kwargs):
        self.writes = []
        self.replies = []

    def write(self, packet):
        self.writes.append(bytes(packet))
        return len(packet)

    def read(self, size, timeout_ms=None):
        if self.replies:
            return self.replies.pop(0)
        reply = bytearray(512)
        reply[0] = lcd.WirelessCommand.GET_VER
        reply[8:26] = b"tlv2_2024091003_01"
        return bytes(reply)

    def close(self):
        pass

    def headers(self):
        return [decrypt_header(w) for w in self.writes]


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(lcd, "USBEndpointDevice", FakeUSB)
    t = lcd.WirelessUSBTransport(0x1CBE, 0x0006, location_id=1)
    return t


def commands(t):
    return [h[0] for h in t._device.headers()]


def test_header_layout(transport):
    transport.firmware_version()
    header = transport._device.headers()[0]
    assert header[0] == 10 and header[2] == 26 and header[3] == 109
    assert len(transport._device.writes[0]) == 512


@pytest.mark.parametrize(
    "rotation, sent",
    [
        (ScreenRotation.ROTATE_0, 1),
        (ScreenRotation.ROTATE_90, 2),
        (ScreenRotation.ROTATE_180, 3),
        (ScreenRotation.ROTATE_270, 0),
    ],
)
def test_rotation_is_sent_as_the_vendor_app_does(transport, rotation, sent):
    transport.control(
        LCDControlSetting(LCDControlMode.SHOW_JPG, brightness=40, rotation=rotation)
    )
    by_cmd = {h[0]: h for h in transport._device.headers()}
    assert by_cmd[lcd.WirelessCommand.ROTATE][8] == sent
    assert by_cmd[lcd.WirelessCommand.BRIGHTNESS][8] == 40


def test_first_command_sets_frame_rate_120_once(transport):
    transport.send_jpg(b"\xff\xd8x\xff\xd9")
    transport.send_jpg(b"\xff\xd8y\xff\xd9")
    cmds = commands(transport)
    assert cmds[0] == lcd.WirelessCommand.SET_FRAME_RATE
    assert transport._device.headers()[0][8] == 120
    assert cmds.count(lcd.WirelessCommand.SET_FRAME_RATE) == 1
    assert cmds.count(lcd.WirelessCommand.PUSH_JPG) == 2


def test_push_jpg_layout(transport):
    jpg = b"\xff\xd8" + b"a" * 1000 + b"\xff\xd9"
    transport.send_jpg(jpg)
    packet = transport._device.writes[-1]
    header = decrypt_header(packet)
    assert header[0] == 101
    assert int.from_bytes(header[8:12], "big") == len(jpg)
    assert len(packet) == 102400
    assert packet[512 : 512 + len(jpg)] == jpg


def test_boot_image_layout(transport):
    jpg = b"\xff\xd8" + b"b" * 500 + b"\xff\xd9"
    transport.send_boot_jpg(jpg)
    packet = transport._device.writes[-1]
    header = decrypt_header(packet)
    path = b"/usr/data/boot.jpg"
    assert header[0] == 40
    assert int.from_bytes(header[8:12], "big") == len(path)
    assert int.from_bytes(header[12:16], "big") == len(jpg)
    assert header[16 : 16 + len(path)] == path
    assert len(packet) == 102400 and packet[512 : 512 + len(jpg)] == jpg


def test_keep_alive_sends_get_ver(transport):
    assert transport.keep_alive() == "tlv2_2024091003_01"
    assert commands(transport) == [lcd.WirelessCommand.GET_VER]


def test_handshake_reports_group_index(transport):
    reply = bytearray(512)
    reply[0] = lcd.WirelessCommand.GET_POS_INDEX
    reply[8] = 3
    transport._device.replies.append(bytes(reply))
    assert transport.handshake() == {"group_index": 3}


def _png(size, noise=False):
    image = Image.new("RGB", size, (10, 20, 30))
    if noise:
        import random

        rnd = random.Random(1)
        image.putdata(
            [
                (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                for _ in range(size[0] * size[1])
            ]
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_image_scales_to_400_and_encodes_jpeg(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(_png((800, 600)))
    data = lcd.prepare_wireless_image(str(path))
    with Image.open(io.BytesIO(data)) as out:
        assert out.format == "JPEG" and out.size == (400, 400)


def test_prepare_image_fits_the_size_limit(tmp_path):
    path = tmp_path / "noise.png"
    path.write_bytes(_png((400, 400), noise=True))
    data = lcd.prepare_wireless_image(str(path))
    assert len(data) <= lcd.WIRELESS_MAX_JPEG


class DummyLCD:
    def __init__(self, wireless=True):
        self.is_wireless = wireless
        self.sent = []
        self.boot = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send_jpg(self, payload):
        self.sent.append(payload)

    def send_boot_jpg(self, payload):
        self.boot.append(payload)


def _use(monkeypatch, device):
    monkeypatch.setattr(lcd, "TLLCDDevice", lambda serial: device)


def test_cli_send_jpg_prepares_and_saves(monkeypatch, tmp_path, capsys):
    path = tmp_path / "a.png"
    path.write_bytes(_png((100, 50)))
    device = DummyLCD()
    _use(monkeypatch, device)
    cli.main(
        [
            "--output",
            "json",
            "lcd",
            "send-jpg",
            "--serial",
            "x",
            "--file",
            str(path),
            "--save",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert out["saved"] is True and device.boot == device.sent
    assert device.sent[0][:2] == b"\xff\xd8"


def test_cli_send_jpg_raw_is_unchanged(monkeypatch, tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"\xff\xd8raw\xff\xd9")
    device = DummyLCD()
    _use(monkeypatch, device)
    cli.main(["lcd", "send-jpg", "--serial", "x", "--file", str(path), "--raw"])
    assert device.sent == [b"\xff\xd8raw\xff\xd9"] and device.boot == []


def test_cli_save_refused_on_wired_lcd(monkeypatch, tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"\xff\xd8raw\xff\xd9")
    device = DummyLCD(wireless=False)
    _use(monkeypatch, device)
    with pytest.raises(SystemExit):
        cli.main(["lcd", "send-jpg", "--serial", "x", "--file", str(path), "--save"])
    assert device.sent == []


def test_cli_play_video_pushes_every_frame(monkeypatch, tmp_path, capsys):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    device = DummyLCD()
    _use(monkeypatch, device)
    monkeypatch.setattr(
        lcd, "iter_video_frames", lambda p, fps: iter([b"f1", b"f2", b"f3"])
    )
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    cli.main(
        [
            "--output",
            "json",
            "lcd",
            "play-video",
            "--serial",
            "x",
            "--file",
            str(path),
            "--fps",
            "50",
        ]
    )
    assert device.sent == [b"f1", b"f2", b"f3"]
    assert json.loads(capsys.readouterr().out)["frames_sent"] == 3


def test_brightness_range_checked_by_the_parser():
    parser = cli.build_parser()
    parser.parse_args(["lcd", "control", "--brightness", "100"])
    with pytest.raises(SystemExit):
        parser.parse_args(["lcd", "control", "--brightness", "101"])


class ControlLCD(DummyLCD):
    def __init__(self):
        super().__init__()
        self.calls = []

    def set_brightness(self, value):
        self.calls.append(("brightness", value))

    def set_rotation(self, rotation):
        self.calls.append(("rotation", rotation))


def test_cli_control_brightness_only_leaves_rotation_alone(monkeypatch):
    device = ControlLCD()
    _use(monkeypatch, device)
    cli.main(["lcd", "control", "--serial", "x", "--brightness", "50"])
    assert device.calls == [("brightness", 50)]


def test_cli_control_rotation_only(monkeypatch):
    device = ControlLCD()
    _use(monkeypatch, device)
    cli.main(["lcd", "control", "--serial", "x", "--rotation", "90"])
    assert device.calls == [("rotation", ScreenRotation.ROTATE_90)]


def test_cli_control_needs_a_setting_on_wireless(monkeypatch):
    device = ControlLCD()
    _use(monkeypatch, device)
    with pytest.raises(SystemExit):
        cli.main(["lcd", "control", "--serial", "x"])
    assert device.calls == []


def _fake_ffmpeg(tmp_path, monkeypatch, frames, exit_code, delay=0.5):
    script = tmp_path / "ffmpeg"
    size = 400 * 400 * 3 * frames
    script.write_text(
        "#!/bin/sh\n"
        f"head -c {size} /dev/zero\n"
        "exec 1>&-\n"
        f"sleep {delay}\n"
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:" + __import__("os").environ["PATH"])


def test_video_frames_report_an_ffmpeg_failure_after_the_last_frame(
    tmp_path, monkeypatch
):
    # ffmpeg still running when its output ends must not be killed and counted as success.
    _fake_ffmpeg(tmp_path, monkeypatch, frames=2, exit_code=1)
    frames = lcd.iter_video_frames("clip.mp4", 5)
    assert next(frames) and next(frames)
    with pytest.raises(lcd.LCDDeviceError, match="exit 1"):
        next(frames)


def test_video_frames_stopped_early_end_ffmpeg_quietly(tmp_path, monkeypatch):
    _fake_ffmpeg(tmp_path, monkeypatch, frames=3, exit_code=0, delay=5)
    frames = lcd.iter_video_frames("clip.mp4", 5)
    next(frames)
    frames.close()  # no error, and ffmpeg is gone
