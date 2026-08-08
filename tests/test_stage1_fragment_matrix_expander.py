"""Unit tests for matrix expander label constants (harness contract)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_fragment_matrix_expander import (  # noqa: E402
    MATRIX_EXPANDER_LABEL,
    S0_BUTTON_LABEL,
)


class FragmentMatrixExpanderContractTests(unittest.TestCase):
    def test_exact_expander_label_matches_app(self) -> None:
        self.assertEqual(MATRIX_EXPANDER_LABEL, "Stage1 fragment identity matrix (diag)")

    def test_s0_label_exact(self) -> None:
        self.assertEqual(S0_BUTTON_LABEL, "Stage1 Static Fragment Probe")


if __name__ == "__main__":
    unittest.main()
