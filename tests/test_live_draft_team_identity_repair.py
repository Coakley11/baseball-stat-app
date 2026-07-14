"""Team identity + shared-league library repair for Live Draft participants."""

from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from draft_archive_visibility import list_visible_draft_archives
from fantasy_league_context import get_league_context, upsert_league_context
from fantasy_league_team_ownership import assign_team_owner_to_context
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_workspace_team_identity import (
    apply_account_team_identity_to_session,
    detect_account_team_mismatch,
    resolve_current_account_team_for_live_draft_and_league,
)
from live_draft_completion import apply_live_draft_completion
from live_draft_navigation import get_draft_return_context
from live_draft_shared_league import save_live_draft_shared_league_context
from suite_identity_guard import detect_identity_mismatch, render_identity_guard_diagnostic_panel
from tests.test_live_draft_team_identity import _live_robins_fantasy_room
from tests.test_live_draft_workspace_isolation import _cio11_session, _daniel_session


TEAM_B_ROSTER = [
    "Jose Ramirez",
    "Kyle Schwarber",
    "Bobby Witt",
    "Cal Raleigh",
    "Gunnar Henderson",
    "Eugenio Suarez",
    "Mookie Betts",
    "Corbin Carroll",
    "Pete Alonso",
    "Freddie Freeman",
]


def _room_with_rosters() -> dict:
    room = _live_robins_fantasy_room()
    room["teams"] = ["Donny", "Team B"]
    room["config"]["your_team"] = "Donny"
    room["config"]["user_team"] = "Donny"
    room["rosters"] = {
        "Donny": [{"Player": "Francisco Lindor"}],
        "Team B": [{"Player": name} for name in TEAM_B_ROSTER],
    }
    room["draft_board"] = [
        {"Pick": i + 1, "Player": p, "Fantasy Team": "Team B"}
        for i, p in enumerate(TEAM_B_ROSTER)
    ]
    return room


class TestLiveDraftTeamIdentityRepair(unittest.TestCase):
    def test_cio11_resolves_team_b_from_ownership(self) -> None:
        session = _cio11_session(
            live_draft_room=_room_with_rosters(),
            draft_room_participant_team="Donny",
            room_your_team="Donny",
        )
        shared = {
            "league_id": "league:c4eefe793c8abac4764346d6",
            "team_ownership": {
                "Donny": {"user_id": "user:daniel", "external_id": "daniel"},
                "Team B": {"user_id": "user:coakley11", "external_id": "coakley11"},
            },
        }
        with patch(
            "fantasy_workspace_team_identity._load_shared_doc_for_context",
            return_value=shared,
        ):
            team = resolve_current_account_team_for_live_draft_and_league(
                session,
                room=session["live_draft_room"],
                shared_doc=shared,
            )
        self.assertEqual(team, "Team B")

    def test_apply_account_team_updates_session_fields(self) -> None:
        session = _cio11_session(
            live_draft_room=_room_with_rosters(),
            draft_room_participant_team="Donny",
            room_your_team="Donny",
            active_shared_draft_room_code="ABC123",
            draft_room_participant_id="participant-b",
        )
        shared = {
            "league_id": "league:c4eefe793c8abac4764346d6",
            "team_ownership": {
                "Team B": {"user_id": "user:coakley11", "external_id": "coakley11"},
            },
        }
        with patch(
            "fantasy_workspace_team_identity._load_shared_doc_for_context",
            return_value=shared,
        ), patch(
            "draft_room_participant_state.active_participant_team",
            return_value="Team B",
        ):
            out = apply_account_team_identity_to_session(session, reason="test")
        self.assertTrue(out.get("applied"))
        self.assertEqual(session["draft_room_participant_team"], "Team B")
        self.assertEqual(session["room_your_team"], "Team B")
        self.assertEqual(session["live_draft_room"]["config"]["your_team"], "Team B")

    def test_sidebar_return_context_uses_team_b(self) -> None:
        room = _room_with_rosters()
        room["status"] = "in_progress"
        session = _cio11_session(
            live_draft_room=room,
            draft_room_participant_team="Donny",
            active_shared_draft_room_code="ABC123",
        )
        with patch(
            "fantasy_workspace_team_identity.resolve_current_account_team_for_live_draft_and_league",
            return_value="Team B",
        ), patch(
            "live_draft_state.has_active_live_draft",
            return_value=True,
        ):
            ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "live_active")
        self.assertEqual(ctx.get("user_team"), "Team B")

    def test_daniel_remains_donny(self) -> None:
        session = _daniel_session(
            live_draft_room=_room_with_rosters(),
            draft_room_participant_team="Donny",
        )
        shared = {
            "team_ownership": {
                "Donny": {"user_id": "user:daniel", "external_id": "daniel"},
                "Team B": {"user_id": "user:coakley11", "external_id": "coakley11"},
            }
        }
        with patch(
            "fantasy_workspace_team_identity._load_shared_doc_for_context",
            return_value=shared,
        ), patch(
            "draft_room_participant_state.active_participant_team",
            return_value="Donny",
        ):
            team = resolve_current_account_team_for_live_draft_and_league(session, room=session["live_draft_room"])
        self.assertEqual(team, "Donny")

    def test_preassigned_live_draft_owner_visible_without_invite(self) -> None:
        from tests.test_imported_shared_league import _as_user

        room = _live_robins_fantasy_room()
        session = _daniel_session()
        apply_live_draft_completion(room, session)
        with _as_user("user:daniel"):
            _entry, context = save_live_draft_shared_league_context(
                session,
                room,
                my_team_name="Donny",
                league_name="Robins Fantasy",
                assign_team=True,
                preassign_owners={
                    "Donny": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"},
                    "Team B": {"user_id": "user:coakley11", "email": "coakley@test", "display_name": "Coakley"},
                },
            )
        coakley = _cio11_session()
        coakley["draft_archive_teams"] = copy.deepcopy(session.get("draft_archive_teams") or [])
        coakley["fantasy_league_context_state"] = copy.deepcopy(session.get("fantasy_league_context_state") or {})
        loaded = get_league_context(session, str(context.get("league_context_id") or "")) or context
        loaded = assign_team_owner_to_context(
            loaded,
            "Team B",
            user_id="user:coakley11",
            email="coakley@test",
            display_name="Coakley",
        )
        meta = dict(loaded.get("metadata") or {})
        meta.pop("joined_via_invite", None)
        meta["joined_via_live_draft"] = True
        meta["preassigned_live_draft_owner"] = True
        loaded["metadata"] = meta
        upsert_league_context(coakley, loaded)
        with _as_user("user:coakley11"):
            self.assertEqual(len(list_visible_draft_archives(coakley)), 1)

    def test_team_mismatch_detected(self) -> None:
        session = _cio11_session(draft_room_participant_team="Donny", room_your_team="Donny")
        with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}, clear=False), patch(
            "fantasy_workspace_team_identity.resolve_current_account_team_for_live_draft_and_league",
            return_value="Team B",
        ):
            mismatch, reasons = detect_account_team_mismatch(session)
        self.assertTrue(mismatch)
        self.assertTrue(any("Donny" in r for r in reasons))

    def test_emergency_diagnostic_without_developer_mode(self) -> None:
        session = _cio11_session(
            _suite_active_workspace_id="daniel",
            _suite_owned_workspace_id="daniel",
            draft_room_participant_team="Donny",
        )

        class _FakeSt:
            query_params = {}

            def __init__(self, session: dict) -> None:
                self.session_state = session

            def expander(self, title, expanded=False):
                self.title = title
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def dataframe(self, *_args, **_kwargs):
                pass

            def caption(self, *_args, **_kwargs):
                pass

        st = _FakeSt(session)
        with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}, clear=False), patch(
            "suite_workspace.developer_mode_checkbox_enabled",
            return_value=False,
        ), patch(
            "fantasy_workspace_team_identity.resolve_current_account_team_for_live_draft_and_league",
            return_value="Team B",
        ):
            mismatch, _ = detect_identity_mismatch(session)
            self.assertTrue(mismatch)
            render_identity_guard_diagnostic_panel(st, session)
        self.assertIn("Mismatch", getattr(st, "title", ""))

    def test_apply_skips_live_draft_my_team_after_widget_lock(self) -> None:
        """Regression: Streamlit forbids writing selectbox keys after instantiation."""

        class StreamlitAPIException(Exception):
            pass

        class GuardSession(dict):
            def __setitem__(self, key, value) -> None:  # type: ignore[override]
                if key == "live_draft_my_team" and self.get("_widget_live_draft_my_team"):
                    raise StreamlitAPIException(
                        'st.session_state.live_draft_my_team cannot be modified after the widget '
                        'with key "live_draft_my_team" is instantiated.'
                    )
                super().__setitem__(key, value)

        session = GuardSession(
            _cio11_session(
                live_draft_room=_room_with_rosters(),
                draft_room_participant_team="Donny",
            )
        )
        session["live_draft_my_team"] = "Donny"
        session["_widget_live_draft_my_team"] = True
        with patch(
            "fantasy_workspace_team_identity.resolve_current_account_team_for_live_draft_and_league",
            return_value="Team B",
        ):
            out = apply_account_team_identity_to_session(session, reason="post_widget")
        self.assertTrue(out.get("applied"))
        self.assertEqual(out.get("live_draft_my_team_set"), "skipped_widget_locked")
        self.assertEqual(session.get("live_draft_my_team"), "Donny")
        self.assertEqual(session.get("draft_room_participant_team"), "Team B")
        self.assertEqual(session.get("room_your_team"), "Team B")


if __name__ == "__main__":
    unittest.main()
