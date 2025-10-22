"""Command line interface for the UWS toolkit."""

from __future__ import annotations

import argparse
import json
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, cast

from . import lcd, tlcontroller, wireless
from .logging_utils import configure_logging
from .structs import LCDControlSetting, ScreenRotation, clamp_pwm_values


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

    # Fan namespace (wireless TL hubs)
    fan_parser = subparsers.add_parser("fan", help="Interact with UNI FAN TL fans")
    fan_sub = fan_parser.add_subparsers(dest="command", required=True)

    fan_sub.add_parser("list", help="List wireless hubs discovered via RF dongle")

    set_fan_parser = fan_sub.add_parser("set-fan", help="Send PWM to a wireless hub")
    set_fan_parser.add_argument(
        "--mac",
        required=True,
        help="MAC address of the wireless hub (aa:bb:cc:dd:ee:ff)",
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

    set_led_parser = fan_sub.add_parser(
        "set-led", help="Set LED effects on wireless hubs"
    )
    led_target = set_led_parser.add_mutually_exclusive_group(required=True)
    led_target.add_argument(
        "--mac", help="MAC address of the wireless hub (aa:bb:cc:dd:ee:ff)"
    )
    led_target.add_argument(
        "--all", action="store_true", help="Apply to all bound wireless hubs"
    )
    set_led_parser.add_argument(
        "--mode",
        choices=["static", "rainbow", "frames"],
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
        "--dict-size",
        type=int,
        default=4096,
        help="Dictionary size used for TinyUZ compression (default: 4096)",
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

    bind_parser = fan_sub.add_parser(
        "bind", help="Bind an unlinked wireless hub to the current master"
    )
    bind_parser.add_argument(
        "--mac", required=True, help="MAC address of the wireless hub to bind"
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
        "unbind", help="Unbind a wireless hub from the current master"
    )
    unbind_parser.add_argument(
        "--mac", required=True, help="MAC address of the wireless hub to unbind"
    )

    sync_parser = fan_sub.add_parser(
        "pwm-sync",
        help="Continuously mirror motherboard PWM output to wireless hubs",
    )
    sync_target = sync_parser.add_mutually_exclusive_group(required=False)
    sync_target.add_argument("--mac", help="MAC address of the wireless hub to update")
    sync_target.add_argument(
        "--all",
        action="store_true",
        help="Apply to all bound wireless hubs (default when --mac is omitted)",
    )
    sync_parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
    )
    sync_parser.add_argument(
        "--once",
        action="store_true",
        help="Perform a single sync iteration instead of looping until interrupted",
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

    if args.command == "set-fan":
        pwm_values = _ensure_pwm_values(args)
        try:
            with wireless.WirelessTransceiver() as tx:
                tx.set_pwm(args.mac, pwm_values, sequence_index=args.sequence_index)
            payload = {
                "mac": args.mac,
                "pwm": list(pwm_values),
                "sequence_index": args.sequence_index,
            }
            _emit_output(args, payload, text=f"Applied PWM {pwm_values} to {args.mac}")
            return
        except wireless.WirelessError as exc:
            raise SystemExit(str(exc))

    if args.command == "set-led":
        try:
            if args.all:
                with wireless.WirelessTransceiver() as tx:
                    snapshot = tx.list_devices()
                    targets = [dev.mac for dev in snapshot.devices if dev.is_bound]
                    if not targets:
                        raise SystemExit("No bound wireless devices found")
            else:
                targets = [args.mac]
            results: List[Dict[str, Any]] = []
            with wireless.WirelessTransceiver() as tx:
                for mac in targets:
                    text: str
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
                            dict_size=args.dict_size,
                        )
                        payload = {
                            "mac": mac,
                            "mode": "static",
                            "dict_size": args.dict_size,
                        }
                        if base_color is not None:
                            payload["color"] = list(base_color)
                        if colors is not None:
                            payload["color_list"] = [list(c) for c in colors]
                        text = f"Applied static LED effect to {mac}"
                    elif args.mode == "rainbow":
                        frames = max(1, args.frames)
                        interval_ms = max(1, args.interval_ms)
                        tx.set_led_rainbow(
                            mac,
                            frames=frames,
                            interval_ms=interval_ms,
                            dict_size=args.dict_size,
                        )
                        payload = {
                            "mac": mac,
                            "mode": "rainbow",
                            "frames": frames,
                            "interval_ms": interval_ms,
                            "dict_size": args.dict_size,
                        }
                        text = f"Applied rainbow LED effect to {mac}"
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
                            dict_size=args.dict_size,
                        )
                        payload = {
                            "mac": mac,
                            "mode": "frames",
                            "frames": len(frame_list),
                            "interval_ms": interval_ms,
                            "dict_size": args.dict_size,
                        }
                        text = f"Applied custom LED frames to {mac}"
                    results.append(payload)
            overall = {
                "targets": targets,
                "mode": args.mode,
                "dict_size": args.dict_size,
            }
            if args.mode == "rainbow":
                overall["frames"] = max(1, args.frames)
                overall["interval_ms"] = max(1, args.interval_ms)
            elif args.mode == "frames":
                overall["frames_file"] = str(args.frames_file)
                overall["interval_ms"] = max(1, args.interval_ms)
            overall["details"] = results
            text_out = "\n".join(json.dumps(entry) for entry in results)
            if len(targets) == 1:
                _emit_output(args, results[0], text=text)
            else:
                _emit_output(args, overall, text=text_out)
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
        if not args.mac and not args.all:
            args.all = True
        target_macs: list[str]
        if args.mac:
            target_macs = [args.mac]
        else:
            with wireless.WirelessTransceiver() as tx:
                snapshot = tx.list_devices()
            target_macs = [dev.mac for dev in snapshot.devices if dev.is_bound]
            if not target_macs:
                raise SystemExit("No bound wireless devices found")
        interval = max(args.interval, 0.1)
        try:
            tlcontroller.set_motherboard_rpm_sync(True)
            status = "once" if args.once else "running"
            payload = {
                "targets": target_macs,
                "interval": interval,
                "status": status,
            }
            names = ", ".join(target_macs)
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
            _emit_output(args, payload, text=text)
            max_cycles = None
            stop_after_first_send = bool(args.once)
            wireless.run_pwm_sync_loop(
                target_macs,
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
