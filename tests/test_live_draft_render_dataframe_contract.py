"""Regression: render_output_table must never receive Styler/None from Live Draft."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from live_draft_room_ui import add_why_this_pick_column
from live_draft_ux import apply_survival_display_columns, sort_recommendation_table, style_latest_board_row
from table_dataframe_guard import ensure_dataframe


class StylerCopyCrashRootCauseTests(unittest.TestCase):
    """Documents the exact AttributeError that crashed Live Draft after a pick."""

    def test_styler_has_no_copy_method(self) -> None:
        board = pd.DataFrame(
            {
                "Player": ["Juan Soto", "Aaron Judge"],
                "Fantasy Edge": [12, 8],
                "Player Grade": [90.0, 88.0],
            }
        )
        styled = style_latest_board_row(board)
        self.assertFalse(isinstance(styled, pd.DataFrame))
        self.assertFalse(hasattr(styled, "copy"))
        with self.assertRaises(AttributeError):
            # Mirrors render_output_table: table_df = df.copy()
            styled.copy()

    def test_passing_styler_into_naive_copy_path_crashes(self) -> None:
        """Reproduce prior board render: highlight → Styler → render_output_table.copy()."""
        board = pd.DataFrame({"Player": ["A"], "Fantasy Edge": [1]})
        df = style_latest_board_row(board)

        def _naive_render_output_table_copy(payload):
            # Pre-fix body of render_output_table (no DataFrame guard).
            table_df = payload.copy()
            return table_df

        with self.assertRaises(AttributeError) as ctx:
            _naive_render_output_table_copy(df)
        self.assertIn("copy", str(ctx.exception).lower())


class EnsureDataframeAndRenderPathTests(unittest.TestCase):
    def test_ensure_dataframe_recovers_styler_data(self) -> None:
        board = pd.DataFrame({"Player": ["A"], "Fantasy Edge": [3]})
        styled = style_latest_board_row(board)
        recovered = ensure_dataframe(styled, caller="test", key="live_draft_board")
        self.assertIsInstance(recovered, pd.DataFrame)
        self.assertEqual(list(recovered["Player"]), ["A"])
        # Recovered frame is copy-safe.
        self.assertIsInstance(recovered.copy(), pd.DataFrame)

    def test_render_output_table_accepts_styler_without_attributeerror(self) -> None:
        import streamlit_app as app

        board = pd.DataFrame({"Player": ["A"], "Fantasy Edge": [3], "Player Grade": [90.0]})
        styled = style_latest_board_row(board)

        fake_st = mock.MagicMock()
        with mock.patch.object(app, "st", fake_st):
            with mock.patch.object(app, "_df_to_csv_bytes", return_value=b"x"):
                # Must not raise AttributeError on .copy()
                app.render_output_table(
                    styled,
                    key="live_draft_board",
                    file_name="board.csv",
                    display_rows=80,
                )
        fake_st.dataframe.assert_called()
        fake_st.download_button.assert_called()

    def test_render_output_table_with_highlight_last_row_keeps_dataframe_contract(self) -> None:
        import streamlit_app as app

        board = pd.DataFrame({"Player": ["A", "B"], "Fantasy Edge": [3, 1], "Player Grade": [90.0, 80.0]})
        fake_st = mock.MagicMock()
        with mock.patch.object(app, "st", fake_st):
            with mock.patch.object(app, "_df_to_csv_bytes", return_value=b"x"):
                app.render_output_table(
                    board,
                    key="live_draft_board",
                    file_name="board.csv",
                    display_rows=80,
                    style_cols=["Fantasy Edge", "Player Grade"],
                    highlight_last_row=True,
                )
        fake_st.dataframe.assert_called()
        # First arg to dataframe should be Styler (display) not raw DF when highlighting.
        display_arg = fake_st.dataframe.call_args[0][0]
        self.assertFalse(isinstance(display_arg, pd.DataFrame))


class RecommendationPipelineNeverNoneTests(unittest.TestCase):
    def test_why_sort_survival_never_return_none(self) -> None:
        self.assertIsInstance(add_why_this_pick_column(None), pd.DataFrame)
        self.assertIsInstance(sort_recommendation_table(None, "Decision Score"), pd.DataFrame)
        self.assertIsInstance(apply_survival_display_columns(None), pd.DataFrame)
        empty = pd.DataFrame()
        self.assertIsInstance(add_why_this_pick_column(empty), pd.DataFrame)
        self.assertIsInstance(sort_recommendation_table(empty, "Decision Score"), pd.DataFrame)
        self.assertIsInstance(apply_survival_display_columns(empty), pd.DataFrame)

    def test_rec_display_chain_after_timer_never_yields_none(self) -> None:
        """Simulates empty / deferred recs → prepare → clean → format → render.copy()."""
        import streamlit_app as app

        top_rec = None  # what a bad cache / why enrich used to propagate
        top_rec = ensure_dataframe(top_rec, caller="test.top_rec")
        rec_cols = ["fullName", "Primary Position", "Decision Score", "Fantasy Edge"]
        show = top_rec[[c for c in rec_cols if c in top_rec.columns]].rename(columns={"fullName": "Player"})
        show = ensure_dataframe(
            apply_survival_display_columns(sort_recommendation_table(show, "Decision Score")),
            caller="test.prepare",
        )
        cleaned = app.clean_ui_columns(show)
        formatted = app.format_fantasy_table(cleaned)
        self.assertIsInstance(formatted, pd.DataFrame)
        # Exact crash site: df.copy() inside render_output_table
        self.assertIsInstance(formatted.copy(), pd.DataFrame)

        fake_st = mock.MagicMock()
        with mock.patch.object(app, "st", fake_st):
            with mock.patch.object(app, "_df_to_csv_bytes", return_value=b""):
                app.render_output_table(
                    formatted,
                    key="live_draft_rec_top",
                    file_name="recs.csv",
                    display_rows=10,
                )

    def test_invalid_input_is_logged_with_key(self) -> None:
        import streamlit_app as app

        fake_st = mock.MagicMock()
        with mock.patch.object(app, "st", fake_st):
            with mock.patch.object(app, "_df_to_csv_bytes", return_value=b""):
                with self.assertLogs(level="WARNING") as logs:
                    app.render_output_table(
                        None,
                        key="live_draft_rec_top",
                        file_name="recs.csv",
                    )
        joined = " ".join(logs.output)
        self.assertIn("live_draft_rec_top", joined)
        self.assertIn("NoneType", joined)


if __name__ == "__main__":
    unittest.main()
