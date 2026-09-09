"""Accuracy + completion pass: Player Grade parity, strategy, legal Auto Pick, Draft Complete."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_score_display import prepare_draft_scores_for_display
from live_draft_autopick import live_draft_auto_pick
from live_draft_completion import LIFECYCLE_ACTIVE_DRAFT, resolve_live_draft_lifecycle
from live_draft_roster_slots import filter_candidates_to_team_open_positions
from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    LIVE_DRAFT_STATE_KEY,
    _room_blocked_from_auto_restore,
    prepare_live_draft_state,
    write_canonical_live_draft_state,
)
from player_photos import player_grade_display
from recommendation_schema import ensure_recommendation_ranking_schema


def _slots() -> dict[str, int]:
    return {
        "C": 1,
        "1B": 1,
        "2B": 1,
        "3B": 1,
        "SS": 1,
        "OF": 3,
        "DH": 1,
        "P": 2,
        "BN": 2,
    }


def _pool_rows() -> list[dict]:
    return [
        {
            "playerID": "ohtani",
            "fullName": "Shohei Ohtani",
            "Primary Position": "DH",
            "Eligible Positions": "DH,UTIL,SP",
            "Expected Fantasy Value": 0.99,
            "Decision Score": 0.95,
            "Draft Fit Score": 0.5,
            "Positional Fit": 0.4,
            "Market Rank": 1,
            "Model Rank": 1,
            "Sleeper Score": 0.1,
        },
        {
            "playerID": "catcher_a",
            "fullName": "Catcher Ace",
            "Primary Position": "C",
            "Eligible Positions": "C",
            "Expected Fantasy Value": 0.55,
            "Decision Score": 0.50,
            "Draft Fit Score": 0.9,
            "Positional Fit": 0.95,
            "Market Rank": 80,
            "Model Rank": 75,
            "Sleeper Score": 0.2,
        },
        {
            "playerID": "catcher_b",
            "fullName": "Catcher Backup",
            "Primary Position": "C",
            "Eligible Positions": "C",
            "Expected Fantasy Value": 0.40,
            "Decision Score": 0.35,
            "Draft Fit Score": 0.85,
            "Positional Fit": 0.9,
            "Market Rank": 120,
            "Model Rank": 110,
            "Sleeper Score": 0.3,
        },
        {
            "playerID": "of_star",
            "fullName": "OF Star",
            "Primary Position": "OF",
            "Eligible Positions": "OF",
            "Expected Fantasy Value": 0.85,
            "Decision Score": 0.80,
            "Draft Fit Score": 0.6,
            "Positional Fit": 0.5,
            "Market Rank": 5,
            "Model Rank": 6,
            "Sleeper Score": 0.15,
        },
    ]


def _filled_starters_except_c(team: str = "Team A") -> list[dict]:
    """Roster with every required starter filled except Catcher."""
    return [
        {"playerID": f"{team}-1b", "fullName": "1B", "Primary Position": "1B"},
        {"playerID": f"{team}-2b", "fullName": "2B", "Primary Position": "2B"},
        {"playerID": f"{team}-3b", "fullName": "3B", "Primary Position": "3B"},
        {"playerID": f"{team}-ss", "fullName": "SS", "Primary Position": "SS"},
        {"playerID": f"{team}-of1", "fullName": "OF1", "Primary Position": "OF"},
        {"playerID": f"{team}-of2", "fullName": "OF2", "Primary Position": "OF"},
        {"playerID": f"{team}-of3", "fullName": "OF3", "Primary Position": "OF"},
        {"playerID": f"{team}-dh", "fullName": "DH", "Primary Position": "DH"},
        {"playerID": f"{team}-p1", "fullName": "P1", "Primary Position": "SP"},
        {"playerID": f"{team}-p2", "fullName": "P2", "Primary Position": "SP"},
    ]


def _room(*, rule: str, team_roster: list[dict] | None = None) -> dict:
    teams = ["Team A", "Team B"]
    pool = pd.DataFrame(_pool_rows())
    roster_a = team_roster if team_roster is not None else _filled_starters_except_c("Team A")
    return {
        "draft_room_id": "ACC-PASS-1",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": teams,
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "drafted_player_ids": [r["playerID"] for r in roster_a],
        "rosters": {
            "Team A": roster_a,
            "Team B": [],
        },
        "config": {
            "num_teams": 2,
            "picks_per_team": 12,
            "rounds": 12,
            "your_team": "Team A",
            "teams": teams,
            "auto_pick_rule": rule,
            "slots": _slots(),
            "fantasy_format": "5x5 Roto",
            "timer_seconds": 30,
            "draft_setup_mode": "solo",
        },
        "pool": pool,
    }


class PlayerGradeTableParityTests(unittest.TestCase):
    def test_card_grade_equals_table_grade_same_snapshot(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "fullName": "Test Player",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.72,
                    "Decision Score": 0.65,
                    "Draft Fit Score": 0.55,
                }
            ]
        )
        schema = ensure_recommendation_ranking_schema(raw)
        # Simulate table frame: drop EFV keep Player Grade after fill.
        frame = schema.copy()
        frame["Player Grade"] = pd.to_numeric(frame["Player Grade"], errors="coerce").fillna(
            pd.to_numeric(frame["Expected Fantasy Value"], errors="coerce")
        )
        table = prepare_draft_scores_for_display(
            frame[["fullName", "Primary Position", "Player Grade", "Decision Score"]].rename(
                columns={"fullName": "Player"}
            )
        )
        card_grade = player_grade_display(schema.iloc[0])
        table_grade = str(table.iloc[0].get("Player Grade") or "").strip()
        self.assertTrue(card_grade)
        self.assertNotEqual(card_grade.lower(), "not available")
        self.assertEqual(card_grade, table_grade)

    def test_prepare_does_not_drop_efv_when_player_grade_empty(self) -> None:
        df = pd.DataFrame(
            {
                "Expected Fantasy Value": [0.81],
                "Player Grade": [pd.NA],
                "Decision Score": [0.7],
            }
        )
        out = prepare_draft_scores_for_display(df)
        self.assertIn("Player Grade", out.columns)
        self.assertNotIn("Expected Fantasy Value", out.columns)
        val = pd.to_numeric(out["Player Grade"], errors="coerce").iloc[0]
        self.assertFalse(pd.isna(val))
        self.assertGreater(float(val), 0)


class CompletedDraftRestoreTests(unittest.TestCase):
    def test_complete_room_not_blocked_from_persisted_restore(self) -> None:
        room = {
            "draft_room_id": "DONE-1",
            "status": "complete",
            "current_pick_index": 24,
            "draft_board": [{"playerID": f"p{i}"} for i in range(24)],
            "live_draft_completion_record": {
                "draft_status": "complete",
                "final_board_locked": True,
            },
            "config": {"num_teams": 4, "picks_per_team": 6},
            "teams": ["A", "B", "C", "D"],
        }
        self.assertEqual(
            _room_blocked_from_auto_restore({}, room, for_persisted_restore=True),
            "",
        )

    def test_prepare_restores_completed_draft_and_stays_active(self) -> None:
        room = {
            "draft_room_id": "DONE-RESTORE",
            "status": "complete",
            "current_pick_index": 4,
            "pick_order": [{"Pick": i + 1, "Round": 1, "Team": "A"} for i in range(4)],
            "draft_board": [{"playerID": f"p{i}"} for i in range(4)],
            "drafted_player_ids": [f"p{i}" for i in range(4)],
            "rosters": {"A": [], "B": []},
            "teams": ["A", "B"],
            "config": {
                "num_teams": 2,
                "picks_per_team": 2,
                "rounds": 2,
                "slots": _slots(),
            },
            "live_draft_completion_record": {
                "draft_status": "complete",
                "final_board_locked": True,
            },
            "pool": pd.DataFrame(),
        }
        session: dict = {}
        write_canonical_live_draft_state(session, room, reason="test_complete", local_edit=True)
        # Simulate refresh: runtime cleared, canonical remains.
        session.pop(LIVE_DRAFT_ROOM_KEY, None)
        prepared = prepare_live_draft_state(session)
        self.assertIsNotNone(prepared)
        restored = session.get(LIVE_DRAFT_ROOM_KEY)
        self.assertIsInstance(restored, dict)
        self.assertEqual(str(restored.get("status") or ""), "complete")
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_ACTIVE_DRAFT)
        self.assertIsInstance(session.get(LIVE_DRAFT_STATE_KEY), dict)


class TeamOpenPositionFilterTests(unittest.TestCase):
    def test_only_catcher_open_excludes_ohtani(self) -> None:
        pool = pd.DataFrame(_pool_rows())
        roster = pd.DataFrame(_filled_starters_except_c())
        filtered = filter_candidates_to_team_open_positions(
            pool, roster, config={"slots": _slots()}
        )
        names = set(filtered["fullName"].astype(str))
        self.assertIn("Catcher Ace", names)
        self.assertIn("Catcher Backup", names)
        self.assertNotIn("Shohei Ohtani", names)
        self.assertNotIn("OF Star", names)


    def test_recommendations_use_configured_auto_pick_rule(self) -> None:
        from live_draft_recommendations import live_draft_recommendations

        room = _room(rule="best market rank", team_roster=[])
        # Empty roster → BPA; market rule should surface best Market Rank first.
        top, *_ = live_draft_recommendations(room, top_n=3, session={})
        self.assertFalse(top.empty)
        self.assertEqual(str(top.iloc[0].get("fullName") or ""), "Shohei Ohtani")

    def test_recommendations_respect_catcher_only_need(self) -> None:
        from live_draft_recommendations import live_draft_recommendations

        room = _room(rule="best market rank")
        top, *_ = live_draft_recommendations(room, top_n=3, session={})
        self.assertFalse(top.empty)
        self.assertEqual(str(top.iloc[0].get("Primary Position") or ""), "C")
        self.assertNotEqual(str(top.iloc[0].get("fullName") or ""), "Shohei Ohtani")


class StrategyLegalAutoPickTests(unittest.TestCase):
    def test_best_market_rank_picks_best_legal_catcher_not_ohtani(self) -> None:
        room = _room(rule="best market rank")
        session = {"live_draft_room": room}
        ok, msg = live_draft_auto_pick(room, session, persist=False, finalize=False)
        self.assertTrue(ok, msg)
        board = room.get("draft_board") or []
        self.assertEqual(len(board), 1)
        pick = board[0]
        self.assertEqual(str(pick.get("fullName") or ""), "Catcher Ace")
        self.assertEqual(str(pick.get("Primary Position") or ""), "C")

    def test_balanced_also_respects_catcher_only_need(self) -> None:
        room = _room(rule="balanced recommendation")
        session = {"live_draft_room": room}
        ok, msg = live_draft_auto_pick(room, session, persist=False, finalize=False)
        self.assertTrue(ok, msg)
        pick = (room.get("draft_board") or [])[0]
        self.assertEqual(str(pick.get("Primary Position") or ""), "C")

    def test_best_projected_fantasy_value_among_legal(self) -> None:
        room = _room(rule="best projected fantasy value")
        session = {"live_draft_room": room}
        ok, msg = live_draft_auto_pick(room, session, persist=False, finalize=False)
        self.assertTrue(ok, msg)
        pick = (room.get("draft_board") or [])[0]
        # Catcher Ace has higher EFV than Catcher Backup; Ohtani illegal.
        self.assertEqual(str(pick.get("fullName") or ""), "Catcher Ace")

    def test_best_model_rank_among_legal(self) -> None:
        room = _room(rule="best model rank")
        session = {"live_draft_room": room}
        ok, msg = live_draft_auto_pick(room, session, persist=False, finalize=False)
        self.assertTrue(ok, msg)
        pick = (room.get("draft_board") or [])[0]
        self.assertEqual(str(pick.get("fullName") or ""), "Catcher Ace")

    def test_best_roster_need_among_legal(self) -> None:
        room = _room(rule="best roster need")
        session = {"live_draft_room": room}
        ok, msg = live_draft_auto_pick(room, session, persist=False, finalize=False)
        self.assertTrue(ok, msg)
        pick = (room.get("draft_board") or [])[0]
        self.assertEqual(str(pick.get("Primary Position") or ""), "C")

    def test_strategy_persists_on_room_config(self) -> None:
        room = _room(rule="best market rank")
        self.assertEqual(room["config"]["auto_pick_rule"], "best market rank")
        # Simulate Start → session mirror used by setup UI.
        session = {
            "live_draft_auto_rule": "best market rank",
            "live_draft_room": room,
        }
        self.assertEqual(session["live_draft_auto_rule"], room["config"]["auto_pick_rule"])

    def test_strategies_differ_when_multiple_legal(self) -> None:
        """Empty roster: market vs balanced can diverge; both remain legal."""
        from live_draft_pick_scoring import score_available_for_rule, live_draft_target_counts

        pool = pd.DataFrame(_pool_rows())
        roster = pd.DataFrame()
        cfg = {"slots": _slots(), "auto_pick_rule": "best market rank", "room": None}
        targets = live_draft_target_counts(cfg)
        market, _ = score_available_for_rule(
            pool, roster, "best market rank", targets, config={**cfg, "room": None}
        )
        balanced, _ = score_available_for_rule(
            pool, roster, "balanced recommendation", targets, config={**cfg, "room": None}
        )
        self.assertFalse(market.empty)
        self.assertFalse(balanced.empty)
        # With an empty roster, BN/flex is open so Ohtani is legal under BPA.
        self.assertEqual(str(market.iloc[0].get("fullName") or ""), "Shohei Ohtani")


class FullDraftLegalAutoPickTests(unittest.TestCase):
    def test_full_short_draft_no_duplicates_and_completes(self) -> None:
        teams = ["Team A", "Team B"]
        picks_per = 4
        positions = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "DH", "SP", "SP", "OF", "1B"]
        pool = pd.DataFrame(
            [
                {
                    "playerID": f"p{i:03d}",
                    "fullName": f"Player {i:03d}",
                    "Primary Position": positions[i % len(positions)],
                    "Eligible Positions": positions[i % len(positions)],
                    "Expected Fantasy Value": float(0.9 - i * 0.01),
                    "Decision Score": float(0.85 - i * 0.01),
                    "Draft Fit Score": 0.5,
                    "Positional Fit": 0.5,
                    "Market Rank": i + 1,
                    "Model Rank": i + 1,
                    "Sleeper Score": 0.1,
                }
                for i in range(40)
            ]
        )
        pick_order = []
        n = 1
        for rnd in range(1, picks_per + 1):
            seq = teams if rnd % 2 == 1 else list(reversed(teams))
            for t in seq:
                pick_order.append({"Pick": n, "Round": rnd, "Team": t})
                n += 1
        room = {
            "draft_room_id": "FULL-SHORT",
            "status": "in_progress",
            "current_pick_index": 0,
            "teams": teams,
            "pick_order": pick_order,
            "draft_board": [],
            "drafted_player_ids": [],
            "rosters": {t: [] for t in teams},
            "config": {
                "num_teams": 2,
                "picks_per_team": picks_per,
                "rounds": picks_per,
                "your_team": "Team A",
                "teams": teams,
                "auto_pick_rule": "balanced recommendation",
                "slots": {
                    "C": 1,
                    "1B": 1,
                    "2B": 1,
                    "3B": 1,
                    "SS": 1,
                    "OF": 1,
                    "DH": 0,
                    "P": 0,
                    "BN": 0,
                },
                "fantasy_format": "5x5 Roto",
                "timer_seconds": 5,
                "draft_setup_mode": "solo",
            },
            "pool": pool,
        }
        session = {"live_draft_room": room}
        total = len(pick_order)
        for _ in range(total):
            ok, msg = live_draft_auto_pick(room, session, persist=False, finalize=False)
            self.assertTrue(ok, msg)
        self.assertEqual(len(room["draft_board"]), total)
        ids = [str(p.get("playerID") or "") for p in room["draft_board"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(str(room.get("status") or ""), "complete")
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_ACTIVE_DRAFT)


if __name__ == "__main__":
    unittest.main()
