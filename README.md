# Uni Wireless Sync CLI

Warning: This is an unofficial implementation; use at your own risk.

## Overview

Uni Wireless Sync (UWS) CLI provides command-line utilities for managing Uni Fan Wireless controllers, L-Wireless receivers, and LCD panels. Each command re-opens the required USB or RF device so no background daemon is left running, and lower-level HID/USB errors are surfaced directly to simplify scripting.

## Supported Hardware

- UNI FAN TL wireless LCD panels
- UNI FAN TL wireless fan hubs (non-LCD)

Other Uni Fan series are currently not supported.

## Features

- Discover TL LCD USB devices and 2.4 GHz wireless fan controllers.
- Query LCD firmware and handshake data.
- Send JPEG frames or apply control settings (mode, brightness, rotation) to the LCD.
- Keep the wireless TL LCD awake by emitting periodic handshakes.
- List wireless fan hubs with metadata (MAC, master MAC, channel, device type, fan speeds, PWM targets).
- Send one-shot PWM commands to TL wireless fans over the 2.4 GHz dongle.
- Bind or unbind wireless hubs against the active master controller.
- Toggle motherboard PWM sync mode for one hub or every bound hub.

## Roadmap

- Broadcast static RGB payloads to wireless hubs (CLI command not yet implemented).

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

# Fan hub operations
uws fan set-fan --mac aa:bb:cc:dd:ee:ff --pwm 120
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
- `uws fan list` – fetch a snapshot of bound wireless devices via the RF receiver.
- `uws fan set-fan --mac <aa:bb:..> --pwm <0-255>` – send a single shot PWM update to the matching wireless hub using the RF sender.
- `uws fan set-led --mac <aa:bb:..> --mode static|rainbow|frames` – apply LED effects (experimental).
- `uws fan pwm-sync --all|--mac [--once]` – mirror motherboard PWM output to bound hubs (looping by default, single iteration with `--once`).

## Dependencies

- `hidapi` (via `hid`) for TL LCD HID access.
- `pyusb` for the RF sender/receiver WinUSB endpoints.
- `pycryptodomex` for the DES-CBC transport used by the wireless LCD hub.
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
