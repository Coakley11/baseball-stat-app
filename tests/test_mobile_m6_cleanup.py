"""Mobile M6 — remaining workflows + density cleanup (presentation only).

Source-regex wiring checks (same style as the M3/M4/M5 wiring tests) plus unit
tests for the two new reusable helpers this slice adds.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import fantasy_waiver_wire_ui as waiver_ui
import mobile_table_layout as T

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
WAIVER_SRC = (ROOT / "fantasy_waiver_wire_ui.py").read_text(encoding="utf-8")
TUTORIAL_SRC = (ROOT / "app_tutorial.py").read_text(encoding="utf-8")
FOUNDATION_SRC = (ROOT / "mobile_foundation.py").read_text(encoding="utf-8")
SCRIPT_SRC = (ROOT / "scripts" / "local_tb_realtime_analytics_accept.py").read_text(encoding="utf-8")


class StrayDiagnosticTextTests(unittest.TestCase):
    def test_live_draft_setup_anchor_caption_removed(self) -> None:
        self.assertNotIn('st.caption("live-draft-setup-anchor")', APP_SRC)

    def test_acceptance_script_still_detects_setup_page_without_the_anchor(self) -> None:
        """The anchor string itself can still appear in the (untouched) acceptance
        script's OR-chain — it just must not be the only way that chain matches;
        "Draft Setup" (the heading right above where the anchor was) is also checked."""
        self.assertIn('"Draft Setup" in body', SCRIPT_SRC)

    def test_mp_identity_diagnostics_gated_not_unconditional(self) -> None:
        start = APP_SRC.index("from suite_identity_guard import build_mp_identity_snapshot")
        block = APP_SRC[start:start + 1600]
        self.assertIn("developer_mode_enabled()", block)
        self.assertIn("_mp_bad", block)
        # Still reachable when something is actually wrong, not fully deleted.
        self.assertIn("render_mp_identity_diagnostics(", block)


class RankingsCompactionTests(unittest.TestCase):
    def test_recommendation_rankings_uses_compact_expander_type(self) -> None:
        idx = APP_SRC.index('st.expander("Recommendation Rankings"')
        line = APP_SRC[idx: idx + 200].split("\n", 1)[0]
        self.assertIn('type="compact"', line)
        # expanded= default must be unchanged (desktop open-by-default preserved).
        self.assertIn("expanded=True", line)


class EmptyIframeGapTests(unittest.TestCase):
    def test_zero_height_iframe_gap_rule_is_phone_scoped(self) -> None:
        self.assertIn('iframe[height="0"]', FOUNDATION_SRC)
        # Must sit inside a media_phone() block, not apply to desktop.
        idx = FOUNDATION_SRC.index('iframe[height="0"]')
        preceding = FOUNDATION_SRC[max(0, idx - 400):idx]
        self.assertIn("media_phone()", preceding)

    def test_rule_only_targets_the_element_container_not_a_bare_iframe(self) -> None:
        idx = FOUNDATION_SRC.index('iframe[height="0"]')
        line = FOUNDATION_SRC[max(0, idx - 120):idx]
        self.assertIn('stElementContainer', line)


class TutorialBarCompactionTests(unittest.TestCase):
    def test_tutorial_header_bar_uses_inline_row(self) -> None:
        self.assertIn('mobile_inline_row(st, "tutorial-header-bar")', TUTORIAL_SRC)

    def test_inline_row_wraps_the_columns_call_not_something_else(self) -> None:
        idx = TUTORIAL_SRC.index('mobile_inline_row(st, "tutorial-header-bar")')
        next_line = TUTORIAL_SRC[idx:].split("\n", 2)[1]
        self.assertIn("st.columns(", next_line)

    def test_tolerant_of_missing_mobile_foundation(self) -> None:
        self.assertIn("except ImportError:", TUTORIAL_SRC[: TUTORIAL_SRC.index('mobile_inline_row(st, "tutorial-header-bar")')][-700:])


class WaiverDuplicateTeamCaptionTests(unittest.TestCase):
    def test_standalone_my_team_caption_removed(self) -> None:
        self.assertNotIn('st.caption(f"My team: **{my_team}**")', WAIVER_SRC)

    def test_my_team_variable_still_resolved_for_roster_lookup(self) -> None:
        """Only the redundant display line is gone — the functional resolution
        used later for roster matching must still be present."""
        self.assertIn("resolve_account_fantasy_team(session, context)", WAIVER_SRC)


class WaiverListLengthUnchangedFromM5Tests(unittest.TestCase):
    """The "show 5 + Show 10 more" progressive disclosure tried in an earlier M6
    pass was reverted: it changed desktop behavior (fewer cards shown by default
    there too), and this app has no viewport signal to make it phone-only without
    either a fragile client-width hack or losing desktop parity. Both are against
    the mobile project's constraints, so the long list is an accepted, documented
    M7+ limitation (see docs/MOBILE_M6_CLEANUP.md) rather than forced. These tests
    pin the M5 behavior so it can't silently regress back without a deliberate
    test update."""

    def test_show_more_helper_does_not_exist(self) -> None:
        self.assertFalse(hasattr(waiver_ui, "_render_card_list_with_show_more"))
        self.assertFalse(hasattr(waiver_ui, "_on_show_more_cards_click"))
        self.assertNotIn("_render_card_list_with_show_more", WAIVER_SRC)
        self.assertNotIn("Show more", WAIVER_SRC)
        self.assertNotIn('"_waiver_adds_shown"', WAIVER_SRC)
        self.assertNotIn('"_waiver_drops_shown"', WAIVER_SRC)

    def test_both_lists_iterate_the_full_head_15_unconditionally(self) -> None:
        self.assertEqual(WAIVER_SRC.count("adds.head(15).iterrows()"), 1)
        self.assertEqual(WAIVER_SRC.count("drops.head(15).iterrows()"), 1)

    def test_waiver_section_matches_the_m5_checkpoint_exactly(self) -> None:
        import subprocess

        diff = subprocess.run(
            ["git", "diff", "17128af", "--", "fantasy_waiver_wire_ui.py"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        if diff.returncode != 0 or diff.stdout is None:
            self.skipTest("git diff against 17128af unavailable in this environment")
        changed = diff.stdout
        # The only sanctioned difference from M5 is the duplicate "My team" caption
        # removal (kept — approved separately); nothing else in this file should differ.
        self.assertIn("My team", changed)
        self.assertNotIn("show_more", changed.lower())
        self.assertNotIn("_waiver_adds_shown", changed)


class MLPredictionsDualWidthTests(unittest.TestCase):
    def test_dual_width_css_present_and_wired(self) -> None:
        self.assertIn("dual_width_table_css", APP_SRC)
        self.assertIn('compact_key="ml-pred-compact"', APP_SRC)
        self.assertIn('full_key="ml-pred-full"', APP_SRC)

    def test_full_table_call_unchanged_from_m5(self) -> None:
        """The desktop/full table call must be byte-identical to the M5 call —
        this slice must not touch values, columns, or pin set on the real table."""
        self.assertIn(
            'render_output_table(ml_display, key="ml_predictions", file_name="ml_predictions.csv", pin_columns=("Player", "Position", "Team"))',
            APP_SRC,
        )

    def test_compact_table_is_a_column_subset_of_the_same_dataframe(self) -> None:
        idx = APP_SRC.index('key="ml-pred-compact"')
        block = APP_SRC[idx: idx + 1300]
        self.assertIn("ml_display[_ml_compact_cols]", block)
        self.assertIn('pin_columns=("Player", "Position")', block)

    def test_dual_width_css_toggles_opposite_containers_per_breakpoint(self) -> None:
        css = T.dual_width_table_css(compact_key="c", full_key="f")
        phone_block = css.split("max-width:", 1)[1].split("@media", 1)[0]
        desktop_block = css.split("min-width:", 1)[1]
        self.assertIn("st-key-f", phone_block)
        self.assertNotIn("st-key-c", phone_block)
        self.assertIn("st-key-c", desktop_block)
        self.assertNotIn("st-key-f", desktop_block)


class RemainingWorkflowFilterRowWrapTests(unittest.TestCase):
    EXPECTED_NEW_KEYS = (
        "draft-assistant-top-filters",
        "draft-room-setup-filters",
        "draft-room-action-buttons",
        "draft-room-board-assign",
        "draft-room-roster-view",
        "draft-lab-top-filters",
    )

    def test_every_new_wrap_key_present_exactly_once(self) -> None:
        for key in self.EXPECTED_NEW_KEYS:
            needle = f'with mobile_wrap_row(st, "{key}"):'
            self.assertEqual(APP_SRC.count(needle), 1, f"expected exactly one wrap for {key!r}")

    def test_wrap_immediately_precedes_its_columns_call(self) -> None:
        for key in self.EXPECTED_NEW_KEYS:
            needle = f'with mobile_wrap_row(st, "{key}"):'
            idx = APP_SRC.index(needle)
            next_line = APP_SRC[idx:].split("\n", 2)[1]
            self.assertIn("st.columns(", next_line, f"{key!r} wrap body is not a columns() call: {next_line!r}")

    def test_total_wrap_row_count_matches_m3_through_m6(self) -> None:
        # 3 (M3/M4 Live Draft setup) + 21 (M5) + 6 (M6) = 30.
        self.assertEqual(APP_SRC.count('with mobile_wrap_row(st, "'), 30)


if __name__ == "__main__":
    unittest.main()
