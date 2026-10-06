"""Shared-draft countdowns stay honest after the deadline passes.

Both countdowns a shared draft shows -- the On-the-Clock banner and the
"Time on clock" timer bar -- are one-way ``components.html`` srcdoc iframes.
Their tick loops used to ``return`` at zero, so the surface sat on a bare "0"
under a "Time remaining" label until the next canonical repaint, which on the
shared path can take tens of seconds and reads as a broken clock.

These tests pin the two properties that matter: the expired state is labelled
and visibly alive, and the iframe is still display-only -- it cannot report,
persist or decide anything, so the canonical room deadline remains the single
timer authority.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from live_draft_on_clock_ui import _render_on_clock_banner_html
from live_draft_timer_ui import EXPIRED_HINT_AFTER_SEC, _mount_js_countdown

# Anything in this list would turn a display-only iframe into a second timer
# authority or a state mutator.
OUTBOUND_TOKENS = (
    "setComponentValue",
    "postMessage",
    "fetch(",
    "XMLHttpRequest",
    "localStorage",
    "sessionStorage",
    "navigator.sendBeacon",
)


def _banner_markup(pick_index: int = 0, seconds: int = 40) -> str:
    with mock.patch("streamlit.components.v1.html") as html_mock:
        _render_on_clock_banner_html(
            mock.MagicMock(),
            {"Team": "Team 1", "Round": 1, "Pick": 1},
            seconds,
            pick_index=pick_index,
            deadline=time.time() + seconds,
        )
    html_mock.assert_called()
    return str(html_mock.call_args[0][0])


def _timer_bar_markup(element_id: str | None = None, pick_index: int = 3) -> str:
    with mock.patch("streamlit.components.v1.html") as html_mock:
        _mount_js_countdown(
            mock.MagicMock(),
            time.time() + 30,
            pick_index=pick_index,
            element_id=element_id,
        )
    html_mock.assert_called()
    return str(html_mock.call_args[0][0])


class ExpiredHintThresholdTests(unittest.TestCase):
    def test_threshold_is_a_positive_number_of_seconds(self) -> None:
        self.assertIsInstance(EXPIRED_HINT_AFTER_SEC, int)
        self.assertGreater(EXPIRED_HINT_AFTER_SEC, 0)


class OnClockBannerExpiryDisplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markup = _banner_markup()

    def test_steady_state_label_is_unchanged(self) -> None:
        """Nothing about the running clock changes -- only the expired state."""
        self.assertIn("Time remaining", self.markup)
        self.assertIn('id="ld-banner-timer-0-label"', self.markup)
        self.assertIn('data-live-draft-timer-root="1"', self.markup)

    def test_loop_does_not_dead_stop_at_zero(self) -> None:
        """Regression: `if (rem <= 0) return;` left a frozen bare "0" on screen."""
        self.assertNotIn("if (rem <= 0) return;", self.markup)
        # One schedule for the running clock, one for the expired state.
        self.assertGreaterEqual(self.markup.count("setTimeout(tick,"), 2)

    def test_expired_state_is_labelled_and_counts_the_wait(self) -> None:
        self.assertIn('label.textContent = "Time expired', self.markup)
        self.assertIn('root.setAttribute("data-expired", "1")', self.markup)
        self.assertIn('+" + over + "s"', self.markup)

    def test_expired_loop_is_bounded(self) -> None:
        """Past the threshold it stops counting and asks for a reload."""
        self.assertIn(f"over >= {EXPIRED_HINT_AFTER_SEC}", self.markup)
        self.assertIn("refresh if stuck", self.markup)

    def test_big_number_still_reads_zero_not_negative_overtime(self) -> None:
        """Zero really is the time remaining; overtime stays secondary text."""
        self.assertIn("const rem = Math.max(0, Math.ceil(left));", self.markup)
        self.assertIn("el.textContent = String(rem);", self.markup)

    def test_iframe_remains_display_only(self) -> None:
        for token in OUTBOUND_TOKENS:
            self.assertNotIn(token, self.markup, token)
        # The banner iframe never reaches outside its own document.
        self.assertNotIn("window.parent", self.markup)


class TimerBarExpiryDisplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markup = _timer_bar_markup()

    def test_standalone_block_labels_its_expired_state(self) -> None:
        self.assertIn("Time on clock", self.markup)
        self.assertIn('id="ld-timer-3-label"', self.markup)
        self.assertIn('label.textContent = "Expired', self.markup)
        self.assertIn(f"over >= {EXPIRED_HINT_AFTER_SEC}", self.markup)

    def test_standalone_block_keeps_ticking_past_zero(self) -> None:
        self.assertGreaterEqual(self.markup.count("setTimeout(tick,"), 2)

    def test_standalone_block_remains_display_only(self) -> None:
        for token in OUTBOUND_TOKENS:
            self.assertNotIn(token, self.markup, token)

    def test_inline_branch_still_targets_the_parent_document_element(self) -> None:
        """Scope boundary: the inline Solo card writer is deliberately untouched."""
        markup = _timer_bar_markup(element_id="ld-banner-timer-7")
        self.assertIn("window.parent.document", markup)
        self.assertIn("ld-banner-timer-7", markup)


if __name__ == "__main__":
    unittest.main()
