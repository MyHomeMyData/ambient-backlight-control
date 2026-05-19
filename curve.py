"""
Brightness curve: maps ALS raw sensor values to display brightness values.

All logic here is pure (no hardware access) so it can be unit-tested without hardware.
"""


def als_to_brightness(
    als_raw: float,
    als_min: float,
    als_max: float,
    brightness_min: int,
    brightness_max: int,
    exponent: float,
) -> int:
    """Map an ALS raw value to a display brightness value.

    Uses a power curve (gamma) so the result feels perceptually linear to the human eye.
    Input is clamped to [als_min, als_max]; output is clamped to [brightness_min, brightness_max].

    Args:
        als_raw: Current ALS sensor reading (raw ADC value).
        als_min: ALS value that maps to brightness_min.
        als_max: ALS value that maps to brightness_max.
        brightness_min: Minimum display brightness (never go below this).
        brightness_max: Maximum display brightness.
        exponent: Curve exponent (gamma). 0.5 gives a square-root curve.

    Returns:
        Target display brightness as an integer.
    """
    if als_max <= als_min:
        raise ValueError("als_max must be greater than als_min")
    if brightness_max <= brightness_min:
        raise ValueError("brightness_max must be greater than brightness_min")
    if exponent <= 0:
        raise ValueError("exponent must be positive")

    normalized = (als_raw - als_min) / (als_max - als_min)
    normalized = max(0.0, min(1.0, normalized))

    curved = normalized ** exponent

    brightness = brightness_min + curved * (brightness_max - brightness_min)
    return int(round(max(brightness_min, min(brightness_max, brightness))))


def fade_step(current: int, target: int, max_step: int) -> int:
    """Return the next brightness value when fading from current toward target.

    Moves at most max_step per call, so the caller drives the animation loop.

    Args:
        current: Current brightness.
        target: Desired brightness.
        max_step: Maximum change per step.

    Returns:
        Next brightness value (may equal target if already close enough).
    """
    if max_step <= 0:
        raise ValueError("max_step must be positive")
    delta = target - current
    if abs(delta) <= max_step:
        return target
    return current + max_step if delta > 0 else current - max_step
