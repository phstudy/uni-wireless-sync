"""Command line interface for the UWS toolkit."""

from __future__ import annotations

import argparse
import json
import random
import time
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from . import lcd, tl_effects, tlcontroller, wireless
from .logging_utils import configure_logging
from .structs import LCDControlSetting, ScreenRotation, clamp_pwm_values


def _mac_nonzero(mac: str) -> bool:
    return any(part != "00" for part in mac.split(":"))


def _resolve_version() -> str:
    try:
        return metadata.version("uwscli")
    except metadata.PackageNotFoundError:
        from . import __version__

        return getattr(
            __version__,
            "__version__",
            __version__ if isinstance(__version__, str) else "0.0.0",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uws",
        description="UWS CLI for Uni fan wireless controllers",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_resolve_version()}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v for INFO, -vv for DEBUG)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format for supported commands (default: text)",
    )
    subparsers = parser.add_subparsers(dest="namespace")

    # LCD namespace
    lcd_parser = subparsers.add_parser(
        "lcd", help="Interact with UNI FAN TL LCD panels"
    )
    lcd_sub = lcd_parser.add_subparsers(dest="command", required=True)

    lcd_sub.add_parser("list", help="List attached LCD devices")

    info_parser = lcd_sub.add_parser("info", help="Display firmware and handshake info")
    info_parser.add_argument(
        "--serial", required=False, help="USB serial number of the LCD device"
    )

    send_jpg_parser = lcd_sub.add_parser(
        "send-jpg",
        help="Show an image (JPEG or PNG) on the LCD",
        description=(
            "Show an image on the LCD. For the TL Wireless LCD the image is scaled to "
            "400x400 and re-encoded as JPEG (quality 95, lowered until it fits in "
            "100000 bytes), as the vendor app does."
        ),
    )
    send_jpg_parser.add_argument(
        "--file", required=True, type=Path, help="Image file path (JPEG or PNG)"
    )
    send_jpg_parser.add_argument(
        "--serial", required=False, help="USB serial number of the LCD device"
    )
    send_jpg_parser.add_argument(
        "--raw",
        action="store_true",
        help="Send the file bytes unchanged (must already be a JPEG the panel accepts)",
    )
    send_jpg_parser.add_argument(
        "--save",
        action="store_true",
        help="Also store the image as the power-on image (TL Wireless LCD only), as the vendor app does",
    )

    video_parser = lcd_sub.add_parser(
        "play-video",
        help="Play a video on the TL Wireless LCD (decoded here with FFmpeg, sent frame by frame)",
    )
    video_parser.add_argument(
        "--file", required=True, type=Path, help="Video file path"
    )
    video_parser.add_argument(
        "--serial", required=False, help="USB serial number of the LCD device"
    )
    video_parser.add_argument(
        "--fps",
        type=float,
        help="Frames per second (default: the video's own frame rate)",
    )
    video_parser.add_argument(
        "--loop", action="store_true", help="Repeat until interrupted (Ctrl+C)"
    )

    keep_alive_parser = lcd_sub.add_parser(
        "keep-alive", help="Send periodic keep-alive messages"
    )
    keep_alive_parser.add_argument(
        "--serial", required=False, help="USB serial number of the LCD device"
    )
    keep_alive_parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between keep-alive messages (default: 1, as the vendor app)",
    )

    control_parser = lcd_sub.add_parser("control", help="Send an LCD control setting")
    control_parser.add_argument(
        "--serial", required=False, help="USB serial number of the LCD device"
    )
    control_parser.add_argument(
        "--mode",
        default="show_jpg",
        help="Control mode (e.g. show_jpg, show_app_sync, lcd_test)",
    )
    control_parser.add_argument(
        "--jpg-index", type=int, default=0, help="JPG index for show_jpg mode"
    )
    control_parser.add_argument(
        "--brightness",
        type=int,
        choices=range(101),
        metavar="0-100",
        help=(
            "LCD brightness 0-100, sent as is. The vendor app's 0/25/50/75/100%% "
            "steps send 0/10/30/40/100 to the TL Wireless LCD. "
            "TL Wireless LCD: only what is given is changed; wired LCD: default 50"
        ),
    )
    control_parser.add_argument("--fps", type=int, default=30, help="Video FPS")
    control_parser.add_argument(
        "--rotation",
        type=int,
        choices=[0, 90, 180, 270],
        help=(
            "Screen rotation in degrees, as the vendor app names them. "
            "TL Wireless LCD: only what is given is changed; wired LCD: default 0"
        ),
    )
    control_parser.add_argument(
        "--test-color",
        default="0,0,0",
        help="RGB triple for LCD test mode (comma separated)",
    )
    control_parser.add_argument(
        "--enable-test", action="store_true", help="Enable test color overlay"
    )

    # Fan namespace (wireless TL receivers)
    fan_parser = subparsers.add_parser("fan", help="Interact with UNI FAN TL fans")
    fan_sub = fan_parser.add_subparsers(dest="command", required=True)

    fan_sub.add_parser("list", help="List wireless receivers discovered via RF dongle")
    fan_sub.add_parser(
        "list-masters",
        help="List master controllers discovered via RF dongle",
    )

    set_fan_parser = fan_sub.add_parser(
        "set-fan", help="Send PWM to a wireless receiver"
    )
    fan_target = set_fan_parser.add_mutually_exclusive_group(required=True)
    fan_target.add_argument(
        "--mac",
        help="MAC address of the wireless receiver (aa:bb:cc:dd:ee:ff)",
    )
    fan_target.add_argument(
        "--all", action="store_true", help="Apply PWM to all bound wireless receivers"
    )
    set_fan_parser.add_argument(
        "--pwm", type=int, help="Single PWM value (0-255) applied to all ports"
    )
    set_fan_parser.add_argument(
        "--pwm-list",
        help="Comma separated list of up to four PWM values",
    )
    set_fan_parser.add_argument(
        "--sequence-index",
        type=int,
        help="Device number sent with the command (default: its position among this master's devices, as the vendor app)",
    )

    effect_names = sorted(effect.name.lower() for effect in tl_effects.TLEffects)

    set_led_parser = fan_sub.add_parser(
        "set-led", help="Set LED effects on wireless receivers"
    )
    # One of --mac/--all is required, except that --mode merge may take --order instead
    # (checked in handle_fan).
    led_target = set_led_parser.add_mutually_exclusive_group(required=False)
    led_target.add_argument(
        "--mac", help="MAC address of the wireless receiver (aa:bb:cc:dd:ee:ff)"
    )
    led_target.add_argument(
        "--all", action="store_true", help="Apply to all bound wireless receivers"
    )
    set_led_parser.add_argument(
        "--mode",
        choices=["static", "rainbow", "frames", "effect", "random-effect", "merge"],
        default="static",
        help="LED effect mode (default: static)",
    )
    set_led_parser.add_argument(
        "--color",
        help="RGB triple applied to all LEDs (comma separated) for static mode",
    )
    set_led_parser.add_argument(
        "--color-list",
        help="Semicolon separated RGB triples for per-LED or per-fan colors in static mode",
    )
    set_led_parser.add_argument(
        "--frames",
        type=int,
        default=24,
        help="Frame count for rainbow mode (default: 24)",
    )
    set_led_parser.add_argument(
        "--interval-ms",
        type=int,
        help="Frame interval in milliseconds (default: 50; effect modes: from --speed)",
    )
    set_led_parser.add_argument(
        "--speed",
        type=int,
        choices=range(1, 6),
        default=tl_effects.DEFAULT_SPEED,
        metavar="1-5",
        help=(
            "Effect speed level as in the vendor app (its 0/25/50/75/100%% steps; "
            f"default: {tl_effects.DEFAULT_SPEED}, the app's default)"
        ),
    )
    set_led_parser.add_argument(
        "--order",
        help=(
            "merge mode: comma separated MACs of the fan groups in the order the effect "
            "runs through them (default: every bound group, in list order)"
        ),
    )
    set_led_parser.add_argument(
        "--reverse",
        help="merge mode: comma separated MACs of groups that run the effect the other way",
    )
    set_led_parser.add_argument(
        "--flip",
        action="store_true",
        help="Swap the front and behind halves of every fan (the vendor app's up/down swap)",
    )
    set_led_parser.add_argument(
        "--effect-colors",
        help=(
            "The effect's colours (R,G,B;R,G,B;..., up to four), as on the vendor app's "
            "lighting page (default: the app's defaults for each effect). Only the nine "
            "computed effects accept other colours"
        ),
    )
    set_led_parser.add_argument(
        "--frames-file",
        type=Path,
        help="JSON file describing animation frames for frames mode",
    )
    set_led_parser.add_argument(
        "--effect",
        choices=effect_names,
        help="TL effect name to apply when mode=effect",
    )
    set_led_parser.add_argument(
        "--effect-brightness",
        type=int,
        default=255,
        help=(
            "Brightness (0-255) applied when mode=effect (default: 255). The vendor app "
            "has 5 levels (0, 64, 128, 192, 255); pre-rendered effects use the closest one"
        ),
    )
    set_led_parser.add_argument(
        "--effect-direction",
        type=int,
        choices=[0, 1],
        default=0,
        help="Direction: 0 clockwise (the vendor app's default), 1 counter-clockwise",
    )
    set_led_parser.add_argument(
        "--effect-scope",
        choices=["front", "behind", "both"],
        default="both",
        help="Fan segment for TL effects (front, behind, or both; default: both)",
    )

    bind_parser = fan_sub.add_parser(
        "bind", help="Bind an unlinked wireless receiver to the current master"
    )
    bind_parser.add_argument(
        "--mac", required=True, help="MAC address of the wireless receiver to bind"
    )
    bind_parser.add_argument(
        "--master-mac",
        help="Expected MAC of the attached master (checked; binding always uses the attached master)",
    )
    bind_parser.add_argument(
        "--rx-type",
        type=int,
        choices=range(1, 14),
        metavar="1-13",
        help="RX slot (1-13). Default: the first free one.",
    )

    unbind_parser = fan_sub.add_parser(
        "unbind", help="Unbind a wireless receiver from the current master"
    )
    unbind_parser.add_argument(
        "--mac", required=True, help="MAC address of the wireless receiver to unbind"
    )

    identify_parser = fan_sub.add_parser(
        "identify", help="Make a wireless device flash so you can find it"
    )
    identify_parser.add_argument(
        "--mac", required=True, help="MAC address of the device"
    )

    reboot_parser = fan_sub.add_parser(
        "reboot-lcd", help="Restart the LCD panels of a TL Wireless LCD fan over RF"
    )
    reboot_parser.add_argument("--mac", required=True, help="MAC address of the device")

    channel_parser = fan_sub.add_parser(
        "set-channel",
        help="Move every device bound to the attached controller to another RF channel",
    )
    channel_parser.add_argument(
        "--channel",
        type=int,
        required=True,
        choices=[*wireless.CHANNELS, wireless.DEFAULT_MASTER_CHANNEL],
        metavar="CHANNEL",
        help=(
            "The vendor app's channels: "
            + ", ".join(map(str, wireless.CHANNELS))
            + f"; {wireless.DEFAULT_MASTER_CHANNEL} is its automatic default"
        ),
    )

    sync_parser = fan_sub.add_parser(
        "pwm-sync",
        help="Synchronize fan receivers using controller polling (default) or motherboard PWM pass-through",
    )
    sync_target = sync_parser.add_mutually_exclusive_group(required=False)
    sync_target.add_argument(
        "--mac", help="MAC address of the wireless receiver to update"
    )
    sync_target.add_argument(
        "--all",
        action="store_true",
        help="Apply to all bound wireless receivers (default when --mac is omitted)",
    )
    sync_parser.add_argument(
        "--mode",
        choices=["controller", "receiver"],
        default="receiver",
        help=(
            "receiver (default): send PWM 6,6,6,6 once so the device follows the motherboard "
            "itself; as the vendor app, only devices whose MAC ends in e1. "
            "controller: read the motherboard PWM from the receiver and send it to the fans in a loop"
        ),
    )
    sync_parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (controller mode only; default: 1.0)",
    )
    sync_parser.add_argument(
        "--once",
        action="store_true",
        help="Perform a single sync iteration instead of looping (controller mode only)",
    )
    sync_parser.add_argument(
        "--sequence-index",
        type=int,
        help="Device number sent with the command (receiver mode only; default: automatic)",
    )

    return parser


def _resolve_lcd_serial(cli_serial: str | None) -> str:
    if cli_serial:
        return _normalize_serial(cli_serial)
    devices = [dev for dev in lcd.enumerate_devices() if dev.serial_number]
    if not devices:
        raise SystemExit("No LCD devices detected")
    if len(devices) > 1:
        choices = "\n".join(
            f"  {dev.serial_number} ({dev.product or 'unknown'} @ {dev.path})"
            for dev in devices
        )
        raise SystemExit(
            "Multiple LCD devices detected; please provide --serial from one of:\n"
            + choices,
        )
    return _normalize_serial(devices[0].serial_number)  # type: ignore[arg-type]


def _normalize_serial(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise SystemExit("Serial value cannot be empty")
    if normalized.startswith("serial:"):
        normalized = normalized.split(":", 1)[1].strip()
    if not normalized:
        raise SystemExit("Serial value cannot be empty")
    return normalized


def _load_file_bytes(path: Path) -> bytes:
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    data = path.read_bytes()
    if not data:
        raise SystemExit("File is empty")
    return data


def _parse_test_color(value: str) -> tuple[int, int, int]:
    try:
        parts = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise SystemExit(
            "--test-color must be three integers separated by commas"
        ) from exc
    if len(parts) != 3:
        raise SystemExit(
            "--test-color must contain exactly three comma separated integers"
        )
    for part in parts:
        if not 0 <= part <= 255:
            raise SystemExit("--test-color values must be between 0 and 255")
    return tuple(parts)  # type: ignore[return-value]


def _parse_rgb_color(value: str) -> tuple[int, int, int]:
    try:
        parts = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise SystemExit("--color must be three integers separated by commas") from exc
    if len(parts) != 3:
        raise SystemExit("--color must contain exactly three comma separated integers")
    for part in parts:
        if not 0 <= part <= 255:
            raise SystemExit("--color values must be between 0 and 255")
    return tuple(parts)  # type: ignore[return-value]


def _parse_color_list(value: str) -> list[tuple[int, int, int]]:
    entries = [entry.strip() for entry in value.split(";") if entry.strip()]
    if not entries:
        raise SystemExit("--color-list cannot be empty")
    colors = []
    for entry in entries:
        colors.append(_parse_rgb_color(entry))
    return colors


def _load_frames_file(path: Path) -> list[list[tuple[int, int, int]]]:
    if not path.exists():
        raise SystemExit(f"Frames file not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse frames file: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise SystemExit("Frames file must contain a non-empty list of frames")
    frames: list[list[tuple[int, int, int]]] = []
    for frame in data:
        if not isinstance(frame, list) or not frame:
            raise SystemExit("Each frame must be a non-empty list of RGB triples")
        parsed: list[tuple[int, int, int]] = []
        for item in frame:
            if isinstance(item, str):
                parsed.append(_parse_rgb_color(item))
            elif isinstance(item, (list, tuple)) and len(item) == 3:
                try:
                    rgb_tuple = tuple(int(v) for v in item)
                except ValueError as exc:
                    raise SystemExit("Frame colors must be integers") from exc
                rgb_cast = cast(tuple[int, int, int], rgb_tuple)
                for v in rgb_cast:
                    if not 0 <= v <= 255:
                        raise SystemExit("Frame color values must be between 0 and 255")
                parsed.append(rgb_cast)
            else:
                raise SystemExit("Frame colors must be RGB triples")
        frames.append(parsed)
    return frames


def _effect_colours_arg(args: argparse.Namespace) -> list[list[int]] | None:
    """--effect-colors for every effect mode: at most four colours, as the vendor app."""
    if not args.effect_colors:
        return None
    colours = [list(c) for c in _parse_color_list(args.effect_colors)]
    if len(colours) > 4:
        raise SystemExit("--effect-colors takes at most four colours")
    return colours


def _set_led_merge(args: argparse.Namespace) -> None:
    if not args.effect:
        raise SystemExit("--effect is required for merge mode")
    if args.flip:
        raise SystemExit(
            "--flip does nothing in merge mode (both halves of every fan show the same strip)"
        )
    effect = tl_effects.TLEffects[args.effect.upper()]
    colours = _effect_colours_arg(args)
    try:
        with wireless.WirelessTransceiver() as tx:
            if args.order:
                order = [m.strip() for m in args.order.split(",") if m.strip()]
            elif args.all:
                order = [d.mac for d in tx.list_devices().devices if d.is_bound]
            else:
                order = [args.mac]
            macs = tx.set_led_merge(
                effect,
                order,
                reversed_macs=[
                    m.strip() for m in (args.reverse or "").split(",") if m.strip()
                ],
                brightness=args.effect_brightness,
                direction=int(args.effect_direction),
                speed=args.speed,
                colours=colours,
                interval_ms=args.interval_ms,
            )
    except wireless.WirelessError as exc:
        raise SystemExit(str(exc))
    _emit_output(
        args,
        {"mode": "merge", "effect": effect.name, "order": macs, "speed": args.speed},
        text=f"Applied merged {effect.name} across {', '.join(macs)}",
    )


def _plain_interval(args: argparse.Namespace) -> int:
    return max(1, args.interval_ms or 50)


def _effect_interval(args: argparse.Namespace, effect: tl_effects.TLEffects) -> int:
    if args.interval_ms:
        return max(1, args.interval_ms)
    return tl_effects.effect_interval(effect, args.speed)


def _ensure_pwm_values(args) -> list[int]:
    if args.pwm_list:
        try:
            values = [
                int(part.strip()) for part in args.pwm_list.split(",") if part.strip()
            ]
        except ValueError as exc:
            raise SystemExit("--pwm-list must contain integers") from exc
        if not values:
            raise SystemExit("--pwm-list cannot be empty")
        return list(clamp_pwm_values(values))
    if args.pwm is None:
        raise SystemExit("Either --pwm or --pwm-list must be provided")
    return [args.pwm] * 4


def handle_lcd(args: argparse.Namespace) -> None:
    if args.command == "list":
        devices = lcd.enumerate_devices()
        if not devices:
            _emit_output(args, {"devices": []}, text="No LCD devices detected")
            return
        device_payloads = []
        for dev in devices:
            info = dev.__dict__.copy()
            if dev.serial_number:
                info.setdefault("serial", dev.serial_number)
            device_payloads.append(info)
        response = {"devices": device_payloads}
        text = "\n".join(
            json.dumps(info, ensure_ascii=False) for info in device_payloads
        )
        _emit_output(args, response, text=text)
        return

    serial = _resolve_lcd_serial(getattr(args, "serial", None))
    try:
        with lcd.TLLCDDevice(serial) as device:
            if args.command == "info":
                info = {
                    "handshake": device.handshake(),
                    "firmware": device.firmware_version(),
                }
                _emit_output(args, info, text=json.dumps(info, indent=2))
            elif args.command == "send-jpg":
                raw = _load_file_bytes(args.file)
                if args.save and not device.is_wireless:
                    raise SystemExit("--save is supported only on the TL Wireless LCD")
                if device.is_wireless and not args.raw:
                    jpg_payload = lcd.prepare_wireless_image(str(args.file))
                else:
                    jpg_payload = raw
                device.send_jpg(jpg_payload)
                if args.save:
                    device.send_boot_jpg(jpg_payload)
                _emit_output(
                    args,
                    {"bytes_sent": len(jpg_payload), "saved": bool(args.save)},
                    text=f"Sent {len(jpg_payload)} bytes to LCD"
                    + (" and saved it as the power-on image" if args.save else ""),
                )
            elif args.command == "play-video":
                if not device.is_wireless:
                    raise SystemExit(
                        "play-video is supported only on the TL Wireless LCD"
                    )
                if not args.file.exists():
                    raise SystemExit(f"File not found: {args.file}")
                fps = args.fps or lcd.video_frame_rate(str(args.file))
                if fps <= 0:
                    raise SystemExit("--fps must be positive")
                frames = _play_video(device, str(args.file), fps, args.loop)
                _emit_output(
                    args,
                    {"frames_sent": frames, "fps": fps},
                    text=f"Sent {frames} frames at {fps:g} fps",
                )
            elif args.command == "control":
                if device.is_wireless:
                    if args.brightness is None and args.rotation is None:
                        raise SystemExit(
                            "Give --brightness and/or --rotation for a TL Wireless LCD"
                        )
                    if args.brightness is not None:
                        device.set_brightness(args.brightness)
                    if args.rotation is not None:
                        device.set_rotation(ScreenRotation.from_degrees(args.rotation))
                else:
                    setting = LCDControlSetting(
                        mode=lcd.mode_from_arg(args.mode),
                        jpg_index=args.jpg_index,
                        brightness=50 if args.brightness is None else args.brightness,
                        video_fps=args.fps,
                        rotation=ScreenRotation.from_degrees(args.rotation or 0),
                        enable_test=args.enable_test,
                        test_color=_parse_test_color(args.test_color),
                    )
                    device.control(setting)
                _emit_output(
                    args, {"status": "control_sent"}, text="LCD control command sent"
                )
            elif args.command == "keep-alive":
                interval = max(args.interval, 0.2)
                print(
                    f"Keeping LCD {serial} awake every {interval:.1f}s. Press Ctrl+C to stop.",
                    flush=True,
                )
                device.keep_alive()
                try:
                    while True:
                        time.sleep(interval)
                        device.keep_alive()
                except KeyboardInterrupt:
                    print("Keep-alive stopped.")
            else:
                raise SystemExit("Unknown lcd command")
    except lcd.LCDDeviceError as exc:
        raise SystemExit(str(exc))


def _play_video(device: Any, path: str, fps: float, loop: bool) -> int:
    """Push decoded frames at a steady rate; returns how many were sent."""
    period = 1.0 / fps
    sent = 0
    try:
        while True:
            deadline = time.monotonic()
            for frame in lcd.iter_video_frames(path, fps):
                device.send_jpg(frame)
                sent += 1
                deadline += period
                delay = deadline - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    deadline = time.monotonic()
            if not loop or sent == 0:
                break
    except KeyboardInterrupt:
        pass
    return sent


def handle_fan(args: argparse.Namespace) -> None:
    if args.command == "list":
        try:
            with wireless.WirelessTransceiver() as tx:
                snapshot = tx.list_devices()
                if not snapshot.devices:
                    _emit_output(
                        args, {"devices": []}, text="No wireless devices detected"
                    )
                    return
                devices = [
                    {
                        "mac": dev.mac,
                        "master_mac": dev.master_mac,
                        "channel": dev.channel,
                        "rx_type": dev.rx_type,
                        "device_type": dev.device_type,
                        "fan_count": dev.fan_count,
                        "fan_pwm": list(dev.pwm_values),
                        "fan_rpm": list(dev.fan_rpm),
                        "bound": dev.is_bound,
                        "fans_type": list(dev.fans_type),
                        "rf_version": dev.rf_version,
                        "effect_index": dev.effect_index.hex(),
                        "mb_light_sync": dev.mb_light_sync,
                    }
                    for dev in snapshot.devices
                ]
                _emit_output(
                    args,
                    {"devices": devices},
                    text="\n".join(json.dumps(dev) for dev in devices),
                )
            return
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))

    if args.command == "list-masters":
        master_query: tuple[str, int | None] | None = None
        try:
            with wireless.WirelessTransceiver() as tx:
                snapshot = tx.list_devices()
                try:
                    master_query = tx.query_master_mac()
                except wireless.WirelessError:
                    master_query = None
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))
        masters: dict[str, dict[str, Any]] = {}

        def ensure_entry(master_mac: str) -> dict[str, Any]:
            key = master_mac.lower()
            entry = masters.get(key)
            if entry is None:
                entry = {
                    "master_mac": key,
                    "devices": [],
                    "channels": set(),
                    "rx_types": set(),
                    "channel": None,
                }
                masters[key] = entry
            return entry

        for dev in snapshot.masters + snapshot.devices:
            if dev.device_type == 0xFF:
                master_key: str | None = None
                for candidate in (dev.mac, dev.master_mac):
                    if _mac_nonzero(candidate):
                        master_key = candidate
                        break
                if master_key is None:
                    continue
                entry = ensure_entry(master_key)
                if 0 < dev.channel < 255:
                    entry["channels"].add(dev.channel)
                    entry["channel"] = dev.channel
                if 0 < dev.rx_type < 255:
                    entry["rx_types"].add(dev.rx_type)
                continue

            if not dev.is_bound:
                continue

            entry = ensure_entry(dev.master_mac)
            entry["devices"].append(
                {
                    "mac": dev.mac,
                    "channel": dev.channel,
                    "rx_type": dev.rx_type,
                    "device_type": dev.device_type,
                    "fan_count": dev.fan_count,
                }
            )
            if dev.channel > 0:
                entry["channels"].add(dev.channel)
            if dev.rx_type > 0:
                entry["rx_types"].add(dev.rx_type)
        if master_query:
            master_mac, master_channel = master_query
            entry = ensure_entry(master_mac)
            if master_channel is not None:
                entry["channel"] = entry["channel"] or master_channel
                entry["channels"].add(master_channel)
        masters_payload: list[dict[str, Any]] = []
        for entry in masters.values():
            devices = sorted(entry["devices"], key=lambda item: cast(str, item["mac"]))
            masters_payload.append(
                {
                    "master_mac": entry["master_mac"],
                    "channel": entry["channel"],
                    "device_count": len(devices),
                    "channels": sorted(entry["channels"]),
                    "rx_types": sorted(entry["rx_types"]),
                    "devices": devices,
                }
            )
        masters_payload.sort(key=lambda item: cast(str, item["master_mac"]))
        payload = {"masters": masters_payload}
        if not masters_payload:
            _emit_output(
                args,
                payload,
                text="No master controllers detected",
            )
        else:
            text = "\n\n".join(
                json.dumps(master, ensure_ascii=False, indent=2)
                for master in masters_payload
            )
            _emit_output(args, payload, text=text)
        return

    if args.command == "set-fan":
        pwm_values = _ensure_pwm_values(args)
        try:
            with wireless.WirelessTransceiver() as tx:
                if args.all:
                    snapshot = tx.list_devices()
                    pwm_devices = [d for d in snapshot.devices if d.is_bound]
                    if not pwm_devices:
                        raise SystemExit("No bound wireless devices found")
                    pwm_target_macs: list[str] = []
                    for dev in pwm_devices:
                        tx.set_pwm_direct(
                            dev,
                            pwm_values,
                            sequence_index=args.sequence_index,
                            label=dev.mac,
                            snapshot=snapshot,
                        )
                        pwm_target_macs.append(dev.mac)
                else:
                    tx.set_pwm(args.mac, pwm_values, sequence_index=args.sequence_index)
                    pwm_target_macs = [args.mac]
            if args.all:
                result_payload: dict[str, Any] = {
                    "macs": pwm_target_macs,
                    "count": len(pwm_target_macs),
                    "pwm": list(pwm_values),
                    "sequence_index": args.sequence_index,
                }
                message = f"Applied PWM {pwm_values} to {', '.join(pwm_target_macs)}"
            else:
                result_payload = {
                    "mac": pwm_target_macs[0],
                    "pwm": list(pwm_values),
                    "sequence_index": args.sequence_index,
                }
                message = f"Applied PWM {pwm_values} to {pwm_target_macs[0]}"
            _emit_output(args, result_payload, text=message)
            return
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))

    merge_order = args.command == "set-led" and args.mode == "merge" and args.order
    if args.command == "set-led" and not (args.mac or args.all or merge_order):
        raise SystemExit(
            "set-led needs --mac or --all (merge mode: or --order mac1,mac2,...)"
        )

    if args.command == "set-led" and args.mode == "merge":
        _set_led_merge(args)
        return

    if args.command == "set-led":
        try:
            if args.all:
                with wireless.WirelessTransceiver() as tx:
                    snapshot = tx.list_devices()
                    targets: list[str] = [
                        dev.mac for dev in [d for d in snapshot.devices if d.is_bound]
                    ]
                    if not targets:
                        raise SystemExit("No bound wireless devices found")
            else:
                targets = [args.mac]
            results: list[dict[str, Any]] = []
            last_text: str = ""
            selected_random_effect: tl_effects.TLEffects | None = None
            effect_colours = _effect_colours_arg(args)
            if args.mode == "random-effect":
                choices = [
                    e
                    for e in tl_effects.TLEffects
                    if not (effect_colours and e in tl_effects.PRERENDERED)
                ]
                selected_random_effect = random.choice(choices)
            with wireless.WirelessTransceiver() as tx:
                for mac in targets:
                    entry_text: str
                    entry_data: dict[str, Any]
                    if args.mode == "static":
                        colors: list[tuple[int, int, int]] | None = None
                        if args.color_list:
                            colors = _parse_color_list(args.color_list)
                        if args.color:
                            base_color = _parse_rgb_color(args.color)
                        elif colors is None:
                            raise SystemExit(
                                "Either --color or --color-list must be provided for static mode"
                            )
                        else:
                            base_color = None
                        tx.set_led_static(
                            mac,
                            base_color,
                            color_list=colors,
                        )
                        entry_data = {
                            "mac": mac,
                            "mode": "static",
                        }
                        if base_color is not None:
                            entry_data["color"] = list(base_color)
                        if colors is not None:
                            entry_data["color_list"] = [list(c) for c in colors]
                        entry_text = f"Applied static LED effect to {mac}"
                    elif args.mode == "rainbow":
                        frames = max(1, args.frames)
                        interval_ms = _plain_interval(args)
                        tx.set_led_rainbow(
                            mac,
                            frames=frames,
                            interval_ms=interval_ms,
                        )
                        entry_data = {
                            "mac": mac,
                            "mode": "rainbow",
                            "frames": frames,
                            "interval_ms": interval_ms,
                        }
                        entry_text = f"Applied rainbow LED effect to {mac}"
                    elif args.mode == "effect":
                        if not args.effect:
                            raise SystemExit(
                                "--effect must be provided when mode=effect"
                            )
                        effect = tl_effects.TLEffects[args.effect.upper()]
                        brightness = max(0, min(255, args.effect_brightness))
                        direction = int(args.effect_direction)
                        if args.effect_scope == "front":
                            tb = 0
                        elif args.effect_scope == "behind":
                            tb = 1
                        else:
                            tb = None
                        interval_ms = _effect_interval(args, effect)
                        tx.set_led_effect(
                            mac,
                            effect,
                            tb=tb,
                            brightness=brightness,
                            direction=direction,
                            interval_ms=interval_ms,
                            colours=effect_colours,
                            flip=args.flip,
                        )
                        entry_data = {
                            "mac": mac,
                            "mode": "effect",
                            "effect": effect.name,
                            "brightness": brightness,
                            "direction": direction,
                            "scope": args.effect_scope,
                            "interval_ms": interval_ms,
                        }
                        entry_text = f"Applied TL effect {effect.name} to {mac}"
                    elif args.mode == "random-effect":
                        brightness = max(0, min(255, args.effect_brightness))
                        direction = int(args.effect_direction)
                        if args.effect_scope == "front":
                            tb = 0
                        elif args.effect_scope == "behind":
                            tb = 1
                        else:
                            tb = None
                        effect = selected_random_effect or random.choice(
                            list(tl_effects.TLEffects)
                        )
                        interval_ms = _effect_interval(args, effect)
                        tx.set_led_effect(
                            mac,
                            effect,
                            tb=tb,
                            brightness=brightness,
                            direction=direction,
                            interval_ms=interval_ms,
                            colours=effect_colours,
                            flip=args.flip,
                        )
                        entry_data = {
                            "mac": mac,
                            "mode": "random-effect",
                            "effect": effect.name,
                            "brightness": brightness,
                            "direction": direction,
                            "scope": args.effect_scope,
                            "interval_ms": interval_ms,
                        }
                        entry_text = f"Applied random TL effect {effect.name} to {mac}"
                    else:
                        if not args.frames_file:
                            raise SystemExit(
                                "--frames-file is required for frames mode"
                            )
                        frame_list = _load_frames_file(args.frames_file)
                        interval_ms = _plain_interval(args)
                        tx.set_led_frames(
                            mac,
                            frame_list,
                            interval_ms=interval_ms,
                        )
                        entry_data = {
                            "mac": mac,
                            "mode": "frames",
                            "frames": len(frame_list),
                            "interval_ms": interval_ms,
                        }
                        entry_text = f"Applied custom LED frames to {mac}"
                    results.append(entry_data)
                    last_text = entry_text
            overall: dict[str, Any] = {
                "targets": targets,
                "mode": args.mode,
            }
            if args.mode == "rainbow":
                overall["frames"] = max(1, args.frames)
                overall["interval_ms"] = _plain_interval(args)
            elif args.mode in {"effect", "random-effect"}:
                if args.mode == "random-effect":
                    overall["effect"] = (
                        selected_random_effect.name if selected_random_effect else None
                    )
                else:
                    overall["effect"] = args.effect.upper() if args.effect else None
                overall["speed"] = args.speed
            elif args.mode == "frames":
                overall["frames_file"] = str(args.frames_file)
                overall["interval_ms"] = _plain_interval(args)
            overall["details"] = results
            joined_text = "\n".join(json.dumps(entry) for entry in results)
            if len(targets) == 1:
                _emit_output(args, results[0], text=last_text)
            else:
                _emit_output(args, overall, text=joined_text)
            return
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))

    if args.command == "bind":
        try:
            with wireless.WirelessTransceiver() as tx:
                updated = tx.bind_device(
                    args.mac, master_mac=args.master_mac, rx_type=args.rx_type
                )
            if updated and updated.is_bound:
                data = {
                    "mac": updated.mac,
                    "master_mac": updated.master_mac,
                    "channel": updated.channel,
                    "rx_type": updated.rx_type,
                    "fan_count": updated.fan_count,
                }
                _emit_output(args, data, text=json.dumps(data))
            else:
                _emit_output(
                    args,
                    {"mac": args.mac, "status": "bind_sent"},
                    text="Bind command sent; re-run `uws fan list` to confirm status",
                )
            return
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))

    if args.command in ("identify", "reboot-lcd"):
        try:
            with wireless.WirelessTransceiver() as tx:
                if args.command == "identify":
                    confirmed = tx.identify(args.mac)
                else:
                    confirmed = tx.reboot_lcd(args.mac)
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))
        verb = "Identify" if args.command == "identify" else "LCD restart"
        _emit_output(
            args,
            {"mac": args.mac, "command": args.command, "confirmed": confirmed},
            text=f"{verb} sent to {args.mac}"
            + ("" if confirmed else " (the device did not confirm it)"),
        )
        if not confirmed:
            raise SystemExit(1)
        return

    if args.command == "set-channel":
        try:
            with wireless.WirelessTransceiver() as tx:
                moved = tx.set_channel(args.channel)
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))
        _emit_output(
            args,
            {"channel": args.channel, "results": moved},
            text="\n".join(
                f"{mac}: " + (f"on channel {args.channel}" if ok else "not moved")
                for mac, ok in moved.items()
            ),
        )
        if not all(moved.values()):
            raise SystemExit(1)
        return

    if args.command == "unbind":
        try:
            with wireless.WirelessTransceiver() as tx:
                updated = tx.unbind_device(args.mac)
            if updated and not updated.is_bound:
                data = {
                    "mac": updated.mac,
                    "master_mac": updated.master_mac,
                    "channel": updated.channel,
                    "rx_type": updated.rx_type,
                    "bound": updated.is_bound,
                }
                _emit_output(args, data, text=json.dumps(data))
            else:
                _emit_output(
                    args,
                    {"mac": args.mac, "status": "unbind_sent"},
                    text="Unbind command sent; re-run `uws fan list` to confirm status",
                )
            return
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))

    if args.command == "pwm-sync":
        mode = getattr(args, "mode", "controller")
        if args.once and mode != "controller":
            raise SystemExit("--once is only valid when --mode controller")
        if mode != "controller" and (args.interval != 1.0):
            raise SystemExit("--interval is only valid when --mode controller")
        if mode == "receiver":
            if not args.mac and not args.all:
                args.all = True
            pwm_values = [6, 6, 6, 6]
            try:
                with wireless.WirelessTransceiver() as tx:
                    receiver_macs: list[str]
                    if args.mac:
                        if not wireless.follows_motherboard_itself(args.mac):
                            raise SystemExit(
                                f"{args.mac} cannot follow the motherboard by itself "
                                "(the vendor app does this only for MACs ending in e1); "
                                "use --mode controller"
                            )
                        tx.set_pwm(
                            args.mac, pwm_values, sequence_index=args.sequence_index
                        )
                        receiver_macs = [args.mac]
                    else:
                        snapshot = tx.list_devices()
                        bound = [d for d in snapshot.devices if d.is_bound]
                        if not bound:
                            raise SystemExit("No bound wireless devices found")
                        receiver_targets = [
                            dev
                            for dev in bound
                            if wireless.follows_motherboard_itself(dev.mac)
                        ]
                        if not receiver_targets:
                            raise SystemExit(
                                "None of the bound devices can follow the motherboard by itself; "
                                "use --mode controller"
                            )
                        receiver_macs = []
                        for dev in receiver_targets:
                            tx.set_pwm_direct(
                                dev,
                                pwm_values,
                                sequence_index=args.sequence_index,
                                label=dev.mac,
                                snapshot=snapshot,
                            )
                            receiver_macs.append(dev.mac)
                receiver_payload: dict[str, Any] = {
                    "targets": receiver_macs,
                    "mode": "receiver",
                    "pwm": pwm_values,
                    "sequence_index": args.sequence_index,
                }
                text = "Enabled motherboard PWM sync (receiver mode) for " + ", ".join(
                    receiver_macs
                )
                _emit_output(args, receiver_payload, text=text)
                return
            except wireless.WirelessError as exc:
                raise SystemExit(str(exc))

        if not args.mac and not args.all:
            args.all = True
        controller_targets: list[str]
        if args.mac:
            controller_targets = [args.mac]
        else:
            with wireless.WirelessTransceiver() as tx:
                snapshot = tx.list_devices()
                controller_targets = [
                    dev.mac for dev in [d for d in snapshot.devices if d.is_bound]
                ]
            if not controller_targets:
                raise SystemExit("No bound wireless devices found")
        interval = max(args.interval, 0.1)
        try:
            tlcontroller.set_motherboard_rpm_sync(True)
            status = "once" if args.once else "running"
            controller_payload: dict[str, Any] = {
                "targets": controller_targets,
                "interval": interval,
                "status": status,
                "mode": "controller",
            }
            names = ", ".join(controller_targets)
            if args.once:
                text = (
                    f"Syncing motherboard PWM to {names} once "
                    f"(interval={interval:.2f}s)."
                )
            else:
                text = (
                    f"Syncing motherboard PWM to {names} "
                    f"(interval={interval:.2f}s). Press Ctrl+C to stop."
                )
            _emit_output(args, controller_payload, text=text)
            max_cycles = None
            stop_after_first_send = bool(args.once)
            wireless.run_pwm_sync_loop(
                controller_targets,
                interval=interval,
                max_cycles=max_cycles,
                stop_after_first_send=stop_after_first_send,
            )
            return
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))

    raise SystemExit("Unknown fan command")


def main(argv: Iterable[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_logging(args.verbose)
    if not args.namespace:
        parser.print_help()
        return
    if args.namespace == "lcd":
        handle_lcd(args)
    elif args.namespace == "fan":
        handle_fan(args)
    else:
        raise SystemExit("Unknown namespace")


def _emit_output(args: argparse.Namespace, payload, *, text: str) -> None:
    """Emit payload according to the caller's preferred output format."""
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(text)


if __name__ == "__main__":
    main()
