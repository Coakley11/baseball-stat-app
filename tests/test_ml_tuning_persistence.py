"""ML tuning persistence (maintenance, 2026-11-23): tuning sliders snapped back to an older value after
leaving the ML Predictions page and returning (browser, signed in). Streamlit drops widget keys while
another page is open and a generic session refill put back an older copy; the ML page then took that
copy as a fresh edit ("widget_drift") and overwrote its own canonical state.

Fix: when the ML page is entered again, its canonical state wins for the ML-only tuning keys, unless
an edit is pending. Shared settings (lookback, minimums, projection style, research position filter)
keep their existing sync rules with the draft and research pages.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import projections_state as ps

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def _session_after_edit():
    """An ML session whose canonical state holds the user's edit (0.30, auto-apply off)."""
    s = {
        "ml_regression_strength": 0.30, "ml_age_strength": 0.55, "ml_comp_weight": 0.15, "ml_k_neighbors": 15,
        "ml_auto_apply_tuning": False, "ml_lookback": 3, "ml_projection_style": "Balanced", "ml_sort_by": "Predicted OPS",
        "ml_predictions_have_run": True,
    }
    ps.write_canonical_projections_state(s, reason="projections_page_save", local_edit=True, sync_widget_keys=False)
    return s


def _leave_and_refill(s, **stale):
    """Another page ran: Streamlit dropped the widget keys; a refill put back older values."""
    for k in ("ml_regression_strength", "ml_age_strength", "ml_comp_weight", "ml_k_neighbors", "ml_auto_apply_tuning",
              "ml_lookback", "ml_projection_style", "ml_sort_by"):
        s.pop(k, None)
    s.update(stale)


class EntryTests(unittest.TestCase):
    def test_stale_refill_loses_to_the_pages_own_state(self):
        s = _session_after_edit()
        _leave_and_refill(s, ml_regression_strength=0.25, ml_auto_apply_tuning=True, ml_k_neighbors=10)
        ps.prepare_projections_page(s, entering=True)
        ps.prepare_projections_filters(s)
        self.assertEqual(s["ml_regression_strength"], 0.30)
        self.assertIs(s["ml_auto_apply_tuning"], False)
        self.assertEqual(s["ml_k_neighbors"], 15)
        self.assertEqual(ps.canonical_projections_state(s)["ml_regression_strength"], 0.30, "canonical not overwritten")

    def test_missing_keys_are_filled_from_the_pages_own_state(self):
        s = _session_after_edit()
        _leave_and_refill(s)
        ps.prepare_projections_page(s, entering=True)
        self.assertEqual((s["ml_regression_strength"], s["ml_age_strength"], s["ml_comp_weight"]), (0.30, 0.55, 0.15))

    def test_shared_settings_keep_their_own_sync(self):
        s = _session_after_edit()
        # The draft pages changed the shared lookback / projection style while ML was closed.
        _leave_and_refill(s, ml_lookback=5, ml_projection_style="Aggressive")
        ps.prepare_projections_page(s, entering=True)
        self.assertEqual(s["ml_lookback"], 5, "shared with the draft pages: never overwritten by ML's copy")
        self.assertEqual(s["ml_projection_style"], "Aggressive")
        self.assertNotIn("ml_lookback", ps.PROJECTIONS_ENTRY_OWNED_KEYS)
        self.assertNotIn("ml_projection_style", ps.PROJECTIONS_ENTRY_OWNED_KEYS)
        self.assertNotIn("ml_position_filter", ps.PROJECTIONS_ENTRY_OWNED_KEYS)

    def test_edits_on_the_page_still_win(self):
        s = _session_after_edit()
        s["ml_regression_strength"] = 0.45  # user moved the slider on this (non-entry) run
        ps.prepare_projections_page(s, entering=False)
        self.assertEqual(s["ml_regression_strength"], 0.45)
        self.assertEqual(ps.canonical_projections_state(s)["ml_regression_strength"], 0.45)

    def test_a_pending_edit_wins_even_on_entry(self):
        s = _session_after_edit()
        s["ml_regression_strength"] = 0.50
        ps.mark_projections_filter_pending_sync(s)
        ps.prepare_projections_page(s, entering=True)
        self.assertEqual(s["ml_regression_strength"], 0.50)

    def test_ami_return_and_cloud_restore_still_apply(self):
        s = _session_after_edit()
        ps.apply_projections_source_state_from_ami(s, {"widget_params": {"ml_regression_strength": 0.10}})
        _leave_and_refill(s, ml_regression_strength=0.25)
        ps.prepare_projections_page(s, entering=True)
        self.assertEqual(s["ml_regression_strength"], 0.10, "the AMI return wrote the canonical state")

    def test_first_visit_without_state_is_unchanged(self):
        s = {"ml_regression_strength": 0.20}
        ps.prepare_projections_page(s, entering=True)
        self.assertEqual(s["ml_regression_strength"], 0.20)

    def test_the_marker_is_never_persisted_or_snapshotted(self):
        self.assertFalse(ps.is_projections_state_key(ps.PROJECTIONS_RENDERED_KEY))
        import page_state

        self.assertNotIn(ps.PROJECTIONS_RENDERED_KEY, page_state.PAGE_STATE_REGISTRY["ML Predictions"]["exact"])


class WiringTests(unittest.TestCase):
    def test_entry_is_detected_from_the_previous_run(self):
        self.assertIn("prepare_projections_page(st.session_state, entering=not st.session_state.get(PROJECTIONS_RENDERED_KEY))", APP)
        self.assertIn('if active_page != "ML Predictions":\n    st.session_state.pop("_projections_page_rendered", None)', APP)
        i = APP.index('flush_projections_filter_edits(st.session_state, st, reason="projections_page_save")')
        self.assertIn("st.session_state[PROJECTIONS_RENDERED_KEY] = True", APP[i:i + 200])
        self.assertLess(APP.index('st.session_state.pop("_projections_page_rendered", None)'),
                        APP.index('elif active_page == "ML Predictions":'))


if __name__ == "__main__":
    unittest.main()
