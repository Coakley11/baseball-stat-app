"""Case A app-shell uses shared minimal repro core."""

from __future__ import annotations

import unittest

from minimal_component_wake_repro_core import (
    REQUIRED_CYCLES,
    build_token,
    coerce_token,
    init_minimal_wake_session,
    record_delivery,
    widget_key,
)


class CaseAAppShellCoreTests(unittest.TestCase):
    def test_token_and_key_per_cycle(self) -> None:
        self.assertEqual(widget_key(0), "minimal_wake_repro_0")
        tok = build_token(0, countdown_seconds=5)
        self.assertTrue(tok.startswith("repro|0|"))

    def test_record_delivery_dedupes(self) -> None:
        session: dict = {}
        init_minimal_wake_session(session)
        tok = build_token(0)
        self.assertTrue(record_delivery(session, source="on_change", token=tok, raw=tok))
        self.assertFalse(record_delivery(session, source="on_change", token=tok, raw=tok))
        self.assertEqual(int(session["_minimal_wake_repro_cycles_done"]), 1)

    def test_coerce_token(self) -> None:
        self.assertEqual(coerce_token({"token": "x"}, "fb"), "x")
        self.assertEqual(coerce_token(None, "fb"), "fb")

    def test_required_cycles_constant(self) -> None:
        self.assertEqual(REQUIRED_CYCLES, 4)


if __name__ == "__main__":
    unittest.main()
