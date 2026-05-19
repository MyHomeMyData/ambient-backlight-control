#!/usr/bin/env python3
"""
ambient-backlight-control — automatic keyboard backlight and display brightness daemon.

Reads the ambient light sensor via iio-sensor-proxy (D-Bus), applies a configurable
gamma curve to compute target display brightness, fades smoothly to it, manages
keyboard backlight with hysteresis, adjusts brightness via Fn+F5/F6 (evdev), and
handles suspend/resume via systemd-logind D-Bus signals.
"""

import configparser
import logging
import signal
import sys
import threading
from pathlib import Path

from gi.repository import GLib, Gio
from dasbus.connection import SystemMessageBus
import evdev
from evdev import ecodes

from curve import als_to_brightness, fade_step


CONFIG_SEARCH_PATHS = [
    Path.home() / ".config" / "ambient-backlight-control" / "config.ini",
    Path(__file__).parent / "config.ini",
]

STATE_DIR = Path.home() / ".local" / "state" / "ambient-backlight-control"
OFFSET_FILE = STATE_DIR / "offset"

log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    for path in CONFIG_SEARCH_PATHS:
        if path.exists():
            cfg.read(path)
            log.info("Config: %s", path)
            return cfg
    raise FileNotFoundError(
        "No config.ini found. Searched:\n" + "\n".join(str(p) for p in CONFIG_SEARCH_PATHS)
    )


# ── sysfs backlight I/O ───────────────────────────────────────────────────────

class BacklightWriter:
    """Reads and writes display and keyboard backlight brightness via sysfs."""

    def __init__(self, display_path: Path, kbd_path: Path, display_max_path: Path) -> None:
        self._display = display_path
        self._kbd = kbd_path
        self._display_max = display_max_path

    def read_display_max(self) -> int:
        return int(self._display_max.read_text().strip())

    def read_display(self) -> int:
        return int(self._display.read_text().strip())

    def write_display(self, value: int) -> None:
        try:
            self._display.write_text(str(value))
        except OSError as e:
            log.error("Display brightness write failed: %s", e)

    def read_kbd(self) -> int:
        return int(self._kbd.read_text().strip())

    def write_kbd(self, value: int) -> None:
        try:
            self._kbd.write_text(str(value))
        except OSError as e:
            log.error("Keyboard backlight write failed: %s", e)


# ── Brightness key listener (evdev, runs in background thread) ────────────────

class BrightnessKeyListener(threading.Thread):
    """
    Listens for KEY_BRIGHTNESSUP / KEY_BRIGHTNESSDOWN events from /dev/input/.

    evdev's read_loop() blocks, so this runs in its own daemon thread.
    The on_change callback is called from this thread and must be thread-safe.
    """

    def __init__(self, step: int, on_change) -> None:
        super().__init__(daemon=True, name="evdev-keys")
        self._step = step
        self._on_change = on_change
        self._device: evdev.InputDevice | None = None
        self._stop = threading.Event()

    def _find_device(self) -> evdev.InputDevice | None:
        # Prefer 'Intel HID events' over 'Video Bus': both carry brightness keys on
        # Lenovo laptops, but Intel HID is the higher-level source and less likely
        # to conflict with other consumers.
        candidates = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                keys = dev.capabilities().get(ecodes.EV_KEY, [])
                if ecodes.KEY_BRIGHTNESSUP in keys or ecodes.KEY_BRIGHTNESSDOWN in keys:
                    candidates.append(dev)
            except (OSError, PermissionError):
                continue

        if not candidates:
            return None

        for dev in candidates:
            if "hid" in dev.name.lower() or "intel" in dev.name.lower():
                return dev
        return candidates[0]

    def run(self) -> None:
        # Brief delay so input devices are ready when the service starts early in the session.
        import time
        time.sleep(2)
        self._device = self._find_device()
        if not self._device:
            log.info("No brightness-key input device accessible via evdev "
                     "(offset tracking still works via sysfs change detection)")
            return
        log.info("Brightness keys: %s (%s)", self._device.path, self._device.name)
        try:
            for event in self._device.read_loop():
                if self._stop.is_set():
                    break
                if event.type == ecodes.EV_KEY and event.value == 1:  # key-down only
                    if event.code == ecodes.KEY_BRIGHTNESSUP:
                        self._on_change(+self._step)
                    elif event.code == ecodes.KEY_BRIGHTNESSDOWN:
                        self._on_change(-self._step)
        except OSError:
            log.warning("Brightness-key device disconnected")

    def stop(self) -> None:
        self._stop.set()
        if self._device:
            try:
                self._device.close()
            except OSError:
                pass


# ── Main daemon ───────────────────────────────────────────────────────────────

class Daemon:
    """
    Ties together ALS reading, brightness curve, fade animation, keyboard backlight,
    brightness-key offset, and suspend/resume handling.

    Event loop: GLib.MainLoop (required by dasbus / Gio D-Bus bindings).
    Two GLib timers drive the work:
      - poll timer : read ALS → compute target brightness → update keyboard backlight
      - fade timer : advance current display brightness one step toward target
    """

    def __init__(self) -> None:
        self._cfg = load_config()
        self._loop = GLib.MainLoop()
        self._bus = SystemMessageBus()

        paths = self._cfg["paths"]
        self._hw = BacklightWriter(
            display_path=Path(paths["display_brightness_path"]),
            kbd_path=Path(paths["kbd_brightness_path"]),
            display_max_path=Path(paths["display_brightness_max_path"]),
        )

        als_cfg = self._cfg["als"]
        display_cfg = self._cfg["display"]
        kbd_cfg = self._cfg["keyboard"]

        self._b_min = display_cfg.getint("brightness_min")
        self._b_max = display_cfg.getint("brightness_max")
        self._als_min = als_cfg.getfloat("als_min")
        self._als_max = als_cfg.getfloat("als_max")
        self._exponent = display_cfg.getfloat("curve_exponent")
        self._fade_max_step = display_cfg.getint("fade_max_step")
        self._fade_ms = int(1000 / display_cfg.getint("fade_steps_per_second"))
        self._poll_ms = int(als_cfg.getfloat("poll_interval") * 1000)
        self._smoothing = als_cfg.getint("smoothing_samples")
        self._offset_step = int(display_cfg.getfloat("manual_offset_step") * self._b_max)
        self._kbd_on_thr = kbd_cfg.getfloat("kbd_backlight_on_threshold")
        self._kbd_off_thr = kbd_cfg.getfloat("kbd_backlight_off_threshold")
        self._kbd_max = kbd_cfg.getint("kbd_backlight_max")

        # Runtime state
        self._current = self._hw.read_display()
        self._target = self._current
        self._offset = self._load_offset()
        self._offset_lock = threading.Lock()
        self._kbd_on = self._hw.read_kbd() > 0
        self._suspended = False
        self._als_history: list[float] = []

        self._sensor_proxy = None
        self._key_listener: BrightnessKeyListener | None = None

    # ── ALS smoothing ──────────────────────────────────────────────────────────

    def _smooth(self, value: float) -> float:
        self._als_history.append(value)
        if len(self._als_history) > self._smoothing:
            self._als_history.pop(0)
        return sum(self._als_history) / len(self._als_history)

    # ── Persistent offset state ───────────────────────────────────────────────

    def _load_offset(self) -> int:
        try:
            value = int(OFFSET_FILE.read_text().strip())
            log.info("Restored offset: %+d", value)
            return value
        except (FileNotFoundError, ValueError):
            return 0

    def _save_offset(self, value: int) -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            OFFSET_FILE.write_text(str(value))
        except OSError as e:
            log.warning("Could not save offset: %s", e)

    # ── Manual brightness offset (called from evdev thread or poll timer) ─────

    def _on_offset_change(self, delta: int) -> None:
        with self._offset_lock:
            span = self._b_max - self._b_min
            self._offset = max(-span, min(span, self._offset + delta))
            new_offset = self._offset
        self._save_offset(new_offset)
        log.info("Manual offset: %+d (delta %+d)", new_offset, delta)

    # ── GLib poll timer ───────────────────────────────────────────────────────

    def _on_poll(self) -> bool:
        """Read ALS, compute target brightness, manage keyboard backlight."""
        if self._suspended:
            return GLib.SOURCE_CONTINUE

        # Detect external brightness changes (brightness keys via ACPI, compositor, ...).
        # On most laptops the firmware adjusts the backlight directly via the embedded
        # controller before any input event reaches userspace, so grabbing the evdev
        # device cannot prevent it. Instead we detect the change here and adopt it as
        # a manual offset rather than fighting the kernel by resetting the value.
        actual = self._hw.read_display()
        if actual != self._current:
            delta = actual - self._current
            self._current = actual
            self._on_offset_change(delta)
            log.info("External brightness change detected")

        try:
            als_raw = float(self._sensor_proxy.LightLevel)
        except Exception as e:
            log.warning("ALS read error: %s", e)
            return GLib.SOURCE_CONTINUE

        als = self._smooth(als_raw)
        log.debug("ALS raw=%.1f smooth=%.1f", als_raw, als)

        with self._offset_lock:
            offset = self._offset

        raw_target = als_to_brightness(
            als, self._als_min, self._als_max,
            self._b_min, self._b_max, self._exponent,
        )
        self._target = max(self._b_min, min(self._b_max, raw_target + offset))

        # Keyboard backlight hysteresis
        if self._kbd_on and als > self._kbd_off_thr:
            self._hw.write_kbd(0)
            self._kbd_on = False
            log.info("Keyboard backlight OFF (ALS=%.1f)", als)
        elif not self._kbd_on and als < self._kbd_on_thr:
            self._hw.write_kbd(self._kbd_max)
            self._kbd_on = True
            log.info("Keyboard backlight ON (ALS=%.1f)", als)

        return GLib.SOURCE_CONTINUE

    # ── GLib fade timer ───────────────────────────────────────────────────────

    def _on_fade(self) -> bool:
        """Advance display brightness one step toward target."""
        if self._suspended or self._current == self._target:
            return GLib.SOURCE_CONTINUE
        next_val = fade_step(self._current, self._target, self._fade_max_step)
        self._hw.write_display(next_val)
        self._current = next_val
        return GLib.SOURCE_CONTINUE

    # ── Suspend / resume ──────────────────────────────────────────────────────

    def _on_prepare_for_sleep(
        self, connection, sender, path, iface, signal_name, params, user_data
    ) -> None:
        """
        Called by systemd-logind via D-Bus before suspend and after resume.
        params is a GLib.Variant of type (b,): True = about to suspend, False = resumed.

        We use Gio.DBusConnection.signal_subscribe directly (rather than dasbus proxy)
        because logind's PrepareForSleep requires no prior ClaimXxx handshake and its
        D-Bus interface XML is not always available for dasbus to introspect at runtime.
        """
        before = params.get_child_value(0).get_boolean()
        if before:
            log.info("Suspending — keyboard backlight off")
            self._suspended = True
            self._hw.write_kbd(0)
            self._kbd_on = False
        else:
            log.info("Resumed — clearing ALS history, forcing re-read")
            self._suspended = False
            self._als_history.clear()

    # ── POSIX signal handling ─────────────────────────────────────────────────

    def _on_unix_signal(self) -> bool:
        log.info("Shutdown signal received")
        self._loop.quit()
        return GLib.SOURCE_REMOVE

    # ── Startup and teardown ──────────────────────────────────────────────────

    def run(self) -> None:
        # Connect to iio-sensor-proxy and claim the light sensor
        try:
            self._sensor_proxy = self._bus.get_proxy(
                "net.hadess.SensorProxy",
                "/net/hadess/SensorProxy",
            )
            self._sensor_proxy.ClaimLight()
        except Exception as e:
            log.error("Cannot connect to iio-sensor-proxy: %s", e)
            log.error("Is iio-sensor-proxy installed and running?  "
                      "Check: systemctl status iio-sensor-proxy")
            sys.exit(1)

        if not self._sensor_proxy.HasAmbientLight:
            log.error("iio-sensor-proxy: no ambient light sensor available on this system")
            sys.exit(1)

        log.info("ALS unit=%s  current=%.1f",
                 self._sensor_proxy.LightLevelUnit,
                 self._sensor_proxy.LightLevel)

        # Subscribe to logind PrepareForSleep via raw Gio D-Bus connection.
        # This reuses the GLib main loop that GIO and dasbus share internally.
        gio_conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        gio_conn.signal_subscribe(
            sender="org.freedesktop.login1",
            interface_name="org.freedesktop.login1.Manager",
            member="PrepareForSleep",
            object_path="/org/freedesktop/login1",
            arg0=None,
            flags=Gio.DBusSignalFlags.NONE,
            callback=self._on_prepare_for_sleep,
            user_data=None,
        )

        # evdev brightness-key thread
        self._key_listener = BrightnessKeyListener(self._offset_step, self._on_offset_change)
        self._key_listener.start()

        # GLib timers
        GLib.timeout_add(self._poll_ms, self._on_poll)
        GLib.timeout_add(self._fade_ms, self._on_fade)

        # POSIX signals — use GLib's unix_signal_add so they fire inside the GLib loop.
        # Plain signal.signal() handlers are only invoked between C instructions and
        # can be missed while the GLib event loop is blocking in C code.
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._on_unix_signal)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self._on_unix_signal)

        log.info("Started  poll=%dms  fade_interval=%dms  offset_step=%d",
                 self._poll_ms, self._fade_ms, self._offset_step)

        try:
            self._loop.run()
        finally:
            self._sensor_proxy.ReleaseLight()
            if self._key_listener:
                self._key_listener.stop()
            log.info("Daemon stopped")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    Daemon().run()


if __name__ == "__main__":
    main()
