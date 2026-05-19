"""Unit tests for curve.py — no hardware required."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from curve import als_to_brightness, fade_step

ALS_MIN = 0
ALS_MAX = 1_000_000
B_MIN = 14400
B_MAX = 96000
EXP = 0.5


class TestAlsToBrightness:
    def test_at_als_min_returns_brightness_min(self):
        result = als_to_brightness(ALS_MIN, ALS_MIN, ALS_MAX, B_MIN, B_MAX, EXP)
        assert result == B_MIN

    def test_at_als_max_returns_brightness_max(self):
        result = als_to_brightness(ALS_MAX, ALS_MIN, ALS_MAX, B_MIN, B_MAX, EXP)
        assert result == B_MAX

    def test_below_als_min_clamps_to_brightness_min(self):
        result = als_to_brightness(-1000, ALS_MIN, ALS_MAX, B_MIN, B_MAX, EXP)
        assert result == B_MIN

    def test_above_als_max_clamps_to_brightness_max(self):
        result = als_to_brightness(ALS_MAX + 1000, ALS_MIN, ALS_MAX, B_MIN, B_MAX, EXP)
        assert result == B_MAX

    def test_midpoint_with_exponent_half(self):
        # normalized=0.5, curved=0.5**0.5≈0.707
        result = als_to_brightness(500_000, ALS_MIN, ALS_MAX, B_MIN, B_MAX, EXP)
        expected = int(round(B_MIN + (0.5 ** 0.5) * (B_MAX - B_MIN)))
        assert result == expected

    def test_curve_is_monotonically_increasing(self):
        values = [als_to_brightness(v, ALS_MIN, ALS_MAX, B_MIN, B_MAX, EXP)
                  for v in range(0, ALS_MAX + 1, 10_000)]
        assert values == sorted(values)

    def test_invalid_als_range_raises(self):
        with pytest.raises(ValueError):
            als_to_brightness(0, 1000, 1000, B_MIN, B_MAX, EXP)

    def test_invalid_brightness_range_raises(self):
        with pytest.raises(ValueError):
            als_to_brightness(0, ALS_MIN, ALS_MAX, B_MAX, B_MIN, EXP)

    def test_invalid_exponent_raises(self):
        with pytest.raises(ValueError):
            als_to_brightness(0, ALS_MIN, ALS_MAX, B_MIN, B_MAX, 0)


class TestFadeStep:
    def test_moves_up_by_max_step(self):
        assert fade_step(10000, 50000, 2000) == 12000

    def test_moves_down_by_max_step(self):
        assert fade_step(50000, 10000, 2000) == 48000

    def test_snaps_to_target_when_close(self):
        assert fade_step(10000, 10500, 2000) == 10500

    def test_already_at_target(self):
        assert fade_step(10000, 10000, 2000) == 10000

    def test_invalid_max_step_raises(self):
        with pytest.raises(ValueError):
            fade_step(10000, 50000, 0)
