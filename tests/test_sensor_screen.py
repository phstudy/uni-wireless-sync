"""LCD sensor screens: sensor readers, rendering and the CLI."""

import datetime

import pytest
from PIL import Image

from uwscli import cli, sensor_screen, sensors, wireless


def test_cpu_temperature_prefers_tctl(tmp_path, monkeypatch):
    hw = tmp_path / "hwmon3"
    hw.mkdir()
    (hw / "name").write_text("k10temp\n")
    (hw / "temp1_input").write_text("55250\n")
    (hw / "temp1_label").write_text("Tctl\n")
    (hw / "temp3_input").write_text("40000\n")
    (hw / "temp3_label").write_text("Tccd1\n")
    monkeypatch.setattr(sensors, "HWMON_ROOT", str(tmp_path))
    assert sensors.cpu_temperature() == 55.25


def test_cpu_load_from_proc_stat(monkeypatch):
    samples = iter(["cpu 100 0 100 800 0 0 0 0", "cpu 150 0 150 900 0 0 0 0"])
    monkeypatch.setattr(sensors, "_read", lambda path: next(samples))
    load = sensors.CpuLoad()
    assert load.read() == pytest.approx(50.0)


def _device(rpm):
    return wireless.WirelessDeviceInfo(
        mac="aa:bb:cc:dd:ee:01",
        master_mac="11:22:33:44:55:66",
        channel=8,
        rx_type=1,
        device_type=0,
        fan_count=2,
        pwm_values=(6, 6, 6, 6),
        fan_rpm=rpm,
        command_sequence=0,
        raw=bytes(42),
    )


def test_fan_speed_averages_running_fans_and_keeps_last_when_busy(monkeypatch):
    results = [wireless.WirelessSnapshot(devices=[_device((900, 1100, 0, 0))], raw=b"")]

    def read():
        if results:
            return results.pop()
        raise wireless.WirelessError("busy")

    monkeypatch.setattr(wireless, "read_device_list", read)
    monkeypatch.setattr(sensors.time, "sleep", lambda s: None)
    fan = sensors.FanSpeed(None)
    assert fan.read() == 1000
    assert fan.read() == 1000


@pytest.mark.parametrize("value", [-5, 0, 42, 250])
def test_gauge_renders_any_value(value):
    image = sensor_screen.render(value, sensors.METRICS["cpu-temp"], "red")
    assert image.size == (400, 400) and image.mode == "RGB"


def test_clock_renders():
    image = sensor_screen.render_clock(
        datetime.datetime(2026, 11, 16, 9, 5, 30), "green"
    )
    assert image.size == (400, 400)


def test_cli_writes_a_preview_without_a_panel(monkeypatch, tmp_path):
    monkeypatch.setattr(sensors, "gpu_temperature", lambda: 61.0)
    out = tmp_path / "gpu.png"
    cli.main(["lcd", "sensor", "--metric", "gpu-temp", "--output", str(out)])
    assert Image.open(out).size == (400, 400)


def test_cli_pushes_once_to_the_panel(monkeypatch):
    sent = []

    class Panel:
        is_wireless = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send_jpg(self, data):
            sent.append(data)

    monkeypatch.setattr(cli.lcd, "TLLCDDevice", lambda serial: Panel())
    cli.main(["lcd", "sensor", "--metric", "clock", "--serial", "x", "--once"])
    assert len(sent) == 1 and sent[0][:2] == b"\xff\xd8"


def test_png_output_keeps_the_global_json_format(tmp_path, capsys):
    # lcd sensor --output <png> used to overwrite the global --output json.
    png = tmp_path / "frame.png"
    cli.main(
        ["--output", "json", "lcd", "sensor", "--metric", "clock", "--output", str(png)]
    )
    assert png.exists()
    assert capsys.readouterr().out.strip() == f'{{"output": "{png}"}}'


def test_fan_speed_keeps_last_when_the_receiver_read_fails(monkeypatch):
    from uwscli.usbutil import USBError

    results = [wireless.WirelessSnapshot(devices=[_device((900, 1100, 0, 0))], raw=b"")]

    def read():
        if results:
            return results.pop()
        raise USBError("USB read failed: timed out")

    monkeypatch.setattr(wireless, "read_device_list", read)
    monkeypatch.setattr(sensors.time, "sleep", lambda s: None)
    fan = sensors.FanSpeed(None)
    assert fan.read() == 1000
    assert fan.read() == 1000


@pytest.mark.parametrize("stdout", ["[N/A]\n", ""])
def test_nvidia_smi_without_a_number_is_a_sensor_error(monkeypatch, stdout):
    class Done:
        pass

    def run(*args, **kwargs):
        done = Done()
        done.stdout = stdout
        return done

    monkeypatch.setattr(sensors.subprocess, "run", run)
    monkeypatch.setattr(sensors.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    with pytest.raises(sensors.SensorError):
        sensors.gpu_load()


def test_nvidia_smi_timeout_is_a_sensor_error(monkeypatch):
    def run(*args, **kwargs):
        raise sensors.subprocess.TimeoutExpired("nvidia-smi", 5)

    monkeypatch.setattr(sensors.subprocess, "run", run)
    monkeypatch.setattr(sensors.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    with pytest.raises(sensors.SensorError):
        sensors.gpu_temperature()


class _Receiver:
    def __init__(self, error):
        self.error = error

    def write(self, data):
        pass

    def read(self, size):
        raise self.error


def test_receiver_read_errors_are_wireless_errors():
    from uwscli.usbutil import USBError

    with pytest.raises(wireless.WirelessError, match="timed out"):
        wireless._list_devices(_Receiver(USBError("USB read failed: timed out")))
