"""Read CPU/GPU temperature and load and fan speed on Linux, for the LCD sensor screens."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

HWMON_ROOT = "/sys/class/hwmon"


class SensorError(RuntimeError):
    """Raised when a sensor is not available on this machine."""


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: str
    maximum: float  # value that fills the gauge


METRICS: dict[str, Metric] = {
    "cpu-temp": Metric("cpu-temp", "CPU", "°C", 100),
    "cpu-load": Metric("cpu-load", "CPU", "%", 100),
    "gpu-temp": Metric("gpu-temp", "GPU", "°C", 100),
    "gpu-load": Metric("gpu-load", "GPU", "%", 100),
    "fan-rpm": Metric("fan-rpm", "FAN", "RPM", 2600),
}

# hwmon drivers and labels that report the CPU package temperature, best first.
_CPU_SENSORS = (
    ("k10temp", ("Tctl", "Tdie")),
    ("zenpower", ("Tdie", "Tctl")),
    ("coretemp", ("Package id 0",)),
    ("cpu_thermal", ("",)),
)


def _read(path: str) -> str:
    with open(path, encoding="ascii") as handle:
        return handle.read().strip()


def _hwmon_dirs() -> list[tuple[str, str]]:
    found = []
    for path in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*"))):
        try:
            found.append((_read(os.path.join(path, "name")), path))
        except OSError:
            continue
    return found


def cpu_temperature() -> float:
    hwmons = _hwmon_dirs()
    for driver, labels in _CPU_SENSORS:
        for name, path in hwmons:
            if name != driver:
                continue
            for temp in sorted(glob.glob(os.path.join(path, "temp*_input"))):
                label_path = temp.replace("_input", "_label")
                label = _read(label_path) if os.path.exists(label_path) else ""
                if label in labels or labels == ("",):
                    return int(_read(temp)) / 1000.0
    raise SensorError("No CPU temperature sensor found (k10temp, zenpower or coretemp)")


class CpuLoad:
    """CPU load in percent since the previous call (from /proc/stat)."""

    def __init__(self) -> None:
        self._last = self._sample()

    @staticmethod
    def _sample() -> tuple[int, int]:
        fields = [int(v) for v in _read("/proc/stat").splitlines()[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        return sum(fields), idle

    def read(self) -> float:
        total, idle = self._sample()
        last_total, last_idle = self._last
        self._last = (total, idle)
        busy = (total - last_total) - (idle - last_idle)
        return 100.0 * busy / max(1, total - last_total)


def _nvidia(field: str) -> float:
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={field}", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return float(out.splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        # Includes a timeout, a failed call and values such as "[N/A]".
        raise SensorError(f"nvidia-smi gave no {field}: {exc}") from exc


def _amdgpu_dir() -> str | None:
    for name, path in _hwmon_dirs():
        if name == "amdgpu":
            return path
    return None


def gpu_temperature() -> float:
    if shutil.which("nvidia-smi"):
        return _nvidia("temperature.gpu")
    path = _amdgpu_dir()
    if path:
        return int(_read(os.path.join(path, "temp1_input"))) / 1000.0
    raise SensorError("No GPU temperature found (nvidia-smi or amdgpu)")


def gpu_load() -> float:
    if shutil.which("nvidia-smi"):
        return _nvidia("utilization.gpu")
    for busy in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
        return float(_read(busy))
    raise SensorError("No GPU load found (nvidia-smi or amdgpu)")


class FanSpeed:
    """Average RPM of a wireless fan group, read from the RF receiver.

    The receiver may be busy with another uws command; then the last value is kept.
    """

    def __init__(self, mac: str | None) -> None:
        self._mac = mac
        self._last = 0.0

    def read(self) -> float:
        from . import wireless
        from .usbutil import USBError

        snapshot = None
        for _ in range(3):
            try:
                snapshot = wireless.read_device_list()
                break
            except (wireless.WirelessError, USBError):
                # Busy or timed out (another uws command has the receiver): try again.
                time.sleep(0.3)
        if snapshot is None:
            return self._last
        devices = [d for d in snapshot.devices if d.is_bound]
        if self._mac:
            devices = [d for d in devices if d.mac.lower() == self._mac.lower()]
        speeds = [rpm for d in devices for rpm in d.fan_rpm if rpm > 0]
        if speeds:
            self._last = sum(speeds) / len(speeds)
        elif not devices and self._mac:
            raise SensorError(f"Fan group {self._mac} not found")
        return self._last


class SensorReader:
    """Read one metric repeatedly."""

    def __init__(self, metric: str, *, fan_mac: str | None = None) -> None:
        if metric not in METRICS:
            raise SensorError(f"Unknown metric {metric}")
        self.metric = METRICS[metric]
        self._cpu_load = CpuLoad() if metric == "cpu-load" else None
        self._fan = FanSpeed(fan_mac) if metric == "fan-rpm" else None
        if self._cpu_load:
            time.sleep(0.2)

    def read(self) -> float:
        name = self.metric.name
        if name == "cpu-temp":
            return cpu_temperature()
        if name == "cpu-load":
            assert self._cpu_load is not None
            return self._cpu_load.read()
        if name == "gpu-temp":
            return gpu_temperature()
        if name == "gpu-load":
            return gpu_load()
        assert self._fan is not None
        return self._fan.read()
