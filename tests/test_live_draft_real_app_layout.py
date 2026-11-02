"""Real streamlit_app.py renders of the active drafting screen, Solo and Shared (safety net).

Slow (about 30-60 s per boot): each test boots the whole app, because the drafting layout lives
in the page body and nothing smaller reproduces it. Offline and isolated; see
tests/live_draft_real_app_harness.py.

Solo's order is pinned: the Shared redesign must not move anything in Solo. Shared assertions
cover what the redesign must keep (every section, once; commissioner vs guest permissions) and,
as the redesign lands, the Solo-like order.
"""

from __future__ import annotations

import unittest
from collections import Counter

from tests import live_draft_real_app_harness as harness

SOLO_ORDER = ["clock", "team_needs", "rec_cards", "manual_pick", "control_center", "queue", "board", "rosters"]
SHARED_SECTIONS = {
    "clock", "team_needs", "rec_cards", "manual_pick", "queue", "board",
    "control_center", "chat", "room_code", "rosters",
}


def _errors(at) -> list[str]:
    return [str(e.value)[:300] for e in at.exception]


def _duplicate_widget_keys(at) -> list[str]:
    keys = [w.key for w in list(at.button) + list(at.selectbox) + list(at.text_input) if w.key]
    return sorted(k for k, n in Counter(keys).items() if n > 1)


def _button(at, key):
    found = [b for b in at.button if b.key == key]
    return found[0] if found else None


class _RealAppCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        harness.isolate_environment()


class SoloDraftingScreenTests(_RealAppCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.at = harness.run_page(harness.solo_seed())

    def test_renders_without_errors(self) -> None:
        self.assertEqual(_errors(self.at), [])
        self.assertEqual(_duplicate_widget_keys(self.at), [])

    def test_solo_order_is_unchanged(self) -> None:
        self.assertEqual(harness.landmarks(self.at), SOLO_ORDER)
        hooks = harness.hook_keys(self.at)
        self.assertIn("ldr-m-recs-early", hooks)
        self.assertIn("ldr-m-action-early", hooks)
        self.assertNotIn("ldr-m-recs", hooks)  # cards are not painted a second time below

    def test_solo_has_no_chat_or_room_code(self) -> None:
        marks = harness.landmarks(self.at)
        self.assertNotIn("chat", marks)
        self.assertNotIn("room_code", marks)


class SharedDraftingScreenTests(_RealAppCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.code, host, guest = harness.shared_seeds()
        cls.host = harness.run_page(host)
        cls.guest = harness.run_page(guest)

    def test_both_render_without_errors_or_duplicate_widgets(self) -> None:
        for at in (self.host, self.guest):
            self.assertEqual(_errors(at), [])
            self.assertEqual(_duplicate_widget_keys(at), [])

    def test_every_drafting_section_is_present(self) -> None:
        for at in (self.host, self.guest):
            marks = harness.landmarks(at)
            self.assertEqual(SHARED_SECTIONS - set(marks), set(), marks)

    def test_commissioner_controls_follow_permissions(self) -> None:
        host_pause = _button(self.host, "live_draft_pause")
        guest_pause = _button(self.guest, "live_draft_pause")
        self.assertIsNotNone(host_pause)
        self.assertFalse(host_pause.disabled)
        self.assertTrue(guest_pause is None or guest_pause.disabled)
        # Park / delete for everyone are commissioner-only.
        self.assertIsNotNone(_button(self.host, "live_draft_discard_btn"))
        self.assertIsNone(_button(self.guest, "live_draft_discard_btn"))


class TeamNeedsAfterSoloTests(_RealAppCase):
    def test_shared_draft_after_a_solo_draft_still_shows_team_needs(self) -> None:
        """The Solo early viewport sets _live_draft_team_needs_rendered; it must not leak."""
        at = harness.run_page(harness.solo_seed())
        self.assertIn("team_needs", harness.landmarks(at))
        self.assertTrue(at.session_state["_live_draft_team_needs_rendered"])
        _code, host, _guest = harness.shared_seeds()
        for key, value in host.items():
            at.session_state[key] = value
        at.run()
        self.assertEqual(_errors(at), [])
        marks = harness.landmarks(at)
        self.assertIn("room_code", marks)  # really the Shared screen now
        self.assertIn("team_needs", marks)


if __name__ == "__main__":
    unittest.main()
