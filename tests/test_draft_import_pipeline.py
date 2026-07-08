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
    build_draft_import_debug_status,
    build_import_review,
    get_entry_config,
    import_columns_valid,
    import_review_ready,
    import_review_ready_for_league,
    normalize_imported_draft_columns,
    parse_uploaded_draft_file,
    resolve_uploaded_file_for_import,
    stage_draft_import_upload,
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

    def test_parse_uploaded_draft_file_empty_rows_shows_columns(self) -> None:
        csv = b"Foo,Bar\n1,2\n"
        upload = MagicMock()
        upload.getvalue.return_value = csv
        upload.name = "draft.csv"

        df, err = parse_uploaded_draft_file(upload, read_table_fn=_read_csv_table)
        self.assertTrue(df.empty)
        self.assertIn("Detected columns", err)
        self.assertIn("Foo", err)

    def test_import_pending_banner_helpers_exist(self) -> None:
        from draft_import_pipeline import render_draft_room_import_block, render_import_pending_banner

        self.assertTrue(callable(render_import_pending_banner))
        self.assertTrue(callable(render_draft_room_import_block))

    def test_staged_upload_survives_empty_widget(self) -> None:
        session: dict = {}
        upload = MagicMock()
        upload.getvalue.return_value = b"Team,Player,Pick\nDaniel,Aaron Judge,1\n"
        upload.name = "draft.csv"
        session["draft_room_import_uploader"] = upload
        stage_draft_import_upload(session, widget_key="draft_room_import_uploader")
        session.pop("draft_room_import_uploader", None)
        resolved = resolve_uploaded_file_for_import(session, None, widget_key="draft_room_import_uploader")
        self.assertIsNotNone(resolved)
        df, err = parse_uploaded_draft_file(resolved, read_table_fn=_read_csv_table)
        self.assertEqual(err, "")
        self.assertEqual(len(df), 1)

    def test_debug_status_reports_pipeline_fields(self) -> None:
        session: dict = {}
        upload = MagicMock()
        upload.getvalue.return_value = b"Team,Player,Pick\nDaniel,Aaron Judge,1\n"
        upload.name = "office.csv"
        review = build_import_review(
            parse_uploaded_draft_file(upload, read_table_fn=_read_csv_table)[0],
            self.pool,
        )
        status = build_draft_import_debug_status(
            session,
            entry_point=ENTRY_DRAFT_ROOM,
            uploaded_file=upload,
            widget_key="draft_room_import_uploader",
            import_block_entered=True,
            pipeline_called=True,
            raw_df=pd.read_csv(io.BytesIO(upload.getvalue())),
            parsed_df=review.get("import_df"),
            review=review,
            pool_size=len(self.pool),
        )
        self.assertTrue(status["uploaded_file_present"])
        self.assertEqual(status["uploaded_filename"], "office.csv")
        self.assertTrue(status["validation_review_created"])
        self.assertEqual(status["session_key_used_for_review"], "_draft_import_review")
        self.assertTrue(status["render_uploaded_draft_import_section_called"])

    def test_team_name_diagnostics_compare_sources(self) -> None:
        from draft_import_pipeline import build_import_team_name_diagnostics

        import_df = pd.DataFrame(
            {
                "Round": [1, 1, 1, 1],
                "Pick": [1, 2, 3, 4],
                "Team": ["Team 1", "Team 2", "Team 3", "Team 4"],
                "Player": ["Aaron Judge", "Juan Soto", "Shohei Ohtani", "Bobby Witt Jr."],
            }
        )
        review = build_import_review(import_df, self.pool)
        session = {
            "room_team_names": "Daniel\nTeam 2\nTeam 3\nTeam 4",
            "draft_room_table": pd.DataFrame(
                {
                    "Round": [1, 1],
                    "Pick": [1, 2],
                    "Team": ["Team 1", "Team 2"],
                    "Player": ["Aaron Judge", "Juan Soto"],
                }
            ),
        }
        diag = build_import_team_name_diagnostics(session, review=review)
        self.assertEqual(diag["parsed_csv_teams"], ["Team 1", "Team 2", "Team 3", "Team 4"])
        self.assertEqual(diag["draft_room_settings_teams"], ["Daniel", "Team 2", "Team 3", "Team 4"])
        self.assertEqual(diag["board_teams"], ["Team 1", "Team 2"])
        self.assertEqual(
            diag["shared_league_teams"],
            ["Team 1", "Team 2", "Team 3", "Team 4"],
        )
        self.assertFalse(diag["parsed_matches_room_settings"])

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
        self.assertIn("render_draft_room_import_block", source)
        self.assertIn("pool_fn=", source)
        self.assertNotIn("League setup & import", source)
        self.assertIn("ENTRY_STANDINGS", source)
        self.assertNotIn("def normalize_imported_draft_columns", source)
        self.assertNotIn("def _render_validated_draft_import", source)


if __name__ == "__main__":
    unittest.main()
