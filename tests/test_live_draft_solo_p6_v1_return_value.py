"""Tests for P6 V1 return-value control helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from live_draft_solo_p6_declaration_audit import resolve_p6_callback_control
from live_draft_solo_p6_v1_return_value import _coerce_return_token


class P6V1ReturnValueTests(unittest.TestCase):
    def test_resolve_r4_control(self) -> None:
        st = MagicMock()
        st.query_params = {"solo_p6_callback_control": "R4"}
        session: dict = {}
        self.assertEqual(resolve_p6_callback_control(st, session), "R4")

    def test_coerce_return_token(self) -> None:
        self.assertEqual(_coerce_return_token("PARITY_x|0|1.0"), "PARITY_x|0|1.0")
        self.assertEqual(_coerce_return_token(None), "")


if __name__ == "__main__":
    unittest.main()
