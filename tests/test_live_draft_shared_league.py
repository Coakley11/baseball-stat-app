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
    SHARED_LEAGUE_CONFIRM_CALLBACK_COUNT_KEY,
    SHARED_LEAGUE_CREATE_COMPLETED_KEY,
    SHARED_LEAGUE_CREATE_PROCESSING_KEY,
    SHARED_LEAGUE_CREATE_REQUEST_KEY,
    SHARED_LEAGUE_DIAG_KEY,
    SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY,
    on_confirm_live_draft_shared_league,
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


def _post_save_success_readback(**overrides: object) -> dict[str, object]:
    base = {
        "raw_archive_found": True,
        "visible_archive_found": True,
        "archive_draft_id_matches": True,
        "league_context_found": True,
        "canonical_league_id": "league:test",
        "active_context_matches": True,
        "disk_readback_found": True,
        "cloud_readback_found": True,
        "library_navigation_readback_found": True,
        "commissioner_recognized": True,
        "donny_ownership_recognized": True,
        "roster_counts": {"Daniel": 2, "Team 2": 2},
    }
    base.update(overrides)
    return base


def _post_save_success_tuple(**overrides: object):
    readback = _post_save_success_readback(**overrides)
    entry = {
        "draft_name": "Completed Live Draft",
        "canonical_league_id": readback.get("canonical_league_id") or "league:test",
        "draft_id": "live-two-team-test",
        "league_context_id": "ctx:test",
        "shared_league_created": True,
    }
    context = {"league_id": readback.get("canonical_league_id") or "league:test", "league_context_id": "ctx:test"}
    return True, [], readback, entry, context


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

    def button(self, label, *, on_click=None, kwargs=None, **_kwargs):
        if label in self.clicked:
            if callable(on_click):
                on_click(**(kwargs or {}))
            return True
        return False

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

    def text(self, value):
        self.markdowns.append(str(value))

    def warning(self, value):
        self.markdowns.append(str(value))

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
        self.assertIn("Save to Draft Library", DRAFT_COMPLETE_HUB_ACTIONS)
        self.assertIn("Set Active Draft", DRAFT_COMPLETE_HUB_ACTIONS)

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
        apply_live_draft_completion(self.room, {})
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
                {
                    "draft_name": "Completed Live Draft",
                    "canonical_league_id": "league:test",
                    "draft_id": "live-two-team-test",
                    "league_context_id": "ctx:test",
                    "shared_league_created": True,
                },
                {"league_id": "league:test", "league_context_id": "ctx:test"},
            )
        )
        with (
            patch.dict("sys.modules", {"draft_library_save_trace": self.trace_module}),
            patch("live_draft_shared_league.preview_shared_league_creation", return_value=self.preview),
            patch("live_draft_shared_league.save_live_draft_shared_league_context", save_mock),
            patch(
                "draft_archive_ui._post_save_shared_league_library",
                return_value=_post_save_success_tuple(),
            ),
            patch("draft_archive_ui._persist_archive", return_value=True),
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
                {
                    "draft_name": "Completed Live Draft",
                    "canonical_league_id": "league:test",
                    "draft_id": "live-two-team-test",
                    "league_context_id": "ctx:test",
                },
                {"league_id": "league:test", "league_context_id": "ctx:test"},
            )
        )
        import streamlit as st

        with patch.object(st, "session_state", self.session):
            self._render(
                _FakeStreamlit(
                    clicked={"Confirm Create Shared League"},
                    selected_team="Team 2",
                ),
                save_mock,
            )
        save_mock.assert_called_once()
        self.assertNotIn(SHARED_CONFIRM_OPEN_KEY, self.session)
        self.assertNotIn(SHARED_LEAGUE_CREATE_REQUEST_KEY, self.session)

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

    def _run_fixture(self, *, preview=None, save_mock=None, room=None, team="Daniel", use_robins=False, verify_mock=None):
        fixture = Path(__file__).resolve().parent / "fixtures" / "live_draft_shared_league_confirm_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["live_draft_test_room"] = room if room is not None else self.room
        at.session_state["live_draft_test_team"] = team
        at.session_state["live_draft_use_robins_fixture"] = bool(use_robins)
        preview_patch = patch(
            "live_draft_shared_league.preview_shared_league_creation",
            return_value=preview if preview is not None else self.preview,
        )
        save_patch = patch(
            "live_draft_shared_league.save_live_draft_shared_league_context",
            save_mock
            or Mock(
                return_value=(
                    {
                        "draft_name": "Completed Live Draft",
                        "canonical_league_id": "league:test",
                        "draft_id": "live-two-team-test",
                        "league_context_id": "ctx:test",
                        "shared_league_created": True,
                    },
                    {"league_id": "league:test", "league_context_id": "ctx:test"},
                )
            ),
        )
        verify_patch = patch(
            "draft_archive_ui._post_save_shared_league_library",
            verify_mock
            or Mock(return_value=_post_save_success_tuple()),
        )
        return at, preview_patch, save_patch, verify_patch

    def test_one_click_opens_confirmation_with_rosters(self) -> None:
        at, preview_patch, save_patch, verify_patch = self._run_fixture()
        with preview_patch, save_patch, verify_patch:
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
        at, preview_patch, save_patch, verify_patch = self._run_fixture()
        with preview_patch, save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.selectbox(key="live_draft_complete_shared_my_team").set_value("Team 2").run()
        self.assertTrue(at.session_state["_live_draft_shared_league_confirm_open"])
        blob = "\n".join(str(m.value) for m in at.markdown)
        self.assertIn("SHARED_LEAGUE_CONFIRM_OPEN:yes", blob, blob)

    def test_cancel_closes_confirmation(self) -> None:
        at, preview_patch, save_patch, verify_patch = self._run_fixture()
        with preview_patch, save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_cancel_shared_league").click().run()
        self.assertNotIn("_live_draft_shared_league_confirm_open", at.session_state)

    def test_confirm_saves_exactly_once(self) -> None:
        save_mock = Mock(
            return_value=(
                {
                    "draft_name": "Completed Live Draft",
                    "canonical_league_id": "league:test",
                    "draft_id": "live-two-team-test",
                    "league_context_id": "ctx:test",
                },
                {"league_id": "league:test", "league_context_id": "ctx:test"},
            )
        )
        at, preview_patch, save_patch, verify_patch = self._run_fixture(save_mock=save_mock)
        with preview_patch, save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        save_mock.assert_called_once()
        blob = "\n".join(str(m.value) for m in at.success) + "\n".join(str(m.value) for m in at.info) + "\n".join(str(m.value) for m in at.markdown)
        self.assertIn("Shared League Saved", blob, blob)
        self.assertNotIn("_live_draft_shared_league_confirm_open", at.session_state)
        diag = dict(at.session_state[SHARED_LEAGUE_DIAG_KEY])
        self.assertEqual(int(diag.get("save_call_count") or 0), 1)
        self.assertTrue(diag.get("confirmation_closed_after_success"))
        self.assertEqual(int(at.session_state[SHARED_LEAGUE_CONFIRM_CALLBACK_COUNT_KEY]), 1)

    def test_confirm_rerun_does_not_save_again(self) -> None:
        save_mock = Mock(
            return_value=(
                {
                    "draft_name": "Completed Live Draft",
                    "canonical_league_id": "league:test",
                    "draft_id": "live-two-team-test",
                    "league_context_id": "ctx:test",
                },
                {"league_id": "league:test", "league_context_id": "ctx:test"},
            )
        )
        at, preview_patch, save_patch, verify_patch = self._run_fixture(save_mock=save_mock)
        with preview_patch, save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
            at.run()
        save_mock.assert_called_once()

    def test_confirm_save_exception_stays_open_and_allows_retry(self) -> None:
        save_mock = Mock(side_effect=RuntimeError("save failed"))
        at, preview_patch, save_patch, verify_patch = self._run_fixture(save_mock=save_mock)
        with preview_patch, save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        blob = "\n".join(str(m.value) for m in at.error) + "\n".join(str(m.value) for m in at.success) + "\n".join(str(m.value) for m in at.info)
        self.assertIn("Could not create shared league: RuntimeError: save failed", blob, blob)
        self.assertTrue("_live_draft_shared_league_confirm_open" in at.session_state)
        save_mock.reset_mock()
        save_mock.side_effect = None
        save_mock.return_value = (
            {
                "draft_name": "Completed Live Draft",
                "canonical_league_id": "league:test",
                "draft_id": "live-two-team-test",
                "league_context_id": "ctx:test",
            },
            {"league_id": "league:test", "league_context_id": "ctx:test"},
        )
        with preview_patch, save_patch, verify_patch:
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        save_mock.assert_called_once()

    def test_confirm_recognizes_existing_canonical_league(self) -> None:
        save_mock = Mock()
        at, preview_patch, save_patch, verify_patch = self._run_fixture(save_mock=save_mock)
        record = self.room.get(COMPLETION_RECORD_KEY) or {}
        draft_id = str(record.get("draft_id") or self.room.get("draft_room_id") or "")
        draft_fp = str(record.get("draft_fingerprint") or "")
        request_id = "|".join([draft_id, draft_fp, "Daniel"])
        with preview_patch, save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.session_state[SHARED_LEAGUE_CREATE_COMPLETED_KEY] = {
                request_id: {
                    "request_id": request_id,
                    "draft_id": draft_id,
                    "context_id": "ctx:existing",
                    "canonical_league_id": "league:existing",
                    "my_team_name": "Daniel",
                }
            }
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        save_mock.assert_not_called()
        blob = "\n".join(str(m.value) for m in at.info) + "\n".join(str(m.value) for m in at.success)
        self.assertIn("already converted to shared league", blob, blob)
        self.assertNotIn("_live_draft_shared_league_confirm_open", at.session_state)

    def test_preview_exception_shows_visible_error(self) -> None:
        at, preview_patch, save_patch, verify_patch = self._run_fixture()

        def _boom(*_args, **_kwargs):
            raise RuntimeError("preview failed")

        with patch("live_draft_shared_league.preview_shared_league_creation", side_effect=_boom), save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
        blob = "\n".join(str(m.value) for m in at.error) + "\n".join(str(m.value) for m in at.info)
        self.assertIn("Shared league confirmation opened.", blob, blob)
        self.assertIn("Could not prepare shared league confirmation", blob, blob)
        self.assertIn("RuntimeError: preview failed", blob, blob)
        diag = dict(at.session_state[SHARED_LEAGUE_DIAG_KEY])
        self.assertTrue(diag.get("preview_call_started"))
        self.assertFalse(diag.get("preview_call_completed"))
        self.assertFalse(diag.get("create_processor_entered"))


class LiveDraftSharedLeagueCreateRecoveryAppTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_stale_boolean_lock_self_recovers_and_saves_once(self) -> None:
        save_mock = Mock(
            return_value=(
                {
                    "draft_name": "Completed Live Draft",
                    "canonical_league_id": "league:test",
                    "draft_id": "live-two-team-test",
                    "league_context_id": "ctx:test",
                    "shared_league_created": True,
                },
                {"league_id": "league:test", "league_context_id": "ctx:test"},
            )
        )
        fixture = Path(__file__).resolve().parent / "fixtures" / "live_draft_shared_league_confirm_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["live_draft_test_room"] = self.room
        at.session_state["live_draft_test_team"] = "Daniel"
        with (
            patch("live_draft_shared_league.save_live_draft_shared_league_context", save_mock),
            patch(
                "draft_archive_ui._post_save_shared_league_library",
                return_value=_post_save_success_tuple(),
            ),
        ):
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.session_state[SHARED_LEAGUE_CREATE_PROCESSING_KEY] = True
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        save_mock.assert_called_once()
        blob = "\n".join(str(m.value) for m in at.warning) + "\n".join(str(m.value) for m in at.success)
        self.assertIn("interrupted", blob.lower(), blob)
        diag = dict(at.session_state[SHARED_LEAGUE_DIAG_KEY])
        self.assertFalse(diag.get("processing_lock_present"))
        self.assertEqual(int(diag.get("save_call_count") or 0), 1)

    def test_persistence_readback_failure_keeps_confirmation_open(self) -> None:
        save_mock = Mock(
            return_value=(
                {
                    "draft_name": "Completed Live Draft",
                    "canonical_league_id": "league:test",
                    "draft_id": "live-two-team-test",
                    "league_context_id": "ctx:test",
                    "shared_league_created": True,
                },
                {"league_id": "league:test", "league_context_id": "ctx:test"},
            )
        )
        fixture = Path(__file__).resolve().parent / "fixtures" / "live_draft_shared_league_confirm_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["live_draft_test_room"] = self.room
        at.session_state["live_draft_test_team"] = "Daniel"
        with (
            patch("live_draft_shared_league.save_live_draft_shared_league_context", save_mock),
            patch(
                "draft_archive_ui._post_save_shared_league_library",
                return_value=(
                    False,
                    ["Shared league creation did not persist to the Draft Library."],
                    {"raw_archive_found": False, "visible_archive_found": False},
                    {},
                    {},
                ),
            ),
        ):
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        save_mock.assert_called_once()
        blob = "\n".join(str(m.value) for m in at.error)
        self.assertIn("did not persist to the Draft Library", blob, blob)
        self.assertTrue("_live_draft_shared_league_confirm_open" in at.session_state)
        req = at.session_state[SHARED_LEAGUE_CREATE_REQUEST_KEY]
        self.assertEqual(str((req or {}).get("status") or ""), "failed")


class LiveDraftRobinsFantasyConfirmAppTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_robins_confirm_creates_league_with_ten_player_rosters(self) -> None:
        from tests.test_live_draft_team_identity import _live_robins_fantasy_room

        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, {})
        save_mock = Mock(
            return_value=(
                {
                    "draft_name": "Robins Fantasy Completed Draft",
                    "canonical_league_id": "league:robins",
                    "draft_id": str(room.get("draft_room_id") or ""),
                    "league_context_id": "ctx:robins",
                },
                {"league_id": "league:robins", "league_context_id": "ctx:robins"},
            )
        )
        fixture = Path(__file__).resolve().parent / "fixtures" / "live_draft_shared_league_confirm_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["live_draft_use_robins_fixture"] = True
        at.session_state["live_draft_test_team"] = "Donny"
        save_patch = patch(
            "live_draft_shared_league.save_live_draft_shared_league_context",
            save_mock,
        )
        verify_patch = patch(
            "draft_archive_ui._post_save_shared_league_library",
            return_value=_post_save_success_tuple(
                canonical_league_id="league:robins",
                roster_counts={"Donny": 10, "Team B": 10},
            ),
        )
        with save_patch, verify_patch:
            at.run()
            at.button(key="live_draft_complete_shared_league_btn").click().run()
            at.button(key="live_draft_complete_confirm_shared_league").click().run()
        save_mock.assert_called_once()
        kwargs = save_mock.call_args.kwargs
        self.assertEqual(kwargs.get("my_team_name"), "Donny")
        blob = "\n".join(str(m.value) for m in at.markdown) + "\n".join(str(m.value) for m in at.success) + "\n".join(str(m.value) for m in at.info)
        self.assertIn("SHARED_LEAGUE_CREATE_PROCESSOR:yes", blob, blob)
        self.assertIn("SHARED_LEAGUE_SAVE_CALL_COUNT:1", blob, blob)
        self.assertIn("SHARED_LEAGUE_CONFIRM_CLOSED:yes", blob, blob)
        self.assertIn("Shared League Saved", blob, blob)
        self.assertIn("Donny 10", blob, blob)
        self.assertIn("Team B 10", blob, blob)
        self.assertNotIn("_live_draft_shared_league_confirm_open", at.session_state)
        self.assertEqual(int(at.session_state[SHARED_LEAGUE_CONFIRM_CALLBACK_COUNT_KEY]), 1)
        req = at.session_state[SHARED_LEAGUE_CREATE_REQUEST_KEY] if SHARED_LEAGUE_CREATE_REQUEST_KEY in at.session_state else None
        self.assertTrue(req is None or str((req or {}).get("status") or "") != "pending")
        diag = dict(at.session_state[SHARED_LEAGUE_DIAG_KEY])
        self.assertTrue(diag.get("preview_validation_ok"))
        self.assertEqual(int(diag.get("save_call_count") or 0), 1)


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


class LiveDraftSharedLeagueLibraryPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.session: dict = {}

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_commissioner_archive_visible_after_persist_and_prune(self) -> None:
        from draft_archive_ui import _persist_shared_league_library_entry, _verify_shared_league_persistence
        from draft_archive_state import get_draft_archive, list_draft_archives
        from draft_archive_visibility import list_visible_draft_archives, prune_invisible_shared_league_state
        from tests.test_live_draft_team_identity import _live_robins_fantasy_room

        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, self.session)
        with _as_user("user:daniel"):
            entry, context = save_live_draft_shared_league_context(
                self.session,
                room,
                my_team_name="Donny",
                league_name="Robins Fantasy",
                draft_name="Robins Fantasy Completed Draft",
                assign_team=True,
                preassign_owners={
                    "Donny": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"},
                },
            )
            draft_id = str(entry.get("draft_id") or "")
            context_id = str(context.get("league_context_id") or "")
            canonical_id = str(entry.get("canonical_league_id") or context.get("league_id") or "")
            with patch("draft_archive_ui._persist_archive", return_value=True):
                persist_ok, _readback = _persist_shared_league_library_entry(
                    SimpleNamespace(session_state=self.session),
                    self.session,
                    entry,
                    context,
                    my_team="Donny",
                )
            from draft_archive_state import set_active_draft_archive

            set_active_draft_archive(self.session, draft_id)
            from fantasy_league_context import activate_league_context

            activate_league_context(self.session, context_id)
            self.assertTrue(persist_ok)
            ok, errors, verify = _verify_shared_league_persistence(
                self.session,
                draft_id=draft_id,
                context_id=context_id,
                my_team="Donny",
                expected_counts={"Donny": 10, "Team B": 10},
                entry=entry,
            )
            self.assertTrue(ok, errors)
            self.assertEqual(len(list_draft_archives(self.session)), 1)
            visible = list_visible_draft_archives(self.session)
            self.assertEqual(len(visible), 1)
            self.assertEqual(str(visible[0].get("draft_id") or ""), draft_id)
            removed = prune_invisible_shared_league_state(dict(self.session))
            self.assertEqual(int(removed.get("archives_removed") or 0), 0)
            self.assertEqual(len(list_visible_draft_archives(self.session)), 1)
            self.assertTrue(verify.get("commissioner_recognized"))
            self.assertTrue(verify.get("donny_ownership_recognized"))
            self.assertEqual(str(verify.get("canonical_league_id") or ""), canonical_id)

    def test_existing_league_recovery_does_not_duplicate(self) -> None:
        from draft_archive_ui import _find_existing_live_draft_shared_league, _repair_shared_league_library_entry
        from draft_archive_state import list_draft_archives
        from tests.test_live_draft_team_identity import _live_robins_fantasy_room

        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, self.session)
        with _as_user("user:daniel"):
            entry, context = save_live_draft_shared_league_context(
                self.session,
                room,
                my_team_name="Donny",
                league_name="Robins Fantasy",
                assign_team=True,
                preassign_owners={"Donny": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"}},
            )
            draft_id = str(entry.get("draft_id") or "")
            canonical_id = str(entry.get("canonical_league_id") or "")
            context_id = str(context.get("league_context_id") or "")
            record = room.get(COMPLETION_RECORD_KEY) or {}
            fp = str(record.get("draft_fingerprint") or "")
            existing = _find_existing_live_draft_shared_league(
                self.session,
                request_id="rid",
                draft_id=draft_id,
                draft_fingerprint=fp,
                canonical_league_id=canonical_id,
            )
            self.assertIsNotNone(existing, msg=f"draft_id={draft_id!r} canonical={canonical_id!r}")
            with patch("draft_archive_ui._persist_archive", return_value=True):
                _entry2, _ctx2, repair_ok, _meta = _repair_shared_league_library_entry(
                    SimpleNamespace(session_state=self.session),
                    self.session,
                    draft_id=draft_id,
                    context_id=context_id,
                    canonical_league_id=canonical_id,
                    my_team="Donny",
                )
            self.assertTrue(repair_ok)
            self.assertEqual(len(list_draft_archives(self.session)), 1)

    def test_invitee_sees_league_only_with_valid_membership(self) -> None:
        from draft_archive_visibility import list_visible_draft_archives
        from fantasy_league_context import upsert_league_context
        from tests.test_live_draft_team_identity import _live_robins_fantasy_room

        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, self.session)
        with _as_user("user:daniel"):
            _entry, context = save_live_draft_shared_league_context(
                self.session,
                room,
                my_team_name="Donny",
                league_name="Robins Fantasy",
                assign_team=True,
                preassign_owners={
                    "Donny": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"},
                    "Team B": {"user_id": "user:teamb", "email": "teamb@test", "display_name": "Team B Owner"},
                },
            )
        coakley = dict(self.session)
        coakley["_suite_cloud_user_id"] = "user:coakley"
        coakley["_suite_auth_user_id"] = "user:coakley"
        with _as_user("user:coakley"):
            self.assertEqual(len(list_visible_draft_archives(coakley)), 0)
        loaded = get_league_context(self.session, str(context.get("league_context_id") or "")) or context
        loaded = assign_team_owner_to_context(
            loaded,
            "Team B",
            user_id="user:coakley",
            email="coakley@test",
            display_name="Coakley",
        )
        meta = dict(loaded.get("metadata") or {})
        meta["joined_via_invite"] = True
        loaded["metadata"] = meta
        upsert_league_context(self.session, loaded)
        coakley["draft_archive_teams"] = list(self.session.get("draft_archive_teams") or [])
        coakley["fantasy_league_context_state"] = dict(self.session.get("fantasy_league_context_state") or {})
        with _as_user("user:coakley"):
            self.assertEqual(len(list_visible_draft_archives(coakley)), 1)


if __name__ == "__main__":
    unittest.main()
