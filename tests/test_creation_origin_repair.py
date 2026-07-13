"""Regression tests for guarded creation-origin repair migrations."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE
from fantasy_creation_origin_repair import (
    KNOWN_MISCLASSIFIED_IMPORT_DRAFTS,
    repair_incorrect_creation_origin,
    repair_known_misclassified_import_origins,
)
from fantasy_league_context import (
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    CREATION_ORIGIN_VALIDATED_IMPORT,
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    apply_draft_origin_to_context,
    context_id_for_archive,
    resolve_archive_draft_type_with_reason,
    stamp_immutable_creation_origin,
    upsert_league_context,
)
from saved_draft_library_selection import prepare_saved_draft_library_active_selection


def _session() -> dict:
    return {
        DRAFT_ARCHIVE_KEY: [],
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: {"contexts": {}, "active_league_context_id": ""},
    }


def _upload_poisoned_context() -> dict:
    draft_id = "3ce50b4f2e8b"
    teams = ["Daniel", "Team 2", "Team 3", "Team 4"]
    return {
        "league_context_id": context_id_for_archive(draft_id),
        "context_type": "real_league",
        "display_name": "Upload Test Demo",
        "my_team_name": "Daniel",
        "source": "live_draft_room",
        "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
        "metadata": {
            "source_draft_id": draft_id,
            "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
            "source_draft_type": "live_draft_room",
            "created_from": "live_draft",
            "joined_via_live_draft": True,
            "preassigned_live_draft_owner": True,
        },
        "league_rosters": {t: {"team_name": t, "players": [{"player_name": f"P-{t}"}]} for t in teams},
    }


class CreationOriginRepairTests(unittest.TestCase):
    def test_repair_upload_test_demo_from_poisoned_live_state(self) -> None:
        session = _session()
        draft_id = "3ce50b4f2e8b"
        session[DRAFT_ARCHIVE_KEY] = [
            {
                "draft_id": draft_id,
                "draft_name": "Upload Test Demo",
                "draft_type": DRAFT_TYPE_LIVE,
                "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                "league_context_id": context_id_for_archive(draft_id),
            }
        ]
        ctx = _upload_poisoned_context()
        upsert_league_context(session, ctx)

        trace = repair_incorrect_creation_origin(
            session,
            draft_id=draft_id,
            verified_origin=CREATION_ORIGIN_VALIDATED_IMPORT,
            repair_reason="known_legacy_import_misclassified_as_live",
        )
        self.assertTrue(trace["archive_updated"])
        self.assertTrue(trace["context_updated"])

        archive = session[DRAFT_ARCHIVE_KEY][0]
        self.assertEqual(archive["draft_type"], DRAFT_TYPE_IMPORTED)
        self.assertEqual(archive["creation_origin"], CREATION_ORIGIN_VALIDATED_IMPORT)

        from fantasy_league_context import get_league_context

        repaired_ctx = get_league_context(session, context_id_for_archive(draft_id))
        assert repaired_ctx is not None
        meta = repaired_ctx.get("metadata") or {}
        self.assertEqual(repaired_ctx.get("source"), "imported_draft")
        self.assertEqual(meta.get("creation_origin"), CREATION_ORIGIN_VALIDATED_IMPORT)
        self.assertNotIn("joined_via_live_draft", meta)
        self.assertNotIn("preassigned_live_draft_owner", meta)
        self.assertEqual(len(repaired_ctx.get("league_rosters") or {}), 4)

        draft_type, reason, _ = resolve_archive_draft_type_with_reason(context=repaired_ctx, archive_entry=archive)
        self.assertEqual(draft_type, DRAFT_TYPE_IMPORTED)
        self.assertEqual(reason, "immutable_creation_origin_validated_import")

    def test_repair_is_idempotent(self) -> None:
        session = _session()
        draft_id = "3ce50b4f2e8b"
        session[DRAFT_ARCHIVE_KEY] = [{"draft_id": draft_id, "draft_type": DRAFT_TYPE_LIVE}]
        upsert_league_context(session, _upload_poisoned_context())
        repair_known_misclassified_import_origins(session)
        repair_known_misclassified_import_origins(session)
        archive = session[DRAFT_ARCHIVE_KEY][0]
        self.assertEqual(archive["draft_type"], DRAFT_TYPE_IMPORTED)

    def test_robins_stays_live_draft(self) -> None:
        session = _session()
        draft_id = "c6810611c73e"
        ctx = {
            "league_context_id": context_id_for_archive(draft_id),
            "context_type": "live_draft_result",
            "source": "live_draft_room",
            "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
            "metadata": {"source_draft_id": draft_id, "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM},
            "league_rosters": {
                "Donny": {"players": [{"player_name": "P1"}]},
                "Team B": {"players": [{"player_name": "P2"}]},
            },
        }
        archive = {"draft_id": draft_id, "draft_type": DRAFT_TYPE_LIVE, "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM}
        upsert_league_context(session, ctx)
        repair_known_misclassified_import_origins(session)
        draft_type, _, _ = resolve_archive_draft_type_with_reason(context=ctx, archive_entry=archive)
        self.assertEqual(draft_type, DRAFT_TYPE_LIVE)

    def test_known_ids_not_in_general_resolver(self) -> None:
        from fantasy_league_context import _infer_creation_origin_for_backfill

        source = _infer_creation_origin_for_backfill.__code__.co_consts
        joined = " ".join(str(x) for x in source if isinstance(x, str))
        self.assertNotIn("3ce50b4f2e8b", joined)
        self.assertNotIn("Upload Test Demo", joined)

    def test_stamp_immutable_does_not_overwrite_repaired_origin(self) -> None:
        meta = {"creation_origin": CREATION_ORIGIN_VALIDATED_IMPORT}
        stamped = stamp_immutable_creation_origin(meta, CREATION_ORIGIN_LIVE_DRAFT_ROOM)
        self.assertEqual(stamped["creation_origin"], CREATION_ORIGIN_VALIDATED_IMPORT)

    def test_conflicting_tokens_without_creation_origin_report_conflict(self) -> None:
        ctx = {
            "source": "live_draft_room",
            "metadata": {"created_from": "validated_import", "source_draft_type": "imported_draft"},
            "context_type": "real_league",
        }
        archive = {"draft_type": DRAFT_TYPE_LIVE}
        draft_type, reason, evidence = resolve_archive_draft_type_with_reason(context=ctx, archive_entry=archive)
        self.assertEqual(reason, "origin_conflict")
        self.assertNotEqual(draft_type, DRAFT_TYPE_LIVE)

    def test_prepare_library_runs_known_repair(self) -> None:
        session = _session()
        draft_id = "3ce50b4f2e8b"
        session[DRAFT_ARCHIVE_KEY] = [{"draft_id": draft_id, "draft_type": DRAFT_TYPE_LIVE}]
        upsert_league_context(session, _upload_poisoned_context())
        with patch("fantasy_shared_league_store.load_shared_league", return_value=None), patch(
            "fantasy_shared_league_store.save_shared_league"
        ):
            prepare_saved_draft_library_active_selection(session)
        archive = session[DRAFT_ARCHIVE_KEY][0]
        self.assertEqual(archive["draft_type"], DRAFT_TYPE_IMPORTED)

    def test_repair_reason_recorded(self) -> None:
        self.assertIn("3ce50b4f2e8b", KNOWN_MISCLASSIFIED_IMPORT_DRAFTS)
        self.assertEqual(
            KNOWN_MISCLASSIFIED_IMPORT_DRAFTS["3ce50b4f2e8b"]["repair_reason"],
            "known_legacy_import_misclassified_as_live",
        )


if __name__ == "__main__":
    unittest.main()
