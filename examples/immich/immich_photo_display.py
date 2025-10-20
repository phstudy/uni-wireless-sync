#!/usr/bin/env python3
"""Fetch a photo from Immich, resize to 400x400, and push it to a Uni Fan LCD."""

from __future__ import annotations

import argparse
import random
import sys
import time
from io import BytesIO
from typing import List, Optional

import requests
from PIL import Image, ImageOps

from uwscli import lcd

IMMICH_DEFAULT_TAKE = 1000
TARGET_SIZE = 400
BUSY_RETRY_ATTEMPTS = 3
BUSY_RETRY_DELAY_SECONDS = 0.5
BUSY_ERROR_SNIPPET = "USB interface is busy"


def _search_assets(
    base_url: str,
    api_key: str,
    *,
    take: int = IMMICH_DEFAULT_TAKE,
    person_id: Optional[str] = None,
) -> List[dict]:
    """POST to Immich metadata search to retrieve candidate assets."""
    url = f"{base_url}/search/metadata"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload: dict[str, object] = {"size": take}
    if person_id:
        payload["personIds"] = [person_id]
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    assets = (
        payload.get("assets", {}).get("items")
        if isinstance(payload, dict)
        else payload
    )
    if not assets:
        raise SystemExit("No assets returned by Immich. Check permissions or adjust --take.")
    if not isinstance(assets, list):
        raise SystemExit("Unexpected Immich response format when retrieving assets.")
    return assets


def fetch_asset_id(base_url: str, api_key: str, take: int = IMMICH_DEFAULT_TAKE) -> str:
    """Return a random asset id from the Immich library."""
    assets = _search_assets(base_url, api_key, take=take)
    asset = random.choice(assets)
    asset_id = asset.get("id") if isinstance(asset, dict) else None
    if not asset_id:
        raise SystemExit("Unable to determine asset id from Immich response.")
    return asset_id


def fetch_asset_for_person(
    base_url: str,
    api_key: str,
    person_id: str,
    take: int = IMMICH_DEFAULT_TAKE,
) -> str:
    """Return a random asset id belonging to a specific person."""
    assets = _search_assets(base_url, api_key, take=take, person_id=person_id)
    asset = random.choice(assets)
    asset_id = asset.get("id") if isinstance(asset, dict) else None
    if not asset_id:
        raise SystemExit(f"Unable to determine asset id for person {person_id}.")
    return asset_id


def download_image(asset_id: str, base_url: str, api_key: str) -> Image.Image:
    """Download the preview thumbnail for the specified asset."""
    headers = {"x-api-key": api_key}
    url = f"{base_url}/assets/{asset_id}/thumbnail"
    params = {"size": "preview"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGB")


def resize_to_square(image: Image.Image, size: int = TARGET_SIZE) -> bytes:
    """Return JPEG bytes resized/cropped to a square of the desired size without distorting faces."""
    width, height = image.size
    if width == height:
        fitted = image.resize((size, size), Image.Resampling.LANCZOS)
    else:
        # Fit maintains aspect ratio by cropping excess while keeping scale consistent.
        fitted = ImageOps.fit(image, (size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    fitted.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _normalize_serial(serial: str) -> str:
    value = serial.strip()
    if not value:
        raise SystemExit("Serial value cannot be empty")
    if value.startswith("serial:"):
        value = value.split(":", 1)[1]
    value = value.strip()
    if not value:
        raise SystemExit("Serial value cannot be empty")
    return value


def resolve_lcd_serials(explicit: Optional[List[str]]) -> List[str]:
    if explicit:
        return [_normalize_serial(item) for item in explicit if item]
    devices = [dev for dev in lcd.enumerate_devices() if dev.source == "wireless" and dev.serial_number]
    if not devices:
        raise SystemExit("No wireless TL LCD devices detected. Connect one or pass --serial.")
    if len(devices) > 1:
        choices = "\n".join(f"  {dev.serial_number}" for dev in devices if dev.serial_number)
        raise SystemExit(f"Multiple TL LCDs detected; pass --serial from one of:\n{choices}")
    serial_number = devices[0].serial_number
    if not serial_number:
        raise SystemExit("Detected LCD is missing a serial number; specify --serial explicitly.")
    return [_normalize_serial(serial_number)]


def push_to_lcd(jpeg_bytes: bytes, selector: str) -> None:
    for attempt in range(BUSY_RETRY_ATTEMPTS):
        try:
            with lcd.TLLCDDevice(selector) as panel:
                panel.send_jpg(jpeg_bytes)
            return
        except lcd.LCDDeviceError as exc:
            message = str(exc)
            if BUSY_ERROR_SNIPPET not in message or attempt == BUSY_RETRY_ATTEMPTS - 1:
                raise
            delay = BUSY_RETRY_DELAY_SECONDS * (attempt + 1)
            print(f"LCD {selector} busy; retrying in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Immich server base URL (e.g. https://immich.local/api)")
    parser.add_argument("--api-key", required=True, help="Immich API key with asset read permissions")
    parser.add_argument(
        "--asset-id",
        action="append",
        help="Specific asset id to display (repeat to match multiple serials); random when omitted",
    )
    parser.add_argument(
        "--person-id",
        action="append",
        help="Restrict random selection to assets belonging to this person (repeat to match --serial order)",
    )
    parser.add_argument(
        "--serial",
        action="append",
        help="USB serial of the Uni Fan TL LCD (repeat to target multiple panels)",
    )
    parser.add_argument("--size", type=int, default=TARGET_SIZE, help="Square image size (default: 400)")
    parser.add_argument("--take", type=int, default=IMMICH_DEFAULT_TAKE, help="Number of assets to sample when picking randomly (default: 1000)")

    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    selectors = resolve_lcd_serials(args.serial)
    asset_ids = args.asset_id or []
    person_ids = args.person_id or []

    for index, selector in enumerate(selectors):
        if index < len(asset_ids):
            asset_id = asset_ids[index]
        else:
            person_id = person_ids[index] if index < len(person_ids) else None
            if person_id:
                asset_id = fetch_asset_for_person(base_url, args.api_key, person_id, args.take)
            else:
                asset_id = fetch_asset_id(base_url, args.api_key, args.take)
        image = download_image(asset_id, base_url, args.api_key)
        jpeg_bytes = resize_to_square(image, size=args.size)
        try:
            push_to_lcd(jpeg_bytes, selector)
        except lcd.LCDDeviceError as exc:
            print(f"Failed to push asset {asset_id} to LCD {selector}: {exc}", file=sys.stderr)
            continue
        print(f"Pushed asset {asset_id} to LCD {selector} at {args.size}x{args.size}.")


if __name__ == "__main__":
    main()
