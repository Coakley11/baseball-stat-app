"""Regression tests for coherent Saved Draft Library active selection."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from draft_archive_state import (
    ACTIVE_DRAFT_ARCHIVE_KEY,
    DRAFT_TYPE_IMPORTED,
    DRAFT_TYPE_LIVE,
    activate_draft_archive,
)
from fantasy_league_context import (
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    CREATION_ORIGIN_VALIDATED_IMPORT,
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    activate_league_context,
    apply_draft_origin_to_context,
    context_id_for_archive,
    resolve_archive_draft_type_with_reason,
    upsert_league_context,
)
from saved_draft_library_selection import (
    active_pair_is_coherent,
    prepare_saved_draft_library_active_selection,
    repair_incoherent_active_library_selection,
    resolve_coherent_active_library_selection,
    saved_draft_card_is_active,
)


def _session() -> dict:
    return {
        "draft_archive_teams": [],
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: {"contexts": {}, "active_league_context_id": ""},
    }


def _archive(draft_id: str, *, draft_type: str = DRAFT_TYPE_IMPORTED, name: str = "Draft") -> dict:
    return {
        "draft_id": draft_id,
        "draft_name": name,
        "draft_type": draft_type,
        "team_name": "Daniel",
        "league_context_id": context_id_for_archive(draft_id),
        "snapshot": {"teams": ["Daniel", "Team 2", "Team 3", "Team 4"]},
    }


def _context(
    draft_id: str,
    *,
    my_team: str = "Daniel",
    teams: list[str] | None = None,
    creation_origin: str = "",
    live_flags: bool = False,
) -> dict:
    teams = teams or ["Daniel", "Team 2", "Team 3", "Team 4"]
    meta = {
        "source_draft_id": draft_id,
        "creation_origin": creation_origin,
    }
    if live_flags:
        meta["joined_via_live_draft"] = True
        meta["preassigned_live_draft_owner"] = True
    return {
        "league_context_id": context_id_for_archive(draft_id),
        "context_type": "real_league",
        "display_name": "League",
        "my_team_name": my_team,
        "league_rosters": {t: {"starters": [], "bench": []} for t in teams},
        "metadata": meta,
        "source": "imported_draft",
    }


class ActivePairCoherenceTests(unittest.TestCase):
    def test_detects_hybrid_archive_context_mismatch(self) -> None:
        upload = _archive("3ce50b4f2e8b", name="Upload Test Demo")
        robins_ctx = _context("c6810611c73e", my_team="Donny", teams=["Donny", "Team B"])
        coherent, reason = active_pair_is_coherent(upload, robins_ctx)
        self.assertFalse(coherent)
        self.assertEqual(reason, "source_draft_id_mismatch")

    def test_coherent_when_archive_and_context_match(self) -> None:
        robins = _archive("c6810611c73e", draft_type=DRAFT_TYPE_LIVE, name="Robins Fantasy")
        robins_ctx = _context(
            "c6810611c73e",
            my_team="Donny",
            teams=["Donny", "Team B"],
            creation_origin=CREATION_ORIGIN_LIVE_DRAFT_ROOM,
        )
        coherent, _ = active_pair_is_coherent(robins, robins_ctx)
        self.assertTrue(coherent)

    def test_library_uses_persisted_context_not_effective_override(self) -> None:
        session = _session()
        session["draft_archive_teams"] = [
            _archive("3ce50b4f2e8b", name="Upload Test Demo"),
            _archive("c6810611c73e", draft_type=DRAFT_TYPE_LIVE, name="Robins Fantasy"),
        ]
        upsert_league_context(session, _context("c6810611c73e", my_team="Donny", teams=["Donny", "Team B"]))
        from fantasy_league_context import set_active_league_context

        set_active_league_context(session, context_id_for_archive("c6810611c73e"))
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = "3ce50b4f2e8b"

        with patch(
            "fantasy_context_source.get_effective_fantasy_context",
            return_value=_context("c6810611c73e", my_team="Donny", teams=["Donny", "Team B"]),
        ):
            sel = resolve_coherent_active_library_selection(session)
        self.assertFalse(sel["coherent"])
        self.assertEqual(sel["active_draft_archive_id"], "3ce50b4f2e8b")
        self.assertEqual(sel["persisted_active_context_id"], context_id_for_archive("c6810611c73e"))

    def test_repair_aligns_archive_to_persisted_context(self) -> None:
        session = _session()
        session["draft_archive_teams"] = [
            _archive("3ce50b4f2e8b", name="Upload Test Demo"),
            _archive("c6810611c73e", draft_type=DRAFT_TYPE_LIVE, name="Robins Fantasy"),
        ]
        upsert_league_context(session, _context("c6810611c73e", my_team="Donny", teams=["Donny", "Team B"]))
        from fantasy_league_context import set_active_league_context

        set_active_league_context(session, context_id_for_archive("c6810611c73e"))
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = "3ce50b4f2e8b"

        repaired = repair_incoherent_active_library_selection(session)
        self.assertTrue(repaired["coherent"])
        self.assertEqual(repaired["active_draft_archive_id"], "c6810611c73e")
        self.assertEqual(session[ACTIVE_DRAFT_ARCHIVE_KEY], "c6810611c73e")

    def test_exactly_one_card_active_after_repair(self) -> None:
        session = _session()
        upload = _archive("3ce50b4f2e8b", name="Upload Test Demo")
        robins = _archive("c6810611c73e", draft_type=DRAFT_TYPE_LIVE, name="Robins Fantasy")
        session["draft_archive_teams"] = [upload, robins]
        upsert_league_context(session, _context("3ce50b4f2e8b"))
        upsert_league_context(session, _context("c6810611c73e", my_team="Donny", teams=["Donny", "Team B"]))
        from fantasy_league_context import set_active_league_context

        set_active_league_context(session, context_id_for_archive("c6810611c73e"))
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = "3ce50b4f2e8b"
        selection = prepare_saved_draft_library_active_selection(session)
        active_flags = [
            saved_draft_card_is_active(
                session,
                draft_id=str(a["draft_id"]),
                league_context_id=str(a.get("league_context_id") or ""),
                selection=selection,
            )
            for a in session["draft_archive_teams"]
        ]
        self.assertEqual(sum(1 for x in active_flags if x), 1)
        self.assertFalse(
            saved_draft_card_is_active(
                session,
                draft_id="3ce50b4f2e8b",
                league_context_id=context_id_for_archive("3ce50b4f2e8b"),
                selection=selection,
            )
        )


class CreationOriginTests(unittest.TestCase):
    def test_validated_import_overrides_live_membership_flags(self) -> None:
        ctx = _context(
            "3ce50b4f2e8b",
            creation_origin=CREATION_ORIGIN_VALIDATED_IMPORT,
            live_flags=True,
        )
        draft_type, reason, _ = resolve_archive_draft_type_with_reason(context=ctx)
        self.assertEqual(draft_type, DRAFT_TYPE_IMPORTED)
        self.assertEqual(reason, "immutable_creation_origin_validated_import")

    def test_robins_live_creation_origin_stays_live(self) -> None:
        ctx = _context(
            "c6810611c73e",
            my_team="Donny",
            teams=["Donny", "Team B"],
            creation_origin=CREATION_ORIGIN_LIVE_DRAFT_ROOM,
        )
        draft_type, reason, _ = resolve_archive_draft_type_with_reason(context=ctx)
        self.assertEqual(draft_type, DRAFT_TYPE_LIVE)
        self.assertEqual(reason, "immutable_creation_origin_live_draft_room")

    def test_apply_draft_origin_clears_live_flags_for_import(self) -> None:
        ctx = _context(
            "3ce50b4f2e8b",
            creation_origin=CREATION_ORIGIN_VALIDATED_IMPORT,
            live_flags=True,
        )
        out = apply_draft_origin_to_context(copy.deepcopy(ctx))
        meta = out.get("metadata") or {}
        self.assertNotIn("joined_via_live_draft", meta)
        self.assertNotIn("preassigned_live_draft_owner", meta)
        self.assertEqual(out.get("source"), "imported_draft")


class MaterializationActivationTests(unittest.TestCase):
    def test_finalize_does_not_set_active_archive(self) -> None:
        session = _session()
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = "c6810611c73e"
        shared_doc = {
            "league_id": "league:abc",
            "draft_id": "3ce50b4f2e8b",
            "league_name": "Upload Test Demo",
            "creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT,
        }
        ctx = _context("3ce50b4f2e8b", creation_origin=CREATION_ORIGIN_VALIDATED_IMPORT)
        upsert_league_context(session, ctx)
        with patch(
            "fantasy_admin_draft_archive_repair.find_league_context_by_league_id",
            return_value=ctx,
        ), patch(
            "fantasy_league_context.repair_missing_draft_archives_from_contexts",
            return_value=0,
        ), patch(
            "fantasy_admin_draft_archive_repair._normalize_repaired_archive_types",
            return_value=0,
        ), patch(
            "fantasy_admin_draft_archive_repair._sync_archives_to_workspace_team",
            return_value=0,
        ), patch(
            "workflow_persist_guard.restore_active_draft_archive_selection",
            return_value={"restore_reason": "matched_session_active_to_visible_archive"},
        ), patch(
            "draft_archive_state.set_active_draft_archive",
        ) as set_active_mock:
            from fantasy_shared_league_startup_sync import finalize_repaired_archives_for_membership

            finalize_repaired_archives_for_membership(session, shared_doc=shared_doc)
        set_active_mock.assert_not_called()
        self.assertEqual(session[ACTIVE_DRAFT_ARCHIVE_KEY], "c6810611c73e")


if __name__ == "__main__":
    unittest.main()
