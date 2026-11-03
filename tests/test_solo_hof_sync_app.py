"""Solo Live Draft and Hall of Fame Case Mode across refresh and two devices, through the real app.

The Solo room is the one a started Solo draft leaves in the session (``live_draft_room`` plus its
canonical ``live_draft_state``); picks go through the real pick engine and the app's own saves
carry the room to the account. HOF Case Mode is changed through its checkbox and target selectbox.
"""

from __future__ import annotations

import copy
import unittest

from live_draft_pick_engine import live_draft_make_pick
from live_draft_state import LIVE_DRAFT_DIRTY_KEY, write_canonical_live_draft_state
from tests.test_page_settings_sync import HIST, TREND, _Base, cloud_full, on

CAREER = "Career Totals"
LIVE = "Live Draft Room"


def solo_room(room_id: str = "SOLO-SYNC-1") -> dict:
    teams = ["My Team", "Bot 1"]
    return {
        "status": "in_progress", "draft_room_id": room_id, "teams": teams, "current_pick_index": 0,
        "pick_order": [{"Pick": i + 1, "Round": i // 2 + 1, "Team": teams[i % 2]} for i in range(6)],
        "draft_board": [], "drafted_player_ids": [], "rosters": {t: [] for t in teams}, "pool": None,
        "config": {"num_teams": 2, "picks_per_team": 3, "rounds": 3, "your_team": "My Team", "teams": teams,
                   "timer_seconds": 600, "draft_setup_mode": "solo"},
    }


def player(n: int) -> dict:
    return {"playerID": f"solo{n}", "fullName": f"Solo Player {n}", "Primary Position": "OF"}


class SoloAndHofAcrossDevices(_Base):
    def solo_pick(self, dev, n: int):
        """A pick made on this device: the engine on the room, the room written canonically, a rerun."""
        session = dev.state()
        room = copy.deepcopy(session.get("live_draft_room") or session.get("live_draft_state"))
        work = {"live_draft_room": room}
        live_draft_make_pick(room, player(n), session=work, pick_source="manual", enrich_pick_context=False)
        write_canonical_live_draft_state(work, room, reason="solo_pick", local_edit=True)
        for key in ("live_draft_room", "live_draft_state"):
            dev.at.session_state[key] = work[key]
        dev.at.session_state[LIVE_DRAFT_DIRTY_KEY] = True
        self.store.who = dev.name
        return dev.run()

    def board(self, state: dict) -> list[str]:
        room = state.get("live_draft_state") or state.get("live_draft_room") or {}
        return [str(p.get("Player") or p.get("fullName") or p.get("player") or "") for p in room.get("draft_board") or []]

    def test_a_solo_draft_survives_refresh_and_a_fresh_phone_and_picks_flow_both_ways(self) -> None:
        dell = on(self.device("dell"), LIVE).run()
        work = {"live_draft_room": None}
        write_canonical_live_draft_state(work, solo_room(), reason="solo_start", local_edit=True)
        for key in ("live_draft_room", "live_draft_state"):
            dell.at.session_state[key] = work[key]
        dell.at.session_state[LIVE_DRAFT_DIRTY_KEY] = True
        dell.run()
        self.solo_pick(dell, 1)
        dell.go(TREND)                                       # leaving the page saves
        saved = cloud_full(self.store, self.cloud_key)
        self.assertEqual((saved.get("live_draft_state") or {}).get("draft_room_id"), "SOLO-SYNC-1")
        self.assertEqual(len(self.board(saved)), 1)

        refreshed = on(self.device("dell-refresh"), LIVE).run()
        self.assertEqual(len(self.board(refreshed.state())), 1)
        self.wipe_local_disk()
        phone = on(self.device("phone"), LIVE).run()
        self.assertEqual((phone.state().get("live_draft_state") or {}).get("draft_room_id"), "SOLO-SYNC-1")
        self.assertEqual(len(self.board(phone.state())), 1)

        self.solo_pick(phone, 2)
        phone.go(TREND)
        self.assertEqual(len(self.board(cloud_full(self.store, self.cloud_key))), 2)
        on(dell, HIST)
        dell.go("Historical")
        self.set_hist(dell, hist_HR_min=40)                  # the stale Dell saves something unrelated
        saved = cloud_full(self.store, self.cloud_key)
        self.assertEqual(len(self.board(saved)), 2)          # it never rolls the phone's pick back
        dell.go(TREND)
        self.assertEqual(len(self.board(dell.state())), 2)

    def test_hof_case_mode_and_target_follow_the_account(self) -> None:
        dell = on(self.device("dell"), CAREER).run()
        dell.at.checkbox(key="career_hof_case_mode").check().run()
        target = dell.at.selectbox(key="career_hof_case_target_player")
        choice = [o for o in target.options if o != target.value][0]
        target.set_value(choice).run()
        dell.go(TREND)
        dell.go("Career")
        self.assertTrue(dell.state().get("career_hof_case_mode"))
        self.assertEqual(dell.state().get("career_hof_case_target_player"), choice)
        self.wipe_local_disk()
        phone = on(self.device("phone"), CAREER).run()
        self.assertTrue(phone.state().get("career_hof_case_mode"))
        self.assertEqual(phone.state().get("career_hof_case_target_player"), choice)


if __name__ == "__main__":
    unittest.main()
