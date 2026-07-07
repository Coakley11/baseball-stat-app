"""Regression tests for Waiver Wire Streamlit button callbacks."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from fantasy_league_context import save_simulator_league_context
from fantasy_waiver_wire import WAIVER_PLANNER_ADD_KEY, WAIVER_PLANNER_DROP_KEY, WAIVER_TX_FLASH_KEY
from fantasy_waiver_wire_ui import (
    WAIVER_TX_CLEAR_WIDGETS_KEY,
    _apply_deferred_waiver_widget_clears,
    _apply_waiver_tx_result,
    _on_add_pending_pair_click,
    _on_clear_planner_add_click,
    _on_clear_planner_drop_click,
    _on_confirm_pending_waiver_moves_click,
    _on_confirm_waiver_move_click,
    _on_plan_add_click,
    _on_plan_drop_click,
    _on_planner_pick_changed,
    _on_remove_pending_pair_click,
    purge_waiver_action_widget_keys,
    render_waiver_wire_page,
)


class WaiverCallbackSignatureTests(unittest.TestCase):
    def test_callback_handlers_accept_streamlit_extra_args(self) -> None:
        zero_arg_handlers = (
            _on_clear_planner_add_click,
            _on_clear_planner_drop_click,
            _on_confirm_waiver_move_click,
            _on_add_pending_pair_click,
            _on_confirm_pending_waiver_moves_click,
            _on_planner_pick_changed,
        )
        for handler in zero_arg_handlers:
            with self.subTest(handler=handler.__name__):
                handler("extra", widget_key="ignored", key="ignored")

        with self.subTest(handler=_on_plan_add_click.__name__):
            _on_plan_add_click("Mike Trout", widget_key="ignored", key="ignored")

        with self.subTest(handler=_on_plan_drop_click.__name__):
            _on_plan_drop_click("Aaron Judge", widget_key="ignored", key="ignored")

        with self.subTest(handler=_on_remove_pending_pair_click.__name__):
            _on_remove_pending_pair_click(0, widget_key="ignored", key="ignored")

    def test_plan_add_click_sets_session_planner_key(self) -> None:
        session: dict = {}
        with patch("streamlit.session_state", session, create=True):
            _on_plan_add_click("Mike Trout")
        self.assertEqual(session[WAIVER_PLANNER_ADD_KEY], "Mike Trout")

    def test_confirm_waiver_move_requires_matching_pairs(self) -> None:
        session: dict = {
            "waiver_tx_add_players": ["Mike Trout"],
            "waiver_tx_drop_players": [],
            "_fantasy_current_hitter_stats": pd.DataFrame([{"Player": "Mike Trout", "HR": 10}]),
        }
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        with patch("streamlit.session_state", session, create=True):
            _on_confirm_waiver_move_click()
        flash = session.get(WAIVER_TX_FLASH_KEY)
        self.assertIsInstance(flash, dict)
        assert flash is not None
        self.assertEqual(flash.get("level"), "warning")

    def test_add_pending_pair_requires_both_players(self) -> None:
        session: dict = {WAIVER_PLANNER_ADD_KEY: "Mike Trout"}
        with patch("streamlit.session_state", session, create=True):
            _on_add_pending_pair_click()
        flash = session.get(WAIVER_TX_FLASH_KEY)
        self.assertIsInstance(flash, dict)
        assert flash is not None
        self.assertEqual(flash.get("level"), "warning")

    def test_purge_waiver_action_widget_keys(self) -> None:
        session = {
            "waiver_confirm_tx_btn": True,
            "waiver_save_pair_btn": False,
            "waiver_rm_pair_0_btn": True,
            "lineup_team": "Daniel",
        }
        purge_waiver_action_widget_keys(session)
        self.assertNotIn("waiver_confirm_tx_btn", session)
        self.assertNotIn("waiver_save_pair_btn", session)
        self.assertNotIn("waiver_rm_pair_0_btn", session)
        self.assertEqual(session["lineup_team"], "Daniel")

    def test_apply_waiver_tx_result_requests_deferred_widget_clear(self) -> None:
        session: dict = {
            "waiver_tx_add_players": ["Mike Trout"],
            "waiver_tx_drop_players": ["Aaron Judge"],
        }
        stats = pd.DataFrame([{"Player": "Mike Trout", "HR": 25}])
        with patch("fantasy_waiver_wire_ui.sync_waiver_roster_views"):
            _apply_waiver_tx_result(
                session,
                {"ok": True, "added_players": ["Mike Trout"], "dropped_players": ["Aaron Judge"]},
                stats_pool=stats,
            )
        self.assertTrue(session.get(WAIVER_TX_CLEAR_WIDGETS_KEY))
        self.assertEqual(session["waiver_tx_add_players"], ["Mike Trout"])

    def test_deferred_widget_clear_runs_before_widgets(self) -> None:
        session: dict = {
            WAIVER_TX_CLEAR_WIDGETS_KEY: True,
            "waiver_tx_add_players": ["Mike Trout"],
            "waiver_tx_drop_players": ["Aaron Judge"],
            "waiver_manual_add_select": "Mike Trout",
            "waiver_manual_drop_select": "Aaron Judge",
        }
        _apply_deferred_waiver_widget_clears(session)
        self.assertNotIn(WAIVER_TX_CLEAR_WIDGETS_KEY, session)
        self.assertNotIn("waiver_tx_add_players", session)
        self.assertNotIn("waiver_tx_drop_players", session)
        self.assertNotIn("waiver_manual_add_select", session)
        self.assertNotIn("waiver_manual_drop_select", session)

    def test_confirm_waiver_move_success_sets_clear_flag(self) -> None:
        session: dict = {
            "waiver_tx_add_players": ["Mike Trout"],
            "waiver_tx_drop_players": ["Aaron Judge"],
            "_fantasy_current_hitter_stats": pd.DataFrame(
                [
                    {"Player": "Aaron Judge", "HR": 20},
                    {"Player": "Mike Trout", "HR": 25},
                ]
            ),
        }
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        tx_ok = {"ok": True, "added_players": ["Mike Trout"], "dropped_players": ["Aaron Judge"]}
        with patch("streamlit.session_state", session, create=True), patch(
            "fantasy_waiver_wire_ui.apply_waiver_move_pairs", return_value=tx_ok
        ), patch("fantasy_waiver_wire_ui.sync_waiver_roster_views"):
            _on_confirm_waiver_move_click()
        self.assertTrue(session.get(WAIVER_TX_CLEAR_WIDGETS_KEY))
        flash = session.get(WAIVER_TX_FLASH_KEY)
        self.assertIsInstance(flash, dict)
        assert flash is not None
        self.assertEqual(flash.get("level"), "success")

    def test_confirm_pending_waiver_moves_success_sets_clear_flag(self) -> None:
        session: dict = {
            "_fantasy_current_hitter_stats": pd.DataFrame(
                [
                    {"Player": "Aaron Judge", "HR": 20},
                    {"Player": "Mike Trout", "HR": 25},
                ]
            ),
            "_waiver_pending_move_pairs": [
                {"add_player": "Mike Trout", "drop_player": "Aaron Judge", "category_impact": []},
            ],
        }
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        tx_ok = {"ok": True, "added_players": ["Mike Trout"], "dropped_players": ["Aaron Judge"]}
        with patch("streamlit.session_state", session, create=True), patch(
            "fantasy_waiver_wire_ui.apply_waiver_move_pairs", return_value=tx_ok
        ), patch("fantasy_waiver_wire_ui.sync_waiver_roster_views"):
            _on_confirm_pending_waiver_moves_click()
        self.assertTrue(session.get(WAIVER_TX_CLEAR_WIDGETS_KEY))
        flash = session.get(WAIVER_TX_FLASH_KEY)
        self.assertIsInstance(flash, dict)
        assert flash is not None
        self.assertEqual(flash.get("level"), "success")


class WaiverRenderCallbackTests(unittest.TestCase):
    def _mock_st(self) -> MagicMock:
        st = MagicMock()
        st.warning = MagicMock()
        st.caption = MagicMock()
        st.markdown = MagicMock()
        st.info = MagicMock()
        st.success = MagicMock()
        st.error = MagicMock()
        st.dataframe = MagicMock()
        st.expander = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            )
        )
        st.container = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            )
        )
        st.columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
        st.multiselect = MagicMock(return_value=[])
        st.selectbox = MagicMock(return_value="")
        st.text_input = MagicMock(return_value="")
        st.button = MagicMock(return_value=False)
        st.rerun = MagicMock()
        return st

    def test_render_waiver_page_registers_on_click_for_action_buttons(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        stats = pd.DataFrame(
            [
                {"Player": "Aaron Judge", "HR": 20},
                {"Player": "Juan Soto", "HR": 18},
                {"Player": "Mike Trout", "HR": 25},
            ]
        )
        st = self._mock_st()
        with patch("fantasy_waiver_wire_ui.recommend_adds_current", return_value=pd.DataFrame()), patch(
            "fantasy_waiver_wire_ui.recommend_drops_current", return_value=pd.DataFrame()
        ):
            render_waiver_wire_page(st, session, current_stats_pool=stats)

        on_click_handlers = [
            call.kwargs.get("on_click")
            for call in st.button.call_args_list
            if call.kwargs.get("on_click") is not None
        ]
        handler_names = {getattr(fn, "__name__", str(fn)) for fn in on_click_handlers}
        self.assertIn("_on_confirm_waiver_move_click", handler_names)
        self.assertIn("_on_add_pending_pair_click", handler_names)
        for fn in on_click_handlers:
            params = inspect.signature(fn).parameters.values()
            accepts_var_args = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            accepts_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
            self.assertTrue(
                accepts_var_args or accepts_var_kwargs or len(params) <= 1,
                msg=f"{getattr(fn, '__name__', fn)} must tolerate Streamlit callback args",
            )


if __name__ == "__main__":
    unittest.main()
