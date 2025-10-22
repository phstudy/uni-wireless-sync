"""Data structures shared across CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Tuple, cast


class LCDControlMode(Enum):
    RESERVER = 0
    SHOW_JPG = 1
    SHOW_AVI = 3
    SHOW_APP_SYNC = 4
    LCD_SETTING = 5
    LCD_TEST = 6


class ScreenRotation(Enum):
    ROTATE_0 = 0
    ROTATE_90 = 1
    ROTATE_180 = 2
    ROTATE_270 = 3

    @staticmethod
    def from_degrees(degrees: int) -> "ScreenRotation":
        mapping = {
            0: ScreenRotation.ROTATE_0,
            90: ScreenRotation.ROTATE_90,
            180: ScreenRotation.ROTATE_180,
            270: ScreenRotation.ROTATE_270,
        }
        if degrees not in mapping:
            raise ValueError("Rotation must be one of 0, 90, 180, 270 degrees")
        return mapping[degrees]


@dataclass(frozen=True)
class LCDControlSetting:
    mode: LCDControlMode = LCDControlMode.RESERVER
    jpg_index: int = 0
    brightness: int = 50
    video_fps: int = 30
    rotation: ScreenRotation = ScreenRotation.ROTATE_0
    enable_test: bool = False
    test_color: Tuple[int, int, int] = (0, 0, 0)

    def to_bytes(self) -> bytes:
        if not 0 <= self.jpg_index <= 0xFFFF:
            raise ValueError("jpg_index must be within 0-65535")
        if not 0 <= self.brightness <= 100:
            raise ValueError("brightness must be within 0-100")
        if not 0 <= self.video_fps <= 255:
            raise ValueError("video_fps must fit in a byte")
        for component in self.test_color:
            if not 0 <= component <= 255:
                raise ValueError("test_color components must be within 0-255")
        payload = bytearray(11)
        payload[0] = self.mode.value
        payload[1] = (self.jpg_index >> 8) & 0xFF
        payload[2] = self.jpg_index & 0xFF
        payload[3] = 0
        payload[4] = self.brightness & 0xFF
        payload[5] = self.video_fps & 0xFF
        payload[6] = self.rotation.value
        payload[7] = 1 if self.enable_test else 0
        payload[8] = self.test_color[0]
        payload[9] = self.test_color[1]
        payload[10] = self.test_color[2]
        return bytes(payload)


@dataclass(frozen=True)
class WirelessDeviceInfo:
    mac: str
    master_mac: str
    channel: int
    rx_type: int
    device_type: int
    fan_count: int
    pwm_values: Tuple[int, int, int, int]
    fan_rpm: Tuple[int, int, int, int]
    command_sequence: int
    raw: bytes

    @property
    def is_bound(self) -> bool:
        return any(part != "00" for part in self.master_mac.split(":"))

    def pretty_rpm(self) -> str:
        values = [rpm for rpm in self.fan_rpm if rpm > 0]
        return ",".join(str(rpm) for rpm in values) if values else "-"

    def pretty_pwm(self) -> str:
        return ",".join(str(v) for v in self.pwm_values)


def clamp_pwm_values(values: Iterable[int]) -> Tuple[int, int, int, int]:
    result = []
    for value in values:
        if value < 0:
            value = 0
        elif value > 255:
            value = 255
        result.append(int(value))
    while len(result) < 4:
        result.append(result[-1] if result else 0)
    return cast(Tuple[int, int, int, int], tuple(result[:4]))
