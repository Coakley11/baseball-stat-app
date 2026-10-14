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


class SharedExpiryBoundaryTests(_LocalSharedRoomCase):
    """Auto-pick only after the canonical deadline; a leftover expiry flag never steals a pick."""

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

        for left in (15, 5, 2.5):
            with self.subTest(seconds_left=left):
                code, host, _guest = self._start(first="Team 2", deadline_in=left)
                for _ in range(3):  # reruns near the deadline
                    host[EXPIRED_PICK_PENDING_KEY] = True
                    self.assertFalse(self._expire(host).ok)
                self.assertEqual(self._board(code), [])
                self.assertAlmostEqual(
                    float(self.store.load(code)["room"]["timer_deadline"]) - __import__("time").time(), left, delta=1.5
                )

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
            self._expire(host, source="timer_fragment_zero")
        self.assertEqual(raced, [True])
        self.assertEqual(self._board(code), [("Bobby Witt", "Live Draft Pick")])
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


if __name__ == "__main__":
    unittest.main()
