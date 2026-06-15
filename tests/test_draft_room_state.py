"""Tests for Draft Room Simulator persistence (draft_room_table)."""

from __future__ import annotations

import json
import copy
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from draft_state import DRAFT_QUEUE_KEY, write_canonical_draft_state
from draft_room_state import (
    ACTIVE_DRAFT_MODE_LIVE,
    ACTIVE_DRAFT_MODE_MANUAL,
    CANONICAL_DRAFT_META_KEY,
    DRAFT_ROOM_DIRTY_KEY,
    DRAFT_ROOM_EDITOR_CACHE_KEY,
    DRAFT_ROOM_EDITOR_SEED_KEY,
    DRAFT_ROOM_EDITOR_VERSION_KEY,
    DRAFT_ROOM_STATE_KEY,
    DRAFT_ROOM_TABLE_KEY,
    MANUAL_SAVE_REQUEST_KEY,
    add_player_to_next_open_pick,
    apply_cloud_draft_room_state_if_allowed,
    apply_programmatic_board_update,
    apply_restored_board_to_session,
    assign_player_to_board_row,
    bump_editor_version,
    build_snake_board,
    coerce_board_table,
    commit_draft_room_table,
    commit_draft_room_table_if_changed,
    capture_board_from_data_editor,
    draft_board_diagnostics,
    draft_room_restore_stats,
    detect_player_column,
    delete_live_draft_only,
    _draft_room_from_blob,
    editor_widget_key,
    effective_board_pick_count,
    enrich_save_payload_with_draft_room,
    effective_board_pick_count,
    get_canonical_draft_board,
    get_canonical_draft_meta,
    delete_active_draft,
    is_board_editor_widget_key,
    get_all_drafted_player_names,
    open_pick_row_options,
    paste_players_to_board,
    pick_label_row_map,
    record_board_assignment_diagnostics,
    record_board_assign_submit_trace,
    reset_simulator_board_only,
    submit_board_pick_assignment,
    sync_board_to_session_keys,
    prepare_board_editor_for_render,
    prepare_draft_room_state,
    preserve_richer_session_board,
    reconstruct_board_from_widget_state,
    reset_canonical_draft_board,
    record_manual_save_button_click,
    resolve_active_board,
    save_draft_board_now,
    persist_draft_board_to_storage,
    sanitize_state_dict_for_json,
    sync_live_draft_room_to_canonical_board,
    set_canonical_draft_meta,
    table_from_persist_dict,
    table_pick_count,
    table_picks_fingerprint,
    table_to_persist_dict,
    verify_json_serializable,
    widget_state_has_edits,
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

    def test_sanitize_strips_editor_cache_from_page_filter(self) -> None:
        table = _sample_table(picks=3)
        state = {
            DRAFT_ROOM_TABLE_KEY: table,
            "page_filter_state": {
                "Draft Room Simulator": {
                    DRAFT_ROOM_TABLE_KEY: table,
                    DRAFT_ROOM_EDITOR_CACHE_KEY: table.copy(),
                    DRAFT_ROOM_EDITOR_SEED_KEY: table.copy(),
                }
            },
        }
        diag: dict = {}
        safe = sanitize_state_dict_for_json(state, diag=diag)
        block = safe["page_filter_state"]["Draft Room Simulator"]
        self.assertNotIn(DRAFT_ROOM_EDITOR_CACHE_KEY, block)
        self.assertNotIn(DRAFT_ROOM_EDITOR_SEED_KEY, block)
        self.assertIsInstance(block[DRAFT_ROOM_TABLE_KEY], dict)
        ok, err, offenders = verify_json_serializable(safe)
        self.assertTrue(ok, msg=f"{err} offenders={offenders}")
        self.assertEqual(diag.get("payload_pick_count_after_sanitize"), 3)
        self.assertIn("draft_room_table", diag.get("dataframe_keys_in_payload") or [])

    def test_build_disk_state_is_strict_json_serializable(self) -> None:
        st = MagicMock()
        table = _sample_table(picks=3)
        st.session_state = {
            "active_page": "Draft Room Simulator",
            "main_sidebar_page": "Draft Room Simulator",
            DRAFT_ROOM_TABLE_KEY: table,
            DRAFT_ROOM_EDITOR_CACHE_KEY: table.copy(),
            DRAFT_ROOM_EDITOR_SEED_KEY: table.copy(),
            DRAFT_ROOM_EDITOR_VERSION_KEY: 1,
            "page_filter_state": {
                "Draft Room Simulator": {
                    DRAFT_ROOM_EDITOR_CACHE_KEY: table.copy(),
                }
            },
            "room_your_team": "Team 1",
            "room_team_count": 4,
            "room_rounds": 3,
            "room_format": "Snake",
        }
        state = build_baseball_disk_state(st)
        ok, err, offenders = verify_json_serializable(state)
        self.assertTrue(ok, msg=f"{err} offenders={offenders}")
        self.assertGreaterEqual(draft_room_restore_stats(state)["pick_count"], 3)


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
        self.assertEqual(diag["draft_board_source_key"], DRAFT_ROOM_STATE_KEY)
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
        self.assertEqual(trace.get("draft_board_source_key"), DRAFT_ROOM_STATE_KEY)
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
        self.assertTrue(trace.get("save_button_clicked"))

    def test_record_manual_save_button_click_stamps_session(self) -> None:
        session: dict = {}
        stub = record_manual_save_button_click(session)
        self.assertTrue(stub.get("save_button_clicked"))
        self.assertTrue(session.get("save_button_clicked"))
        self.assertTrue(session.get("save_button_timestamp"))
        self.assertTrue(session.get(MANUAL_SAVE_REQUEST_KEY))
        self.assertEqual(session["_draft_room_manual_save_result"]["path"], "save_draft_board_now")

    def test_save_draft_board_now_always_attempts_direct_cloud(self) -> None:
        st = MagicMock()
        table = _sample_table(picks=3)
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: table,
        }

        def _fake_force(_st: MagicMock, *, reason: str = "") -> bool:
            session["_suite_persist_last_save_disk"] = True
            session["_suite_persist_last_save_cloud"] = True
            session["payload_has_draft_board"] = True
            session["cloud_payload_pick_count"] = 3
            return True

        with patch("baseball_persistent_state.force_save_baseball_state", side_effect=_fake_force):
            with patch("suite_cloud_state.load_cloud_full_session", return_value=({}, "2026-01-01T00:00:00Z")):
                with patch(
                    "draft_room_state.save_draft_board_direct_to_cloud",
                    return_value={
                        "saved_cloud": True,
                        "cloud_payload_pick_count": 3,
                        "payload_has_draft_board": True,
                        "cloud_timestamp_after": "2026-06-13T03:00:00Z",
                        "supabase_row_pick_count_after_write": 3,
                    },
                ) as mock_direct:
                    trace = save_draft_board_now(st, session, board=table)
        mock_direct.assert_called_once()
        self.assertTrue(trace.get("direct_cloud_save_attempted"))
        self.assertTrue(trace.get("direct_cloud_save_ok"))
        self.assertTrue(trace.get("saved_cloud"))
        self.assertEqual(trace.get("saved_pick_count"), 3)

    def test_enrich_save_payload_uses_richest_runtime_board(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=3),
            DRAFT_ROOM_STATE_KEY: {
                "_persist_schema": 1,
                "table_records": [],
                "table_columns": ["Round", "Pick", "Team", "Player"],
                "pick_count": 0,
            },
        }
        state: dict = {"active_page": "Draft Room Simulator"}
        out, diag = enrich_save_payload_with_draft_room(session, state)
        self.assertTrue(diag.get("payload_has_draft_board"))
        self.assertEqual(diag.get("cloud_payload_pick_count"), 3)
        self.assertEqual(table_pick_count(out.get(DRAFT_ROOM_STATE_KEY)), 3)

    def test_manual_save_survives_disk_refresh(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Draft Room Simulator",
            "main_sidebar_page": "Draft Room Simulator",
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            "room_team_names": "Team 1\nTeam 2",
            "room_rounds": 5,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=3),
        }
        table = st.session_state[DRAFT_ROOM_TABLE_KEY]
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True):
            with patch("suite_cloud_state.load_cloud_full_session", return_value=({}, "2026-01-01T00:00:00Z")):
                trace = save_draft_board_now(st, st.session_state, board=table)
        self.assertEqual(trace.get("saved_pick_count"), 3)
        disk_state = build_baseball_disk_state(st)
        st2 = MagicMock()
        st2.session_state = {"active_page": "Draft Room Simulator", "main_sidebar_page": "Draft Room Simulator"}
        apply_baseball_disk_state(st2, disk_state)
        prepare_draft_room_state(st2.session_state)
        self.assertEqual(len(get_all_drafted_player_names(st2.session_state)), 3)

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

    def test_reconstruct_board_from_numeric_column_indexes(self) -> None:
        base = _sample_table(picks=0)
        player_col_idx = list(base.columns).index("Player")
        widget_state = {
            "edited_rows": {
                0: {player_col_idx: "Aaron Judge"},
                1: {str(player_col_idx): "Juan Soto"},
                2: {"3": "Corbin Carroll"},
            },
            "added_rows": [],
            "deleted_rows": [],
        }
        reconstructed = reconstruct_board_from_widget_state(widget_state, base)
        self.assertEqual(table_pick_count(reconstructed), 3)
        self.assertEqual(reconstructed.at[0, "Player"], "Aaron Judge")

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

    def test_widget_state_has_edits_false_when_empty(self) -> None:
        self.assertFalse(widget_state_has_edits({"edited_rows": {}, "added_rows": [], "deleted_rows": []}))
        self.assertTrue(widget_state_has_edits({"edited_rows": {0: {"Player": "A"}}, "added_rows": [], "deleted_rows": []}))

    def test_resolve_prefers_table_when_widget_has_no_edits(self) -> None:
        st = MagicMock()
        widget_key = "draft_room_board_editor_1"
        filled = _sample_table(picks=3)
        st.session_state = {
            widget_key: {"edited_rows": {}, "added_rows": [], "deleted_rows": []},
        }
        session: dict = {
            DRAFT_ROOM_EDITOR_SEED_KEY: filled,
            DRAFT_ROOM_TABLE_KEY: filled,
        }
        active, source, count = resolve_active_board(session, widget_key, filled, st=st)
        assert active is not None
        self.assertEqual(count, 3)
        self.assertIn("draft_room_table", source)

    def test_apply_programmatic_board_update_syncs_seed(self) -> None:
        session: dict = {DRAFT_ROOM_EDITOR_VERSION_KEY: 0}
        table = _sample_table(picks=2)
        out = apply_programmatic_board_update(session, table, bump_widget=False)
        self.assertEqual(table_pick_count(out), 2)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 2)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_EDITOR_SEED_KEY]), 2)
        self.assertTrue(session.get(DRAFT_ROOM_DIRTY_KEY))

    def test_log_quick_draft_pick_adds_player(self) -> None:
        """Legacy quick-draft path still adds via next-open-pick (deprecated UI)."""
        session: dict = {DRAFT_ROOM_EDITOR_VERSION_KEY: 0, DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0)}
        res = add_player_to_next_open_pick(session, "Aaron Judge")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("after_pick_count"), 1)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 1)

    def test_preserve_richer_session_board_keeps_runtime(self) -> None:
        session: dict = {DRAFT_ROOM_TABLE_KEY: _sample_table(picks=2)}
        empty = _sample_table(picks=0)
        out, count, note = preserve_richer_session_board(session, empty, 0)
        assert out is not None
        self.assertEqual(count, 2)
        self.assertEqual(note, "preserved_session_table")


class TestCanonicalDraftBoard(unittest.TestCase):
    def test_add_player_to_next_open_pick(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
        }
        res = add_player_to_next_open_pick(session, "Aaron Judge")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("after_pick_count"), 1)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 1)
        self.assertEqual(session[DRAFT_ROOM_TABLE_KEY].loc[0, "Player"], "Aaron Judge")

    def test_paste_players_to_board(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
        }
        text = "1. Aaron Judge\n2. Bobby Witt Jr.\n3. Juan Soto"
        res = paste_players_to_board(session, text)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("added_count"), 3)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 3)

    def test_reset_canonical_draft_board(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            "room_team_names": "Alpha\nBeta",
            "room_rounds": 2,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=5),
        }
        out = reset_canonical_draft_board(session)
        self.assertEqual(table_pick_count(out), 0)
        self.assertEqual(len(out), 4)
        meta = session.get(CANONICAL_DRAFT_META_KEY) or {}
        self.assertEqual(meta.get("pick_count"), 0)

    def test_sync_live_draft_room_to_canonical_board(self) -> None:
        session: dict = {DRAFT_ROOM_EDITOR_VERSION_KEY: 0}
        room = {
            "status": "in_progress",
            "teams": ["Team A", "Team B"],
            "config": {"picks_per_team": 2, "your_team": "Team A"},
            "pick_order": [
                {"Round": 1, "Pick": 1, "Team": "Team A"},
                {"Round": 1, "Pick": 2, "Team": "Team B"},
                {"Round": 2, "Pick": 3, "Team": "Team B"},
                {"Round": 2, "Pick": 4, "Team": "Team A"},
            ],
            "draft_board": [
                {"Pick": 1, "fullName": "Aaron Judge", "Fantasy Team": "Team A"},
                {"Pick": 2, "fullName": "Bobby Witt Jr.", "Fantasy Team": "Team B"},
            ],
        }
        out = sync_live_draft_room_to_canonical_board(session, room)
        self.assertEqual(table_pick_count(out), 2)
        self.assertEqual(session.get("room_team_count"), 2)
        meta = session.get(CANONICAL_DRAFT_META_KEY) or {}
        self.assertEqual(meta.get("active_mode"), ACTIVE_DRAFT_MODE_LIVE)

    def test_get_canonical_draft_board_unifies_runtime(self) -> None:
        session: dict = {}
        table = _sample_table(picks=2)
        write_canonical_draft_room_state(session, table, reason="test")
        board = get_canonical_draft_board(session)
        self.assertEqual(table_pick_count(board), 2)

    def test_coerce_board_table_from_persisted_blob(self) -> None:
        table = _sample_table(picks=2)
        blob = table_to_persist_dict(table)
        session = {DRAFT_ROOM_TABLE_KEY: copy.deepcopy(blob), DRAFT_ROOM_STATE_KEY: copy.deepcopy(blob)}
        coerced = coerce_board_table(session[DRAFT_ROOM_TABLE_KEY])
        self.assertIsInstance(coerced, pd.DataFrame)
        self.assertEqual(table_pick_count(coerced), 2)
        board = get_canonical_draft_board(session)
        self.assertIsInstance(board, pd.DataFrame)
        self.assertEqual(table_pick_count(board), 2)
        self.assertTrue(hasattr(session[DRAFT_ROOM_TABLE_KEY], "to_dict"))

    def test_prepare_draft_room_state_coerces_blob_session_key(self) -> None:
        table = _sample_table(picks=1)
        blob = table_to_persist_dict(table)
        session = {DRAFT_ROOM_TABLE_KEY: copy.deepcopy(blob)}
        out = prepare_draft_room_state(session)
        self.assertIsInstance(out, pd.DataFrame)
        self.assertIsInstance(session[DRAFT_ROOM_TABLE_KEY], pd.DataFrame)
        self.assertEqual(table_pick_count(out), 1)


    def test_canonical_meta_persists_in_blob(self) -> None:
        session: dict = {}
        table = _sample_table(picks=2)
        set_canonical_draft_meta(session, mode=ACTIVE_DRAFT_MODE_MANUAL, source="test", pick_count=2)
        write_canonical_draft_room_state(session, table, reason="test")
        blob = session[DRAFT_ROOM_STATE_KEY]
        self.assertIn("canonical_draft_meta", blob)
        self.assertEqual(blob["canonical_draft_meta"].get("pick_count"), 2)

        session2: dict = {DRAFT_ROOM_STATE_KEY: copy.deepcopy(blob)}
        restored = prepare_draft_room_state(session2)
        assert restored is not None
        self.assertEqual(table_pick_count(restored), 2)
        self.assertEqual(session2.get(CANONICAL_DRAFT_META_KEY, {}).get("pick_count"), 2)

    def test_acceptance_three_players_survive_disk_refresh(self) -> None:
        """Simulate: paste 3 players → save to disk → fresh session (browser refresh)."""
        st = MagicMock()
        st.session_state = {
            "active_page": "Draft Room Simulator",
            "main_sidebar_page": "Draft Room Simulator",
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            "room_team_names": "Team 1\nTeam 2",
            "room_rounds": 5,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
        }
        res = paste_players_to_board(
            st.session_state,
            "Aaron Judge\nBobby Witt Jr.\nJuan Soto",
        )
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("added_count"), 3)

        disk_state = build_baseball_disk_state(st)
        st2 = MagicMock()
        st2.session_state = {"active_page": "Draft Room Simulator", "main_sidebar_page": "Draft Room Simulator"}
        apply_baseball_disk_state(st2, disk_state)
        prepare_draft_room_state(st2.session_state)
        names = get_all_drafted_player_names(st2.session_state)
        self.assertEqual(len(names), 3)
        self.assertIn("Aaron Judge", names)

    def test_acceptance_three_players_survive_cloud_cross_device(self) -> None:
        """Simulate: phone saves 3 picks → cloud payload → Dell restores."""
        phone_session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            "room_team_names": "Team 1\nTeam 2",
            "room_rounds": 5,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
        }
        paste_players_to_board(phone_session, "Aaron Judge\nBobby Witt Jr.\nJuan Soto")
        write_canonical_draft_room_state(phone_session, phone_session[DRAFT_ROOM_TABLE_KEY], reason="phone_save")

        cloud_payload, diag = enrich_save_payload_with_draft_room(phone_session, {"active_page": "Draft Room Simulator"})
        self.assertTrue(diag["payload_has_draft_board"])
        self.assertEqual(diag["cloud_payload_pick_count"], 3)

        dell_session: dict = {"active_page": "Draft Room Simulator"}
        self.assertTrue(apply_cloud_draft_room_state_if_allowed(dell_session, cloud_payload))
        prepare_draft_room_state(dell_session)
        names = get_all_drafted_player_names(dell_session)
        self.assertEqual(len(names), 3)


class TestEditorCapture(unittest.TestCase):
    def test_capture_prefers_editor_return(self) -> None:
        base = _sample_table(picks=0)
        edited = _sample_table(picks=2)
        session: dict = {
            DRAFT_ROOM_TABLE_KEY: base,
            DRAFT_ROOM_EDITOR_CACHE_KEY: base.copy(),
        }
        captured, count, source = capture_board_from_data_editor(
            session, "draft_room_board_editor_0", edited
        )
        self.assertEqual(count, 2)
        self.assertEqual(source, "editor_return")

    def test_capture_reconstructs_widget_edited_rows(self) -> None:
        base = _sample_table(picks=0)
        session: dict = {
            DRAFT_ROOM_TABLE_KEY: base,
            DRAFT_ROOM_EDITOR_SEED_KEY: base.copy(),
            "draft_room_board_editor_0": {
                "edited_rows": {0: {"Player": "Aaron Judge"}, 2: {"Player": "Juan Soto"}},
                "added_rows": [],
                "deleted_rows": [],
            },
        }
        st = MagicMock()
        st.session_state = session
        captured, count, source = capture_board_from_data_editor(
            session, "draft_room_board_editor_0", base, st=st
        )
        self.assertEqual(count, 2)
        self.assertIn("widget_reconstructed", source)
        self.assertEqual(captured.at[0, "Player"], "Aaron Judge")

    def test_is_board_editor_widget_key_excludes_cache(self) -> None:
        self.assertTrue(is_board_editor_widget_key("draft_room_board_editor_0"))
        self.assertFalse(is_board_editor_widget_key(DRAFT_ROOM_EDITOR_CACHE_KEY))


class TestPickRestoreDraftRoom(unittest.TestCase):
    def test_disk_board_beats_newer_empty_cloud(self) -> None:
        from suite_cloud_state import pick_restore_session

        table = _sample_table(picks=3)
        blob = table_to_persist_dict(table)
        cloud = {
            "active_page": "Draft Room Simulator",
            DRAFT_ROOM_STATE_KEY: table_to_persist_dict(_sample_table(picks=0)),
        }
        disk = {"active_page": "Draft Room Simulator", DRAFT_ROOM_STATE_KEY: blob}
        picked = pick_restore_session(
            cloud,
            "2026-06-13T02:00:00+00:00",
            disk,
            "2026-06-13T01:00:00+00:00",
            cloud_first=True,
        )
        self.assertEqual(picked.source, "disk")
        self.assertIn("draft room", picked.reason.lower())


class TestDraftRoomSyncGuards(unittest.TestCase):
    def test_sync_does_not_clobber_blob_when_runtime_empty(self) -> None:
        from draft_room_state import sync_draft_room_session_before_save

        table = _sample_table(picks=3)
        session: dict = {
            "room_team_names": "Team 1\nTeam 2",
            "room_rounds": 5,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
        }
        write_canonical_draft_room_state(session, table, reason="test")
        sync_draft_room_session_before_save(session)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_STATE_KEY]), 3)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 3)

    def test_prepare_dirty_restores_from_blob_when_runtime_empty(self) -> None:
        table = _sample_table(picks=3)
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_DIRTY_KEY: True,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
            "room_team_names": "Team 1\nTeam 2",
            "room_rounds": 5,
        }
        write_canonical_draft_room_state(session, table, reason="test")
        restored = prepare_draft_room_state(session)
        self.assertEqual(table_pick_count(restored), 3)

    def test_paste_fills_next_open_picks_after_existing(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            "room_team_names": "Team 1\nTeam 2",
            "room_rounds": 5,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=5),
        }
        res = paste_players_to_board(session, "Aaron Judge\nJuan Soto\nShohei Ohtani")
        self.assertTrue(res.get("ok"))
        table = session[DRAFT_ROOM_TABLE_KEY]
        filled = table[table["Player"].astype(str).str.strip() != ""]
        self.assertEqual(len(filled), 8)
        self.assertEqual(str(filled.iloc[5]["Player"]), "Aaron Judge")


    def test_delete_live_draft_only_keeps_board(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=3),
            "live_draft_room": {"status": "completed", "draft_room_id": "X1"},
            CANONICAL_DRAFT_META_KEY: {"active_mode": ACTIVE_DRAFT_MODE_LIVE},
        }
        trace = delete_live_draft_only(session)
        self.assertTrue(trace.get("cleared_live"))
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 3)
        self.assertIsNone(session.get("live_draft_room"))
        pf = session.get("page_filter_state", {}).get("Live Draft Room", {})
        self.assertNotIn("live_draft_room", pf)


class TestBoardTeamSync(unittest.TestCase):
    def test_board_team_names_match(self) -> None:
        import pandas as pd

        from draft_room_state import board_team_names_match, rebuild_simulator_board_for_teams

        table = pd.DataFrame(
            [
                {"Round": 1, "Pick": 1, "Team": "Team A", "Player": ""},
                {"Round": 1, "Pick": 2, "Team": "Team B", "Player": ""},
            ]
        )
        self.assertFalse(board_team_names_match(table, ["Daniel", "Team 2"]))
        session = {
            "room_team_names": "Daniel\nTeam 2",
            "room_rounds": 1,
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
        }
        out = rebuild_simulator_board_for_teams(session)
        self.assertTrue(board_team_names_match(out, ["Daniel", "Team 2"]))


class TestDeleteActiveDraft(unittest.TestCase):
    def test_delete_active_draft_clears_board_and_live(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=3),
            "live_draft_room": {"status": "completed", "draft_room_id": "X1"},
            DRAFT_QUEUE_KEY: ["Aaron Judge"],
        }
        write_canonical_draft_state(session, queue=["Aaron Judge"], reason="setup")
        trace = delete_active_draft(session)
        self.assertTrue(trace.get("ok"))
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 0)
        self.assertEqual(session.get(DRAFT_QUEUE_KEY), [])

    def test_reset_simulator_only_keeps_live_record(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=2),
            "live_draft_room": {"status": "completed", "draft_room_id": "X1", "draft_board": [{"Pick": 1}]},
        }
        reset_simulator_board_only(session)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 0)
        self.assertIsNotNone(session.get("live_draft_room"))


class TestBoardPickAssignment(unittest.TestCase):
    def test_open_pick_row_options_lists_empty_slots(self) -> None:
        table = _sample_table(picks=2)
        options = open_pick_row_options(table)
        self.assertEqual(len(options), 10)
        self.assertIn("Pick 3", options[0][1])

    def test_assign_player_to_board_row_sets_player_and_diagnostics(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
        }
        res = assign_player_to_board_row(session, 0, "Aaron Judge")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("after_pick_count"), 1)
        self.assertEqual(str(session[DRAFT_ROOM_TABLE_KEY].iloc[0]["Player"]), "Aaron Judge")
        dbg = session.get("_draft_room_widget_capture_debug")
        self.assertIsInstance(dbg, dict)
        self.assertEqual(dbg.get("capture_pick_count"), 1)
        self.assertEqual(session.get("_draft_room_active_board_pick_count"), 1)

    def test_assign_player_rejects_duplicate(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=1),
        }
        res = assign_player_to_board_row(session, 1, "Player 1")
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "duplicate")

    def test_record_board_assignment_diagnostics(self) -> None:
        session: dict = {}
        record_board_assignment_diagnostics(session, pick_count=2, source="board_display")
        dbg = session["_draft_room_widget_capture_debug"]
        self.assertEqual(dbg["capture_pick_count"], 2)
        self.assertEqual(dbg["capture_source"], "board_display")

    def test_submit_board_pick_assignment_records_trace_and_writes_board(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
        }
        table = session[DRAFT_ROOM_TABLE_KEY]
        row_map = pick_label_row_map(table)
        pick_label = next(iter(row_map.keys()))
        res = submit_board_pick_assignment(
            session,
            pick_label=pick_label,
            player_match="Aaron Judge",
            pick_row_by_label=row_map,
            search_text="Judge",
        )
        self.assertTrue(res.get("ok"))
        trace = session["_draft_room_assign_submit_trace"]
        self.assertTrue(trace.get("assignment_button_clicked"))
        self.assertEqual(trace.get("selected_player_match"), "Aaron Judge")
        self.assertEqual(trace.get("selected_player_official_name"), "Aaron Judge")
        self.assertTrue(trace.get("assign_player_to_board_row_called"))
        self.assertEqual(trace.get("before_pick_count"), 0)
        self.assertEqual(trace.get("after_pick_count"), 1)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_TABLE_KEY]), 1)

    def test_assign_promotes_cache_to_draft_room_state(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_VERSION_KEY: 0,
            DRAFT_ROOM_TABLE_KEY: _sample_table(picks=0),
            DRAFT_ROOM_STATE_KEY: {
                "_persist_schema": 1,
                "table_records": [],
                "table_columns": ["Round", "Pick", "Team", "Player"],
                "pick_count": 0,
            },
        }
        res = assign_player_to_board_row(session, 0, "Aaron Judge")
        self.assertTrue(res.get("ok"))
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_STATE_KEY]), 1)
        self.assertEqual(table_pick_count(session[DRAFT_ROOM_EDITOR_CACHE_KEY]), 1)
        self.assertEqual(get_canonical_draft_meta(session).get("pick_count"), 1)
        self.assertTrue(session.get("local_has_draft_room_board"))
        stats = draft_room_restore_stats(session)
        self.assertEqual(stats["pick_count"], 1)

    def test_draft_room_restore_stats_prefers_cache_over_empty_blob(self) -> None:
        session: dict = {
            DRAFT_ROOM_EDITOR_CACHE_KEY: _sample_table(picks=3),
            DRAFT_ROOM_STATE_KEY: {
                "_persist_schema": 1,
                "table_records": [],
                "table_columns": ["Round", "Pick", "Team", "Player"],
                "pick_count": 0,
            },
        }
        stats = draft_room_restore_stats(session)
        self.assertEqual(stats["pick_count"], 3)
        self.assertTrue(stats["has_draft_board"])
        blob = _draft_room_from_blob(session)
        self.assertEqual(table_pick_count(blob), 3)


if __name__ == "__main__":
    unittest.main()
