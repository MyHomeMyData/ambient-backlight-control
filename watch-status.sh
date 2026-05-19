#!/usr/bin/env bash
# watch-status.sh — display ambient-backlight-control sensor values in real time
#
# Usage:  ./watch-status.sh
#         watch -n 1 ./watch-status.sh   (alternative, same effect)

ALS_RAW=/sys/bus/iio/devices/iio:device0/in_illuminance_raw
DISPLAY_BR=/sys/class/backlight/intel_backlight/brightness
DISPLAY_MAX=/sys/class/backlight/intel_backlight/max_brightness
KBD_BR=/sys/class/leds/platform::kbd_backlight/brightness
OFFSET_FILE="$HOME/.local/state/ambient-backlight-control/offset"

read_or_na() { cat "$1" 2>/dev/null || echo "N/A"; }

als_raw=$(read_or_na "$ALS_RAW")
disp=$(read_or_na "$DISPLAY_BR")
disp_max=$(read_or_na "$DISPLAY_MAX")
kbd=$(read_or_na "$KBD_BR")

# Compute derived values when data is available
if [[ "$als_raw" =~ ^[0-9]+$ ]]; then
    als_lux=$(awk "BEGIN { printf \"%.1f\", $als_raw / 1000 }")
else
    als_lux="N/A"
fi

if [[ "$disp" =~ ^[0-9]+$ && "$disp_max" =~ ^[0-9]+$ && "$disp_max" -gt 0 ]]; then
    disp_pct=$(awk "BEGIN { printf \"%.1f\", $disp / $disp_max * 100 }")
else
    disp_pct="N/A"
fi

echo "=== ambient-backlight-control status ==="
echo ""
if [[ "$als_raw" == "N/A" ]]; then
    printf "  ALS raw value   : N/A  (iio-sensor-proxy owns the sensor)\n"
else
    printf "  ALS raw value   : %s\n"    "$als_raw"
    printf "  ALS (approx.)   : %s Lux\n" "$als_lux"
fi
echo ""
offset=$(cat "$OFFSET_FILE" 2>/dev/null || echo "0")
if [[ "$disp_max" =~ ^[0-9]+$ && "$disp_max" -gt 0 ]]; then
    offset_pct=$(awk "BEGIN { printf \"%.1f\", $offset / $disp_max * 100 }")
else
    offset_pct="N/A"
fi

printf "  Display bright. : %s / %s  (%s%%)\n" "$disp" "$disp_max" "$disp_pct"
printf "  Manual offset   : %s  (%s%%)\n"       "$offset" "$offset_pct"
printf "  Keyboard backl. : %s\n"               "$kbd"
echo ""

# iio-sensor-proxy value (only updated when a client has called ClaimLight)
iio_raw=$(gdbus call --system \
    --dest net.hadess.SensorProxy \
    --object-path /net/hadess/SensorProxy \
    --method org.freedesktop.DBus.Properties.Get \
    net.hadess.SensorProxy LightLevel 2>/dev/null)
iio_val=$(echo "$iio_raw" | grep -oP '[0-9]+\.?[0-9]*' | head -1)

iio_unit=$(gdbus call --system \
    --dest net.hadess.SensorProxy \
    --object-path /net/hadess/SensorProxy \
    --method org.freedesktop.DBus.Properties.Get \
    net.hadess.SensorProxy LightLevelUnit 2>/dev/null \
    | grep -oP "'\K[^']*(?=')")

if [[ -n "$iio_val" ]]; then
    iio_fmt=$(awk "BEGIN { printf \"%.1f\", $iio_val }")
    printf "  iio-sensor-proxy: %s %s\n" "$iio_fmt" "${iio_unit:-lux}"
else
    printf "  iio-sensor-proxy: N/A (daemon not running?)\n"
fi
