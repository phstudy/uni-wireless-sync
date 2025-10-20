# Immich Quick Sync Example

Fetch a photo from your Immich server, resize it to 400×400, and send it straight to a Uni Fan LCD using the UWS CLI libraries.

## Setup

1. Generate an Immich API key with permission to view assets.
2. (Optional) Create `~/.immich_config` containing:
   ```bash
IMMICH_BASE_URL="https://immich.local/api"
IMMICH_TOKEN="your-token"
IMMICH_ASSET_ID="optional-specific-asset"
   ```
3. Install project dependencies in editable mode:
   ```bash
   pip install -e .[dev]
   ```

## Running the Python Script

```bash
python examples/immich/immich_photo_display.py \
  --base-url "https://immich.local/api" \
  --api-key "<token>" \
  --serial b738e4b2c61e0a66 \
  --serial 999a8e502c1613a6 \
  --serial 49ec6039b31e0366
```

- Repeat `--serial` to address multiple wireless panels in one run.
- Repeat `--asset-id` to pin specific assets to matching panels; omit to fetch random previews.
- Repeat `--person-id` to limit random picks to specific Immich people (aligned with each `--serial`).
- Use `--size` if you need a square other than 400×400.

When no `--serial` arguments are provided, the script autodetects a single connected LCD. Each requested panel downloads (or reuses) a thumbnail, crops it to a centered square, resizes it, encodes JPEG bytes, and pushes the frame via `uwscli.lcd.TLLCDDevice`.

## Running with the Helper Shell Script

```bash
examples/immich/send_image.sh
```

- Override the target panels by exporting `IMMICH_DEVICE_SERIALS="serialA,serialB,..."` before running the script.
- Provide matching asset IDs with `IMMICH_ASSET_IDS="idA,idB,idC"` (or set `IMMICH_ASSET_ID` for a single value).
- Supply matching Immich person IDs via a bash array in `~/.immich_config`, e.g.
  ```bash
  IMMICH_PERSON_IDS=(
    "e38982aa-6b44-436f-ae3c-60a33d89ad71"  # panel 1
    "a6a6d5c2-caa6-4e6f-bc60-937b4759ab41"  # panel 2
    "56dc9a54-1f5e-450d-b9e7-796cc816f639"  # panel 3
  )
  ```
- Alternatively set `IMMICH_PERSON_IDS_STR="id1,id2,id3"` when array syntax is inconvenient.
- Additional CLI flags are forwarded to the Python helper.

## Notes

- Immich endpoints must be reachable from the machine driving the LCD.
- The LCD expects JPEG payloads; the helper resamples using Lanczos filtering for best quality.
- For multiple LCDs, grab the USB serial numbers via `uws lcd list` and pass them with `--serial`.
