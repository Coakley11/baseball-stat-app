"""Regression tests for the Live Draft quality pass (ready loop, eligibility, shared rooms)."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import MutableMapping
from pathlib import Path

import pandas as pd


class _ProxySession(MutableMapping):
    """Mapping that is not a dict — like Streamlit's SessionStateProxy."""

    def __init__(self, data=None):
        self._d = dict(data or {})

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v

    def __delitem__(self, k):
        del self._d[k]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


class Pick1SnapshotReadinessTests(unittest.TestCase):
    def test_ready_snapshot_is_seen_through_a_non_dict_session(self) -> None:
        from live_draft_ready_prewarm import (
            PICK1_READY_FLAG,
            PICK1_SNAPSHOT_KEY,
            pick1_snapshot_is_ready,
        )

        room = {"draft_room_id": "R1", "current_pick_index": 0, "draft_board": []}
        session = _ProxySession(
            {PICK1_SNAPSHOT_KEY: {"ok": True, "room_id": "R1"}, PICK1_READY_FLAG: True}
        )
        # A dict-only guard returned False here, so the Ready lobby rebuilt the
        # snapshot and called st.rerun() on every run.
        self.assertTrue(pick1_snapshot_is_ready(session, room))

    def test_snapshot_for_a_started_room_is_not_ready(self) -> None:
        from live_draft_ready_prewarm import PICK1_SNAPSHOT_KEY, pick1_snapshot_is_ready

        room = {"draft_room_id": "R1", "current_pick_index": 1, "draft_board": [{}]}
        session = _ProxySession({PICK1_SNAPSHOT_KEY: {"ok": True, "room_id": "R1"}})
        self.assertFalse(pick1_snapshot_is_ready(session, room))


class SetupDefaultsTests(unittest.TestCase):
    def test_default_picks_cover_default_required_starters(self) -> None:
        from fantasy_roster_validation import validate_live_draft_setup
        from user_page_preferences import default_live_draft_setup_settings

        picks = default_live_draft_setup_settings()["live_draft_picks_per_team"]
        default_slots = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0, "BN": 5}
        self.assertTrue(validate_live_draft_setup(picks_per_team=picks, slots=default_slots)["ok"])


class OpenNeedEligibilityTests(unittest.TestCase):
    def test_flex_slot_takes_two_way_hitters(self) -> None:
        from live_draft_roster_slots import _eligible_for_draft_slot, _eligible_for_open_need_recommendation

        tokens = ["DH", "P"]  # Ohtani: DH/UTIL/P
        self.assertTrue(_eligible_for_draft_slot(tokens, "DH"))
        self.assertTrue(_eligible_for_open_need_recommendation(tokens, "UTIL"))
        self.assertFalse(_eligible_for_draft_slot(["SP"], "DH"))

    def test_player_fills_open_needs(self) -> None:
        from live_draft_roster_slots import player_fills_open_needs as fills

        # Starter gaps remain: only those positions count (BN is no escape hatch) …
        self.assertFalse(fills(["SS"], ["C", "DH", "BN"]))
        self.assertTrue(fills(["C"], ["C", "DH"]))
        # … except a DH-only hitter while DH is open.
        self.assertTrue(fills(["DH", "P"], ["C", "DH"]))
        # Only DH left: any hitter, never a pitcher.
        self.assertTrue(fills(["SS"], ["DH"]))
        self.assertFalse(fills(["SP"], ["DH"]))
        # Bench open: anyone league-legal.
        self.assertTrue(fills(["SP"], ["DH", "BN"]))

    def test_recommendation_filter_keeps_dh_only_player_while_starters_remain(self) -> None:
        from live_draft_roster_slots import filter_candidates_to_team_open_positions

        pool = pd.DataFrame(
            [
                {"fullName": "Two Way", "Primary Position": "DH", "Eligible Positions": "DH/UTIL/P"},
                {"fullName": "Short Stop", "Primary Position": "SS", "Eligible Positions": None},
                {"fullName": "Catcher", "Primary Position": "C", "Eligible Positions": None},
            ]
        )
        roster = pd.DataFrame([{"fullName": "Filled SS", "Primary Position": "SS"}])
        cfg = {"slots": {"C": 1, "SS": 1, "DH": 1, "BN": 2}}
        kept = set(filter_candidates_to_team_open_positions(pool, roster, config=cfg)["fullName"])
        self.assertEqual(kept, {"Two Way", "Catcher"})

    def test_autopick_candidate_valid_when_only_dh_is_open(self) -> None:
        from live_draft_autopick import _candidate_still_valid

        cand = {"playerID": "x1", "fullName": "Short Stop", "Primary Position": "SS", "Eligible Positions": None}
        # Text matching required a literal "DH", so this stalled the draft.
        self.assertTrue(_candidate_still_valid(cand, drafted=set(), gaps=["DH"]))
        pitcher = {"playerID": "p1", "fullName": "Arm", "Primary Position": "SP", "Eligible Positions": None}
        self.assertFalse(_candidate_still_valid(pitcher, drafted=set(), gaps=["DH"]))
        self.assertFalse(_candidate_still_valid(cand, drafted={"id:x1"}, gaps=["DH"]))


class RosterProjectionTests(unittest.TestCase):
    def test_roster_rows_gain_pool_projections(self) -> None:
        from live_draft_roster_tracker import roster_df_for_team

        pool = pd.DataFrame(
            [{"playerID": "a1", "fullName": "Slugger", "proj_HR": 40.0, "proj_SB": 5.0}]
        )
        room = {"rosters": {"Team A": [{"playerID": "a1", "fullName": "Slugger"}]}, "pool": pool}
        df = roster_df_for_team(room, "Team A")
        self.assertEqual(float(df.loc[0, "proj_HR"]), 40.0)

    def test_category_outlook_counts_rostered_projections(self) -> None:
        from live_draft_category_outlook import compute_category_outlook
        from live_draft_roster_tracker import roster_df_for_team

        pool = pd.DataFrame(
            [
                {"playerID": f"p{i}", "fullName": f"P{i}", "proj_HR": 10.0, "proj_SB": 5.0,
                 "proj_RBI": 50.0, "proj_R": 50.0, "proj_BA": 0.250}
                for i in range(10)
            ]
        )
        room = {"rosters": {"Team A": [{"playerID": "p0", "fullName": "P0"}]}, "pool": pool}
        outlook = compute_category_outlook(roster_df_for_team(room, "Team A"), pool, config={})
        hr = next(b for b in outlook["bars"] if b["category"] == "HR")
        self.assertEqual(hr["team_value"], 10.0)


class LocalSharedRoomWriteTests(unittest.TestCase):
    def test_save_is_atomic_and_leaves_no_temp_files(self) -> None:
        import draft_room_shared_state as m

        with tempfile.TemporaryDirectory() as tmp:
            store = m.LocalFileSharedRoomStore.__new__(m.LocalFileSharedRoomStore)
            store.root = Path(tmp)
            store.save({"room_code": "ABC123", "revision": 1, "filler": "x" * 5000})
            store.save({"room_code": "ABC123", "revision": 2})
            path = Path(tmp) / "ABC123.json"
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["revision"], 2)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["ABC123.json"])


class PhoneLayoutGapTests(unittest.TestCase):
    """Invisible carriers must not leave blank bands on phones."""

    def test_zero_height_iframe_carrier_rule_matches_current_streamlit_markup(self) -> None:
        import mobile_foundation as mf

        css = mf.mobile_foundation_css()
        sel = '[data-testid="stElementContainer"][height="0px"]:has(> iframe[data-testid="stIFrame"])'
        self.assertIn(sel, css)
        self.assertIn(mf.media_phone(), css[: css.index(sel)])

    def test_solo_wake_carrier_is_taken_out_of_flow_not_hidden(self) -> None:
        import live_draft_mobile_layout as L

        rule = next(ln for ln in L.live_draft_mobile_css().splitlines() if "st-key-solo_countdown_wake_" in ln)
        self.assertIn("position: absolute", rule)
        self.assertNotIn("display: none", rule)

    def test_p2a_entry_marker_is_trace_only(self) -> None:
        from unittest import mock

        import live_draft_solo_p2a_path_diag as diag

        st = mock.MagicMock()
        session: dict = {}
        with mock.patch.object(diag, "p2a_trace_requested", return_value=False):
            diag.render_p2a_fn_entry(st, session, {"draft_room_id": "S1"})
        st.markdown.assert_not_called()
        self.assertEqual(session, {})

    def test_team_totals_has_no_orphan_panel_wrapper(self) -> None:
        src = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertNotIn("""st.markdown('<div class="live-draft-totals-panel">'""", src)


class LocalSharedRoomConcurrencyTests(unittest.TestCase):
    """A checked write that succeeded must not be undone by a concurrent lease renewal."""

    def _race(self, picks: int = 80) -> tuple[list[str], set[str]]:
        import threading
        import time

        import draft_room_shared_state as m

        with tempfile.TemporaryDirectory() as tmp:
            store = m.LocalFileSharedRoomStore(root=Path(tmp))
            store.save({"room_code": "RACE01", "revision": 1, "room": {"draft_board": []}})
            stop = threading.Event()

            def renew() -> None:  # timer-authority renewal: same revision, older room
                while not stop.is_set():
                    doc = store.load("RACE01")
                    if doc:
                        rev = int(doc.get("revision") or 0)
                        store.save_if_revision(
                            dict(doc, timer_authority={"user_id": "host", "lease_expires_at": time.time() + 8}),
                            expected_revision=rev,
                        )

            renewer = threading.Thread(target=renew)
            renewer.start()
            committed: list[str] = []
            try:
                for i in range(picks):
                    for _ in range(100):
                        doc = store.load("RACE01")
                        rev = int(doc.get("revision") or 0)
                        room = dict(doc["room"], draft_board=list(doc["room"]["draft_board"]) + [{"id": f"p{i}"}])
                        ok, _saved = store.save_if_revision(dict(doc, room=room, revision=rev + 1), expected_revision=rev)
                        if ok:
                            committed.append(f"p{i}")
                            break
            finally:
                stop.set()
                renewer.join()
            final = store.load("RACE01")
            return committed, {e["id"] for e in final["room"]["draft_board"]}

    def test_committed_picks_survive_concurrent_lease_renewals(self) -> None:
        committed, on_board = self._race()
        self.assertEqual(len(committed), 80)
        self.assertEqual([p for p in committed if p not in on_board], [])


class SharedPresenceLabelTests(unittest.TestCase):
    def test_guest_seat_is_not_labelled_with_the_host_name(self) -> None:
        from live_draft_presence import required_human_participant_rows

        doc = {
            "room": {"teams": ["Team A", "Team B"], "config": {"num_teams": 2}},
            "commissioner_participant_id": "workspace:host",
            "host_participant_id": "workspace:host",
            "participants": {
                "workspace:host": {"assigned_team": "Team A", "user_id": "local:default", "display_name": "workspace:host"},
                "workspace:guest": {"assigned_team": "Team B", "user_id": "local:default", "display_name": "workspace:guest"},
            },
            "joined_participants": {
                "local:default": {"display_name": "workspace:host", "team_name": "Team A", "user_id": "local:default"},
                "workspace:host": {"display_name": "workspace:host", "team_name": "Team A", "user_id": "workspace:host"},
                "workspace:guest": {"display_name": "workspace:guest", "team_name": "Team B", "user_id": "workspace:guest"},
            },
        }
        rows = required_human_participant_rows({}, doc["room"], document=doc, allow_network=False)
        names = {r["team_name"]: r["display_name"] for r in rows}
        self.assertEqual(names.get("Team B"), "workspace:guest")


class CanonicalPeekTests(unittest.TestCase):
    def test_peek_returns_the_stored_blob_without_copying(self) -> None:
        from live_draft_state import LIVE_DRAFT_STATE_KEY, has_active_live_draft, peek_canonical_live_draft

        blob = {"draft_room_id": "R9", "status": "in_progress"}
        session = {LIVE_DRAFT_STATE_KEY: blob}
        self.assertIs(peek_canonical_live_draft(session), blob)
        self.assertTrue(has_active_live_draft(session))

    def test_owned_save_pipeline_matches_copying_pipeline(self) -> None:
        from live_draft_state import LIVE_DRAFT_STATE_KEY, sanitize_state_dict_for_json

        def state():
            return {
                LIVE_DRAFT_STATE_KEY: {
                    "draft_room_id": "R9",
                    "status": "in_progress",
                    "pool_records": [{"playerID": "a"}],
                    "pool_columns": ["playerID"],
                },
                "page_filter_state": {},
            }

        a = sanitize_state_dict_for_json(state())
        b = sanitize_state_dict_for_json(state(), copy_input=False)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))


class DecisionScoreCopyTests(unittest.TestCase):
    def test_tooltip_does_not_promise_a_0_to_100_range(self) -> None:
        from draft_score_display import DISPLAY_PICK_SCORE, SCORE_TOOLTIPS

        self.assertNotIn("0–100", SCORE_TOOLTIPS[DISPLAY_PICK_SCORE])


class RecCardDraftClickTests(unittest.TestCase):
    """The card's Draft click is queued by on_click and refused once its pick has closed."""

    def _render_cards(self, session: dict, room: dict):
        from unittest.mock import MagicMock, patch

        from live_draft_room_ui import render_live_draft_rec_cards

        st = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        st.container.return_value = ctx
        st.expander.return_value = ctx
        st.columns.side_effect = lambda n, *a, **k: [ctx] * (n if isinstance(n, int) else len(n))
        st.button.return_value = False
        with patch("live_draft_room_ui.record_rec_card_diagnostics"):
            render_live_draft_rec_cards(st, session, room, room["pool"], max_cards=2, layout="horizontal", dense=False)
        return [c for c in st.button.call_args_list if str(c.kwargs.get("key") or "").startswith("rec_card_draft_")]

    def _room(self) -> dict:
        pool = pd.DataFrame(
            [
                {"fullName": "Manny Machado", "playerID": "m1", "Primary Position": "3B", "Team": "SD", "Decision Score": 0.8},
                {"fullName": "Ketel Marte", "playerID": "m2", "Primary Position": "2B", "Team": "AZ", "Decision Score": 0.7},
            ]
        )
        return {
            "draft_room_id": "LDQCARD",
            "current_pick_index": 0,
            "status": "in_progress",
            "config": {"your_team": "Team A", "num_teams": 2},
            "pool": pool,
            "teams": ["Team A", "Team B"],
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team A"}, {"Pick": 2, "Round": 1, "Team": "Team B"}],
            "draft_board": [],
            "rosters": {"Team A": [], "Team B": []},
            "drafted_player_ids": [],
        }

    def test_draft_button_queues_the_pick_on_click_for_the_shown_pick(self) -> None:
        from draft_ui import PENDING_MANUAL_PICK_KEY

        room = self._room()
        session: dict = {"draft_queue": [], "live_draft_room": room}
        calls = self._render_cards(session, room)
        enabled = [c for c in calls if not c.kwargs.get("disabled")]
        self.assertTrue(enabled, calls)
        self.assertTrue(callable(enabled[0].kwargs.get("on_click")))
        enabled[0].kwargs["on_click"]()
        pending = session.get(PENDING_MANUAL_PICK_KEY) or {}
        self.assertEqual(pending.get("player_name"), "Manny Machado")
        self.assertEqual(pending.get("target_pick_index"), 0)

    def test_click_for_a_pick_that_has_closed_is_refused_not_drafted_into_the_next(self) -> None:
        from unittest.mock import MagicMock, patch

        from draft_ui import queue_manual_draft_pick, process_pending_manual_draft_pick

        room = self._room()
        session: dict = {"draft_queue": [], "live_draft_room": room}
        queue_manual_draft_pick(
            session, player_name="Ketel Marte", player_id="m2", candidate_source="rec_card", target_pick_index=0
        )
        room["current_pick_index"] = 1  # pick 1 expired before the click was processed
        with patch("draft_ui.draft_player") as draft:
            result = process_pending_manual_draft_pick(MagicMock(), session)
        draft.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("Pick 1 closed", result["error"])


class _LocalSharedRoomCase(unittest.TestCase):
    """Host and guest sessions against a temporary local shared-room store."""

    def setUp(self) -> None:
        from unittest import mock

        from draft_room_shared_state import LocalFileSharedRoomStore

        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()


class SharedManualPickCommitTests(_LocalSharedRoomCase):
    """A seat's manual pick must reach the shared room document before the next poll."""

    def test_guest_pick_is_in_the_room_document_and_survives_the_next_poll(self) -> None:
        import time

        from draft_actions import draft_player
        from draft_room_context import create_and_host_shared_room, join_shared_draft_room, poll_shared_draft_room
        from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY

        pool = pd.DataFrame(
            [
                {"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
                {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
                {"playerID": "p3", "fullName": "Bobby Witt", "Primary Position": "SS"},
            ]
        )
        room = {
            "draft_room_id": "LDQPICK",
            "status": "in_progress",
            "current_pick_index": 0,
            "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60},
            "teams": ["Team 1", "Team 2"],
            "pick_order": [
                {"Pick": 1, "Round": 1, "Team": "Team 1"},
                {"Pick": 2, "Round": 1, "Team": "Team 2"},
                {"Pick": 3, "Round": 2, "Team": "Team 2"},
            ],
            "draft_board": [],
            "rosters": {"Team 1": [], "Team 2": []},
            "drafted_player_ids": [],
            "pool": pool,
            "timer_deadline": time.time() + 45,
        }
        host: dict = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        guest: dict = {"draft_room_participant_id": "guest-user", "room_your_team": "Team 2"}
        code, _ = create_and_host_shared_room(host, room, store=self.store)
        join_shared_draft_room(guest, code, requested_team="Team 2", store=self.store)

        def board(entries) -> list[str]:
            return [str(e.get("fullName")) for e in (entries or [])]

        for seat, name in ((host, "Juan Soto"), (guest, "Bobby Witt")):
            poll_shared_draft_room(seat, force=True, store=self.store)
            result = draft_player(seat, name, source="live_draft_room")
            self.assertTrue(result.get("ok"), result)
            # Durable before any deferred flush: the room document already has the pick.
            self.assertEqual(board(self.store.load(code)["room"].get("draft_board"))[-1], name)

        # Later polls must not replace either seat's board with an older one.
        for seat in (host, guest):
            poll_shared_draft_room(seat, force=True, store=self.store)
            self.assertEqual(board(seat[LIVE_DRAFT_ROOM_KEY].get("draft_board")), ["Juan Soto", "Bobby Witt"])


class _SharedDraftCase(_LocalSharedRoomCase):
    """A two-seat shared room whose first pick's deadline is ``deadline_in`` seconds away."""

    NAMES = ["Juan Soto", "Aaron Judge", "Bobby Witt", "Jose Ramirez", "Freddie Freeman", "Mookie Betts"]

    def _start(self, *, first: str, deadline_in: float) -> tuple[str, dict, dict]:
        import time

        from draft_room_context import create_and_host_shared_room, join_shared_draft_room, poll_shared_draft_room

        second = "Team 1" if first == "Team 2" else "Team 2"
        pool = pd.DataFrame(
            [{"playerID": f"p{i}", "fullName": n, "Primary Position": "OF"} for i, n in enumerate(self.NAMES)]
        )
        now = time.time()
        room = {
            "draft_room_id": "LDQEXP",
            "status": "in_progress",
            "current_pick_index": 0,
            "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60},
            "timer_seconds": 60,
            "teams": ["Team 1", "Team 2"],
            "pick_order": [
                {"Pick": 1, "Round": 1, "Team": first},
                {"Pick": 2, "Round": 1, "Team": second},
                {"Pick": 3, "Round": 2, "Team": second},
                {"Pick": 4, "Round": 2, "Team": first},
            ],
            "draft_board": [],
            "rosters": {"Team 1": [], "Team 2": []},
            "drafted_player_ids": [],
            "pool": pool,
            "timer_started_at": now + deadline_in - 60,
            "timer_deadline": now + deadline_in,
        }
        host: dict = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        guest: dict = {"draft_room_participant_id": "guest-user", "room_your_team": "Team 2"}
        code, _ = create_and_host_shared_room(host, room, store=self.store)
        join_shared_draft_room(guest, code, requested_team="Team 2", store=self.store)
        for seat in (host, guest):
            poll_shared_draft_room(seat, force=True, store=self.store)
        return code, host, guest

    def _board(self, code: str) -> list[tuple[str, str]]:
        entries = self.store.load(code)["room"].get("draft_board") or []
        return [(str(e.get("fullName")), str(e.get("pick_source"))) for e in entries]

    def _expire(self, seat: dict, source: str = "page_autopick"):
        from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY
        from live_draft_expired_pick import handle_expired_pick_on_page

        return handle_expired_pick_on_page(seat, seat[LIVE_DRAFT_ROOM_KEY], source=source)


class SharedExpiryBoundaryTests(_SharedDraftCase):
    """Auto-pick only after the canonical deadline; a leftover expiry flag never steals a pick."""

    def test_flag_left_by_a_manual_pick_at_the_deadline_does_not_steal_the_next_pick(self) -> None:
        from draft_actions import draft_player
        from draft_room_context import poll_shared_draft_room
        from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY
        from live_draft_expired_pick import EXPIRED_PICK_PENDING_KEY, should_attach_timer_fragment

        code, host, guest = self._start(first="Team 2", deadline_in=-0.5)
        # Host (timer authority) sees zero; the guest's manual pick lands first.
        should_attach_timer_fragment(host, host[LIVE_DRAFT_ROOM_KEY])
        self.assertTrue(host.get(EXPIRED_PICK_PENDING_KEY))
        self.assertTrue(draft_player(guest, "Bobby Witt", source="live_draft_room").get("ok"))
        poll_shared_draft_room(host, force=True, store=self.store)

        self._expire(host)
        self.assertEqual(self._board(code), [("Bobby Witt", "Live Draft Pick")])
        self.assertFalse(host.get(EXPIRED_PICK_PENDING_KEY))

    def test_flag_left_by_a_lease_handover_does_not_steal_the_next_pick(self) -> None:
        from unittest import mock

        import live_draft_timer_authority as lta
        from draft_room_context import poll_shared_draft_room
        from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY
        from live_draft_expired_pick import should_attach_timer_fragment

        code, host, guest = self._start(first="Team 1", deadline_in=-3)
        should_attach_timer_fragment(host, host[LIVE_DRAFT_ROOM_KEY])  # host saw zero, then stalled
        self.assertTrue(self._expire(guest, source="timer_fragment_zero").ok)  # guest watchdog expires pick 1
        poll_shared_draft_room(host, force=True, store=self.store)
        real_now = lta._utc_now
        with mock.patch.object(lta, "_utc_now", lambda: real_now() + lta.TIMER_AUTHORITY_LEASE_SEC + 1):
            self._expire(host)  # host takes the lease back
        board = self._board(code)
        self.assertEqual(len(board), 1, board)
        self.assertEqual(board[0][1], "Auto Pick")

    def test_no_auto_pick_while_time_remains_even_with_the_flag_set(self) -> None:
        from live_draft_expired_pick import EXPIRED_PICK_PENDING_KEY

        # The first room setup in a process is slow (imports, pool) and the clock runs
        # from room creation; warm it so a slow machine does not expire the pick for real.
        self._start(first="Team 2", deadline_in=60)
        for left in (15, 5, 2.5):
            with self.subTest(seconds_left=left):
                code, host, _guest = self._start(first="Team 2", deadline_in=left)
                deadline = float(self.store.load(code)["room"]["timer_deadline"])
                if deadline - __import__("time").time() < 0.5:
                    continue  # setup alone used up the clock on this machine; nothing to test
                for _ in range(3):  # reruns near the deadline
                    host[EXPIRED_PICK_PENDING_KEY] = True
                    if __import__("time").time() < deadline:
                        self.assertFalse(self._expire(host).ok)
                self.assertEqual(self._board(code), [])
                # No auto-pick and no timer reset: the pick keeps its deadline.
                self.assertEqual(float(self.store.load(code)["room"]["timer_deadline"]), deadline)

    def test_manual_pick_just_before_the_deadline_wins_and_the_next_pick_keeps_its_clock(self) -> None:
        from draft_actions import draft_player
        from draft_room_context import poll_shared_draft_room
        from live_draft_expired_pick import EXPIRED_PICK_PENDING_KEY

        code, host, guest = self._start(first="Team 2", deadline_in=1.0)
        self.assertTrue(draft_player(guest, "Jose Ramirez", source="live_draft_room").get("ok"))
        poll_shared_draft_room(host, force=True, store=self.store)
        host[EXPIRED_PICK_PENDING_KEY] = True
        self._expire(host)
        self.assertEqual(self._board(code), [("Jose Ramirez", "Live Draft Pick")])
        self.assertGreater(float(self.store.load(code)["room"]["timer_deadline"]) - __import__("time").time(), 55)

    def test_expired_pick_auto_picks_exactly_once_and_not_the_next_pick(self) -> None:
        code, host, _guest = self._start(first="Team 2", deadline_in=-0.05)
        self.assertTrue(self._expire(host).ok)
        for _ in range(3):  # immediate reruns after the expiry
            self._expire(host)
        board = self._board(code)
        self.assertEqual(len(board), 1, board)
        self.assertEqual(board[0][1], "Auto Pick")

    def test_auto_pick_cannot_overwrite_a_manual_pick_committed_in_the_same_slot(self) -> None:
        from unittest import mock

        import live_draft_pick_commit as lpc
        from draft_actions import draft_player
        from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY, SHARED_DOC_SOFT_CACHE_KEY

        code, host, guest = self._start(first="Team 2", deadline_in=-0.5)
        real_persist = lpc.persist_applied_pick
        raced: list[bool] = []

        def persist_after_guest_pick(session, room, **kw):
            # The guest's manual pick lands while the host's auto-pick is being selected.
            if session is host and not raced:
                raced.append(draft_player(guest, "Bobby Witt", source="live_draft_room").get("ok"))
                session.pop(SHARED_DOC_SOFT_CACHE_KEY, None)  # cache refreshed before the write
            return real_persist(session, room, **kw)

        with mock.patch.object(lpc, "persist_applied_pick", persist_after_guest_pick):
            result = self._expire(host, source="timer_fragment_zero")
        self.assertEqual(raced, [True])
        self.assertEqual(self._board(code), [("Bobby Witt", "Live Draft Pick")])
        # The losing auto-pick must not announce a player who was not drafted.
        self.assertNotIn("Juan Soto", result.message)
        self.assertNotIn("Juan Soto", str(host.get("_live_draft_pick_notice") or ""))
        host_board = [e.get("fullName") for e in host[LIVE_DRAFT_ROOM_KEY].get("draft_board") or []]
        self.assertEqual(host_board, ["Bobby Witt"])

    def test_expiry_interrupted_by_a_rerun_still_auto_picks_once_on_the_next_run(self) -> None:
        from unittest import mock

        import live_draft_expired_pick as lep
        from streamlit.runtime.scriptrunner_utils.exceptions import RerunException
        from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

        code, host, _guest = self._start(first="Team 2", deadline_in=-0.5)

        def interrupted(*_a, **_k):
            raise RerunException(RerunData())

        with mock.patch.object(lep, "run_autopick_selection", interrupted):
            with self.assertRaises(RerunException):
                self._expire(host, source="timer_fragment_zero")
        self.assertIsNone(host.get(lep.CLAIMED_EXPIRATION_TOKEN_KEY))
        self.assertTrue(self._expire(host).ok)
        self._expire(host)
        board = self._board(code)
        self.assertEqual(len(board), 1, board)
        self.assertEqual(board[0][1], "Auto Pick")

    def test_paused_draft_never_expires_and_keeps_its_remaining_time(self) -> None:
        from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY
        from live_draft_expired_pick import EXPIRED_PICK_PENDING_KEY, clock_needs_autopick

        _code, host, _guest = self._start(first="Team 2", deadline_in=-1)
        room = dict(host[LIVE_DRAFT_ROOM_KEY], status="paused", paused_remaining_seconds=12, timer_deadline=None)
        host[EXPIRED_PICK_PENDING_KEY] = True
        self.assertFalse(clock_needs_autopick(host, room))
        self.assertEqual(room["paused_remaining_seconds"], 12)



class SharedDeadlineFairnessTests(_SharedDraftCase):
    """A click the server received before the canonical deadline may commit after it;
    one first received at or after the deadline is refused."""

    def _deadline(self, code: str) -> float:
        return float(self.store.load(code)["room"]["timer_deadline"])

    def _queue(self, seat: dict, name: str, pid: str, received_at: float, target: int = 0) -> None:
        from draft_ui import PENDING_MANUAL_PICK_KEY, queue_manual_draft_pick

        queue_manual_draft_pick(seat, player_name=name, player_id=pid, candidate_source="rec_card", target_pick_index=target)
        seat[PENDING_MANUAL_PICK_KEY]["queued_at"] = received_at

    def _process(self, seat: dict) -> dict:
        from unittest.mock import MagicMock

        from draft_ui import process_pending_manual_draft_pick

        return process_pending_manual_draft_pick(MagicMock(), seat)

    def test_pre_deadline_click_commits_even_when_processed_after_the_deadline(self) -> None:
        for before in (5.0, 2.0, 0.5):
            with self.subTest(received_before_deadline=before):
                code, host, guest = self._start(first="Team 2", deadline_in=-0.3)
                self._queue(guest, "Bobby Witt", "p2", self._deadline(code) - before)
                result = self._process(guest)
                self.assertTrue(result["ok"], result)
                self._expire(host)  # the timer authority's expiry runs afterwards
                self.assertEqual(self._board(code), [("Bobby Witt", "Live Draft Pick")])

    def test_click_received_at_or_after_the_deadline_is_refused(self) -> None:
        for after in (0.0, 0.3):
            with self.subTest(received_after_deadline=after):
                code, host, guest = self._start(first="Team 2", deadline_in=-0.5)
                self._queue(guest, "Bobby Witt", "p2", self._deadline(code) + after)
                result = self._process(guest)
                self.assertFalse(result["ok"])
                self.assertIn("clock had run out", result["error"])
                self.assertEqual(self._board(code), [])
                self.assertTrue(self._expire(host).ok)
                board = self._board(code)
                self.assertEqual(len(board), 1, board)
                self.assertEqual(board[0][1], "Auto Pick")

    def test_expiry_waits_for_this_sessions_pre_deadline_click_but_not_a_late_one(self) -> None:
        code, host, _guest = self._start(first="Team 1", deadline_in=-0.5)
        self._queue(host, "Juan Soto", "p0", self._deadline(code) - 1.0)
        self.assertFalse(self._expire(host).ok)  # held for the pending pick
        self.assertEqual(self._board(code), [])
        self.assertTrue(self._process(host)["ok"])
        self._expire(host)
        self.assertEqual(self._board(code), [("Juan Soto", "Live Draft Pick")])

        code, host, _guest = self._start(first="Team 1", deadline_in=-0.5)
        self._queue(host, "Juan Soto", "p0", self._deadline(code) + 0.2)
        self.assertTrue(self._expire(host).ok)  # a late click does not hold the clock
        self.assertFalse(self._process(host)["ok"])
        board = self._board(code)
        self.assertEqual(len(board), 1, board)
        self.assertEqual(board[0][1], "Auto Pick")

    def test_in_flight_state_from_the_previous_pick_does_not_hold_the_next_pick(self) -> None:
        import time

        from draft_actions import draft_player
        from draft_room_context import poll_shared_draft_room

        code, host, _guest = self._start(first="Team 1", deadline_in=40)
        self.assertTrue(draft_player(host, "Juan Soto", source="live_draft_room").get("ok"))
        doc = self.store.load(code)
        doc["room"]["timer_deadline"] = time.time() - 0.5  # pick 2 has now expired
        self.store.save(doc)
        poll_shared_draft_room(host, force=True, store=self.store)
        host["_live_draft_manual_pick_in_flight"] = True  # post-commit guard from pick 1
        host["_live_draft_manual_pick_in_flight_idx"] = 0
        self.assertTrue(self._expire(host).ok)
        self.assertEqual([b[1] for b in self._board(code)], ["Live Draft Pick", "Auto Pick"])

    def test_click_for_a_pick_already_expired_is_refused_not_drafted_into_the_next(self) -> None:
        from draft_room_context import poll_shared_draft_room

        code, host, guest = self._start(first="Team 2", deadline_in=-0.5)
        dl = self._deadline(code)
        self.assertTrue(self._expire(host).ok)
        poll_shared_draft_room(guest, force=True, store=self.store)  # next pick already open
        self._queue(guest, "Bobby Witt", "p2", dl - 1.0, target=0)
        result = self._process(guest)
        self.assertFalse(result["ok"])
        self.assertIn("closed before", result["error"])
        self.assertEqual(len(self._board(code)), 1)

    def test_pre_deadline_click_that_loses_the_race_to_a_committed_expiry_is_refused(self) -> None:
        code, host, guest = self._start(first="Team 2", deadline_in=-0.5)
        dl = self._deadline(code)
        self.assertTrue(self._expire(host).ok)  # expiry accepted first; guest has not polled
        self._queue(guest, "Bobby Witt", "p2", dl - 1.0, target=0)
        result = self._process(guest)
        self.assertFalse(result["ok"])
        board = self._board(code)
        self.assertEqual(len(board), 1, board)
        self.assertEqual(board[0][1], "Auto Pick")


class SoloDeadlineFairnessTests(unittest.TestCase):
    """Solo applies the same received-before-deadline rule; its expiry then picks once."""

    def _session(self, deadline_in: float) -> dict:
        import time

        pool = pd.DataFrame(
            [{"playerID": f"s{i}", "fullName": n, "Primary Position": "OF"}
             for i, n in enumerate(["Juan Soto", "Aaron Judge", "Bobby Witt", "Jose Ramirez"])]
        )
        now = time.time()
        room = {
            "draft_room_id": "SOLODL",
            "status": "in_progress",
            "current_pick_index": 0,
            "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60},
            "timer_seconds": 60,
            "teams": ["Team 1", "Team 2"],
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}, {"Pick": 2, "Round": 1, "Team": "Team 2"}],
            "draft_board": [],
            "rosters": {"Team 1": [], "Team 2": []},
            "drafted_player_ids": [],
            "pool": pool,
            "timer_started_at": now + deadline_in - 60,
            "timer_deadline": now + deadline_in,
        }
        return {"live_draft_room": room, "room_your_team": "Team 1"}

    def _click(self, session: dict, received_delta: float) -> dict:
        from unittest.mock import MagicMock

        from draft_ui import PENDING_MANUAL_PICK_KEY, process_pending_manual_draft_pick, queue_manual_draft_pick

        deadline = float(session["live_draft_room"]["timer_deadline"])
        queue_manual_draft_pick(session, player_name="Aaron Judge", player_id="s1", candidate_source="rec_card", target_pick_index=0)
        session[PENDING_MANUAL_PICK_KEY]["queued_at"] = deadline + received_delta
        return process_pending_manual_draft_pick(MagicMock(), session)

    def _board(self, session: dict) -> list[str]:
        return [str(e.get("fullName")) for e in session["live_draft_room"].get("draft_board") or []]

    def test_pre_deadline_click_commits_after_the_deadline(self) -> None:
        session = self._session(deadline_in=-0.3)
        self.assertTrue(self._click(session, -0.5)["ok"])
        self.assertEqual(self._board(session), ["Aaron Judge"])

    def test_click_received_after_the_deadline_is_refused_and_expiry_picks_once(self) -> None:
        from live_draft_solo_timer import expire_current_pick_and_advance

        session = self._session(deadline_in=-0.3)
        result = self._click(session, 0.1)
        self.assertFalse(result["ok"])
        self.assertIn("clock had run out", result["error"])
        self.assertEqual(self._board(session), [])
        self.assertTrue(expire_current_pick_and_advance(session["live_draft_room"], session=session).ok)
        expire_current_pick_and_advance(session["live_draft_room"], session=session)  # immediate retry
        self.assertEqual(len(self._board(session)), 1)


def _persisted_room_blob(rows: int = 6) -> dict:
    import time

    from live_draft_state import room_to_persist_dict

    pool = pd.DataFrame(
        [{"playerID": f"q{i}", "fullName": f"Player {i}", "Primary Position": "OF", "Expected Fantasy Value": 50.0 - i}
         for i in range(rows)]
    )
    room = {
        "draft_room_id": "PERSIST1",
        "status": "in_progress",
        "current_pick_index": 1,
        "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}, {"Pick": 2, "Round": 1, "Team": "Team 2"}],
        "draft_board": [{"Pick": 1, "Round": 1, "Team": "Team 1", "fullName": "Player 0", "playerID": "q0"}],
        "rosters": {"Team 1": [{"fullName": "Player 0", "playerID": "q0"}], "Team 2": []},
        "drafted_player_ids": ["q0"],
        "pool": pool,
        "timer_started_at": time.time() - 10,
        "timer_deadline": time.time() + 50,
    }
    return room_to_persist_dict(room)


class WorkspacePersistenceSlimmingTests(unittest.TestCase):
    """Shared saves carry no rebuildable pool; the unread page copy is gone; old saves still load."""

    CANON_KEYS = ("draft_room_id", "status", "current_pick_index", "draft_board", "rosters", "pick_order",
                  "drafted_player_ids", "config")

    def _session_and_state(self, blob: dict) -> tuple[dict, dict]:
        import copy

        from live_draft_state import room_from_persist_dict

        session = {"live_draft_state": copy.deepcopy(blob), "live_draft_room": room_from_persist_dict(blob)}
        state = {"live_draft_state": copy.deepcopy(blob), "page_filter_state": {
            "Live Draft Room": {"live_draft_state": copy.deepcopy(blob), "live_draft_room": copy.deepcopy(blob),
                                "live_draft_timer": "60 sec"}}}
        return session, state

    def _enrich(self, session: dict, state: dict, *, shared: bool) -> dict:
        from unittest import mock

        import live_draft_state as lds

        with mock.patch.object(lds, "shared_room_pool_is_rebuildable", return_value=shared):
            out, _diag = lds.enrich_save_payload_with_live_draft(session, state)
        return out

    def test_shared_save_carries_no_pool_and_keeps_every_canonical_field(self) -> None:
        from live_draft_state import is_persisted_room_blob

        blob = _persisted_room_blob()
        session, state = self._session_and_state(blob)
        out = self._enrich(session, state, shared=True)
        block = out["page_filter_state"]["Live Draft Room"]
        for copy_ in (out["live_draft_state"], out["live_draft_room"], block["live_draft_room"]):
            self.assertEqual(copy_["pool_records"], [])
            self.assertTrue(is_persisted_room_blob(copy_))
            for key in self.CANON_KEYS:
                self.assertEqual(copy_.get(key), blob.get(key), key)
            self.assertAlmostEqual(float(copy_["timer_deadline"]), float(blob["timer_deadline"]), places=3)
        self.assertNotIn("live_draft_state", block)
        self.assertEqual(block["live_draft_timer"], "60 sec")

    def test_solo_save_keeps_its_pool_and_drops_only_the_unread_page_copy(self) -> None:
        blob = _persisted_room_blob()
        session, state = self._session_and_state(blob)
        out = self._enrich(session, state, shared=False)
        block = out["page_filter_state"]["Live Draft Room"]
        for copy_ in (out["live_draft_state"], out["live_draft_room"], block["live_draft_room"]):
            self.assertEqual(len(copy_["pool_records"]), 6)
        self.assertNotIn("live_draft_state", block)

    def test_old_shape_save_with_four_full_copies_still_restores(self) -> None:
        import copy

        from live_draft_state import _peek_live_draft_blob, restore_live_draft_page_filters, room_from_persist_dict

        blob = _persisted_room_blob()
        old_state = {
            "live_draft_state": copy.deepcopy(blob),
            "live_draft_room": copy.deepcopy(blob),
            "page_filter_state": {"Live Draft Room": {"live_draft_state": copy.deepcopy(blob),
                                                      "live_draft_room": copy.deepcopy(blob)}},
        }
        self.assertEqual(len(_peek_live_draft_blob(old_state)["pool_records"]), 6)
        self.assertEqual(len(room_from_persist_dict(old_state["live_draft_state"])["pool"]), 6)
        session: dict = {}
        self.assertTrue(restore_live_draft_page_filters(session, old_state["page_filter_state"]))
        self.assertEqual(len(session["live_draft_state"]["pool_records"]), 6)
        self.assertEqual(session["live_draft_state"]["draft_board"], blob["draft_board"])

    def test_old_shape_shared_save_is_normalized_on_the_next_save(self) -> None:
        blob = _persisted_room_blob()
        session, state = self._session_and_state(blob)
        out = self._enrich(session, state, shared=True)
        self.assertEqual(out["live_draft_room"]["pool_records"], [])
        self.assertNotIn("live_draft_state", out["page_filter_state"]["Live Draft Room"])

    def test_page_snapshot_no_longer_captures_the_canonical_blob(self) -> None:
        import page_state as pg_state

        blob = _persisted_room_blob()
        session = {"live_draft_state": blob, "live_draft_room": blob, "live_draft_timer": "60 sec"}
        store = {"Live Draft Room": {"live_draft_state": blob}}  # captured by an older build
        pg_state.save_page_state(session, "Live Draft Room", store)
        block = store["Live Draft Room"]
        self.assertNotIn("live_draft_state", block)
        self.assertIn("live_draft_room", block)
        self.assertEqual(block["live_draft_timer"], "60 sec")

    def test_saved_size_drops_by_more_than_ninety_percent_for_shared(self) -> None:
        import json

        blob = _persisted_room_blob(rows=400)
        session, state = self._session_and_state(blob)
        before = len(json.dumps(state, default=str))
        after = len(json.dumps(self._enrich(session, state, shared=True), default=str))
        self.assertLess(after, before * 0.1)


class SharedPoolLessRestoreTests(_LocalSharedRoomCase):
    """A Shared room restored from a pool-less save gets its pool back from the room's pool sources."""

    def setUp(self) -> None:
        from unittest import mock

        super().setUp()
        pool_dir = Path(self._tmpdir.name) / "pools"
        pool_dir.mkdir()

        def _path(code: str):
            return pool_dir / f"{str(code).strip().upper()}.pkl"

        patcher = mock.patch("shared_draft_local_pool._local_pool_disk_path", side_effect=_path)
        patcher.start()
        self._patches.append(patcher)

    def test_restore_from_a_pool_less_save_rebuilds_the_same_pool(self) -> None:
        from draft_room_context import create_and_host_shared_room
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LIVE_DRAFT_ROOM_KEY
        from live_draft_state import copy_room_without_pool, room_from_persist_dict, room_to_persist_dict
        from shared_draft_local_pool import ensure_local_shared_player_pool

        blob = _persisted_room_blob()
        room = room_from_persist_dict(blob)
        host: dict = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        code, _ = create_and_host_shared_room(host, room, store=self.store)
        live = host[LIVE_DRAFT_ROOM_KEY]
        original = ensure_local_shared_player_pool(host, live)
        self.assertEqual(len(original), 6)

        saved = copy_room_without_pool(room_to_persist_dict(live))  # what the workspace now keeps
        restored = room_from_persist_dict(saved)
        self.assertEqual(len(restored["pool"]), 0)
        fresh: dict = {ACTIVE_SHARED_ROOM_CODE_KEY: code, "draft_room_participant_id": "host-user"}
        pool = ensure_local_shared_player_pool(fresh, restored)
        self.assertEqual(sorted(pool["playerID"]), sorted(original["playerID"]))
        self.assertEqual(restored["draft_board"], blob["draft_board"])
        self.assertEqual(restored["rosters"], blob["rosters"])


class RecommendationTeamContextTests(unittest.TestCase):
    """Decision Scores, needs and roster fit follow the team on the clock and move with the pick."""

    def test_scores_needs_and_fit_switch_to_the_next_team_after_a_pick(self) -> None:
        from live_draft_recommendation_context import build_live_draft_recommendation_context
        from live_draft_recommendations import live_draft_recommendations
        from live_draft_roster_slots import ensure_room_slot_config

        def player(pid, name, pos, value, rank):
            return {"playerID": pid, "fullName": name, "Primary Position": pos, "Eligible Positions": pos,
                    "Expected Fantasy Value": value, "Model Rank": rank, "Market Rank": rank,
                    "proj_HR": 20, "proj_R": 70, "proj_RBI": 70, "proj_SB": 5, "proj_BA": 0.26}

        pool = pd.DataFrame([
            player("c1", "Catcher One", "C", 60, 3), player("c2", "Catcher Two", "C", 55, 5),
            player("o1", "Outfield One", "OF", 62, 2), player("s1", "Short One", "SS", 58, 4),
        ])
        room = {
            "draft_room_id": "CTX1", "status": "in_progress", "current_pick_index": 1,
            "config": {"num_teams": 2, "your_team": "Team 1", "slots": {"C": 1, "OF": 1, "SS": 1}},
            "teams": ["Team 1", "Team 2"],
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 2"}, {"Pick": 2, "Round": 1, "Team": "Team 1"},
                           {"Pick": 3, "Round": 2, "Team": "Team 1"}, {"Pick": 4, "Round": 2, "Team": "Team 2"}],
            "draft_board": [{"Pick": 1, "Round": 1, "Team": "Team 2", "fullName": "Catcher Two", "playerID": "c2"}],
            "rosters": {"Team 1": [], "Team 2": [{"fullName": "Catcher Two", "playerID": "c2",
                                                  "Primary Position": "C", "Eligible Positions": "C"}]},
            "drafted_player_ids": ["c2"],
            "pool": pool,
        }
        ensure_room_slot_config(room)

        def snapshot():
            ctx = build_live_draft_recommendation_context(room, {}, team_override="Team 1")
            top = live_draft_recommendations(room, top_n=3, session={})[0]
            return ctx, dict(zip(top["fullName"], top["Decision Score"]))

        ctx, scores = snapshot()  # pick 2: Team 1 (empty roster) is on the clock
        self.assertEqual(ctx["team_on_clock"], "Team 1")
        self.assertEqual(ctx["team_roster"], [])
        self.assertIn("C", ctx["needed_positions"])
        self.assertIn("Catcher One", scores)

        room["current_pick_index"] = 3  # pick 4: Team 2 already has its catcher
        ctx2, scores2 = snapshot()
        self.assertEqual(ctx2["team_on_clock"], "Team 2")
        self.assertEqual([r["fullName"] for r in ctx2["team_roster"]], ["Catcher Two"])
        self.assertNotIn("C", ctx2["needed_positions"])
        self.assertNotIn("Catcher One", scores2)  # Team 1's catcher need does not leak across
        self.assertNotEqual(scores["Outfield One"], scores2["Outfield One"])  # recalculated for Team 2


class TimerLeaseRenewalCadenceTests(_SharedDraftCase):
    """The timer authority renews its lease at the heartbeat cadence, not on every tick."""

    def test_checks_within_the_heartbeat_do_not_rewrite_the_room_and_renewal_still_happens(self) -> None:
        from unittest import mock

        import live_draft_timer_authority as lta
        from draft_room_shared_state import invalidate_shared_room_document_cache

        code, host, _guest = self._start(first="Team 1", deadline_in=40)
        self.assertTrue(lta.multiparty_may_run_autopick(host))  # host takes the lease
        lease0 = float(self.store.load(code)["timer_authority"]["lease_expires_at"])

        writes: list[int] = []
        real_save = self.store.save_if_revision

        def counting_save(doc, *, expected_revision):
            writes.append(1)
            return real_save(doc, expected_revision=expected_revision)

        with mock.patch.object(self.store, "save_if_revision", side_effect=counting_save):
            for _ in range(5):  # five timer ticks inside the heartbeat interval
                invalidate_shared_room_document_cache(host, code)
                self.assertTrue(lta.multiparty_may_run_autopick(host))
            self.assertEqual(writes, [])
            real_now = lta._utc_now
            with mock.patch.object(lta, "_utc_now", lambda: real_now() + lta.TIMER_AUTHORITY_HEARTBEAT_SEC + 0.5):
                invalidate_shared_room_document_cache(host, code)
                self.assertTrue(lta.multiparty_may_run_autopick(host))
        self.assertEqual(len(writes), 1)
        self.assertGreater(float(self.store.load(code)["timer_authority"]["lease_expires_at"]), lease0)


class SharedOnClockBannerTickTests(unittest.TestCase):
    """The Shared banner lives in a run_every fragment, and a fragment rerun
    drops any element it does not emit again."""

    def test_every_tick_emits_banner_on_synced_deadline(self) -> None:
        import time
        from unittest import mock

        import live_draft_on_clock_ui as ui

        deadline = time.time() + 90
        room = {
            "status": "in_progress",
            "current_pick_index": 3,
            "timer_deadline": deadline,
            "config": {"timer_seconds": 120},
            "pick_order": [{"Team": t, "Round": 1 + i // 2, "Pick": i + 1} for i, t in enumerate("ABBAAB")],
            "draft_board": [{"Team": "A"}, {"Team": "B"}, {"Team": "B"}],
        }
        session: dict = {"live_draft_room": dict(room)}
        ticks: list = []
        st = mock.MagicMock()
        st.fragment = lambda **_kw: (lambda fn: ticks.append(fn) or fn)
        painted: list = []
        with mock.patch.object(ui, "_render_on_clock_banner_html", lambda *a, **k: painted.append((a, k))), \
                mock.patch("app_page_generation.fragment_allowed", return_value=True), \
                mock.patch("live_draft_safe_mode.timer_should_run", return_value=True), \
                mock.patch("live_draft_solo_timer.is_solo_live_draft", return_value=False), \
                mock.patch("live_draft_timer_ui._sync_room_on_timer_tick", return_value=(room, False)):
            ui.render_live_on_clock_banner(st, session, room, room["pick_order"][3])
            self.assertEqual(len(ticks), 1)
            # Between full runs the session's room alias can lag the room the
            # tick just synced (seen live: pick 0, no deadline).
            session["live_draft_room"] = {"status": "in_progress", "current_pick_index": 0}
            for _ in range(3):
                ticks[0]()
        # Initial tick plus one emission per later tick: none are skipped.
        self.assertEqual(len(painted), 4)
        for args, kw in painted:
            self.assertEqual(kw["pick_index"], 3)
            self.assertAlmostEqual(float(kw["deadline"]), deadline, places=3)
            self.assertEqual(args[1]["Team"], "A")
        # Same seed between repaints, so the markup (and the iframe) is unchanged.
        self.assertEqual(len({args[2] for args, _ in painted}), 1)


class SharedAutoPickTransactionTests(_SharedDraftCase):
    """The timer holder's auto-pick advances its own room before writing the shared room.
    Whatever stops it in between, the session must end up on the shared room and the
    expired pick must still be auto-picked exactly once (seen live: frozen at 0:00)."""

    def setUp(self) -> None:
        from unittest import mock

        super().setUp()
        patch = mock.patch("draft_room_context.get_shared_room_store", return_value=self.store)
        patch.start()
        self.addCleanup(patch.stop)

    def _next_run(self, seat: dict) -> None:
        from draft_room_context import poll_shared_draft_room, reset_shared_draft_sync_gate

        for _ in range(3):
            reset_shared_draft_sync_gate(seat)
            poll_shared_draft_room(seat, store=self.store)
            self._expire(seat)

    def _assert_one_auto_pick_and_in_step(self, code: str, host: dict) -> None:
        import time

        from live_draft_expired_pick import AUTOPICK_TXN_KEY

        doc = self.store.load(code)["room"]
        self.assertEqual([src for _n, src in self._board(code)], ["Auto Pick"])
        self.assertEqual(int(doc["current_pick_index"]), 1)
        self.assertGreater(float(doc["timer_deadline"]), time.time())
        live = host["live_draft_room"]
        self.assertEqual((int(live["current_pick_index"]), len(live["draft_board"])), (1, 1))
        self.assertIsNone(host.get(AUTOPICK_TXN_KEY))

    def test_rerun_between_local_apply_and_shared_write_is_undone(self) -> None:
        from unittest import mock

        from streamlit.runtime.scriptrunner_utils.exceptions import RerunException
        from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

        code, host, _guest = self._start(first="Team 1", deadline_in=-0.5)

        def rerun(*_a, **_k):
            raise RerunException(RerunData())

        with mock.patch("draft_room_context.commit_shared_room_state", rerun):
            with self.assertRaises(RerunException):
                self._expire(host, source="timer_fragment_zero")
        # The shared room never advanced, and the timer holder no longer believes it did.
        self.assertEqual(self._board(code), [])
        self.assertEqual(int(host["live_draft_room"]["current_pick_index"]), 0)
        self._next_run(host)
        self._assert_one_auto_pick_and_in_step(code, host)

    def test_shared_write_failing_quietly_leaves_no_phantom_pick(self) -> None:
        from unittest import mock

        import live_draft_expired_pick as lep

        code, host, _guest = self._start(first="Team 1", deadline_in=-0.5)
        with mock.patch("draft_room_context.commit_shared_room_state", return_value=(False, "store down", None)):
            result = self._expire(host)
        self.assertFalse(result.ok)
        self.assertEqual(self._board(code), [])
        self.assertEqual(int(host["live_draft_room"]["current_pick_index"]), 0)
        for key in (lep.AUTOPICK_BACKOFF_INDEX_KEY, lep.AUTOPICK_BACKOFF_UNTIL_KEY, lep.AUTOPICK_ATTEMPTED_INDEX_KEY):
            host.pop(key, None)  # the 1 s retry backoff has passed
        self._next_run(host)
        self._assert_one_auto_pick_and_in_step(code, host)

    def test_interruption_anywhere_in_the_attempt_still_auto_picks_once(self) -> None:
        import sys

        import live_draft_expired_pick as lep
        from streamlit.runtime.scriptrunner_utils.exceptions import RerunException
        from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

        target = lep.run_expired_autopick_once.__code__

        def run(host: dict, nth: int) -> int:
            st = {"inside": 0, "count": 0}

            def tracer(frame, event, _arg):
                if event == "call" and frame.f_code is target:
                    st["inside"] += 1
                if st["inside"]:
                    if event == "return" and frame.f_code is target:
                        st["inside"] -= 1
                    elif event == "line":
                        st["count"] += 1
                        if st["count"] == nth:
                            raise RerunException(RerunData())
                return tracer

            sys.settrace(tracer)
            try:
                self._expire(host, source="timer_fragment_zero")
            except RerunException:
                pass
            finally:
                sys.settrace(None)
            return st["count"]

        code, host, _guest = self._start(first="Team 1", deadline_in=-0.5)
        total = run(host, 10**9)
        self._assert_one_auto_pick_and_in_step(code, host)
        for nth in range(1, total, max(1, total // 12)):
            with self.subTest(interrupted_at_line=nth):
                code, host, _guest = self._start(first="Team 1", deadline_in=-0.5)
                run(host, nth)
                self._next_run(host)
                self._assert_one_auto_pick_and_in_step(code, host)

    def test_a_second_rerun_during_cleanup_cannot_freeze_the_pick(self) -> None:
        """Streamlit's session state is itself a stop point: with another rerun pending,
        the cleanup in ``finally`` was stopped too, the auto-pick lock stayed set, and
        every later expiry for that pick was refused (seen live: frozen at 0:00)."""
        import sys
        import time
        from unittest import mock

        import live_draft_expired_pick as lep
        from streamlit.runtime.scriptrunner_utils.exceptions import RerunException
        from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

        class StoppingSession(dict):
            armed = False

            def _stop(self):
                if self.armed:
                    self.armed = False
                    raise RerunException(RerunData())

            def get(self, *a, **k):
                self._stop(); return super().get(*a, **k)

            def __getitem__(self, k):
                self._stop(); return super().__getitem__(k)

            def __setitem__(self, k, v):
                self._stop(); return super().__setitem__(k, v)

            def pop(self, *a, **k):
                self._stop(); return super().pop(*a, **k)

        target = lep.run_expired_autopick_once.__code__

        def run(host, nth: int) -> int:
            st = {"inside": 0, "count": 0}

            def tracer(frame, event, _arg):
                if event == "call" and frame.f_code is target:
                    st["inside"] += 1
                if st["inside"]:
                    if event == "return" and frame.f_code is target:
                        st["inside"] -= 1
                    elif event == "line":
                        st["count"] += 1
                        if st["count"] == nth:
                            host.armed = True  # the cleanup's first session access stops too
                            raise RerunException(RerunData())
                return tracer

            sys.settrace(tracer)
            try:
                self._expire(host, source="timer_fragment_zero")
            except RerunException:
                pass
            finally:
                sys.settrace(None)
                host.armed = False
            return st["count"]

        with mock.patch.object(lep, "AUTOPICK_MARKER_STALE_SEC", 0.3):
            code, plain, _guest = self._start(first="Team 1", deadline_in=-0.5)
            total = run(StoppingSession(plain), 10**9)
            for nth in range(1, total, max(1, total // 10)):
                with self.subTest(interrupted_at_line=nth):
                    code, plain, _guest = self._start(first="Team 1", deadline_in=-0.5)
                    host = StoppingSession(plain)
                    run(host, nth)
                    time.sleep(0.35)  # a later tick, after the leftover lock or claim lapsed
                    self._next_run(host)
                    self._assert_one_auto_pick_and_in_step(code, host)

    def test_lock_left_by_a_stopped_attempt_lapses(self) -> None:
        import time

        import live_draft_expired_pick as lep

        session: dict = {lep.AUTOPICK_LOCK_KEY: time.time()}
        self.assertTrue(lep.autopick_lock_held(session))  # an attempt in progress still blocks
        session[lep.AUTOPICK_LOCK_KEY] = time.time() - lep.AUTOPICK_MARKER_STALE_SEC - 1
        self.assertFalse(lep.autopick_lock_held(session))
        self.assertNotIn(lep.AUTOPICK_LOCK_KEY, session)
        session[lep.AUTOPICK_LOCK_KEY] = True  # the pre-timestamp value can only be a leftover
        self.assertFalse(lep.autopick_lock_held(session))
        # A fresh lock from the previous pick (its attempt stopped while the other seat
        # committed that pick) must not hold off this pick's expiry.
        session.update({lep.AUTOPICK_LOCK_KEY: time.time(), lep.AUTOPICK_LOCK_PICK_KEY: 3})
        self.assertTrue(lep.autopick_lock_held(session, {"current_pick_index": 3}))
        self.assertFalse(lep.autopick_lock_held(session, {"current_pick_index": 4}))
        self.assertNotIn(lep.AUTOPICK_LOCK_KEY, session)

    def test_manual_pick_flag_past_its_guard_no_longer_holds_expiry(self) -> None:
        import time

        from draft_ui import MANUAL_PICK_IN_FLIGHT_IDX_KEY, manual_pick_holds_expiry

        room = {"status": "in_progress", "current_pick_index": 4, "timer_deadline": time.time() - 1}
        session = {"_live_draft_manual_pick_in_flight": True, MANUAL_PICK_IN_FLIGHT_IDX_KEY: 4,
                   "_live_draft_manual_pick_guard_until": time.time() + 10}
        self.assertTrue(manual_pick_holds_expiry(session, room))  # a pick still committing
        session["_live_draft_manual_pick_guard_until"] = time.time() - 1
        self.assertFalse(manual_pick_holds_expiry(session, room))  # left by a stopped run


if __name__ == "__main__":
    unittest.main()
