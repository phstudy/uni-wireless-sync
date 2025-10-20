#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${IMMICH_CONFIG_PATH:-$HOME/.immich_config}"
UWS_CLI_BIN="${UWS_CLI_BIN:-uws}"

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

: "${IMMICH_BASE_URL:?IMMICH_BASE_URL not set (set in env or $CONFIG_FILE)}"
: "${IMMICH_TOKEN:?IMMICH_TOKEN not set (set in env or $CONFIG_FILE)}"

# Provide comma separated USB serial numbers.
IFS=',' read -r -a DEVICE_SERIALS <<< "${IMMICH_DEVICE_SERIALS:-}"
IFS=',' read -r -a ASSET_IDS <<< "${IMMICH_ASSET_IDS:-${IMMICH_ASSET_ID:-}}"

if declare -p IMMICH_PERSON_IDS >/dev/null 2>&1; then
  PERSON_IDS=("${IMMICH_PERSON_IDS[@]}")
else
  IFS=',' read -r -a PERSON_IDS <<< "${IMMICH_PERSON_IDS_STR:-}"
fi

BASE_ARGS=(
  "--base-url" "$IMMICH_BASE_URL"
  "--api-key" "$IMMICH_TOKEN"
)

for serial in "${DEVICE_SERIALS[@]}"; do
  [[ -n "$serial" ]] || continue
  BASE_ARGS+=("--serial" "$serial")
done

for asset in "${ASSET_IDS[@]}"; do
  [[ -n "$asset" ]] || continue
  BASE_ARGS+=("--asset-id" "$asset")
done

for person in "${PERSON_IDS[@]}"; do
  [[ -n "$person" ]] || continue
  BASE_ARGS+=("--person-id" "$person")
done

run_uws() {
  if command -v "$UWS_CLI_BIN" >/dev/null 2>&1; then
    "$UWS_CLI_BIN" "$@"
  else
    python -m uwscli.cli "$@"
  fi
}

set_brightness() {
  local level="$1"
  for serial in "${DEVICE_SERIALS[@]}"; do
    [[ -n "$serial" ]] || continue
    echo "Adjusting LCD $serial brightness to $level" >&2
    if ! output=$(run_uws lcd control --serial "$serial" --brightness "$level" 2>&1); then
      echo "Failed to set brightness for $serial" >&2
      [[ -z "$output" ]] || echo "$output" >&2
    fi
  done
}

HOUR=$(date +%H)
DAY=$(date +%u)  # 1-7, where 1 is Monday

if [ $DAY -le 5 ] && [ $HOUR -ge 17 ] && [ $HOUR -le 21 ]; then
  set_brightness 50
  python "$SCRIPT_DIR/immich_photo_display.py" "${BASE_ARGS[@]}" "$@"
# Saturday-Sunday 7-21
elif [ $DAY -ge 6 ] && [ $HOUR -ge 7 ] && [ $HOUR -le 21 ]; then
  set_brightness 50
  python "$SCRIPT_DIR/immich_photo_display.py" "${BASE_ARGS[@]}" "$@"
else
  set_brightness 0
fi
