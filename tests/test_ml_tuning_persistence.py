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

    def test_ml_only_display_choices_are_kept_too(self):
        s = _session_after_edit()
        s["ml_sort_by"] = "Predicted SB"
        ps.write_canonical_projections_state(s, reason="projections_page_save", local_edit=True, sync_widget_keys=False)
        _leave_and_refill(s, ml_sort_by="Predicted HR")
        ps.prepare_projections_page(s, entering=True)
        self.assertEqual(s["ml_sort_by"], "Predicted SB")
        import page_state

        shared = {k for k in page_state._global_snapshot_excluded_keys({}) if k.startswith("ml_")}
        self.assertFalse(shared & set(ps.PROJECTIONS_ENTRY_OWNED_KEYS), "never a shared draft/research key")

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


class OwnershipTests(unittest.TestCase):
    """Browser QA (2026-11-23, pre-existing on Dev): user A tuned ML, the page reloaded while A was signed
    in, and the new session restored a device-level copy of A's settings — a signed-out visitor and then
    user B on the same browser saw A's value. The ML state now records its owner and is never shown to
    another identity."""

    def _a_session(self):
        s = {"_suite_auth_user_id": "user-a", "ml_regression_strength": 0.35, "ml_auto_apply_tuning": False,
             "ml_lookback": 3}
        ps.write_canonical_projections_state(s, reason="projections_page_save", local_edit=False)
        return s

    def test_the_state_records_its_owner(self):
        self.assertEqual(self._a_session()["projections_state"]["owner"], "user-a")
        self.assertEqual(ps.write_canonical_projections_state({}, reason="x")["owner"], "", "signed out")

    def test_another_signed_in_user_never_sees_it(self):
        s = self._a_session()
        s["_suite_auth_user_id"] = "user-b"
        ps.prepare_projections_page(s, entering=True)
        ps.prepare_projections_filters(s)
        self.assertNotIn("ml_regression_strength", s, "A's value is dropped; the page default applies")
        self.assertNotIn("ml_auto_apply_tuning", s)
        self.assertEqual(s["projections_state"]["owner"], "user-b")
        self.assertEqual(s["ml_lookback"], 3, "shared draft settings are not ML-owned and are untouched")

    def test_a_signed_out_visitor_never_sees_it(self):
        s = self._a_session()
        s.pop("_suite_auth_user_id")
        ps.prepare_projections_page(s, entering=True)
        self.assertNotIn("ml_regression_strength", s)

    def test_the_owner_keeps_their_settings(self):
        s = self._a_session()
        s.pop("ml_regression_strength")
        ps.prepare_projections_page(s, entering=True)
        self.assertEqual(s["ml_regression_strength"], 0.35)

    def test_a_foreign_restore_is_not_applied(self):
        a = self._a_session()
        blob = {"projections_state": dict(a["projections_state"])}
        b = {"_suite_auth_user_id": "user-b", "ml_regression_strength": 0.20}
        self.assertFalse(ps.apply_cloud_projections_state_if_allowed(b, blob))
        self.assertNotIn("ml_regression_strength", b)
        store = {ps.PROJECTIONS_PAGE: {"projections_state": dict(a["projections_state"]), "ml_regression_strength": 0.35}}
        b2 = {"_suite_auth_user_id": "user-b", "page_filter_state": store}
        self.assertFalse(ps.restore_projections_page_filters(b2, store))
        self.assertNotIn("ml_regression_strength", b2)
        self.assertNotIn("ml_regression_strength", store[ps.PROJECTIONS_PAGE], "the foreign block copy is cleared too")

    def test_own_restore_and_legacy_copies_still_apply(self):
        a = self._a_session()
        own = {"_suite_auth_user_id": "user-a"}
        self.assertTrue(ps.apply_cloud_projections_state_if_allowed(own, {"projections_state": dict(a["projections_state"])}))
        self.assertEqual(own["ml_regression_strength"], 0.35)
        legacy_meta = {k: v for k, v in a["projections_state"].items() if k != "owner"}
        other = {"_suite_auth_user_id": "user-b"}
        self.assertTrue(ps.apply_cloud_projections_state_if_allowed(other, {"projections_state": legacy_meta}),
                        "copies saved before the owner field behave as before")


class WiringTests(unittest.TestCase):
    def test_callbacks_on_the_run_that_leaves_the_page_are_not_edits(self):
        i = APP.index("def projections_filter_changed():")
        body = APP[i:APP.index("\n\n\n", i)]
        self.assertIn('if str(st.session_state.get("active_page") or "ML Predictions") == "ML Predictions":\n'
                      '            mark_projections_filter_pending_sync(st.session_state)', body)
        self.assertIn("on_draft_settings_changed(", body, "shared draft settings still sync")

    def test_entry_is_detected_from_the_previous_run(self):
        self.assertIn("prepare_projections_page(st.session_state, entering=not st.session_state.get(PROJECTIONS_RENDERED_KEY))", APP)
        self.assertIn('if active_page != "ML Predictions":\n    st.session_state.pop("_projections_page_rendered", None)', APP)
        i = APP.index('flush_projections_filter_edits(st.session_state, st, reason="projections_page_save")')
        self.assertIn("st.session_state[PROJECTIONS_RENDERED_KEY] = True", APP[i:i + 200])
        self.assertLess(APP.index('st.session_state.pop("_projections_page_rendered", None)'),
                        APP.index('elif active_page == "ML Predictions":'))


if __name__ == "__main__":
    unittest.main()
