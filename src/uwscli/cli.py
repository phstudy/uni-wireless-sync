"""Command line interface for the UWS toolkit."""

from __future__ import annotations

import argparse
import json
import random
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

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
        "send-jpg", help="Send a JPEG frame to the LCD"
    )
    send_jpg_parser.add_argument(
        "--file", required=True, type=Path, help="JPEG file path"
    )
    send_jpg_parser.add_argument(
        "--serial", required=False, help="USB serial number of the LCD device"
    )

    keep_alive_parser = lcd_sub.add_parser(
        "keep-alive", help="Send periodic keep-alive handshakes"
    )
    keep_alive_parser.add_argument(
        "--serial", required=False, help="USB serial number of the LCD device"
    )
    keep_alive_parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between keep-alive messages (default: 5)",
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
        "--brightness", type=int, default=50, help="LCD brightness 0-100"
    )
    control_parser.add_argument("--fps", type=int, default=30, help="Video FPS")
    control_parser.add_argument(
        "--rotation",
        type=int,
        default=0,
        choices=[0, 90, 180, 270],
        help="Screen rotation in degrees",
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

    set_fan_parser = fan_sub.add_parser("set-fan", help="Send PWM to a wireless receiver")
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
        default=1,
        help="Sequence index used by the RF command (default: 1)",
    )

    effect_names = sorted(effect.name.lower() for effect in tl_effects.TLEffects)

    set_led_parser = fan_sub.add_parser(
        "set-led", help="Set LED effects on wireless receivers"
    )
    led_target = set_led_parser.add_mutually_exclusive_group(required=True)
    led_target.add_argument(
        "--mac", help="MAC address of the wireless receiver (aa:bb:cc:dd:ee:ff)"
    )
    led_target.add_argument(
        "--all", action="store_true", help="Apply to all bound wireless receivers"
    )
    set_led_parser.add_argument(
        "--mode",
        choices=["static", "rainbow", "frames", "effect", "random-effect"],
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
        default=50,
        help="Frame interval in milliseconds for rainbow mode (default: 50)",
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
        help="Brightness (0-255) applied when mode=effect (default: 255)",
    )
    set_led_parser.add_argument(
        "--effect-direction",
        type=int,
        choices=[0, 1],
        default=1,
        help="Direction for TL effects (0=reverse, 1=forward; default: 1)",
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
        help="Master MAC to bind against (defaults to first bound device)",
    )
    bind_parser.add_argument(
        "--rx-type",
        type=int,
        help="Optional RX type (1-15). Auto-selects when omitted.",
    )

    unbind_parser = fan_sub.add_parser(
        "unbind", help="Unbind a wireless receiver from the current master"
    )
    unbind_parser.add_argument(
        "--mac", required=True, help="MAC address of the wireless receiver to unbind"
    )

    sync_parser = fan_sub.add_parser(
        "pwm-sync",
        help="Synchronize fan receivers using controller polling (default) or motherboard PWM pass-through",
    )
    sync_target = sync_parser.add_mutually_exclusive_group(required=False)
    sync_target.add_argument("--mac", help="MAC address of the wireless receiver to update")
    sync_target.add_argument(
        "--all",
        action="store_true",
        help="Apply to all bound wireless receivers (default when --mac is omitted)",
    )
    sync_parser.add_argument(
        "--mode",
        choices=["controller", "receiver"],
        default="receiver",
        help="Sync mode: receiver (default, set PWM=6) or controller (legacy poll)",
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
        default=1,
        help="Sequence index used by the RF command (receiver mode only; default: 1)",
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
                rgb_cast = cast(Tuple[int, int, int], rgb_tuple)
                for v in rgb_cast:
                    if not 0 <= v <= 255:
                        raise SystemExit("Frame color values must be between 0 and 255")
                parsed.append(rgb_cast)
            else:
                raise SystemExit("Frame colors must be RGB triples")
        frames.append(parsed)
    return frames


def _ensure_pwm_values(args) -> List[int]:
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
                jpg_payload = _load_file_bytes(args.file)
                device.send_jpg(jpg_payload)
                _emit_output(
                    args,
                    {"bytes_sent": len(jpg_payload)},
                    text=f"Sent {len(jpg_payload)} bytes to LCD",
                )
            elif args.command == "control":
                setting = LCDControlSetting(
                    mode=lcd.mode_from_arg(args.mode),
                    jpg_index=args.jpg_index,
                    brightness=args.brightness,
                    video_fps=args.fps,
                    rotation=ScreenRotation.from_degrees(args.rotation),
                    enable_test=args.enable_test,
                    test_color=_parse_test_color(args.test_color),
                )
                device.control(setting)
                _emit_output(
                    args, {"status": "control_sent"}, text="LCD control command sent"
                )
            elif args.command == "keep-alive":
                interval = max(args.interval, 0.5)
                print(
                    f"Keeping LCD {serial} awake every {interval:.1f}s. Press Ctrl+C to stop."
                )
                # Perform an initial handshake to confirm connectivity.
                device.handshake()
                try:
                    while True:
                        time.sleep(interval)
                        device.handshake()
                except KeyboardInterrupt:
                    print("Keep-alive stopped.")
            else:
                raise SystemExit("Unknown lcd command")
    except lcd.LCDDeviceError as exc:
        raise SystemExit(str(exc))


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
        master_query: tuple[str, Optional[int]] | None = None
        try:
            with wireless.WirelessTransceiver() as tx:
                snapshot = tx.list_devices()
                try:
                    master_query = tx.query_master_mac()
                except wireless.WirelessError:
                    master_query = None
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))
        masters: Dict[str, Dict[str, Any]] = {}

        def ensure_entry(master_mac: str) -> Dict[str, Any]:
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

        for dev in snapshot.devices:
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
        masters_payload: List[Dict[str, Any]] = []
        for entry in masters.values():
            devices = sorted(
                entry["devices"], key=lambda item: cast(str, item["mac"])
            )
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
                    pwm_devices = [dev for dev in snapshot.devices if dev.is_bound]
                    if not pwm_devices:
                        raise SystemExit("No bound wireless devices found")
                    pwm_target_macs: List[str] = []
                    for dev in pwm_devices:
                        tx.set_pwm_direct(
                            dev,
                            pwm_values,
                            sequence_index=args.sequence_index,
                            label=dev.mac,
                        )
                        pwm_target_macs.append(dev.mac)
                else:
                    tx.set_pwm(args.mac, pwm_values, sequence_index=args.sequence_index)
                    pwm_target_macs = [args.mac]
            if args.all:
                result_payload: Dict[str, Any] = {
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

    if args.command == "set-led":
        try:
            if args.all:
                with wireless.WirelessTransceiver() as tx:
                    snapshot = tx.list_devices()
                    targets: List[str] = [
                        dev.mac for dev in snapshot.devices if dev.is_bound
                    ]
                    if not targets:
                        raise SystemExit("No bound wireless devices found")
            else:
                targets = [args.mac]
            results: List[Dict[str, Any]] = []
            last_text: str = ""
            selected_random_effect: Optional[tl_effects.TLEffects] = None
            if args.mode == "random-effect":
                selected_random_effect = random.choice(list(tl_effects.TLEffects))
            with wireless.WirelessTransceiver() as tx:
                for mac in targets:
                    entry_text: str
                    entry_data: Dict[str, Any]
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
                        interval_ms = max(1, args.interval_ms)
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
                        interval_ms = max(1, args.interval_ms)
                        tx.set_led_effect(
                            mac,
                            effect,
                            tb=tb,
                            brightness=brightness,
                            direction=direction,
                            interval_ms=interval_ms,
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
                        interval_ms = max(1, args.interval_ms)
                        tx.set_led_effect(
                            mac,
                            effect,
                            tb=tb,
                            brightness=brightness,
                            direction=direction,
                            interval_ms=interval_ms,
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
                        interval_ms = max(1, args.interval_ms)
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
            overall: Dict[str, Any] = {
                "targets": targets,
                "mode": args.mode,
            }
            if args.mode == "rainbow":
                overall["frames"] = max(1, args.frames)
                overall["interval_ms"] = max(1, args.interval_ms)
            elif args.mode in {"effect", "random-effect"}:
                if args.mode == "random-effect":
                    overall["effect"] = (
                        selected_random_effect.name if selected_random_effect else None
                    )
                else:
                    overall["effect"] = args.effect.upper() if args.effect else None
                overall["interval_ms"] = max(1, args.interval_ms)
            elif args.mode == "frames":
                overall["frames_file"] = str(args.frames_file)
                overall["interval_ms"] = max(1, args.interval_ms)
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
                    receiver_macs: List[str]
                    if args.mac:
                        tx.set_pwm(args.mac, pwm_values, sequence_index=args.sequence_index)
                        receiver_macs = [args.mac]
                    else:
                        snapshot = tx.list_devices()
                        receiver_targets = [
                            dev for dev in snapshot.devices if dev.is_bound
                        ]
                        if not receiver_targets:
                            raise SystemExit("No bound wireless devices found")
                        receiver_macs = []
                        for dev in receiver_targets:
                            tx.set_pwm_direct(
                                dev,
                                pwm_values,
                                sequence_index=args.sequence_index,
                                label=dev.mac,
                            )
                            receiver_macs.append(dev.mac)
                receiver_payload: Dict[str, Any] = {
                    "targets": receiver_macs,
                    "mode": "receiver",
                    "pwm": pwm_values,
                    "sequence_index": args.sequence_index,
                }
                text = (
                    "Enabled motherboard PWM sync (receiver mode) for "
                    + ", ".join(receiver_macs)
                )
                _emit_output(args, receiver_payload, text=text)
                return
            except wireless.WirelessError as exc:
                raise SystemExit(str(exc))

        if not args.mac and not args.all:
            args.all = True
        controller_targets: List[str]
        if args.mac:
            controller_targets = [args.mac]
        else:
            with wireless.WirelessTransceiver() as tx:
                snapshot = tx.list_devices()
            controller_targets = [dev.mac for dev in snapshot.devices if dev.is_bound]
            if not controller_targets:
                raise SystemExit("No bound wireless devices found")
        interval = max(args.interval, 0.1)
        try:
            tlcontroller.set_motherboard_rpm_sync(True)
            status = "once" if args.once else "running"
            controller_payload: Dict[str, Any] = {
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


if __name__ == "__main__":
    main()


def _emit_output(args: argparse.Namespace, payload, *, text: str) -> None:
    """Emit payload according to the caller's preferred output format."""
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(text)
