"""The Account & Workspace control recovers from a stray value on one of its button keys
(D4J phone: "Account control failed ... (StreamlitValueAssignmentNotAllowedError)")."""

from __future__ import annotations

import unittest

from streamlit.errors import StreamlitValueAssignmentNotAllowedError
from streamlit.testing.v1 import AppTest

from account_control_recovery import RECOVERED_KEYS, offending_key, recover_from_value_assignment


def _script() -> None:
    import streamlit as st

    from account_control_recovery import recover_from_value_assignment

    if not st.session_state.get("_seeded"):
        st.session_state["_seeded"] = True
        st.session_state["suite_nav_home_btn"] = True  # a stray value on a button key
    try:
        st.button("Home", key="suite_nav_home_btn")
        st.markdown("control rendered")
    except Exception as exc:  # noqa: BLE001
        if recover_from_value_assignment(st.session_state, exc):
            st.rerun()
        st.error("control failed")


class RecoveryTests(unittest.TestCase):
    def test_the_key_is_read_from_streamlits_error(self) -> None:
        exc = StreamlitValueAssignmentNotAllowedError(key="suite_nav_home_btn")
        self.assertEqual(offending_key(exc), "suite_nav_home_btn")
        self.assertEqual(offending_key(ValueError("key 'x'")), "")

    def test_a_stray_button_value_recovers_in_one_rerun(self) -> None:
        at = AppTest.from_function(_script, default_timeout=30)
        at.run()
        self.assertFalse(at.exception)
        self.assertTrue(any("control rendered" in str(m.value) for m in at.markdown))
        self.assertFalse(at.error)
        self.assertEqual(at.session_state[RECOVERED_KEYS], ["suite_nav_home_btn"])

    def test_only_once_per_key_so_it_never_loops(self) -> None:
        s = {"k": True}
        exc = StreamlitValueAssignmentNotAllowedError(key="k")
        self.assertTrue(recover_from_value_assignment(s, exc))
        self.assertNotIn("k", s)
        s["k"] = True
        self.assertFalse(recover_from_value_assignment(s, exc))

    def test_other_errors_are_not_touched(self) -> None:
        s = {"k": True}
        self.assertFalse(recover_from_value_assignment(s, RuntimeError("boom")))
        self.assertIn("k", s)

    def test_the_app_wires_the_recovery_into_the_account_control(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath("streamlit_app.py").read_text(encoding="utf-8")
        k = src.index("render_baseball_account_workspace_control(")
        self.assertIn("recover_from_value_assignment", src[k:k + 1600])


if __name__ == "__main__":
    unittest.main()
