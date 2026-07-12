"""Integration-style render smoke tests for Fantasy Lineup Assistant top-level tabs."""

from __future__ import annotations

import ast
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]


class _StreamlitStub:
    def __init__(self, session: dict) -> None:
        self.session_state = session
        self.markdown_calls: list[str] = []
        self.selectbox_calls: list[str] = []
        self._widget_values: dict[str, object] = {}

    def markdown(self, body: str, **kwargs: object) -> None:
        self.markdown_calls.append(str(body))

    def caption(self, body: str, **kwargs: object) -> None:
        pass

    def info(self, body: str, **kwargs: object) -> None:
        pass

    def warning(self, body: str, **kwargs: object) -> None:
        pass

    def error(self, body: str, **kwargs: object) -> None:
        pass

    def columns(self, spec: object) -> list["_StreamlitStub"]:
        count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_StreamlitStub(self.session_state) for _ in range(count)]

    @contextmanager
    def __enter__(self) -> "_StreamlitStub":
        yield self

    def __exit__(self, *args: object) -> bool:
        return False

    def number_input(self, label: str, **kwargs: object) -> float:
        key = str(kwargs.get("key") or label)
        value = float(kwargs.get("value") or 0.0)
        self.session_state[key] = value
        return value

    def radio(self, label: str, options: list[str], **kwargs: object) -> str:
        key = str(kwargs.get("key") or label)
        value = str(self.session_state.get(key) or options[0])
        self.session_state[key] = value
        return value

    @contextmanager
    def expander(self, label: str, **kwargs: object):
        yield self

    @contextmanager
    def container(self, **kwargs: object):
        yield self

    def subheader(self, body: str) -> None:
        pass

    def sidebar(self) -> "_StreamlitStub":
        return self

    def selectbox(self, label: str, options: list[str], **kwargs: object) -> str:
        key = str(kwargs.get("key") or label)
        self.selectbox_calls.append(label)
        if key not in self._widget_values:
            self._widget_values[key] = options[0]
        self.session_state[key] = self._widget_values[key]
        return str(self._widget_values[key])

    def slider(self, label: str, **kwargs: object) -> int:
        key = str(kwargs.get("key") or label)
        value = int(kwargs.get("value") or kwargs.get("min_value") or 3)
        self.session_state[key] = value
        return value

    def checkbox(self, label: str, **kwargs: object) -> bool:
        key = str(kwargs.get("key") or label)
        value = bool(kwargs.get("value", True))
        self.session_state[key] = value
        return value

    def text_input(self, label: str, **kwargs: object) -> str:
        key = str(kwargs.get("key") or label)
        value = str(kwargs.get("value") or "")
        self.session_state[key] = value
        return value

    def button(self, label: str, **kwargs: object) -> bool:
        return False

    def radio(self, label: str, options: list[str], **kwargs: object) -> str:
        key = str(kwargs.get("key") or label)
        value = str(self.session_state.get(key) or options[0])
        self.session_state[key] = value
        return value

    def dataframe(self, *args: object, **kwargs: object) -> None:
        pass

    def data_editor(self, *args: object, **kwargs: object) -> pd.DataFrame:
        if args and isinstance(args[0], pd.DataFrame):
            return args[0]
        return pd.DataFrame()

    def divider(self) -> None:
        pass

    def text(self, body: str) -> None:
        pass


def _roster_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Team": "Daniel",
                "Player": "Mookie Betts",
                "Primary Position": "OF",
                "HR": 20,
                "RBI": 62,
                "R": 75,
                "SB": 10,
                "BA": 0.285,
                "OBP": 0.360,
                "SLG": 0.500,
                "OPS": 0.860,
            },
            {
                "Team": "Team 2",
                "Player": "Aaron Judge",
                "Primary Position": "OF",
                "HR": 31,
                "RBI": 72,
                "R": 68,
                "SB": 4,
                "BA": 0.291,
                "OBP": 0.390,
                "SLG": 0.580,
                "OPS": 0.970,
            },
        ]
    )


def _lineup_deps() -> object:
    from fantasy_lineup_management_ui import LineupManagementDeps

    return LineupManagementDeps(
        build_lineup_assistant_scores=lambda roster, fmt, weights=None: roster.assign(
            **{"Lineup Confidence": 1.0, "Momentum Score": 1.0, "Consistency Score": 1.0, "Volatility Meter": 1.0}
        ),
        enrich_lineup_roster_positions=lambda df: df,
        parse_custom_lineup_slots=lambda text: None,
        build_position_aware_lineup=lambda scored, **kwargs: {
            "lineup_df": pd.DataFrame(),
            "slot_warnings": [],
            "missing_slots": [],
        },
        roster_position_slot_list=lambda row: ["OF"],
        lineup_diagnosis_report=lambda starters, scored, lineup_format, **kwargs: {
            "hitting_table": pd.DataFrame(),
            "pitching_table": pd.DataFrame(),
            "recommendations": [],
        },
        open_waiver_wire_from_lineup_slot=lambda **kwargs: None,
        fantasy_filter_changed=lambda: None,
        ensure_select_in_options=lambda key, options, value: value,
        ensure_widget_state=lambda key, value: None,
        render_output_table=lambda *args, **kwargs: None,
        format_lineup_assistant_table=lambda df: df,
        clean_ui_columns=lambda df: df,
        render_contextual_page_nav=lambda *args, **kwargs: None,
        developer_mode_enabled=lambda: False,
        navigate_to_page=lambda *args, **kwargs: None,
        page_option_label=lambda page: page,
        safe_collection_len=lambda value: len(value or []),
        lineup_default_hitting_slots=("C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"),
        resolve_lineup_scoring_format=lambda session: "5x5 Roto",
    )


class LineupAssistantTabRenderSmokeTests(unittest.TestCase):
    def test_trade_center_branch_does_not_touch_lineup_format(self) -> None:
        from fantasy_trade_center_ui import render_trade_center_tab

        session: dict = {
            "fantasy_current_roster_stats": _roster_stats(),
            "_suite_auth_external_id": "daniel",
            "_suite_active_workspace_id": "daniel",
        }
        st = _StreamlitStub(session)

        render_trade_center_tab(
            st,
            session,
            lineup_team="Daniel",
            ensure_select_in_options=lambda *a, **k: a[2],
            ensure_multiselect_state=lambda *a, **k: None,
            evaluate_trade_fn=MagicMock(return_value=(pd.DataFrame(), "Neutral", 0.0)),
            build_trade_verdict_text_fn=lambda *a, **k: "ok",
            render_output_table_fn=lambda *a, **k: None,
            format_trade_eval_table_fn=lambda df: df,
            format_fantasy_table_fn=lambda df: df,
            clean_ui_columns_fn=lambda df: df,
            summarize_team_category_needs_fn=lambda *a, **k: {},
            developer_mode_enabled_fn=lambda: False,
        )

        self.assertNotIn("lineup_format", session)
        self.assertNotIn("Start/Sit", "\n".join(st.selectbox_calls))

    def test_lineup_management_sets_lineup_format_and_controls(self) -> None:
        from fantasy_lineup_management_ui import render_lineup_management_page

        session: dict = {"lineup_bench_rows": 12}
        st = _StreamlitStub(session)
        render_lineup_management_page(
            st,
            session,
            roster_stats=_roster_stats(),
            lineup_team="Daniel",
            lineup_teams=["Daniel", "Team 2"],
            deps=_lineup_deps(),
        )
        self.assertEqual(session.get("lineup_format"), "5x5 Roto")
        self.assertIn("Lineup Scoring Mode", st.selectbox_calls)
        self.assertNotIn("Trade Analyzer", "\n".join(st.markdown_calls))

    def test_switching_tabs_via_session_state(self) -> None:
        from fantasy_trade_ideas import (
            LINEUP_ASSISTANT_TAB_KEY,
            LINEUP_ASSISTANT_TAB_WIDGET_KEY,
            apply_lineup_assistant_tab_selection,
            resolve_lineup_assistant_tab,
            sync_lineup_assistant_tab_widget,
        )
        from fantasy_lineup_management_ui import render_lineup_management_page
        from fantasy_trade_center_ui import render_trade_center_tab

        session: dict = {"lineup_bench_rows": 12, "fantasy_current_roster_stats": _roster_stats()}
        st = _StreamlitStub(session)

        apply_lineup_assistant_tab_selection(session, "Lineup Management")
        sync_lineup_assistant_tab_widget(session)
        render_lineup_management_page(
            st,
            session,
            roster_stats=_roster_stats(),
            lineup_team="Daniel",
            lineup_teams=["Daniel", "Team 2"],
            deps=_lineup_deps(),
        )
        self.assertEqual(resolve_lineup_assistant_tab(session), "Lineup Management")

        apply_lineup_assistant_tab_selection(session, "Trade Center")
        sync_lineup_assistant_tab_widget(session)
        session[LINEUP_ASSISTANT_TAB_WIDGET_KEY] = "Trade Center"
        render_trade_center_tab(
            st,
            session,
            lineup_team="Daniel",
            ensure_select_in_options=lambda *a, **k: a[2],
            ensure_multiselect_state=lambda *a, **k: None,
            evaluate_trade_fn=MagicMock(return_value=(pd.DataFrame(), "Neutral", 0.0)),
            build_trade_verdict_text_fn=lambda *a, **k: "ok",
            render_output_table_fn=lambda *a, **k: None,
            format_trade_eval_table_fn=lambda df: df,
            format_fantasy_table_fn=lambda df: df,
            clean_ui_columns_fn=lambda df: df,
            summarize_team_category_needs_fn=lambda *a, **k: {},
            developer_mode_enabled_fn=lambda: False,
        )
        self.assertEqual(resolve_lineup_assistant_tab(session), "Trade Center")
        self.assertEqual(session[LINEUP_ASSISTANT_TAB_KEY], "Trade Center")

    def test_streamlit_assistant_block_uses_extracted_lineup_renderer(self) -> None:
        source = (REPO_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("render_lineup_management_page(", source)
        self.assertNotIn("if lineup_format == \"Points League\":", source)


if __name__ == "__main__":
    unittest.main()
