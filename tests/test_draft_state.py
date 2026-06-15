"""Tests for canonical Draft Workflow state (Sprint 3 acceptance A–E)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from draft_state import (
    DRAFT_DIRTY_KEY,
    DRAFT_QUEUE_KEY,
    DRAFT_WATCHLIST_FOCUS_KEY,
    DRAFT_WORKFLOW_BLOCK,
    add_player_to_draft_queue,
    add_player_to_watchlist,
    apply_cloud_draft_state_if_allowed,
    apply_draft_source_state_from_ami,
    clear_draft_queue,
    draft_top_queue_player,
    flush_draft_workflow_edits,
    is_draft_locally_dirty,
    mark_draft_local_edit,
    mark_draft_pending_sync,
    prepare_draft_workflow,
    restore_draft_workflow_page_filters,
    sync_draft_queue,
    write_canonical_draft_state,
)

_SAMPLE = {
    "queue": ["Mike Trout", "Shohei Ohtani"],
    "watchlist_focus": ["Aaron Judge"],
    "watchlist_favorites": ["Aaron Judge", "Mookie Betts"],
}


class TestDraftState(unittest.TestCase):
    def test_a_local_persist_prepare_preserves_queue(self) -> None:
        """A. Local persistence — edit queue, rerun prepare, values remain."""
        session: dict = {}
        write_canonical_draft_state(session, queue=_SAMPLE["queue"], reason="setup", local_edit=True)
        session[DRAFT_QUEUE_KEY] = ["Mike Trout", "Ronald Acuna Jr."]
        mark_draft_pending_sync(session)
        flush_draft_workflow_edits(session, reason="queue_change")
        prepare_draft_workflow(session)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Mike Trout", "Ronald Acuna Jr."])
        self.assertEqual(session["draft_state"]["queue"], ["Mike Trout", "Ronald Acuna Jr."])
        self.assertTrue(is_draft_locally_dirty(session))

    def test_a_add_to_queue_updates_canonical(self) -> None:
        session: dict = {}
        add_player_to_draft_queue(session, "Mike Trout")
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Mike Trout"])
        self.assertEqual(session["draft_state"]["queue"], ["Mike Trout"])

    def test_b_cross_device_cloud_restore(self) -> None:
        """B. Phone↔Dell — cloud workspace restores draft queue + watchlist."""
        session: dict = {"active_page": "Historical Explorer"}
        cloud = {
            "draft_state": {
                "queue": _SAMPLE["queue"],
                "watchlist_focus": _SAMPLE["watchlist_focus"],
                "watchlist_favorites": _SAMPLE["watchlist_favorites"],
            },
            "page_filter_state": {
                DRAFT_WORKFLOW_BLOCK: {
                    "draft_state": {
                        "queue": _SAMPLE["queue"],
                        "watchlist_focus": _SAMPLE["watchlist_focus"],
                        "watchlist_favorites": _SAMPLE["watchlist_favorites"],
                    },
                    DRAFT_QUEUE_KEY: _SAMPLE["queue"],
                }
            },
            "baseball_workspace_state": {"draft_workflow": dict(_SAMPLE)},
        }
        self.assertTrue(apply_cloud_draft_state_if_allowed(session, cloud))
        self.assertEqual(session[DRAFT_QUEUE_KEY], _SAMPLE["queue"])
        self.assertEqual(session[DRAFT_WATCHLIST_FOCUS_KEY], _SAMPLE["watchlist_focus"])

    def test_c_local_dirty_blocks_cloud_restore(self) -> None:
        """C. Cloud protection — local dirty blocks stale cloud overwrite."""
        session = {
            DRAFT_QUEUE_KEY: ["Local Only"],
            "draft_state": {"queue": ["Local Only"], "watchlist_focus": [], "watchlist_favorites": []},
        }
        mark_draft_local_edit(session)
        write_canonical_draft_state(session, queue=["Local Only"], reason="local_edit", local_edit=True)
        cloud = {"draft_state": {"queue": _SAMPLE["queue"]}}
        self.assertFalse(apply_cloud_draft_state_if_allowed(session, cloud))
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Local Only"])

    def test_c_local_dirty_blocks_page_filter_restore(self) -> None:
        session = {DRAFT_QUEUE_KEY: ["Local Only"]}
        mark_draft_local_edit(session)
        store = {DRAFT_WORKFLOW_BLOCK: {DRAFT_QUEUE_KEY: _SAMPLE["queue"]}}
        self.assertFalse(restore_draft_workflow_page_filters(session, store))
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Local Only"])

    def test_d_prepare_preserves_local_queue_over_canonical(self) -> None:
        """D. Navigation stability — widget drift preserved on prepare."""
        session = {
            "draft_state": {"queue": _SAMPLE["queue"], "watchlist_focus": [], "watchlist_favorites": []},
            DRAFT_QUEUE_KEY: ["Mike Trout", "New Pick"],
        }
        mark_draft_local_edit(session)
        prepare_draft_workflow(session)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Mike Trout", "New Pick"])

    def test_e_ami_return_restores_queue_and_watchlist(self) -> None:
        """E. AMI return preservation — queue + watchlist restored."""
        session: dict = {DRAFT_QUEUE_KEY: []}
        source = {
            "source_page": "Draft Assistant Simulator",
            "entity_params": {
                "draft_queue": _SAMPLE["queue"],
                "watchlist_focus": _SAMPLE["watchlist_focus"],
                "watchlist_favorites": _SAMPLE["watchlist_favorites"],
            },
        }
        apply_draft_source_state_from_ami(session, source)
        self.assertEqual(session[DRAFT_QUEUE_KEY], _SAMPLE["queue"])
        self.assertEqual(session[DRAFT_WATCHLIST_FOCUS_KEY], _SAMPLE["watchlist_focus"])
        self.assertFalse(is_draft_locally_dirty(session))

    def test_e_build_and_apply_source_state_roundtrip(self) -> None:
        session = {
            "active_page": "Draft Assistant Simulator",
            "draft_state": {
                "queue": _SAMPLE["queue"],
                "watchlist_focus": _SAMPLE["watchlist_focus"],
                "watchlist_favorites": _SAMPLE["watchlist_favorites"],
            },
            **{DRAFT_QUEUE_KEY: _SAMPLE["queue"]},
            DRAFT_WATCHLIST_FOCUS_KEY: _SAMPLE["watchlist_focus"],
        }
        built = build_source_state("Draft Assistant Simulator", session)
        self.assertEqual(built["entity_params"]["draft_queue"], _SAMPLE["queue"][:6])
        self.assertEqual(built["entity_params"]["watchlist_focus"], _SAMPLE["watchlist_focus"])
        target: dict = {DRAFT_QUEUE_KEY: []}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target[DRAFT_QUEUE_KEY], _SAMPLE["queue"][:6])

    def test_disk_blob_includes_draft_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Historical Explorer",
            "draft_state": {
                "queue": _SAMPLE["queue"],
                "watchlist_focus": _SAMPLE["watchlist_focus"],
                "watchlist_favorites": _SAMPLE["watchlist_favorites"],
            },
            DRAFT_QUEUE_KEY: _SAMPLE["queue"],
            DRAFT_WATCHLIST_FOCUS_KEY: _SAMPLE["watchlist_focus"],
            "page_filter_state": {},
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob["draft_state"]["queue"], _SAMPLE["queue"])
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("draft_workflow", {}).get("queue"), _SAMPLE["queue"])

    def test_draft_edit_bypasses_blank_comparison_cloud_block(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        st = MagicMock()
        st.session_state = {"comparison_state": {"players": []}, "compare_players": []}
        state = {"draft_state": {"queue": _SAMPLE["queue"]}}
        self.assertIsNone(_cloud_autosave_blocked_reason(st, "baseball", state, save_reason="draft_edit"))

    def test_clear_queue_marks_dirty_and_empty(self) -> None:
        session = {DRAFT_QUEUE_KEY: _SAMPLE["queue"]}
        write_canonical_draft_state(session, queue=_SAMPLE["queue"], reason="setup")
        clear_draft_queue(session, reason="clear_queue")
        self.assertEqual(session[DRAFT_QUEUE_KEY], [])
        self.assertTrue(is_draft_locally_dirty(session))

    def test_add_to_watchlist(self) -> None:
        session: dict = {}
        focus, added = add_player_to_watchlist(session, "Aaron Judge")
        self.assertTrue(added)
        self.assertEqual(focus, ["Aaron Judge"])
        self.assertIn("Aaron Judge", session[DRAFT_WATCHLIST_FOCUS_KEY])

    def test_sync_draft_queue_normalizes(self) -> None:
        session: dict = {}
        sync_draft_queue(session, ["B", "A", "B", ""], reason="test")
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["B", "A"])

    def test_draft_top_queue_player_updates_board_and_queue(self) -> None:
        import pandas as pd
        from draft_room_state import DRAFT_ROOM_EDITOR_VERSION_KEY, DRAFT_ROOM_TABLE_KEY, get_all_drafted_player_names, table_pick_count

        empty_board = pd.DataFrame(
            [{"Round": 1, "Pick": i + 1, "Team": f"Team {(i % 2) + 1}", "Player": ""} for i in range(8)]
        )
        session: dict = {
            "room_your_team": "Team 1",
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: empty_board,
            DRAFT_QUEUE_KEY: ["Aaron Judge", "Bobby Witt Jr.", "Julio Rodríguez"],
        }
        write_canonical_draft_state(session, queue=session[DRAFT_QUEUE_KEY], reason="setup")
        result = draft_top_queue_player(session)
        self.assertTrue(result.get("ok"))
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 1)
        self.assertIn("Aaron Judge", get_all_drafted_player_names(session))
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Bobby Witt Jr.", "Julio Rodríguez"])


if __name__ == "__main__":
    unittest.main()
