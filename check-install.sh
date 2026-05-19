#!/usr/bin/env bash
# check-install.sh — show installation status without changing anything

INSTALL_DIR="$HOME/.local/lib/ambient-backlight-control"
CONFIG_DIR="$HOME/.config/ambient-backlight-control"
STATE_DIR="$HOME/.local/state/ambient-backlight-control"
SERVICE_NAME="ambient-backlight-control"
SERVICE_FILE="$HOME/.config/systemd/user/${SERVICE_NAME}.service"
UDEV_RULES="/etc/udev/rules.d/90-ambient-backlight-control.rules"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✔${NC}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "  ${RED}✘${NC}  $*"; }
section() { echo -e "\n${CYAN}── $* ${NC}"; }

# ── System dependencies ───────────────────────────────────────────────────────
section "System dependencies"

if systemctl is-active --quiet iio-sensor-proxy 2>/dev/null; then
    ok "iio-sensor-proxy  active"
else
    fail "iio-sensor-proxy  not running  (sudo apt install iio-sensor-proxy)"
fi

for pkg in evdev dasbus gi; do
    apt_pkg="python3-${pkg}"
    if python3 -c "import ${pkg}" 2>/dev/null; then
        ok "python3-${pkg}  installed"
    else
        fail "python3-${pkg}  not found  (sudo apt install ${apt_pkg})"
    fi
done

# ── User / permissions ────────────────────────────────────────────────────────
section "User & permissions"

if id -nG "$USER" | grep -qw input; then
    ok "User '$USER' is in the 'input' group"
else
    fail "User '$USER' is NOT in the 'input' group  (sudo usermod -aG input $USER  + re-login)"
fi

for path in \
    "/sys/class/backlight/intel_backlight/brightness" \
    "/sys/class/leds/platform::kbd_backlight/brightness"; do
    if [ -w "$path" ]; then
        ok "Writable: $path"
    elif [ -e "$path" ]; then
        fail "Not writable: $path  (udev rules missing or not yet active)"
    else
        warn "Not found: $path"
    fi
done

# ── udev rules ────────────────────────────────────────────────────────────────
section "udev rules"

if [ -f "$UDEV_RULES" ]; then
    ok "Installed: $UDEV_RULES"
else
    fail "Not installed: $UDEV_RULES"
fi

# ── Installed files ───────────────────────────────────────────────────────────
section "Installed files"

for f in "ambient-backlight-control.py" "curve.py"; do
    if [ -f "$INSTALL_DIR/$f" ]; then
        ok "$INSTALL_DIR/$f"
    else
        fail "Missing: $INSTALL_DIR/$f"
    fi
done

# ── Configuration ─────────────────────────────────────────────────────────────
section "Configuration"

if [ -f "$CONFIG_DIR/config.ini" ]; then
    ok "Config: $CONFIG_DIR/config.ini"
else
    fail "Missing: $CONFIG_DIR/config.ini"
fi

# ── Runtime state ─────────────────────────────────────────────────────────────
section "Runtime state"

if [ -f "$STATE_DIR/offset" ]; then
    offset=$(cat "$STATE_DIR/offset")
    ok "Offset file: $STATE_DIR/offset  (value: $offset)"
else
    warn "No offset file yet  (created by daemon on first brightness-key press)"
fi

# ── systemd service ───────────────────────────────────────────────────────────
section "systemd user service"

if [ -f "$SERVICE_FILE" ]; then
    ok "Unit file: $SERVICE_FILE"
else
    fail "Unit file not installed: $SERVICE_FILE"
fi

enabled=$(systemctl --user is-enabled "$SERVICE_NAME" 2>/dev/null)
active=$(systemctl --user is-active  "$SERVICE_NAME" 2>/dev/null)

case "$enabled" in
    enabled)  ok   "Service enabled (auto-start on login)" ;;
    disabled) warn "Service installed but not enabled" ;;
    *)        fail "Service not found by systemd  ($enabled)" ;;
esac

case "$active" in
    active)   ok   "Service is running" ;;
    inactive) warn "Service is not running" ;;
    failed)   fail "Service has FAILED  (journalctl --user -u $SERVICE_NAME -n 20)" ;;
    *)        fail "Service status unknown  ($active)" ;;
esac

echo ""
