"""Coakley11 Saved Draft Library badge — Live Draft origin repair."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from draft_archive_state import (
    DRAFT_ARCHIVE_KEY,
    DRAFT_TYPE_IMPORTED,
    DRAFT_TYPE_LIVE,
    DRAFT_TYPE_SIMULATOR,
    get_draft_archive,
    list_draft_archives,
)
from draft_archive_ui import draft_type_display
from fantasy_admin_draft_archive_repair import (
    _normalize_repaired_archive_types,
    _sync_archives_to_workspace_team,
    build_context_from_shared_for_workspace,
    repair_workspace_session_for_league,
)
from fantasy_league_context import (
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    CONTEXT_TYPE_REAL_LEAGUE,
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    SOURCE_IMPORTED_DRAFT,
    SOURCE_LIVE_DRAFT_ROOM,
    apply_draft_origin_to_context,
    context_id_for_archive,
    repair_archive_draft_types_from_contexts,
    resolve_archive_draft_type_from_origin,
    upsert_league_context,
)
from fantasy_shared_league_library_sync import materialize_owned_shared_leagues_for_session
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from live_draft_shared_league import CREATED_FROM_LIVE_DRAFT
from tests.test_live_draft_workspace_isolation import _cio11_session, _daniel_session


LEAGUE_ID = "league:c4eefe793c8abac4764346d6"
DRAFT_ID = "c6810611c73e"
CONTEXT_ID = f"archive:{DRAFT_ID}"


def _rosters() -> dict:
    return {
        "Donny": {"players": [{"player_name": f"D{i}"} for i in range(10)]},
        "Team B": {"players": [{"player_name": f"B{i}"} for i in range(10)]},
    }


def _live_shared_doc(*, with_origin_fields: bool = True) -> dict:
    doc = {
        "schema_version": 1,
        "league_id": LEAGUE_ID,
        "draft_id": DRAFT_ID,
        "draft_fingerprint": "fp-robins",
        "league_name": "Robins Fantasy",
        "commissioner_user_id": "user:daniel",
        "revision": 2,
        "updated_at": "2026-07-12T00:00:00+00:00",
        "league_rosters": _rosters(),
        "team_ownership": {
            "Donny": {"user_id": "user:daniel", "external_id": "daniel", "display_name": "Daniel"},
            "Team B": {"user_id": "user:coakley11", "external_id": "coakley11", "display_name": "Coakley11"},
        },
        "trade_proposals": [],
        "league_invites": [],
        "league_activity": [],
    }
    if with_origin_fields:
        doc.update(
            {
                "created_from": CREATED_FROM_LIVE_DRAFT,
                "source_draft_type": DRAFT_TYPE_LIVE,
                "source": SOURCE_LIVE_DRAFT_ROOM,
                "metadata": {
                    "created_from": CREATED_FROM_LIVE_DRAFT,
                    "source_draft_type": DRAFT_TYPE_LIVE,
                    "source": SOURCE_LIVE_DRAFT_ROOM,
                },
            }
        )
    return doc


def _imported_shared_doc() -> dict:
    return {
        "schema_version": 1,
        "league_id": "league:imported99",
        "draft_id": "imported99",
        "league_name": "Office League",
        "commissioner_user_id": "user:donny",
        "revision": 1,
        "league_rosters": {
            "Daniel": {"players": [{"player_name": "Aaron Judge"}]},
            "Team 2": {"players": [{"player_name": "Mookie Betts"}]},
        },
        "team_ownership": {
            "Daniel": {"user_id": "user:donny"},
            "Team 2": {"user_id": "user:seal11"},
        },
        "created_from": "imported_draft",
        "source_draft_type": DRAFT_TYPE_IMPORTED,
        "source": SOURCE_IMPORTED_DRAFT,
        "league_invites": [],
    }


class Coakley11LiveDraftBadgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedLeagueStore(root=Path(self._tmp.name))
        set_shared_league_store(self.store)
        self.store.save(_live_shared_doc())

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_live_shared_league_materialized_for_coakley11_displays_live_draft(self) -> None:
        session = _cio11_session()
        materialize_owned_shared_leagues_for_session(session)
        entry = get_draft_archive(session, DRAFT_ID)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_LIVE)
        self.assertEqual(draft_type_display(entry), "Live Draft")

    def test_context_remains_real_league_for_coakley11(self) -> None:
        session = _cio11_session()
        materialize_owned_shared_leagues_for_session(session)
        ctx = session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["contexts"][CONTEXT_ID]
        self.assertEqual(ctx.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)

    def test_coakley11_remains_team_b(self) -> None:
        session = _cio11_session()
        materialize_owned_shared_leagues_for_session(session)
        entry = get_draft_archive(session, DRAFT_ID)
        ctx = session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["contexts"][CONTEXT_ID]
        assert entry is not None
        self.assertEqual(entry.get("team_name"), "Team B")
        self.assertEqual(ctx.get("my_team_name"), "Team B")

    def test_daniel_remains_donny(self) -> None:
        session = _daniel_session()
        context = {
            "league_context_id": CONTEXT_ID,
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_LIVE_DRAFT_ROOM,
            "display_name": "Robins Fantasy — Donny vs Team B",
            "my_team_name": "Donny",
            "league_rosters": _rosters(),
            "metadata": {
                "created_from": CREATED_FROM_LIVE_DRAFT,
                "source_draft_id": DRAFT_ID,
                "league_id": LEAGUE_ID,
                "commissioner_user_id": "user:daniel",
            },
        }
        upsert_league_context(session, context)
        session[DRAFT_ARCHIVE_KEY] = [
            {
                "draft_id": DRAFT_ID,
                "draft_name": "Robins Fantasy — Donny vs Team B",
                "draft_type": DRAFT_TYPE_LIVE,
                "team_name": "Donny",
                "league_context_id": CONTEXT_ID,
                "league_rosters": _rosters(),
            }
        ]
        repair_archive_draft_types_from_contexts(session)
        entry = get_draft_archive(session, DRAFT_ID)
        assert entry is not None
        self.assertEqual(entry.get("team_name"), "Donny")
        self.assertEqual(draft_type_display(entry), "Live Draft")

    def test_existing_coakley11_archive_repaired_in_place(self) -> None:
        session = _cio11_session()
        session[DRAFT_ARCHIVE_KEY] = [
            {
                "draft_id": DRAFT_ID,
                "draft_name": "Robins Fantasy — Donny vs Team B",
                "draft_type": DRAFT_TYPE_IMPORTED,
                "team_name": "Team B",
                "league_context_id": CONTEXT_ID,
                "league_rosters": _rosters(),
            }
        ]
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = {
            "active_league_context_id": CONTEXT_ID,
            "contexts": {
                CONTEXT_ID: {
                    "league_context_id": CONTEXT_ID,
                    "context_type": CONTEXT_TYPE_REAL_LEAGUE,
                    "source": SOURCE_IMPORTED_DRAFT,
                    "display_name": "Robins Fantasy — Donny vs Team B",
                    "my_team_name": "Team B",
                    "league_rosters": _rosters(),
                    "metadata": {
                        "source_draft_id": DRAFT_ID,
                        "league_id": LEAGUE_ID,
                        "commissioner_user_id": "user:daniel",
                        "joined_via_invite": True,
                    },
                }
            },
        }
        repaired = repair_archive_draft_types_from_contexts(session)
        self.assertEqual(repaired, 1)
        entry = get_draft_archive(session, DRAFT_ID)
        assert entry is not None
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_LIVE)
        self.assertEqual(draft_type_display(entry), "Live Draft")

    def test_no_duplicate_archive_context_or_league_on_repair(self) -> None:
        session = _cio11_session()
        repair_workspace_session_for_league(
            session,
            league_id=LEAGUE_ID,
            shared_doc=_live_shared_doc(),
        )
        first_count = len(list_draft_archives(session))
        first_contexts = len(session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["contexts"])
        second = repair_workspace_session_for_league(
            session,
            league_id=LEAGUE_ID,
            shared_doc=_live_shared_doc(),
        )
        self.assertEqual(len(list_draft_archives(session)), first_count)
        self.assertEqual(len(session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["contexts"]), first_contexts)
        self.assertTrue(second.get("skipped_duplicate") or second.get("archive_team_rows_rewritten", 0) == 0)

    def test_uploaded_league_still_displays_imported_league(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_IMPORTED_DRAFT,
            "metadata": {"source_draft_type": DRAFT_TYPE_IMPORTED, "source_draft_id": "imported99"},
        }
        shared = _imported_shared_doc()
        self.assertEqual(
            resolve_archive_draft_type_from_origin(context=context, shared_doc=shared),
            DRAFT_TYPE_IMPORTED,
        )
        entry = {"draft_type": DRAFT_TYPE_IMPORTED, "draft_id": "imported99"}
        self.assertEqual(draft_type_display(entry), "Imported League")

    def test_simulator_draft_retains_simulator_classification(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
            "source": "draft_simulator",
            "metadata": {"source_draft_type": DRAFT_TYPE_SIMULATOR, "source_draft_id": "sim1"},
        }
        self.assertEqual(resolve_archive_draft_type_from_origin(context=context), DRAFT_TYPE_SIMULATOR)

    def test_team_archive_sync_does_not_overwrite_live_draft_origin(self) -> None:
        session = _cio11_session()
        context = build_context_from_shared_for_workspace(
            _live_shared_doc(),
            owner_user_id="user:coakley11",
            owner_external_id="coakley11",
            workspace_id="coakley11",
        )
        context = apply_draft_origin_to_context(context, shared_doc=_live_shared_doc())
        upsert_league_context(session, context)
        session[DRAFT_ARCHIVE_KEY] = [
            {
                "draft_id": DRAFT_ID,
                "draft_name": "Robins Fantasy — Donny vs Team B",
                "draft_type": DRAFT_TYPE_LIVE,
                "team_name": "Donny",
                "league_context_id": CONTEXT_ID,
                "league_rosters": _rosters(),
            }
        ]
        refreshed = copy.deepcopy(context)
        refreshed["my_team_name"] = "Team B"
        _sync_archives_to_workspace_team(session, refreshed)
        entry = get_draft_archive(session, DRAFT_ID)
        assert entry is not None
        self.assertEqual(entry.get("team_name"), "Team B")
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_LIVE)

    def test_normalize_and_materialize_preserve_live_draft_badge(self) -> None:
        session = _cio11_session()
        materialize_owned_shared_leagues_for_session(session)
        entry = get_draft_archive(session, DRAFT_ID)
        assert entry is not None
        entry["draft_type"] = DRAFT_TYPE_IMPORTED
        session[DRAFT_ARCHIVE_KEY] = [entry]
        _normalize_repaired_archive_types(session)
        repair_archive_draft_types_from_contexts(session)
        restored = get_draft_archive(session, DRAFT_ID)
        assert restored is not None
        self.assertEqual(restored.get("draft_type"), DRAFT_TYPE_LIVE)
        self.assertEqual(draft_type_display(restored), "Live Draft")
        self.assertEqual(len(list_draft_archives(session)), 1)


if __name__ == "__main__":
    unittest.main()
