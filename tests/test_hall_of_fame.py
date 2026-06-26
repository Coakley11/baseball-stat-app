"""Tests for Hall of Fame badges, filters, and Case Mode packets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from hall_of_fame_data import (
    CASE_SCORE_LABEL,
    HOF_DATA_FILENAME,
    HOF_FILTER_ALL,
    HOF_FILTER_NON,
    HOF_FILTER_ONLY,
    KNOWN_HOF_PLAYER_IDS,
    apply_hof_membership_filter,
    attach_hof_flag,
    build_hof_case_packet,
    build_hof_case_question,
    build_hof_runtime_diagnostics,
    decorate_player_column,
    decorate_player_name,
    hall_of_fame_csv_path,
    hof_case_ami_guidance,
    hof_data_available,
    hof_load_diagnostics,
    hof_data_setup_message,
    load_hall_of_fame_player_ids,
    merge_hof_flag,
    player_in_results,
)


class HallOfFameDataTests(unittest.TestCase):
    def test_load_hof_ids_from_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HallOfFame.csv"
            path.write_text(
                "playerID,yearid,votedBy,ballots,needed,votes,inducted,category\n"
                "ruthbabe01,1936,BBWAA,1,1,1,Y,Player\n"
                "bondsba01,2022,BBWAA,1,1,1,N,Player\n"
                "mayswi01,1979,BBWAA,1,1,1,Y,Player\n"
                "mackco01,1937,Veterans,1,1,1,Y,Manager\n",
                encoding="utf-8",
            )
            ids = load_hall_of_fame_player_ids(tmp)
            self.assertEqual(ids, frozenset({"ruthbabe01", "mayswi01"}))

    def test_hof_filter_and_star(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Babe Ruth", "playerID": "ruthbabe01", "isHallOfFamer": True, "HR": 714},
                {"fullName": "Player X", "playerID": "x01", "isHallOfFamer": False, "HR": 300},
            ]
        )
        only = apply_hof_membership_filter(df, HOF_FILTER_ONLY)
        self.assertEqual(len(only), 1)
        non = apply_hof_membership_filter(df, HOF_FILTER_NON)
        self.assertEqual(len(non), 1)
        self.assertTrue(decorate_player_name("Babe Ruth", True).startswith("⭐"))

    def test_hof_case_packet_and_validation(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Babe Ruth", "isHallOfFamer": True, "HR": 714},
                {"fullName": "Mike Trout", "isHallOfFamer": False, "HR": 310},
                {"fullName": "Hank Aaron", "isHallOfFamer": True, "HR": 755},
            ]
        )
        packet = build_hof_case_packet(
            "Mike Trout",
            df,
            filters_summary={"year_range": [1901, 2024], "stat_minimums": {"HR": 300}},
            sort_stat="HR",
        )
        self.assertEqual(packet["total_players_returned"], 3)
        self.assertEqual(packet["hall_of_famers_returned"], 2)
        self.assertAlmostEqual(packet["hall_of_fame_rate_pct"], 66.7, places=1)
        self.assertEqual(packet["target_rank"], 3)
        self.assertTrue(player_in_results("Mike Trout", df))
        self.assertFalse(player_in_results("Juan Soto", df))
        q = build_hof_case_question("Mike Trout", packet)
        self.assertIn("Hall of Fame Statistical Case Score", q)
        self.assertIn("do not present this as true hall of fame induction odds", q.lower())

    def test_attach_hof_flag(self) -> None:
        df = pd.DataFrame([{"playerID": "a1", "fullName": "A"}])
        out = attach_hof_flag(df, frozenset({"a1"}))
        self.assertTrue(bool(out.iloc[0]["isHallOfFamer"]))

    def test_missing_hof_csv_is_graceful(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(hof_data_available(tmp))
            self.assertEqual(load_hall_of_fame_player_ids(tmp), frozenset())
            self.assertIn(HOF_DATA_FILENAME, hof_data_setup_message())
            self.assertEqual(hall_of_fame_csv_path(tmp).name, HOF_DATA_FILENAME)

    def test_hof_filter_all_modes(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "A", "isHallOfFamer": True},
                {"fullName": "B", "isHallOfFamer": False},
                {"fullName": "C", "isHallOfFamer": True},
            ]
        )
        self.assertEqual(len(apply_hof_membership_filter(df, HOF_FILTER_ALL)), 3)
        self.assertEqual(len(apply_hof_membership_filter(df, HOF_FILTER_ONLY)), 2)
        self.assertEqual(len(apply_hof_membership_filter(df, HOF_FILTER_NON)), 1)

    def test_decorate_player_column_stars(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Babe Ruth", "isHallOfFamer": True},
                {"fullName": "Mike Trout", "isHallOfFamer": False},
            ]
        )
        out = decorate_player_column(df)
        self.assertTrue(str(out.iloc[0]["fullName"]).startswith("⭐"))
        self.assertFalse(str(out.iloc[1]["fullName"]).startswith("⭐"))

    def test_hof_case_packet_required_fields(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Babe Ruth", "isHallOfFamer": True, "HR": 714, "H": 2873},
                {"fullName": "Mike Trout", "isHallOfFamer": False, "HR": 310, "H": 1200},
            ]
        )
        filters = {"year_range": [2000, 2024], "stat_minimums": {"HR": 300}}
        packet = build_hof_case_packet(
            "Mike Trout",
            df,
            filters_summary=filters,
            sort_stat="HR",
        )
        self.assertEqual(packet["target_player"], "Mike Trout")
        self.assertEqual(packet["filters_used"], filters)
        self.assertEqual(packet["total_players_returned"], 2)
        self.assertEqual(packet["hall_of_famers_returned"], 1)
        self.assertEqual(packet["hall_of_fame_rate_pct"], 50.0)
        self.assertEqual(packet["target_rank"], 2)
        self.assertTrue(packet["target_in_results"])
        self.assertIsInstance(packet["result_sample"], list)
        self.assertGreater(len(packet["result_sample"]), 0)
        self.assertEqual(packet["score_label"], CASE_SCORE_LABEL)

    def test_player_not_in_results_blocks_packet_rank(self) -> None:
        df = pd.DataFrame([{"fullName": "Babe Ruth", "isHallOfFamer": True, "HR": 714}])
        packet = build_hof_case_packet(
            "Juan Soto",
            df,
            filters_summary={},
            sort_stat="HR",
        )
        self.assertFalse(packet["target_in_results"])
        self.assertIsNone(packet["target_rank"])
        self.assertFalse(player_in_results("Juan Soto", df))

    def test_ami_label_and_guidance_exact(self) -> None:
        packet = {"total_players_returned": 10, "hall_of_famers_returned": 8, "hall_of_fame_rate_pct": 80.0, "sort_stat": "HR"}
        q = build_hof_case_question("Juan Soto", packet)
        self.assertIn(CASE_SCORE_LABEL, q)
        guidance = hof_case_ami_guidance()
        self.assertIn(CASE_SCORE_LABEL, guidance)
        self.assertIn("Never present the score as true induction probability", guidance)


    def test_build_hof_runtime_diagnostics_fields(self) -> None:
        df = pd.DataFrame(
            [
                {"playerID": "ruthbabe01", "fullName": "Babe Ruth", "isHallOfFamer": True, "HR": 714},
                {"playerID": "troutmi01", "fullName": "Mike Trout", "isHallOfFamer": False, "HR": 310},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HallOfFame.csv"
            path.write_text(
                "playerID,yearid,inducted,category\nruthbabe01,1936,Y,Player\n",
                encoding="utf-8",
            )
            ids = load_hall_of_fame_player_ids(tmp)
            diag = build_hof_runtime_diagnostics(
                tmp,
                results_df=df,
                batting_df=df,
                hof_player_ids=ids,
                hof_cache_key=1.0,
                git_commit="abc1234",
                hof_filter_value=HOF_FILTER_ALL,
                page_label="Career Totals",
            )
            self.assertEqual(diag["git_commit"], "abc1234")
            self.assertTrue(diag["csv_exists"])
            self.assertEqual(diag["results_df_row_count"], 2)
            self.assertEqual(diag["results_df_isHallOfFamer_true_count"], 1)
            self.assertEqual(diag["first_5_hof_player_ids"], ["ruthbabe01"])
            self.assertTrue(diag["known_ids_present"]["ruthba01"] is False)
            self.assertIn("csv_modified_utc", diag)


class HofRuntimeSmokeTests(unittest.TestCase):
    """Smoke test against repo ``HallOfFame.csv`` when present."""

    def test_runtime_hof_smoke_when_csv_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not hall_of_fame_csv_path(root).exists():
            self.skipTest("HallOfFame.csv not in repo root")
        diag = hof_load_diagnostics(root)
        self.assertTrue(diag["csv_exists"])
        self.assertTrue(diag["hof_data_available"])
        self.assertGreater(diag["inducted_player_count"], 100)
        for pid in KNOWN_HOF_PLAYER_IDS:
            self.assertTrue(diag["known_ids_present"].get(pid), pid)

        batting = pd.read_csv(root / "Batting.csv", low_memory=False, usecols=["playerID", "yearID", "HR"])
        ids = load_hall_of_fame_player_ids(root)
        batting = attach_hof_flag(batting, ids)
        self.assertGreater(int(batting["isHallOfFamer"].sum()), 0)
        for pid in KNOWN_HOF_PLAYER_IDS:
            self.assertTrue(bool(batting.loc[batting["playerID"] == pid, "isHallOfFamer"].any()))

        career = (
            batting.groupby("playerID", as_index=False)["HR"]
            .sum()
            .merge(batting[["playerID"]].drop_duplicates(), on="playerID")
        )
        career = merge_hof_flag(career, ids)
        hof_only = apply_hof_membership_filter(career, HOF_FILTER_ONLY)
        self.assertGreater(len(hof_only), 50)

        hist = batting[batting["HR"] >= 50].copy()
        hist = merge_hof_flag(hist, ids)
        hist_hof = apply_hof_membership_filter(hist, HOF_FILTER_ONLY)
        self.assertGreater(len(hist_hof), 10)


class HofCaseAmiIntegrationTests(unittest.TestCase):
    def test_submit_hof_case_creates_cc_and_insight(self) -> None:
        from unittest.mock import patch

        import pandas as pd

        from hall_of_fame_data import (
            HOF_CASE_PACKET_KEY,
            build_hof_case_packet,
            build_hof_case_question,
            summarize_career_filters,
        )

        df = pd.DataFrame(
            [
                {"fullName": "Mike Trout", "isHallOfFamer": False, "HR": 310},
                {"fullName": "Babe Ruth", "isHallOfFamer": True, "HR": 714},
            ]
        )
        session: dict = {
            "career_year_range_filter": [2000, 2024],
            "career_sort_stat_filter": "HR",
        }
        packet = build_hof_case_packet(
            "Mike Trout",
            df,
            filters_summary=summarize_career_filters(session),
            sort_stat="HR",
        )
        question = build_hof_case_question("Mike Trout", packet)
        session[HOF_CASE_PACKET_KEY] = packet

        recorded: list = []
        with patch("suite_activity_client.record_activity", side_effect=lambda *a, **k: recorded.append((a, k))):
            from suite_analytical_question import submit_analytical_question

            result = submit_analytical_question(
                source_app="baseball",
                source_page="Career Totals",
                question=question,
                context={"hof_case_packet": packet, "player": "Mike Trout"},
                context_summary=f"{CASE_SCORE_LABEL} — Mike Trout",
                quant_area="hall_of_fame_case",
                session_state=session,
            )
            from baseball_hof_activity import log_hof_case_analysis_submitted

            log_hof_case_analysis_submitted(
                session,
                target_player="Mike Trout",
                packet=packet,
                question_id=str(result.get("question_id") or ""),
            )

        self.assertTrue(result.get("question_id"))
        self.assertTrue(str(result.get("action_url") or "").strip())
        self.assertIn(CASE_SCORE_LABEL, question)
        activity_events = [args[1] for args, _kwargs in recorded if len(args) > 1]
        self.assertIn("hof_case_analysis_submitted", activity_events)
        self.assertIn("analytical_question", activity_events)


if __name__ == "__main__":
    unittest.main()
