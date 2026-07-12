"""Tests for Live Draft → shared league workflow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from draft_archive_ui import (
    SHARED_CONFIRM_OPEN_KEY,
    SHARED_LEAGUE_DIAG_KEY,
    SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY,
    on_open_live_draft_shared_league_confirmation,
    render_live_draft_completion_panel,
)
from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, get_league_context
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import (
    TRADES_AWAITING_CLAIMS_MESSAGE,
    assign_team_owner_to_context,
    get_team_ownership,
    owned_team_for_user,
    trades_enabled,
    upsert_league_context,
)
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from live_draft_completion import COMPLETION_RECORD_KEY, apply_live_draft_completion, is_live_draft_explicitly_complete
from live_draft_completion import DRAFT_COMPLETE_HUB_ACTIONS
from live_draft_roster_transfer import (
    build_authoritative_live_draft_rosters,
    extract_draft_results_from_room,
    validate_roster_transfer,
)
from live_draft_shared_league import preview_shared_league_creation, save_live_draft_shared_league_context
from tests.test_imported_shared_league import _as_user


class _RerunSignal(Exception):
    pass


class _FakeStreamlit:
    def __init__(self, *, clicked: set[str] | None = None, selected_team: str = "Daniel") -> None:
        self.clicked = set(clicked or set())
        self.selected_team = selected_team
        self.markdowns: list[str] = []
        self.dataframes: list[pd.DataFrame] = []
        self.errors: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def columns(self, count):
        return [self for _ in range(int(count))]

    def expander(self, *_args, **_kwargs):
        return self

    def button(self, label, **_kwargs):
        return label in self.clicked

    def text_input(self, _label, *, value="", **_kwargs):
        return value

    def selectbox(self, _label, options, **_kwargs):
        return self.selected_team if self.selected_team in options else options[0]

    def markdown(self, value, **_kwargs):
        self.markdowns.append(str(value))

    def dataframe(self, value, **_kwargs):
        self.dataframes.append(value)

    def error(self, value):
        self.errors.append(str(value))

    def warning(self, _value):
        pass

    def info(self, value):
        self.markdowns.append(str(value))

    def success(self, value):
        self.markdowns.append(str(value))

    def caption(self, _value):
        pass

    def download_button(self, *_args, **_kwargs):
        return False

    def rerun(self):
        raise _RerunSignal()


def _completed_two_team_room() -> dict:
    board = [
        {"Pick": 1, "Round": 1, "Team": "Daniel", "playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
        {"Pick": 2, "Round": 1, "Team": "Team 2", "playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
        {"Pick": 3, "Round": 2, "Team": "Team 2", "playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS"},
        {"Pick": 4, "Round": 2, "Team": "Daniel", "playerID": "p4", "fullName": "Mookie Betts", "Primary Position": "OF"},
    ]
    rosters = {
        "Daniel": [
            {"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "p4", "fullName": "Mookie Betts", "Primary Position": "OF"},
        ],
        "Team 2": [
            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS"},
        ],
    }
    return {
        "draft_room_id": "live-two-team-test",
        "status": "complete",
        "current_pick_index": 4,
        "teams": ["Daniel", "Team 2"],
        "config": {
            "league_name": "Two Team Live Draft",
            "num_teams": 2,
            "picks_per_team": 2,
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 5, "BN": 3},
        },
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Daniel"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
            {"Pick": 3, "Round": 2, "Team": "Team 2"},
            {"Pick": 4, "Round": 2, "Team": "Daniel"},
        ],
        "draft_board": board,
        "rosters": rosters,
        "drafted_player_ids": ["p1", "p2", "p3", "p4"],
        "pool": [],
    }


class LiveDraftRosterTransferTests(unittest.TestCase):
    def test_extract_draft_results_preserves_every_pick(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]["team"], "Daniel")
        self.assertEqual(results[0]["player_name"], "Juan Soto")
        self.assertEqual(results[1]["team"], "Team 2")

    def test_validate_roster_transfer_passes_for_completed_board(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        _, league_rosters, errors = build_authoritative_live_draft_rosters(room, my_team_name="Daniel")
        self.assertEqual(errors, [])
        ok, validation_errors = validate_roster_transfer(room, results, league_rosters)
        self.assertTrue(ok)
        self.assertEqual(validation_errors, [])

    def test_validate_roster_transfer_blocks_mismatch(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        _, league_rosters, _ = build_authoritative_live_draft_rosters(room, my_team_name="Daniel")
        league_rosters["Daniel"]["players"] = []
        ok, errors = validate_roster_transfer(room, results, league_rosters)
        self.assertFalse(ok)
        self.assertTrue(any("missing drafted players" in e for e in errors))


class LiveDraftCompletionTests(unittest.TestCase):
    def test_apply_completion_sets_locked_record(self) -> None:
        room = _completed_two_team_room()
        session: dict = {}
        apply_live_draft_completion(room, session)
        self.assertTrue(is_live_draft_explicitly_complete(room))
        record = room.get(COMPLETION_RECORD_KEY) or {}
        self.assertEqual(record.get("draft_status"), "complete")
        self.assertTrue(record.get("final_board_locked"))
        self.assertIsNone(room.get("timer_started_at"))

    def test_draft_complete_hub_actions(self) -> None:
        self.assertIn("Create Shared League", DRAFT_COMPLETE_HUB_ACTIONS)
        self.assertIn("Review Draft Results", DRAFT_COMPLETE_HUB_ACTIONS)
        self.assertNotIn("Set Active Draft", DRAFT_COMPLETE_HUB_ACTIONS)

    def test_repeated_completion_preserves_record_identity_and_timestamp(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, {})
        first = dict(room.get(COMPLETION_RECORD_KEY) or {})
        apply_live_draft_completion(room, {})
        second = dict(room.get(COMPLETION_RECORD_KEY) or {})
        for field in (
            "completed_at",
            "draft_id",
            "draft_fingerprint",
            "final_pick_number",
            "final_board_locked",
        ):
            self.assertEqual(first.get(field), second.get(field), field)


class LiveDraftCompletionPanelLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = _completed_two_team_room()
        self.session: dict = {}
        self.preview = {
            "ready": True,
            "validation_errors": [],
            "league_name": "Two Team Live Draft",
            "canonical_league_id": "league:test",
            "draft_id": "live-two-team-test",
            "draft_fingerprint": "fingerprint",
            "teams": ["Daniel", "Team 2"],
            "trade_eligibility_status": "disabled",
            "roster_count_by_team": {"Daniel": 2, "Team 2": 2},
            "final_rosters": {
                "Daniel": {"players": [{"player_name": "Juan Soto"}, {"player_name": "Mookie Betts"}]},
                "Team 2": {"players": [{"player_name": "Aaron Judge"}, {"player_name": "Gunnar Henderson"}]},
            },
            "roster_slots": {"OF": 2},
            "scoring_settings": {"scoring_type": "Roto (5x5)"},
        }
        self.trace_module = SimpleNamespace(render_save_trace_inline=lambda *_args, **_kwargs: None)

    def _render(self, st: _FakeStreamlit, save_mock: Mock | None = None) -> None:
        save_mock = save_mock or Mock(
            return_value=(
                {"draft_name": "Completed Live Draft", "canonical_league_id": "league:test"},
                {"league_id": "league:test"},
            )
        )
        with (
            patch.dict("sys.modules", {"draft_library_save_trace": self.trace_module}),
            patch("live_draft_shared_league.preview_shared_league_creation", return_value=self.preview),
            patch("live_draft_shared_league.save_live_draft_shared_league_context", save_mock),
        ):
            render_live_draft_completion_panel(
                st,
                self.session,
                self.room,
                team_name="Daniel",
                board_df_fn=lambda room: pd.DataFrame(room["draft_board"]),
            )

    def test_create_confirmation_persists_across_reruns_and_closes_after_success(self) -> None:
        import streamlit as st

        apply_live_draft_completion(self.room, self.session)
        record = self.room.get(COMPLETION_RECORD_KEY) or {}
        with patch.object(st, "session_state", self.session):
            on_open_live_draft_shared_league_confirmation(
                key_prefix="live_draft_complete",
                draft_id=str(record.get("draft_id") or self.room.get("draft_room_id") or ""),
                draft_fingerprint=str(record.get("draft_fingerprint") or ""),
            )
        self._render(_FakeStreamlit())
        self.assertTrue(self.session.get(SHARED_CONFIRM_OPEN_KEY))

        self._render(_FakeStreamlit(selected_team="Team 2"))
        self.assertTrue(self.session.get(SHARED_CONFIRM_OPEN_KEY))

        save_mock = Mock(
            return_value=(
                {"draft_name": "Completed Live Draft", "canonical_league_id": "league:test"},
                {"league_id": "league:test"},
            )
        )
        with self.assertRaises(_RerunSignal):
            self._render(
                _FakeStreamlit(
                    clicked={"Confirm Create Shared League"},
                    selected_team="Team 2",
                ),
                save_mock,
            )
        save_mock.assert_called_once()
        self.assertNotIn(SHARED_CONFIRM_OPEN_KEY, self.session)

    def test_cancel_closes_confirmation(self) -> None:
        self.session[SHARED_CONFIRM_OPEN_KEY] = True
        with self.assertRaises(_RerunSignal):
            self._render(_FakeStreamlit(clicked={"Cancel"}))
        self.assertNotIn(SHARED_CONFIRM_OPEN_KEY, self.session)

    def test_review_renders_board_and_roster_counts_without_importing_entrypoint(self) -> None:
        st = _FakeStreamlit(clicked={"Review Draft Results"})
        real_import = __import__
        imported_entrypoint = []

        def guarded_import(name, *args, **kwargs):
            if name.lower() == "streamlit_app":
                imported_entrypoint.append(name)
                raise AssertionError("draft_archive_ui must not import streamlit_app")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            self._render(st)

        self.assertEqual(imported_entrypoint, [])
        self.assertEqual(len(st.dataframes), 1)
        self.assertTrue(any("**Daniel** — 2 players" in line for line in st.markdowns))
        self.assertTrue(any("**Team 2** — 2 players" in line for line in st.markdowns))


class LiveDraftSharedLeagueAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:
            raise unittest.SkipTest(f"streamlit.testing.v1.AppTest unavailable: {exc}") from exc
        cls.AppTest = AppTest

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.room = _completed_two_team_room()
        apply_live_draft_completion(self.room, {})
        self.preview = {
            "ready": True,
            "validation_errors": [],
            "league_name": "Two Team Live Draft",
            "canonical_league_id": "league:test",
            "draft_id": "live-two-team-test",
            "draft_fingerprint": "fingerprint",
            "teams": ["Daniel", "Team 2"],
            "trade_eligibility_status": "disabled",
            "roster_count_by_team": {"Daniel": 2, "Team 2": 2},
            "final_rosters": {
                "Daniel": {"players": [{"player_name": "Juan Soto"}, {"player_name": "Mookie Betts"}]},
                "Team 2": {"players": [{"player_name": "Aaron Judge"}, {"player_name": "Gunnar Henderson"}]},
            },
            "roster_slots": {"OF": 2},
            "scoring_settings": {"scoring_type": "Roto (5x5)"},
        }

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def _run_fixture(self, *, preview=None, save_mock=None):
        fixture = Path(__file__).resolve().parent / "fixtures" / "live_draft_shared_league_confirm_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["live_draft_test_room"] = self.room
        at.session_state["live_draft_test_team"] = "Daniel"
        preview_patch = patch(
            "live_draft_shared_league.preview_shared_league_creation",
            return_value=preview if preview is not None else self.preview,
        )
        save_patch = patch(
            "live_draft_shared_league.save_live_draft_shared_league_context",
            save_mock
            or Mock(
                return_value=(
                    {"draft_name": "Completed Live Draft", "canonical_league_id": "league:test"},
                    {"league_id": "league:test"},
                )
            ),
        )
        return at, preview_patch, save_patch

    def test_one_click_opens_confirmation_with_rosters(self) -> None:
        at, preview_patch, save_patch = self._run_fixture()
        with preview_patch, save_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
        blob = "\n".join(str(m.value) for m in at.markdown) + "\n".join(str(m.value) for m in at.info)
        self.assertIn("SHARED_LEAGUE_CONFIRM_OPEN:yes", blob, blob)
        self.assertIn("SHARED_LEAGUE_CONFIRM_RENDERED:yes", blob, blob)
        self.assertIn("Shared league confirmation opened.", blob, blob)
        self.assertIn("Daniel: 2", blob, blob)
        self.assertIn("Team 2: 2", blob, blob)
        self.assertTrue(at.session_state["_live_draft_shared_league_confirm_open"])
        self.assertEqual(int(at.session_state[SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY]), 1)
        diag = dict(at.session_state[SHARED_LEAGUE_DIAG_KEY])
        self.assertTrue(diag.get("confirmation_render_entered"))
        self.assertTrue(diag.get("preview_call_completed"))

    def test_team_selector_rerun_keeps_confirmation_open(self) -> None:
        at, preview_patch, save_patch = self._run_fixture()
        with preview_patch, save_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.selectbox(key="live_draft_complete_shared_my_team").set_value("Team 2").run()
        self.assertTrue(at.session_state["_live_draft_shared_league_confirm_open"])
        blob = "\n".join(str(m.value) for m in at.markdown)
        self.assertIn("SHARED_LEAGUE_CONFIRM_OPEN:yes", blob, blob)

    def test_cancel_closes_confirmation(self) -> None:
        at, preview_patch, save_patch = self._run_fixture()
        with preview_patch, save_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_cancel_shared_league").click().run()
        self.assertNotIn("_live_draft_shared_league_confirm_open", at.session_state)

    def test_confirm_saves_exactly_once(self) -> None:
        save_mock = Mock(
            return_value=(
                {"draft_name": "Completed Live Draft", "canonical_league_id": "league:test"},
                {"league_id": "league:test"},
            )
        )
        at, preview_patch, save_patch = self._run_fixture(save_mock=save_mock)
        with preview_patch, save_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        save_mock.assert_called_once()
        blob = "\n".join(str(m.value) for m in at.success)
        self.assertIn("Shared league created", blob, blob)

    def test_preview_exception_shows_visible_error(self) -> None:
        at, preview_patch, save_patch = self._run_fixture()

        def _boom(*_args, **_kwargs):
            raise RuntimeError("preview failed")

        with patch("live_draft_shared_league.preview_shared_league_creation", side_effect=_boom), save_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
        blob = "\n".join(str(m.value) for m in at.error) + "\n".join(str(m.value) for m in at.info)
        self.assertIn("Shared league confirmation opened.", blob, blob)
        self.assertIn("Could not prepare shared league confirmation", blob, blob)
        self.assertIn("RuntimeError: preview failed", blob, blob)
        diag = dict(at.session_state[SHARED_LEAGUE_DIAG_KEY])
        self.assertTrue(diag.get("preview_call_started"))
        self.assertFalse(diag.get("preview_call_completed"))
        self.assertFalse(diag.get("claim_attempted"))


class LiveDraftSharedLeagueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.session: dict = {}

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_preview_includes_exact_rosters(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, {})
        preview = preview_shared_league_creation(room, my_team_name="Daniel", league_name="Daniel vs Team 2")
        self.assertTrue(preview.get("ready"))
        self.assertEqual(set((preview.get("roster_count_by_team") or {}).keys()), {"Daniel", "Team 2"})
        daniel_players = [
            str(p.get("player_name") or "")
            for p in (preview.get("final_rosters") or {}).get("Daniel", {}).get("players") or []
        ]
        self.assertIn("Juan Soto", daniel_players)
        self.assertIn("Mookie Betts", daniel_players)

    def test_save_creates_real_league_with_canonical_id(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        entry, context = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Daniel vs Team 2",
            draft_name="Completed Live Draft",
            assign_team=True,
            preassign_owners={
                "Daniel": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"},
            },
        )
        self.assertEqual(context.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)
        self.assertTrue(resolve_canonical_league_id(context))
        self.assertEqual(entry.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)
        meta = context.get("metadata") or {}
        self.assertEqual(meta.get("created_from"), "live_draft")
        self.assertEqual(len(meta.get("draft_results") or context.get("draft_results") or []), 4)

    def test_one_owner_blocks_trades_second_owner_enables(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        _entry, context = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Trade Gate League",
            assign_team=True,
            preassign_owners={
                "Daniel": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"},
            },
        )
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(self.session, league_context_id) or context
        with _as_user("user:daniel"):
            enabled, msg = trades_enabled(loaded, self.session)
        self.assertFalse(enabled)
        self.assertEqual(msg, TRADES_AWAITING_CLAIMS_MESSAGE)

        loaded = assign_team_owner_to_context(
            loaded,
            "Team 2",
            user_id="user:coakley11",
            email="coakley11@test",
            display_name="Team 2 Owner",
        )
        upsert_league_context(self.session, loaded)
        with _as_user("user:daniel"):
            enabled, _msg = trades_enabled(loaded, self.session)
        self.assertTrue(enabled)
        ownership = get_team_ownership(loaded)
        self.assertIn("Daniel", ownership)
        self.assertIn("Team 2", ownership)
        with _as_user("user:daniel"):
            self.assertEqual(owned_team_for_user(loaded), "Daniel")
        with _as_user("user:coakley11"):
            self.assertEqual(owned_team_for_user(loaded), "Team 2")

    def test_exact_roster_transfer_chain_matches_board(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        _, league_rosters, errors = build_authoritative_live_draft_rosters(room, my_team_name="Daniel")
        self.assertEqual(errors, [])
        board_names = {str(r["player_name"]) for r in results}
        roster_names = {
            str(p.get("player_name") or "")
            for entry in league_rosters.values()
            for p in (entry.get("players") or [])
            if str(p.get("player_name") or "").strip()
        }
        self.assertEqual(board_names, roster_names)
        self.assertEqual(len(results), sum(len((e or {}).get("players") or []) for e in league_rosters.values()))

    def test_identical_live_draft_reuses_canonical_league_id(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        _entry_a, ctx_a = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Canonical Live League",
            assign_team=True,
            preassign_owners={"Daniel": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"}},
        )
        _entry_b, ctx_b = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Team 2",
            league_name="Canonical Live League copy",
            assign_team=True,
            preassign_owners={"Team 2": {"user_id": "user:coakley11", "email": "coakley11@test", "display_name": "Team 2"}},
        )
        self.assertEqual(resolve_canonical_league_id(ctx_a), resolve_canonical_league_id(ctx_b))

    def test_changed_roster_changes_canonical_league_id(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        _entry_a, ctx_a = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Canonical A",
            assign_team=False,
        )
        mutated = dict(room)
        mutated_board = list(room["draft_board"])
        mutated_board[0] = dict(mutated_board[0])
        mutated_board[0]["fullName"] = "Different Player"
        mutated_board[0]["playerID"] = "px"
        mutated["draft_board"] = mutated_board
        mutated["rosters"] = dict(room["rosters"])
        mutated["rosters"]["Daniel"] = [
            {"playerID": "px", "fullName": "Different Player", "Primary Position": "OF"},
            {"playerID": "p4", "fullName": "Mookie Betts", "Primary Position": "OF"},
        ]
        apply_live_draft_completion(mutated, self.session)
        _entry_b, ctx_b = save_live_draft_shared_league_context(
            self.session,
            mutated,
            my_team_name="Daniel",
            league_name="Canonical B",
            assign_team=False,
        )
        self.assertNotEqual(resolve_canonical_league_id(ctx_a), resolve_canonical_league_id(ctx_b))

    def test_completion_blocks_additional_pick_gate(self) -> None:
        from draft_actions import resolve_player_draft_gate

        room = _completed_two_team_room()
        session = {"live_draft_room": apply_live_draft_completion(room, {})}
        gate = resolve_player_draft_gate(session, "Free Agent")
        self.assertTrue(gate.get("draft_complete"))
        self.assertEqual(gate.get("disable_reason"), "draft_complete")

    def test_preview_does_not_create_shared_league(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        preview = preview_shared_league_creation(room, my_team_name="Daniel")
        self.assertTrue(preview.get("ready"))
        self.assertIsNone(get_league_context(self.session, str(preview.get("canonical_league_id") or "")))


if __name__ == "__main__":
    unittest.main()
