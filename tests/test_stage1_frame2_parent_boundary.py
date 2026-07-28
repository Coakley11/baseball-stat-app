"""Tests for Stage 1A frame-2 parent boundary P classification."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_frame2_parent_boundary import classify_parent_boundary_p  # noqa: E402


class Frame2ParentBoundaryTests(unittest.TestCase):
    def test_p4_probe_and_scv(self) -> None:
        p = classify_parent_boundary_p(
            frame2_probe_received=True,
            frame2_scv_received=True,
            sender_stale_or_detached=False,
            observer_in_frame2=True,
            frame2_listener_lost=False,
            scv_from_stale_source=False,
            scv_from_current_source=True,
            python_bound=False,
        )
        self.assertEqual(p, "P8")

    def test_p5_probe_only(self) -> None:
        p = classify_parent_boundary_p(
            frame2_probe_received=True,
            frame2_scv_received=False,
            sender_stale_or_detached=False,
            observer_in_frame2=True,
            frame2_listener_lost=False,
            scv_from_stale_source=False,
            scv_from_current_source=False,
            python_bound=False,
        )
        self.assertEqual(p, "P5")

    def test_p6_neither(self) -> None:
        p = classify_parent_boundary_p(
            frame2_probe_received=False,
            frame2_scv_received=False,
            sender_stale_or_detached=False,
            observer_in_frame2=True,
            frame2_listener_lost=False,
            scv_from_stale_source=False,
            scv_from_current_source=False,
            python_bound=False,
        )
        self.assertEqual(p, "P6")


if __name__ == "__main__":
    unittest.main()
