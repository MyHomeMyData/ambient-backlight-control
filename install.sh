#!/usr/bin/env bash
# install.sh — installer / uninstaller for ambient-backlight-control
#
# Usage:
#   ./install.sh            Install
#   ./install.sh --uninstall  Uninstall

set -euo pipefail

INSTALL_DIR="$HOME/.local/lib/ambient-backlight-control"
CONFIG_DIR="$HOME/.config/ambient-backlight-control"
SERVICE_NAME="ambient-backlight-control"
SERVICE_FILE="$SERVICE_NAME.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
UDEV_RULES_FILE="90-ambient-backlight-control.rules"
UDEV_RULES_DIR="/etc/udev/rules.d"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Dependency check ──────────────────────────────────────────────────────────
check_dependencies() {
    local missing=()

    if ! systemctl is-active --quiet iio-sensor-proxy 2>/dev/null; then
        warn "iio-sensor-proxy is not running. Install with: sudo apt install iio-sensor-proxy"
        missing+=(iio-sensor-proxy)
    fi

    if ! python3 -c "import evdev" 2>/dev/null; then
        warn "Python package 'evdev' not found. Install with: sudo apt install python3-evdev"
        missing+=(python3-evdev)
    fi

    if ! python3 -c "import dasbus" 2>/dev/null; then
        warn "Python package 'dasbus' not found. Install with: sudo apt install python3-dasbus"
        missing+=(python3-dasbus)
    fi

    if ! python3 -c "from gi.repository import GLib" 2>/dev/null; then
        warn "Python package 'python3-gi' not found. Install with: sudo apt install python3-gi"
        missing+=(python3-gi)
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        error "Missing dependencies: ${missing[*]}"
        error "Please install them and re-run this script."
        exit 1
    fi
}

# ── input group setup ─────────────────────────────────────────────────────────
setup_input_group() {
    if id -nG "$USER" | grep -qw input; then
        info "User '$USER' is already in the 'input' group."
        return
    fi
    info "Adding '$USER' to the 'input' group (requires sudo)..."
    sudo usermod -aG input "$USER"
    echo ""
    warn "You have been added to the 'input' group."
    warn "You must LOG OUT and LOG BACK IN for this to take effect."
    warn "After re-login, run: systemctl --user start $SERVICE_NAME"
    echo ""
}

# ── Install ───────────────────────────────────────────────────────────────────
install() {
    info "Installing ambient-backlight-control..."

    check_dependencies
    setup_input_group

    # Copy Python files
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/ambient-backlight-control.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/curve.py"         "$INSTALL_DIR/"
    info "Installed Python files to $INSTALL_DIR"

    # Copy default config (do not overwrite existing user config)
    mkdir -p "$CONFIG_DIR"
    if [ ! -f "$CONFIG_DIR/config.ini" ]; then
        cp "$SCRIPT_DIR/config.ini" "$CONFIG_DIR/config.ini"
        info "Installed default config to $CONFIG_DIR/config.ini"
    else
        info "Existing config kept at $CONFIG_DIR/config.ini"
    fi

    # Install udev rules (requires sudo)
    info "Installing udev rules (requires sudo)..."
    sudo cp "$SCRIPT_DIR/$UDEV_RULES_FILE" "$UDEV_RULES_DIR/$UDEV_RULES_FILE"
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    info "udev rules installed and reloaded."

    # Install systemd user service
    mkdir -p "$SYSTEMD_USER_DIR"
    cp "$SCRIPT_DIR/$SERVICE_FILE" "$SYSTEMD_USER_DIR/$SERVICE_FILE"
    systemctl --user daemon-reload
    info "systemd service installed."

    echo ""
    info "Installation complete."
    echo ""
    echo "  Start now:       systemctl --user start $SERVICE_NAME"
    echo "  Enable on login: systemctl --user enable $SERVICE_NAME"
    echo "  View logs:       journalctl --user -u $SERVICE_NAME -f"
}

# ── Uninstall ─────────────────────────────────────────────────────────────────
uninstall() {
    info "Uninstalling ambient-backlight-control..."

    systemctl --user stop    "$SERVICE_NAME" 2>/dev/null || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SYSTEMD_USER_DIR/$SERVICE_FILE"
    systemctl --user daemon-reload
    info "systemd service removed."

    rm -rf "$INSTALL_DIR"
    info "Removed $INSTALL_DIR"

    if [ -f "$UDEV_RULES_DIR/$UDEV_RULES_FILE" ]; then
        info "Removing udev rules (requires sudo)..."
        sudo rm -f "$UDEV_RULES_DIR/$UDEV_RULES_FILE"
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        info "udev rules removed."
    fi

    echo ""
    warn "Your configuration at $CONFIG_DIR was kept. Remove manually if desired:"
    echo "  rm -rf $CONFIG_DIR"
}

# ── Entry point ───────────────────────────────────────────────────────────────
case "${1:-}" in
    --uninstall) uninstall ;;
    "")          install   ;;
    *) error "Unknown argument: $1"; echo "Usage: $0 [--uninstall]"; exit 1 ;;
esac
