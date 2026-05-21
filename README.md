# ambient-backlight-control

A Python daemon for **automatic keyboard backlight and display brightness control** based on the
ambient light sensor (ALS) built into Lenovo laptops running Linux.

Developed and tested on a **Lenovo Yoga Slim 7 14ITL05 (82A3)** running **Linux Mint 22.3
(Cinnamon)**. Linux Mint / Cinnamon does not provide automatic brightness control natively —
this daemon fills that gap.

---

## Features

- Smooth, perceptually linear brightness curve (no fixed steps)
- Manual brightness offset via keyboard brightness keys (Fn+F5 / Fn+F6)
- Keyboard backlight on/off with hysteresis, off when screen blanks
- Correct resume-from-suspend and screen-unblank handling via D-Bus
- All parameters configurable in a single `config.ini` file
- No root required at runtime (udev rules handle sysfs permissions)

---

## Hardware Requirements

| Component          | sysfs Path                                                    |
|--------------------|---------------------------------------------------------------|
| ALS sensor         | `/sys/bus/iio/devices/iio:device0/in_illuminance_raw`         |
| Keyboard backlight | `/sys/class/leds/platform::kbd_backlight/brightness`          |
| Display backlight  | `/sys/class/backlight/intel_backlight/brightness`             |

The daemon reads the ALS sensor via **iio-sensor-proxy** (D-Bus interface `net.hadess.SensorProxy`),
which must be installed and running.

---

## Dependencies

Install all required packages via apt:

```bash
sudo apt install iio-sensor-proxy python3-evdev python3-dasbus python3-gi
```

> **Note:** `python3-gi` (PyGObject) is usually pre-installed on Cinnamon / GNOME desktops.
> `iio-sensor-proxy` may also already be present — check with `systemctl status iio-sensor-proxy`.

| Package            | Purpose                                            |
|--------------------|----------------------------------------------------|
| `iio-sensor-proxy` | ALS sensor abstraction (D-Bus)                     |
| `python3-evdev`    | Detect brightness key input devices                |
| `python3-dasbus`   | D-Bus client for iio-sensor-proxy                  |
| `python3-gi`       | GLib/Gio event loop and logind D-Bus signals        |

---

## Installation

Run the installer script — it checks dependencies, adds you to the `input` group, installs
files, sets up udev rules, and registers the systemd user service:

```bash
git clone https://github.com/MyHomeMyData/ambient-backlight-control.git
cd ambient-backlight-control
./install.sh
```

> **Important:** The installer adds your user to the `input` group. You must **log out and log
> back in** after installation for this to take effect.

After logging back in, start the service:

```bash
systemctl --user start ambient-backlight-control
systemctl --user enable ambient-backlight-control   # auto-start on login
```

Check the status:

```bash
systemctl --user status ambient-backlight-control
journalctl --user -u ambient-backlight-control -f
```

---

## How brightness keys work

On most Lenovo laptops the firmware (embedded controller) adjusts display brightness directly
when Fn+F5 / Fn+F6 is pressed, before any input event reaches userspace. The daemon detects
this by comparing the sysfs brightness value on each poll cycle against the value it last wrote.
Any difference is treated as a manual adjustment and added to a persistent **offset** on top of
the ALS-based curve.

The offset is saved to `~/.local/state/ambient-backlight-control/offset` on every change and
restored automatically when the daemon starts. To reset it to zero:

```bash
echo 0 > ~/.local/state/ambient-backlight-control/offset
systemctl --user restart ambient-backlight-control
```

---

## Monitoring

`watch-status.sh` displays all relevant values in real time:

```bash
watch -n 1 ./watch-status.sh
```

Output includes ALS level (from iio-sensor-proxy), display brightness (absolute and percent),
current manual offset, and keyboard backlight state.

`check-install.sh` shows the full installation status without changing anything — useful before
installation and for troubleshooting:

```bash
./check-install.sh
```

---

## Configuration

Edit `~/.config/ambient-backlight-control/config.ini` after installation.
All parameters are documented inline. Restart the service after changes:

```bash
systemctl --user restart ambient-backlight-control
```

---

## Uninstallation

```bash
./install.sh --uninstall
```

---

## Project Structure

```
ambient-backlight-control.py        # Main daemon: event loop, D-Bus, suspend/resume
curve.py                            # Brightness curve logic (isolated, unit-testable)
config.ini                          # Default configuration (copied to ~/.config/... on install)
install.sh                          # Installer / uninstaller
check-install.sh                    # Installation status checker (read-only)
watch-status.sh                     # Real-time monitoring helper
ambient-backlight-control.service   # systemd user service unit
90-ambient-backlight-control.rules  # udev rules for sysfs write permissions
tests/
    test_curve.py                   # Unit tests for curve.py
```

Runtime state is kept in `~/.local/state/ambient-backlight-control/`:

```
offset    # Persistent manual brightness offset (integer, restored on daemon start)
```

---

## Changelog

### v0.1.2 — 2026-05-21 — Screen-blank keyboard backlight

- Keyboard backlight is now turned off when the screen blanks (idle timeout or screensaver)
- On unblank, keyboard backlight state is forced off and re-evaluated on the next poll cycle —
  prevents firmware from leaving the backlight on in a bright environment after resume
- Implemented via `org.cinnamon.ScreenSaver` D-Bus signal (`ActiveChanged`, session bus)

### v0.1.1 — 2026-05-20 — Configurable offset limit

- Added `manual_offset_limit` to `config.ini` (default: ±25% of `brightness_max`)
- Offset is now clamped to this absolute limit in addition to the brightness range
- Stored offset is clamped to the configured limit on daemon start

### v0.1.0 — 2026-05-19 — Initial version

- Smooth, gamma-corrected brightness curve (ALS → display brightness)
- ALS sensor read via iio-sensor-proxy D-Bus interface (unit: lux)
- Manual brightness offset via Fn+F5 / Fn+F6, detected through sysfs change monitoring
- Persistent offset — saved on change, restored on daemon start
- Keyboard backlight on/off with configurable hysteresis thresholds
- Suspend/resume handling via systemd-logind D-Bus signal
- Smooth fade animation for brightness transitions
- systemd user service with automatic restart
- udev rules for rootless sysfs write access
- `install.sh` / `check-install.sh` / `watch-status.sh` helper scripts
- Unit tests for brightness curve logic (`pytest`)

---

## License

MIT — see [LICENSE](LICENSE).
