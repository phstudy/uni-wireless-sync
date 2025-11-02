# Uni Wireless Sync CLI

Warning: This is an unofficial implementation; use at your own risk.

## Overview

Uni Wireless Sync (UWS) CLI provides command-line utilities for managing Uni Fan Wireless controllers, L-Wireless receivers, and LCD panels. Each command re-opens the required USB or RF device so no background daemon is left running, and lower-level HID/USB errors are surfaced directly to simplify scripting.

## Supported Hardware

- UNI FAN TL wireless LCD panels
- UNI FAN TL wireless fans (non-LCD)

Other Uni Fan series are currently not supported.

## Features

- Discover TL LCD USB devices and 2.4 GHz wireless fan controllers.
- Query LCD firmware and handshake data.
- Send JPEG frames or apply control settings (mode, brightness, rotation) to the LCD.
- Keep the wireless TL LCD awake by emitting periodic handshakes.
- List wireless fan receivers with metadata (MAC, master MAC, channel, device type, fan speeds, PWM targets).
- List detected master controller MAC addresses to simplify binding workflows.
- Send one-shot PWM commands to TL wireless fans over the 2.4 GHz dongle.
- Bind or unbind wireless receivers against the active master controller.
- Toggle motherboard PWM sync mode for one receiver or every bound receiver.
- Broadcast static RGB payloads to wireless receivers (experimental).

### Fan wiring modes

- **USB + PWM header (controller mode):** leave the receiver's PWM lead unplugged; control every fan via `uws fan set-fan` (any PWM value 0-255). The reported `fan_pwm` reflects your last command.
- **USB-only (receiver mode, PWM lead connected to motherboard):** the CLI writes a PWM of 6 (e.g. `uws fan pwm-sync --mode receiver --all`) so the receiver keeps syncing to the motherboard header. Sending another `set-fan` value at any time overrides the sync immediately; writing 6 (or re-running the sync helper) hands control back to the motherboard.

## FAQ

- **How do I mount the L-Wireless Controller (v1)?** The thicker dongle supports two options: (1) plug into a USB Type-A port—this wiring is equivalent to `pwm-sync` receiver mode; (2) plug the header into a 9-pin USB port on the motherboard—this matches `pwm-sync` controller mode, but 2.4 GHz signal strength drops because the dongle lives inside the chassis.
- **How do I mount the L-Wireless Controller (v2)?** The slimmer dongle only supports option (1): plug into a USB Type-A port (`pwm-sync` receiver mode).
- **What is the difference between L-Wireless Receiver (v1) and (v2)?** Receiver v1 exposes both USB and a 2-pin PWM lead only on the LCD bundle (USB powers the LCD, the 2-pin lead powers fans); non-LCD receiver v1 units ship with just the 2-pin power lead. Receiver v2 adds a dedicated 4-pin PWM header; plug it into the motherboard when you want it to mirror the motherboard duty cycle via `pwm-sync --mode receiver`, or leave it disconnected and the controller will keep driving fan PWM directly.

## Installation

```bash
pip install uwscli
# optional image helpers
pip install uwscli[images]

python -m venv .venv
source .venv/bin/activate
pip install -e .
# or include dev extras
pip install -e .[dev]
```

## Usage Examples

```bash
# Enumerate connected devices
uws lcd list
uws fan list

# Display operations
uws lcd info --serial <usb-serial>
uws lcd send-jpg --serial <usb-serial> --file assets/sample_lcd.jpg
uws lcd keep-alive --serial <usb-serial> --interval 5

# Fan receiver operations
uws fan set-fan --mac aa:bb:cc:dd:ee:ff --pwm 120  # direct PWM control
uws fan pwm-sync --mode receiver --all           # receiver mode receivers (sets PWM=6)
uws fan bind --mac aa:bb:cc:dd:ee:ff
uws fan unbind --mac aa:bb:cc:dd:ee:ff
uws fan pwm-sync --all
uws fan pwm-sync --mac aa:bb:cc:dd:ee:ff --once
```

`uws lcd list` prints JSON rows that include a `serial` field—copy that value when invoking other LCD subcommands.

## Command Reference

- `uws lcd list` – enumerate TL LCD devices and show their USB serial numbers.
- `uws lcd info --serial <usb-serial>` – read firmware and handshake data.
- `uws lcd send-jpg --serial <usb-serial> --file <image.jpg>` – stream a JPEG asset.
- `uws lcd keep-alive --serial <usb-serial> [--interval seconds]` – emit periodic handshakes to prevent the wireless panel from dimming.
- `uws lcd control --serial <usb-serial> [--mode show-jpg|show-app-sync|lcd-test] [--jpg-index N] [--brightness 0-100] [--fps N] [--rotation 0|90|180|270] [--test-color R,G,B]` – send an `LCDControlSetting` payload.
- `uws fan list` – fetch a snapshot of bound wireless receivers via the RF receiver.
- `uws fan list-masters` – enumerate master controllers and associated wireless receivers.
- `uws fan set-fan --mac <aa:bb:..> --pwm <0-255> [--sequence-index N]` – send a single shot PWM update to one receiver; `--all` broadcasts to every bound receiver.
- `uws fan pwm-sync --mac|--all [--mode controller|receiver] [--interval seconds] [--once] [--sequence-index N]` – synchronize receiver speeds. `controller` polls motherboard PWM and replays the value via RF (`--interval` / `--once` apply here); `receiver` sets PWM=6 so the receiver tracks the motherboard header directly (`--sequence-index` applies here).
- `uws fan set-led --mac <aa:bb:..> --mode static|rainbow|frames|effect|random-effect` – apply wireless LED effects (**experimental**).

### `uws fan set-led` modes

- `static`: requires `--color R,G,B` or `--color-list R,G,B;...` to paint the LED strip once.
- `rainbow`: procedural rainbow; optional `--frames N` (default 24) and `--interval-ms` (default 50).
- `frames`: feed a JSON animation via `--frames-file`. Each frame is an array of `[R, G, B]` triples; see `examples/tl_frames_sample.json` for a minimal illustration (the CLI will pad or truncate per device LED count).
- `effect`: drives any of the 29 TL presets. Choose an effect with `--effect <name>` (e.g. `twinkle`, `meteor_shower`), adjust brightness 0‑255 via `--effect-brightness`, pick direction with `--effect-direction 0|1`, and select which segment to update using `--effect-scope front|behind|both` (default `both`).
- `random-effect`: picks a random preset each time; accepts the same brightness/direction/scope flags as `effect`.

  Available effect names (case-insensitive): `rainbow`, `rainbow_morph`, `static_color`, `breathing`, `runway`, `meteor`, `color_cycle`, `staggered`, `tide`, `mixing`, `voice`, `door`, `render`, `ripple`, `reflect`, `tail_chasing`, `paint`, `ping_pong`, `stack`, `cover_cycle`, `wave`, `racing`, `lottery`, `intertwine`, `meteor_shower`, `collide`, `electric_current`, `kaleidoscope`, `twinkle`.

  Example:

  ```
  uws fan set-led --mac aa:bb:cc:dd:ee:ff --mode effect --effect twinkle --effect-brightness 180 --effect-direction 0 --effect-scope both
  ```

  Random example:

  ```
  uws fan set-led --mac aa:bb:cc:dd:ee:ff --mode random-effect --effect-brightness 200 --effect-direction 1
  ```
- `uws fan pwm-sync --all|--mac [--mode controller|receiver] [--interval seconds] [--once] [--sequence-index N]` – default `receiver` mode writes PWM=6 so fans follow the motherboard; `controller` mode polls and replays PWM from the motherboard (supports `--interval`/`--once` for polling loops; `--sequence-index` applies to receiver broadcasts).

## Dependencies

- `hidapi` (via `hid`) for TL LCD HID access.
- `pyusb` for the RF sender/receiver WinUSB endpoints.
- `pycryptodomex` for the DES-CBC transport used by the wireless LCD receiver.
- `Pillow` is optional for JPEG frame validation.

Each command expects the TL LCD USB display (vendor 0x04FC or 0x1CBE) and the wireless transmitter/receiver pair (vendor 0x0416) to be attached when the command executes.

## Linux udev Permissions

Grant non-root access to the TL wireless dongles by adding `/etc/udev/rules.d/99-tl-wireless.rules` with:

```
# Winbond SLV3RX_V1.6 (receiver)
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="8041", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="0416", ATTR{idProduct}=="8041", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_interface", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="8041", MODE="0666", GROUP="plugdev"

# Winbond SLV3TX_V1.6 (transmitter)
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="8040", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="0416", ATTR{idProduct}=="8040", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_interface", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="8040", MODE="0666", GROUP="plugdev"

# Luminary Micro TL-LCD Wireless-1.3
SUBSYSTEM=="usb", ATTR{idVendor}=="1cbe", ATTR{idProduct}=="0006", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_device", ATTR{idVendor}=="1cbe", ATTR{idProduct}=="0006", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb_interface", ATTRS{idVendor}=="1cbe", ATTRS{idProduct}=="0006", MODE="0666", GROUP="plugdev"
```

Reload the rules and replug the dongles:

```
sudo udevadm control --reload
sudo udevadm trigger
```

## License

Released under the MIT License. See `LICENSE` for details.
