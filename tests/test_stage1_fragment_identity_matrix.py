"""Stage1 fragment identity matrix — unit + AppTest coverage."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from live_draft_rec_fragment_exec_diag import FRAGMENT_CALLBACK_LEDGER_KEY
from live_draft_stage1_fragment_identity_matrix import (
    CONTROL_S0,
    on_fragment_matrix_probe_click,
    matrix_widget_key,
    _mount_dynamic_fragment,
)


class FragmentMatrixCallbackTests(unittest.TestCase):
    def test_matrix_callback_appends_ledger_with_control_source(self) -> None:
        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 3}
        wk = matrix_widget_key(CONTROL_S0, "ROOM1")
        with patch(
            "live_draft_stage1_fragment_identity_runtime.snapshot_fragment_identity",
            return_value={"phase": "callback", "thread_state_fragment_id": "fid1"},
        ):
            on_fragment_matrix_probe_click(
                session,
                control=CONTROL_S0,
                room_id="ROOM1",
                widget_key=wk,
            )
        book = session.get(FRAGMENT_CALLBACK_LEDGER_KEY) or []
        self.assertEqual(len(book), 1)
        self.assertEqual(book[0]["source"], "fragment_matrix_s0")
        self.assertTrue(book[0]["callback_entered"])
        self.assertEqual(book[0]["widget_key"], wk)

    def test_dynamic_mount_invokes_fragment_decorator_pattern(self) -> None:
        st = MagicMock()
        calls: list[str] = []

        def _fragment_decorator(**kwargs):
            run_every = kwargs.get("run_every")

            def _wrap(fn):
                def _run():
                    calls.append(f"run_every={run_every}")
                    fn()

                return _run

            return _wrap

        st.fragment = _fragment_decorator
        body = MagicMock()
        _mount_dynamic_fragment(st, body, run_every=1)
        self.assertEqual(calls, ["run_every=1"])
        body.assert_called_once()


class FragmentMatrixAppTest(unittest.TestCase):
    def test_s0_button_click_appends_matrix_ledger(self) -> None:
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        fixture = Path(__file__).resolve().parent / "fixtures" / "stage1_fragment_matrix_apptest.py"
        at = AppTest.from_file(str(fixture), default_timeout=120)
        at.run()
        wk = matrix_widget_key(CONTROL_S0, "APPTEST1")
        buttons = [b for b in at.button if b.key == wk]
        self.assertTrue(buttons, f"missing button key {wk}")
        buttons[0].click().run()
        ledger = (
            at.session_state[FRAGMENT_CALLBACK_LEDGER_KEY]
            if FRAGMENT_CALLBACK_LEDGER_KEY in at.session_state
            else []
        )
        self.assertGreaterEqual(len(ledger), 1)
        self.assertEqual(ledger[-1].get("source"), "fragment_matrix_s0")


if __name__ == "__main__":
    unittest.main()
