"""Mobile M5 — matplotlib chart legibility context manager."""

from __future__ import annotations

import unittest

import matplotlib
import matplotlib.pyplot as plt

import mobile_chart_layout as C


class LegibleMatplotlibChartTests(unittest.TestCase):
    def test_bumps_font_sizes_above_matplotlib_defaults(self) -> None:
        defaults = matplotlib.rcParamsDefault
        for rc_key in ("font.size", "axes.titlesize", "axes.labelsize", "xtick.labelsize", "ytick.labelsize", "legend.fontsize"):
            if rc_key not in C.MOBILE_CHART_RC:
                continue
            default_val = defaults.get(rc_key)
            # Default sizes can be strings ("large", "medium"); only compare when both are numeric.
            if isinstance(default_val, (int, float)):
                self.assertGreaterEqual(C.MOBILE_CHART_RC[rc_key], default_val)

    def test_enables_autolayout_so_bigger_titles_dont_clip(self) -> None:
        self.assertTrue(C.MOBILE_CHART_RC.get("figure.autolayout"))

    def test_rc_params_apply_only_inside_the_context(self) -> None:
        before = plt.rcParams["font.size"]
        with C.legible_matplotlib_chart():
            self.assertEqual(plt.rcParams["font.size"], C.MOBILE_CHART_RC["font.size"])
        self.assertEqual(plt.rcParams["font.size"], before)

    def test_context_manager_is_reentrant_safe_for_repeated_charts(self) -> None:
        """Multiple chart functions on the same page each open/close their own
        context — must not leak state between them."""
        with C.legible_matplotlib_chart():
            fig1, ax1 = plt.subplots(figsize=(2, 2))
            plt.close(fig1)
        with C.legible_matplotlib_chart():
            self.assertEqual(plt.rcParams["axes.titlesize"], C.MOBILE_CHART_RC["axes.titlesize"])
            fig2, ax2 = plt.subplots(figsize=(2, 2))
            plt.close(fig2)


if __name__ == "__main__":
    unittest.main()
