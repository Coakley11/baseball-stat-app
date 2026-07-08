"""Tests for shared draft import pipeline (UDSL-1)."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from draft_import_pipeline import (
    ENTRY_DRAFT_ROOM,
    ENTRY_STANDINGS,
    build_import_review,
    get_entry_config,
    import_columns_valid,
    import_review_ready,
    import_review_ready_for_league,
    normalize_imported_draft_columns,
    parse_uploaded_draft_file,
    validate_imported_draft_df,
)
from draft_player_names import classify_draft_player_import_name, build_draft_player_name_index


def _read_csv_table(file_bytes: bytes, file_name: str = "") -> pd.DataFrame:
    del file_name
    return pd.read_csv(io.BytesIO(file_bytes))


class TestDraftImportPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = pd.DataFrame(
            {
                "fullName": [
                    "Francisco Lindor",
                    "Aaron Judge",
                    "Juan Soto",
                    "Juan Yepez",
                    "Yandy Diaz",
                ]
            }
        )
        self.index = build_draft_player_name_index(self.pool)

    def test_normalize_imported_draft_columns_aliases(self) -> None:
        raw = pd.DataFrame(
            {
                "Owner": ["Daniel", "Team 2"],
                "Player Name": ["Aaron Judge", "Francsco Lindor"],
                "overall pick": [1, 2],
            }
        )
        out = normalize_imported_draft_columns(raw)
        self.assertEqual(list(out.columns), ["Round", "Pick", "Team", "Player"])
        self.assertEqual(out.iloc[0]["Team"], "Daniel")
        self.assertEqual(out.iloc[0]["Player"], "Aaron Judge")

    def test_parse_uploaded_draft_file_success(self) -> None:
        csv = b"Team,Player,Pick\nDaniel,Aaron Judge,1\nTeam 2,Juan Soto,2\n"
        upload = MagicMock()
        upload.getvalue.return_value = csv
        upload.name = "draft.csv"

        df, err = parse_uploaded_draft_file(upload, read_table_fn=_read_csv_table)
        self.assertEqual(err, "")
        self.assertTrue(import_columns_valid(df))
        self.assertEqual(len(df), 2)

    def test_parse_uploaded_draft_file_empty_rows(self) -> None:
        csv = b"Team,Player\n"
        upload = MagicMock()
        upload.getvalue.return_value = csv
        upload.name = "draft.csv"

        df, err = parse_uploaded_draft_file(upload, read_table_fn=_read_csv_table)
        self.assertTrue(df.empty)
        self.assertIn("No usable Team/Player rows", err)

    def test_unresolved_player_blocks_league_ready(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Team 2"],
                "Player": ["Aaron Judge", "Francsco Lindor"],
            }
        )
        review = build_import_review(import_df, self.pool)
        self.assertFalse(import_review_ready_for_league(review, self.pool))
        self.assertFalse(import_review_ready(review))

    def test_misspelled_player_shows_suggestions(self) -> None:
        info = classify_draft_player_import_name(
            "Francsco Lindor",
            self.index,
            all_names=self.pool["fullName"].tolist(),
        )
        self.assertEqual(info["status"], "close")
        self.assertIn("Francisco Lindor", info["candidates"])

    def test_juan_diaz_ambiguous_suggestions(self) -> None:
        info = classify_draft_player_import_name(
            "Juan Diaz",
            self.index,
            all_names=self.pool["fullName"].tolist(),
        )
        self.assertIn(info["status"], {"ambiguous", "close", "invalid"})
        if info["status"] in {"ambiguous", "close"}:
            self.assertTrue(len(info["candidates"]) >= 1)

    def test_corrected_player_allows_league_ready(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Team 2"],
                "Player": ["Aaron Judge", "Francsco Lindor"],
            }
        )
        review = build_import_review(import_df, self.pool)
        review["rows"][1]["resolved_canonical"] = "Francisco Lindor"
        self.assertTrue(import_review_ready_for_league(review, self.pool))

    def test_casual_skip_allows_board_ready_but_not_league_ready(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1],
                "Pick": [1],
                "Team": ["Daniel"],
                "Player": ["Mike Piazza"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        review["rows"][0]["skip"] = True
        self.assertTrue(import_review_ready(review))
        self.assertFalse(import_review_ready_for_league(review, self.pool))

    def test_strict_never_allows_blanks_in_validated_output(self) -> None:
        from draft_import_validation import build_validated_import_dataframe

        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Team 2"],
                "Player": ["Aaron Judge", "Francsco Lindor"],
            }
        )
        review = build_import_review(import_df, self.pool)
        self.assertFalse(import_review_ready_for_league(review, self.pool))
        review["rows"][1]["resolved_canonical"] = "Francisco Lindor"
        self.assertTrue(import_review_ready_for_league(review, self.pool))
        out = build_validated_import_dataframe(review)
        self.assertNotIn("", out["Player"].astype(str).str.strip().tolist())

    def test_both_entry_points_use_shared_pipeline(self) -> None:
        draft_cfg = get_entry_config(ENTRY_DRAFT_ROOM)
        standings_cfg = get_entry_config(ENTRY_STANDINGS)
        self.assertNotEqual(draft_cfg["session_key"], standings_cfg["session_key"])
        self.assertEqual(
            draft_cfg["apply_label"],
            "Apply validated import to draft board",
        )
        self.assertIn("Draft Room Simulator", standings_cfg["apply_label"])

        csv = b"Team,Player,Pick\nDaniel,Aaron Judge,1\n"
        upload = MagicMock()
        upload.getvalue.return_value = csv
        upload.name = "draft.csv"

        for entry_point in (ENTRY_DRAFT_ROOM, ENTRY_STANDINGS):
            with self.subTest(entry_point=entry_point):
                df, err = parse_uploaded_draft_file(upload, read_table_fn=_read_csv_table)
                self.assertEqual(err, "")
                review = build_import_review(df, self.pool)
                cfg = get_entry_config(entry_point)
                self.assertEqual(review["summary"]["exact"], 1)
                self.assertTrue(import_review_ready_for_league(review, self.pool))
                session: dict = {cfg["session_key"]: review}
                self.assertIn(cfg["session_key"], session)

    def test_streamlit_entry_points_use_shared_pipeline_module(self) -> None:
        """Regression: both import UIs must route through draft_import_pipeline."""
        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        source = app_path.read_text(encoding="utf-8")
        self.assertIn("render_uploaded_draft_import_section", source)
        self.assertIn("ENTRY_DRAFT_ROOM", source)
        self.assertIn("ENTRY_STANDINGS", source)
        self.assertNotIn("def normalize_imported_draft_columns", source)
        self.assertNotIn("def _render_validated_draft_import", source)


if __name__ == "__main__":
    unittest.main()
