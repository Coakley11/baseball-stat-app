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

    def test_header_is_one_compact_caption_and_one_room_code(self) -> None:
        """Step 1: Solo-style header. League header, room header card, badges and the duplicate
        status summary are gone; the summary is kept once, collapsed under "Room & managers"."""
        for at in (self.host, self.guest):
            captions = [c.value for c in at.caption]
            self.assertTrue(any("· Shared ·" in c and "On clock:" in c for c in captions), captions[:8])
            self.assertEqual(harness.count(at, 'body: "### Parity League"'), 0)
            self.assertEqual(harness.count(at, 'class="ld-room-header"'), 0)
            self.assertEqual(harness.count(at, 'class="live-draft-status-badges"'), 0)
            self.assertEqual(harness.count(at, 'class="ld-room-code-panel"'), 1)
            self.assertEqual(harness.count(at, 'body: "#### Draft Status Summary"'), 1)
            inside = harness.expander_texts(at, "👥 Room & managers")
            self.assertTrue(any("#### Draft Status Summary" in t for t in inside))
            self.assertTrue(any("Claimed Teams" in t for t in inside))

    def test_clock_then_team_needs_open_the_drafting_screen(self) -> None:
        """Step 2: synchronized clock at the top, Team Needs directly below (Solo order)."""
        for at in (self.host, self.guest):
            marks = harness.landmarks(at)
            self.assertLess(marks.index("clock"), marks.index("team_needs"), marks)
            for later in ("control_center", "chat", "queue", "board", "rec_cards"):
                self.assertLess(marks.index("team_needs"), marks.index(later), marks)

    def test_cards_and_manual_pick_follow_team_needs_like_solo(self) -> None:
        """Step 3: full-width cards (Solo settings) and Manual Pick directly under Team Needs."""
        order = ["clock", "team_needs", "rec_cards", "manual_pick", "control_center"]
        for at in (self.host, self.guest):
            marks = harness.landmarks(at)
            self.assertEqual([m for m in marks if m in order], order, marks)
            for later in ("chat", "queue", "board"):
                self.assertLess(marks.index("manual_pick"), marks.index(later), marks)
            self.assertEqual(harness.count(at, 'body: "##### Recommended Players"'), 1)
            self.assertEqual(harness.count(at, 'class="ld-rec-summary-banner'), 0)  # as in Solo
            cards = harness.count(at, 'class="ld-rec-card-header')
            self.assertTrue(1 <= cards <= 6, cards)
            queue_buttons = [b for b in at.button if str(b.key or "").startswith("rec_card_queue_")]
            self.assertEqual(len(queue_buttons), cards)  # Add to Queue on every card
            self.assertEqual(harness.count(at, 'body: "Manual Draft"'), 1)

    def test_slim_control_bar_and_chat_below_the_board(self) -> None:
        """Step 4: Pause / Resume / Auto Pick in a slim bar, the rest under "More draft controls";
        live chat in a collapsible panel below the board."""
        full = ["clock", "team_needs", "rec_cards", "manual_pick", "control_center", "queue", "board", "chat"]
        for at, extra_key in ((self.host, "live_draft_reset_timer"), (self.guest, "live_draft_leave_this_room_btn")):
            marks = harness.landmarks(at)
            self.assertEqual([m for m in marks if m in full], full, marks)
            self.assertEqual(harness.count(at, 'body: "### Draft Control Center"'), 0)
            for key in ("live_draft_pause", "live_draft_resume", "live_draft_auto_now"):
                self.assertIsNotNone(_button(at, key), key)
            more = harness.expander_texts(at, "More draft controls")
            self.assertTrue(any(f"-{extra_key}" in t for t in more), extra_key)
            chat = harness.expander_texts(at, "💬 Live Draft Chat")
            self.assertTrue(any('class="ld-aim-root' in t for t in chat))
        self.assertIsNone(_button(self.guest, "live_draft_reset_timer"))  # still commissioner-only

    def test_team_needs_once_with_category_outlook(self) -> None:
        for at in (self.host, self.guest):
            panels = [
                str(n.proto).replace('\\"', '"')
                for n in harness._walk(at.main)
                if 'class="ld-team-needs-panel' in str(getattr(n, "proto", "")).replace('\\"', '"')
            ]
            self.assertEqual(len(panels), 1)
            self.assertTrue(
                "ld-cat-bar-row" in panels[0] or "outlook updates after your first pick" in panels[0],
                panels[0][:400],
            )

    def test_commissioner_controls_follow_permissions(self) -> None:
        host_pause = _button(self.host, "live_draft_pause")
        guest_pause = _button(self.guest, "live_draft_pause")
        self.assertIsNotNone(host_pause)
        self.assertFalse(host_pause.disabled)
        self.assertTrue(guest_pause is None or guest_pause.disabled)
        # Park / delete for everyone are commissioner-only.
        self.assertIsNotNone(_button(self.host, "live_draft_discard_btn"))
        self.assertIsNone(_button(self.guest, "live_draft_discard_btn"))


def _verified(seed: dict) -> dict:
    """A verified sign-in for this browser (the Shared Draft write check, security release
    6442d8d, accepts only verified accounts inside a user request)."""
    return {**seed, "_suite_auth_session": {"user": {"id": seed["_suite_auth_user_id"]}}}


class SharedPickRerunTests(_RealAppCase):
    def setUp(self) -> None:
        super().setUp()
        from unittest import mock

        import fantasy_shared_league_authz

        patcher = mock.patch.object(fantasy_shared_league_authz, "sign_in_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_signed_out_commissioner_is_told_to_sign_in_not_to_retry(self) -> None:
        _code, host_seed, _guest_seed = harness.shared_seeds()
        host = harness.run_page(host_seed)  # sign-in on, but this browser is not signed in
        draft = [b for b in host.button if str(b.key or "").startswith("rec_card_draft_") and not b.disabled]
        self.assertTrue(draft)
        draft[0].click().run()
        self.assertEqual(len(host.session_state["live_draft_room"].get("draft_board") or []), 0)
        shown = " ".join(str(w.value) for w in list(host.warning) + list(host.error))
        self.assertIn("Sign in to make picks in a Shared Draft", shown)
        self.assertNotIn("Another participant updated the room", shown)

    def test_commissioner_pick_then_reruns_keep_the_layout_for_both_browsers(self) -> None:
        code, host_seed, guest_seed = harness.shared_seeds()
        host_seed, guest_seed = _verified(host_seed), _verified(guest_seed)
        host = harness.run_page(host_seed)
        guest = harness.run_page(guest_seed)
        draft = [b for b in host.button if str(b.key or "").startswith("rec_card_draft_") and not b.disabled]
        self.assertTrue(draft, "commissioner (Team A, on the clock) has no enabled Draft button")
        draft[0].click().run()
        host.run()
        self.assertEqual(_errors(host), [])
        self.assertEqual(len(host.session_state["live_draft_room"].get("draft_board") or []), 1)
        guest.run()  # the guest's next run polls the shared room
        self.assertEqual(_errors(guest), [])
        self.assertEqual(len(guest.session_state["live_draft_room"].get("draft_board") or []), 1)
        for at in (host, guest):
            self.assertEqual(_duplicate_widget_keys(at), [])
            marks = harness.landmarks(at)
            self.assertLess(marks.index("clock"), marks.index("team_needs"), marks)
            self.assertLess(marks.index("team_needs"), marks.index("control_center"), marks)


class ManualDraftAddToQueueTests(_RealAppCase):
    def test_waiting_guest_queues_from_manual_draft_without_touching_the_room(self) -> None:
        """Manual Draft offers ⭐ Add to Queue while another team is on the clock; it changes only
        this participant's queue (no pick, no board change, no room revision, host unaffected)."""
        import draft_room_shared_state as shared_state

        code, host_seed, guest_seed = harness.shared_seeds()
        host = harness.run_page(host_seed)
        guest = harness.run_page(guest_seed)  # Team B waits: Team A is on the clock
        on_clock = [b for b in host.button if str(b.key or "").startswith("manual_draft_queue_") and b.key != "manual_draft_queue_waiting"]
        self.assertTrue(on_clock, "on-the-clock Manual Draft lost its Add to Queue")
        self.assertIsNotNone(_button(host, "draft_btn_live_draft_room_live_manual"))
        queue_btn = _button(guest, "manual_draft_queue_waiting")
        self.assertIsNotNone(queue_btn, "waiting Manual Draft has no Add to Queue")
        self.assertFalse(queue_btn.disabled)
        self.assertIn("⭐", queue_btn.label)
        self.assertTrue(_button(guest, "draft_btn_live_draft_room_live_manual_waiting").disabled)
        before = shared_state.get_shared_room_store().load(code)
        target = str(guest.selectbox(key="live_draft_player_view_only").value)
        queue_btn.click().run()
        self.assertEqual(_errors(guest), [])
        self.assertIn(target, list(guest.session_state["draft_queue"]))
        after = shared_state.get_shared_room_store().load(code)
        self.assertEqual(int(after["revision"]), int(before["revision"]))
        self.assertEqual(len(guest.session_state["live_draft_room"].get("draft_board") or []), 0)
        _button(guest, "manual_draft_queue_waiting").click().run()  # again: no duplicate
        self.assertEqual(list(guest.session_state["draft_queue"]).count(target), 1)
        host.run()
        host_queue = list(host.session_state["draft_queue"]) if "draft_queue" in host.session_state else []
        self.assertNotIn(target, host_queue)


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
