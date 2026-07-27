"""Tests for P6 declaration audit and callback controls."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from live_draft_solo_p6_declaration_audit import (
    build_b2_reference_declaration_snapshot,
    build_production_declaration_snapshot,
    resolve_p6_callback_control,
    store_declaration_diff,
    wrap_p6_sentinel_deliver,
)


class P6DeclarationAuditTests(unittest.TestCase):
    def test_resolve_control_defaults_r0(self) -> None:
        st = MagicMock()
        st.query_params = {}
        session: dict = {}
        self.assertEqual(resolve_p6_callback_control(st, session), "R0")

    def test_declaration_diff_finds_session_prefix(self) -> None:
        prod = build_production_declaration_snapshot(
            widget_key="k1",
            expire_token="PARITY_abcd|0|100.0",
            chain_persist_key="ls",
            deliver_callback=lambda *a, **k: None,
            suppress_immediate_session_on_change=True,
            location="ldr_page_entry_early_persistent",
            production_delivery_only=False,
            isolated_mode="",
        )
        b2 = build_b2_reference_declaration_snapshot(
            widget_key="k1",
            expire_token="PARITY_abcd|0|100.0",
            chain_persist_key="ls",
            deliver_callback=lambda *a, **k: None,
        )
        session: dict = {}
        store_declaration_diff(session, production=prod, b2_reference=b2)
        diff = session.get("_solo_p6_declaration_diff") or {}
        fields = {d["field"] for d in diff.get("differences") or []}
        self.assertIn("render_micro_isolation_once_kwargs", fields)

    def test_sentinel_wrapper_calls_inner(self) -> None:
        calls: list[str] = []

        def inner(_st, _sess, _raw, _key) -> None:
            calls.append("inner")

        wrapped = wrap_p6_sentinel_deliver(inner)
        session: dict = {}
        wrapped(MagicMock(), session, "tok", "k")
        self.assertEqual(calls, ["inner"])


if __name__ == "__main__":
    unittest.main()
