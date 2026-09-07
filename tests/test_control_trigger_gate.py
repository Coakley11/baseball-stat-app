"""Pause/Resume pending gate must preempt expire on the same ScriptRun."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from live_draft_control_trigger_gate import (
    control_center_pause_resume_pending,
    _widget_id_matches_control_key,
)


class _FakeNewWidgetState:
    def __init__(self, states: dict):
        self.states = states

    def get(self, wid: str):
        return self.states.get(wid)


class ControlTriggerGateTests(unittest.TestCase):
    def test_widget_id_suffix_match(self) -> None:
        self.assertTrue(
            _widget_id_matches_control_key("$$ID-abc-live_draft_pause", "live_draft_pause")
        )
        self.assertFalse(
            _widget_id_matches_control_key("$$ID-abc-live_draft_resume", "live_draft_pause")
        )

    def test_pending_when_pause_trigger_true(self) -> None:
        ss = SimpleNamespace(
            _new_widget_state=_FakeNewWidgetState(
                {"$$ID-x-live_draft_pause": True}
            )
        )
        with patch(
            "live_draft_streamlit_widget_metadata_diag.get_streamlit_session_state",
            return_value=ss,
        ):
            self.assertTrue(control_center_pause_resume_pending(None))

    def test_not_pending_when_only_unrelated_trigger(self) -> None:
        ss = SimpleNamespace(
            _new_widget_state=_FakeNewWidgetState(
                {"$$ID-x-some_other_button": True}
            )
        )
        with patch(
            "live_draft_streamlit_widget_metadata_diag.get_streamlit_session_state",
            return_value=ss,
        ):
            self.assertFalse(control_center_pause_resume_pending(None))

    def test_resume_trigger_also_pending(self) -> None:
        ss = SimpleNamespace(
            _new_widget_state=_FakeNewWidgetState(
                {"$$ID-y-live_draft_resume": True}
            )
        )
        with patch(
            "live_draft_streamlit_widget_metadata_diag.get_streamlit_session_state",
            return_value=ss,
        ):
            self.assertTrue(control_center_pause_resume_pending(None))


if __name__ == "__main__":
    unittest.main()
