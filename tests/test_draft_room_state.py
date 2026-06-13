"""Tests for Draft Room Simulator persistence (draft_room_table)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from draft_room_state import (
    DRAFT_ROOM_EDITOR_CACHE_KEY,
    DRAFT_ROOM_EDITOR_SEED_KEY,
    DRAFT_ROOM_EDITOR_VERSION_KEY,
    DRAFT_ROOM_STATE_KEY,
    DRAFT_ROOM_TABLE_KEY,
    apply_cloud_draft_room_state_if_allowed,
    apply_restored_board_to_session,
    bump_editor_version,
    commit_draft_room_table,
    commit_draft_room_table_if_changed,
    draft_board_diagnostics,
    draft_room_restore_stats,
    detect_player_column,
    editor_widget_key,
    enrich_save_payload_with_draft_room,
    prepare_board_editor_for_render,
    prepare_draft_room_state,
    reconstruct_board_from_widget_state,
    resolve_active_board,
    save_draft_board_now,
    sanitize_state_dict_for_json,
    table_from_persist_dict,
    table_pick_count,
    table_picks_fingerprint,
    table_to_persist_dict,
    write_canonical_draft_room_state,
)


def _sample_table(*, picks: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(12):
        rows.append(
            {
                "Round": (i // 4) + 1,
                "Pick": i + 1,
                "Team": f"Team {(i % 4) + 1}",
                "Player": f"Player {i + 1}" if i < picks else "",
            }
        )
    return pd.DataFrame(rows)


class TestDraftRoomSerialization(unittest.TestCase):
    def test_table_roundtrips_through_json(self) -> None:
        table = _sample_table(picks=3)
        blob = table_to_persist_dict(table)
        self.assertEqual(blob["pick_count"], 3)
        raw = json.dumps(blob, ensure_ascii=False)
        parsed = json.loads(raw)
        restored = table_from_persist_dict(parsed)
        assert restored is not None
        self.assertEqual(table_pick_count(restored), 3)

    def test_sanitize_strips_runtime_dataframe(self) -> None:
        table = _sample_table(picks=2)
        state = {DRAFT_ROOM_TABLE_KEY: table}
        safe = sanitize_state_dict_for_json(state)
        self.assertIsInstance(safe[DRAFT_ROOM_TABLE_KEY], dict)
        self.assertIn("table_records", safe[DRAFT_ROOM_TABLE_KEY])


class TestDraftRoomPersistence(unittest.TestCase):
    def test_prepare_hydrates_from_canonical_blob(self) -> None:
        session: dict = {}
        table = _sample_table(picks=3)
        write_canonical_draft_room_state(session, table, reason="test")
        session.pop(DRAFT_ROOM_TABLE_KEY)
        restored = prepare_draft_room_state(session)
        assert restored is not None
        self.assertEqual(table_pick_count(restored), 3)

    def test_enrich_save_payload_injects_board(self) -> None:
        session: dict = {"active_page": "Draft Room Simulator"}
        table = _sample_table(picks=3)
        write_canonical_draft_room_state(session, table, reason="test")
        session[DRAFT_ROOM_TABLE_KEY] = table
        payload, diag = enrich_save_payload_with_draft_room(session, {"active_page": "Draft Room Simulator"})
        self.assertTrue(diag["payload_has_draft_board"])
        self.assertEqual(diag["cloud_payload_pick_count"], 3)
        self.assertEqual(table_pick_count(payload[DRAFT_ROOM_STATE_KEY]), 3)

    def test_draft_board_diagnostics_points_at_simulator(self) -> None:
        session: dict = {"active_page": "Draft Room Simulator"}
        table = _sample_table(picks=3)
        session[DRAFT_ROOM_TABLE_KEY] = table
        write_canonical_draft_room_state(session, table, reason="test")
        diag = draft_board_diagnostics(session)
        self.assertEqual(diag["active_draft_page"], "Draft Room Simulator")
        self.assertEqual(diag["draft_board_source_key"], DRAFT_ROOM_TABLE_KEY)
        self.assertTrue(diag["session_has_draft_board"])
        self.assertEqual(diag["session_pick_count"], 3)

    def test_apply_cloud_respects_local_dirty(self) -> None:
        session: dict = {"draft_room_state_dirty": True}
        table = _sample_table(picks=2)
        cloud = {DRAFT_ROOM_STATE_KEY: table_to_persist_dict(table)}
        self.assertFalse(apply_cloud_draft_room_state_if_allowed(session, cloud))

    def test_apply_cloud_restores_when_clean(self) -> None:
        session: dict = {}
        table = _sample_table(picks=2)
        cloud = {DRAFT_ROOM_STATE_KEY: table_to_persist_dict(table)}
        self.assertTrue(apply_cloud_draft_room_state_if_allowed(session, cloud))
        self.assertEqual(draft_room_restore_stats(session)["pick_count"], 2)

    def test_build_and_apply_disk_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Draft Room Simulator",
            "main_sidebar_page": "Draft Room Simulator",
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=3),
            "room_your_team": "Team 1",
            "room_team_count": 4,
            "room_rounds": 3,
            "room_format": "Snake",
        }
        state = build_baseball_disk_state(st)
        self.assertGreaterEqual(draft_room_restore_stats(state)["pick_count"], 3)
        st2 = MagicMock()
        st2.session_state = {"active_page": "Draft Room Simulator", "main_sidebar_page": "Draft Room Simulator"}
        apply_baseball_disk_state(st2, state)
        self.assertEqual(draft_room_restore_stats(st2.session_state)["pick_count"], 3)

    @patch("draft_room_state.force_save_baseball_state", create=True)
    def test_commit_triggers_force_save(self, mock_force: MagicMock) -> None:
        mock_force.return_value = True
        st = MagicMock()
        session: dict = {"active_page": "Draft Room Simulator"}
        table = _sample_table(picks=1)
        with patch("baseball_persistent_state.force_save_baseball_state", mock_force):
            trace = commit_draft_room_table(st, session, table, reason="board_edit")
        mock_force.assert_called_once()
        self.assertEqual(trace.get("draft_board_source_key"), DRAFT_ROOM_TABLE_KEY)
        self.assertEqual(trace.get("commit_input_pick_count"), 1)

    def test_prepare_does_not_clobber_runtime_picks_with_empty_blob(self) -> None:
        session: dict = {
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=2),
            DRAFT_ROOM_STATE_KEY: table_to_persist_dict(_sample_table(picks=0)),
        }
        restored = prepare_draft_room_state(session)
        assert restored is not None
        self.assertEqual(table_pick_count(restored), 2)

    def test_commit_if_changed_skips_empty_board(self) -> None:
        st = MagicMock()
        session: dict = {"active_page": "Draft Room Simulator"}
        table = _sample_table(picks=0)
        with patch("baseball_persistent_state.force_save_baseball_state") as mock_force:
            trace = commit_draft_room_table_if_changed(st, session, table, reason="board_edit")
        mock_force.assert_not_called()
        self.assertEqual(trace.get("skipped"), "no_picks_yet")

    def test_picks_fingerprint_ignores_empty_rows(self) -> None:
        empty = _sample_table(picks=0)
        one = _sample_table(picks=1)
        self.assertNotEqual(table_picks_fingerprint(empty), table_picks_fingerprint(one))

    def test_save_draft_board_now_reads_editor(self) -> None:
        st = MagicMock()
        table = _sample_table(picks=3)
        session: dict = {
            "active_page": "Draft Room Simulator",
            DRAFT_ROOM_EDITOR_CACHE_KEY: table,
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
        }
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True) as mock_force:
            with patch("suite_cloud_state.load_cloud_full_session", return_value=({}, "2026-01-01T00:00:00Z")):
                trace = save_draft_board_now(st, session, board=table)
        mock_force.assert_called_once()
        self.assertEqual(trace.get("saved_pick_count"), 3)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 3)

    def test_editor_widget_key_is_versioned(self) -> None:
        session = {DRAFT_ROOM_EDITOR_VERSION_KEY: 2}
        self.assertEqual(editor_widget_key(session), "draft_room_board_editor_2")

    def test_apply_restored_board_bumps_version(self) -> None:
        session: dict = {DRAFT_ROOM_EDITOR_VERSION_KEY: 0}
        table = _sample_table(picks=2)
        apply_restored_board_to_session(session, table)
        self.assertEqual(session[DRAFT_ROOM_EDITOR_VERSION_KEY], 1)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_EDITOR_SEED_KEY]), 2)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_EDITOR_CACHE_KEY]), 2)

    def test_reconstruct_board_from_edited_rows(self) -> None:
        base = _sample_table(picks=0)
        widget_state = {
            "edited_rows": {
                0: {"Player": "Aaron Judge"},
                1: {"Player": "Juan Soto"},
                2: {"Player": "Corbin Carroll"},
            },
            "added_rows": [],
            "deleted_rows": [],
        }
        reconstructed = reconstruct_board_from_widget_state(widget_state, base)
        self.assertEqual(table_pick_count(reconstructed), 3)

    def test_resolve_active_board_reconstructs_widget_dict(self) -> None:
        st = MagicMock()
        widget_key = "draft_room_board_editor_1"
        base = _sample_table(picks=0)
        st.session_state = {
            widget_key: {
                "edited_rows": {0: {"Player": "Player 1"}, 1: {"Player": "Player 2"}, 2: {"Player": "Player 3"}},
                "added_rows": [],
                "deleted_rows": [],
            }
        }
        session: dict = {DRAFT_ROOM_EDITOR_SEED_KEY: base}
        active, source, count = resolve_active_board(session, widget_key, base, st=st)
        assert active is not None
        self.assertEqual(count, 3)
        self.assertTrue(source.startswith("widget_reconstructed:"))

    def test_detect_player_column_finds_player(self) -> None:
        table = _sample_table(picks=2)
        self.assertEqual(detect_player_column(table), "Player")


if __name__ == "__main__":
    unittest.main()
