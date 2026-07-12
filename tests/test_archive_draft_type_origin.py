"""Archive origin labels for promoted live-draft shared leagues."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_archive_state import (
    DRAFT_TYPE_IMPORTED,
    DRAFT_TYPE_LIVE,
    DRAFT_TYPE_SIMULATOR,
    get_draft_archive,
    list_draft_archives,
)
from draft_archive_ui import (
    _on_click_open_saved_draft_library_focus,
    _saved_archive_is_active,
    draft_type_display,
)
from fantasy_league_context import (
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    CONTEXT_TYPE_REAL_LEAGUE,
    SOURCE_DRAFT_SIMULATOR,
    SOURCE_IMPORTED_DRAFT,
    SOURCE_LIVE_DRAFT_ROOM,
    context_id_for_archive,
    repair_archive_draft_type_for_entry,
    repair_archive_draft_types_from_contexts,
    resolve_archive_draft_type_from_context,
    upsert_league_context,
    _archive_stub_from_league_context,
)
from live_draft_shared_league import CREATED_FROM_LIVE_DRAFT
from live_draft_completion import apply_live_draft_completion
from live_draft_shared_league import save_live_draft_shared_league_context
from tests.test_imported_shared_league import _as_user
from tests.test_live_draft_team_identity import _live_robins_fantasy_room


class ArchiveDraftTypeOriginTests(unittest.TestCase):
    def test_live_real_league_resolves_live_draft_type(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_LIVE_DRAFT_ROOM,
            "metadata": {"created_from": CREATED_FROM_LIVE_DRAFT, "source_draft_id": "c6810611c73e"},
        }
        self.assertEqual(resolve_archive_draft_type_from_context(context), DRAFT_TYPE_LIVE)

    def test_imported_real_league_resolves_imported_type(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_IMPORTED_DRAFT,
            "metadata": {"source": SOURCE_IMPORTED_DRAFT, "source_draft_id": "imp1"},
        }
        self.assertEqual(resolve_archive_draft_type_from_context(context), DRAFT_TYPE_IMPORTED)

    def test_simulator_context_resolves_simulator_type(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
            "source": SOURCE_DRAFT_SIMULATOR,
            "metadata": {"source_draft_id": "sim1"},
        }
        self.assertEqual(resolve_archive_draft_type_from_context(context), DRAFT_TYPE_SIMULATOR)

    def test_archive_stub_from_live_shared_league_is_live_draft(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_LIVE_DRAFT_ROOM,
            "league_context_id": "archive:c6810611c73e",
            "display_name": "Robins Fantasy — Donny vs Team B",
            "my_team_name": "Donny",
            "league_rosters": {
                "Donny": {"players": [{"player_name": "Aaron Judge"}]},
                "Team B": {"players": [{"player_name": "Jose Ramirez"}]},
            },
            "metadata": {
                "created_from": CREATED_FROM_LIVE_DRAFT,
                "source_draft_id": "c6810611c73e",
                "league_id": "league:c4eefe793c8abac4764346d6",
            },
        }
        stub = _archive_stub_from_league_context(context)
        self.assertIsNotNone(stub)
        assert stub is not None
        self.assertEqual(stub.get("draft_type"), DRAFT_TYPE_LIVE)
        self.assertEqual(stub.get("draft_id"), "c6810611c73e")

    def test_robins_archive_repaired_in_place_without_duplication(self) -> None:
        session: dict = {}
        draft_id = "c6810611c73e"
        context_id = context_id_for_archive(draft_id)
        context = {
            "league_context_id": context_id,
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_LIVE_DRAFT_ROOM,
            "display_name": "Robins Fantasy — Donny vs Team B",
            "league_name": "Robins Fantasy",
            "my_team_name": "Donny",
            "league_id": "league:c4eefe793c8abac4764346d6",
            "league_rosters": {
                "Donny": {"players": [{"player_name": f"P{i}"} for i in range(10)]},
                "Team B": {"players": [{"player_name": f"T{i}"} for i in range(10)]},
            },
            "metadata": {
                "created_from": CREATED_FROM_LIVE_DRAFT,
                "source_draft_id": draft_id,
                "league_id": "league:c4eefe793c8abac4764346d6",
                "commissioner_user_id": "user:daniel",
            },
        }
        upsert_league_context(session, context)
        session["draft_archive_teams"] = [
            {
                "draft_id": draft_id,
                "draft_name": "Robins Fantasy — Donny vs Team B",
                "draft_type": DRAFT_TYPE_IMPORTED,
                "team_name": "Donny",
                "league_context_id": context_id,
                "league_rosters": context["league_rosters"],
            }
        ]
        session["active_draft_archive_id"] = draft_id
        store = session["fantasy_league_context_state"]
        store["active_league_context_id"] = context_id

        repaired = repair_archive_draft_types_from_contexts(session)
        self.assertEqual(repaired, 1)
        self.assertEqual(len(list_draft_archives(session)), 1)
        entry = get_draft_archive(session, draft_id)
        assert entry is not None
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_LIVE)
        self.assertEqual(draft_type_display(entry), "Live Draft")
        self.assertEqual(str(entry.get("draft_id")), draft_id)
        ctx = session["fantasy_league_context_state"]["contexts"][context_id]
        self.assertEqual(ctx.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)

    def test_open_library_focus_does_not_activate(self) -> None:
        session = {
            "active_draft_archive_id": "other-draft",
            "fantasy_league_context_state": {"active_league_context_id": "archive:other"},
        }

        class _St:
            session_state = session

        import streamlit as st

        with patch.object(st, "session_state", session):
            _on_click_open_saved_draft_library_focus(
                draft_id="c6810611c73e",
                return_page="Live Draft Room",
            )
        self.assertEqual(session.get("active_draft_archive_id"), "other-draft")
        self.assertEqual(session.get("_saved_draft_library_focus_draft_id"), "c6810611c73e")

    def test_shared_league_save_does_not_auto_activate_when_other_league_active(self) -> None:
        session: dict = {
            "active_draft_archive_id": "other-draft",
            "fantasy_league_context_state": {
                "active_league_context_id": "archive:other",
                "contexts": {},
            },
        }
        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, session)
        with _as_user("user:daniel"):
            entry, context = save_live_draft_shared_league_context(
                session,
                room,
                my_team_name="Donny",
                league_name="Robins Fantasy",
                defer_activation=True,
                assign_team=True,
                preassign_owners={"Donny": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"}},
            )
        self.assertEqual(str(entry.get("draft_type") or ""), DRAFT_TYPE_LIVE)
        self.assertNotEqual(session.get("active_draft_archive_id"), str(entry.get("draft_id") or ""))

    def test_explicit_set_active_league_marks_active(self) -> None:
        session: dict = {}
        draft_id = "c6810611c73e"
        context_id = context_id_for_archive(draft_id)
        context = {
            "league_context_id": context_id,
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_LIVE_DRAFT_ROOM,
            "display_name": "Robins Fantasy",
            "my_team_name": "Donny",
            "metadata": {"created_from": CREATED_FROM_LIVE_DRAFT, "source_draft_id": draft_id},
        }
        upsert_league_context(session, context)
        session["draft_archive_teams"] = [
            {
                "draft_id": draft_id,
                "draft_name": "Robins Fantasy",
                "draft_type": DRAFT_TYPE_LIVE,
                "league_context_id": context_id,
            }
        ]
        with _as_user("user:daniel"):
            self.assertFalse(_saved_archive_is_active(session, draft_id=draft_id, context_id=context_id))
            from draft_archive_ui import _on_click_set_active_league

            class _St:
                session_state = session

            import streamlit as st

            with patch.object(st, "session_state", session), patch(
                "draft_archive_ui._persist_archive", return_value=True
            ):
                _on_click_set_active_league(draft_id=draft_id, context_id=context_id, league_label="Robins Fantasy")
            self.assertTrue(_saved_archive_is_active(session, draft_id=draft_id, context_id=context_id))


if __name__ == "__main__":
    unittest.main()
