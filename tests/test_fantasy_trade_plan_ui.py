"""Regression tests for Fantasy Trade Plan UI session-state safety."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    TRADE_MODE_ACQUIRE,
    TRADE_MODE_TRADE_AWAY,
    add_workflow_target,
    get_workflow_targets,
)
from fantasy_state import (
    is_fantasy_lineup_state_key,
    prepare_fantasy_lineup_filters,
    restore_fantasy_page_filters,
    write_canonical_fantasy_section,
)
from fantasy_trade_plan_ui import (
    pending_remove_key,
    render_trade_plan_section,
    stable_trade_plan_button_key,
    strip_trade_plan_button_keys,
    trade_plan_button_key_prefixes,
)
from page_state import _is_ephemeral_widget_key


def _session_with_targets() -> dict:
    session = {
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: {
            "schema_version": 1,
            "active_league_context_id": "live:test",
            "contexts": {
                "live:test": {
                    "league_context_id": "live:test",
                    "display_name": "Test League",
                    "my_team_name": "Daniel",
                    "workflow": {
                        "trade_candidates": [
                            {
                                "player_name": "Mike Trout",
                                "player_key": "mike trout",
                                "owner_team": "Daniel",
                            }
                        ],
                        "acquire_targets": [
                            {
                                "player_name": "Juan Soto",
                                "player_key": "juan soto",
                                "owner_team": "Rivals",
                            }
                        ],
                    },
                }
            },
        }
    }
    return session


def _mock_streamlit():
    st = MagicMock()

    def _columns(n: int):
        count = max(int(n or 1), 1)
        return [MagicMock() for _ in range(count)]

    st.columns.side_effect = _columns
    st.button.return_value = False
    st.rerun.side_effect = RuntimeError("rerun")
    return st


class TestTradePlanButtonKeys(unittest.TestCase):
    def test_trade_plan_button_keys_are_ephemeral(self) -> None:
        trade_key = stable_trade_plan_button_key("lineup_trade_plan", action="remove_trade", player_key="mike trout")
        acquire_key = stable_trade_plan_button_key("lineup_trade_plan", action="remove_acquire", player_key="juan soto")
        self.assertTrue(_is_ephemeral_widget_key(trade_key))
        self.assertTrue(_is_ephemeral_widget_key(acquire_key))
        self.assertFalse(is_fantasy_lineup_state_key(trade_key))
        self.assertFalse(is_fantasy_lineup_state_key(acquire_key))

    def test_render_does_not_prepopulate_button_keys(self) -> None:
        session = _session_with_targets()
        st = _mock_streamlit()

        render_trade_plan_section(st, session, key_prefix="lineup_trade_plan")

        prefixes = trade_plan_button_key_prefixes("lineup_trade_plan")
        button_keys = [k for k in session if any(str(k).startswith(p) for p in prefixes)]
        self.assertEqual(button_keys, [])
        st.button.assert_called()

    def test_strip_removes_stale_button_assignments(self) -> None:
        session = _session_with_targets()
        stale = stable_trade_plan_button_key("lineup_trade_plan", action="remove_trade", player_key="mike trout")
        session[stale] = True
        strip_trade_plan_button_keys(session, "lineup_trade_plan")
        self.assertNotIn(stale, session)

    def test_pending_remove_updates_workflow_without_button_key_writes(self) -> None:
        session = _session_with_targets()
        session[pending_remove_key("lineup_trade_plan", TRADE_MODE_TRADE_AWAY)] = {
            "player_name": "Mike Trout",
            "player_key": "mike trout",
        }
        st = _mock_streamlit()

        with self.assertRaises(RuntimeError):
            render_trade_plan_section(st, session, key_prefix="lineup_trade_plan")

        # rerun called from pending removal path
        st.rerun.assert_called_once()
        ctx = session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["contexts"]["live:test"]
        self.assertEqual(get_workflow_targets(ctx, TRADE_MODE_TRADE_AWAY), [])
        prefixes = trade_plan_button_key_prefixes("lineup_trade_plan")
        button_keys = [k for k in session if any(str(k).startswith(p) for p in prefixes)]
        self.assertEqual(button_keys, [])

    def test_button_click_queues_pending_remove_not_widget_key(self) -> None:
        session = _session_with_targets()
        st = _mock_streamlit()
        trade_key = stable_trade_plan_button_key("lineup_trade_plan", action="remove_trade", player_key="mike trout")

        def _btn_side_effect(*_args, **kwargs):
            return kwargs.get("key") == trade_key

        st.button.side_effect = _btn_side_effect

        with self.assertRaises(RuntimeError):
            render_trade_plan_section(st, session, key_prefix="lineup_trade_plan")

        self.assertEqual(
            session.get(pending_remove_key("lineup_trade_plan", TRADE_MODE_TRADE_AWAY)),
            {"player_name": "Mike Trout", "player_key": "mike trout"},
        )
        stale = stable_trade_plan_button_key("lineup_trade_plan", action="remove_trade", player_key="mike trout")
        self.assertNotIn(stale, session)

    def test_fantasy_restore_skips_trade_plan_button_keys(self) -> None:
        session: dict = {}
        stale = stable_trade_plan_button_key("lineup_trade_plan", action="remove_trade", player_key="mike trout")
        store = {
            "Fantasy Lineup Assistant": {
                "lineup_format": "5x5 Roto",
                stale: True,
            }
        }
        restore_fantasy_page_filters(session, store, "Fantasy Lineup Assistant")
        self.assertEqual(session.get("lineup_format"), "5x5 Roto")
        self.assertNotIn(stale, session)

    def test_write_canonical_lineup_filters_skip_button_keys(self) -> None:
        session: dict = {}
        stale = stable_trade_plan_button_key("lineup_trade_plan", action="remove_acquire", player_key="juan soto")
        write_canonical_fantasy_section(
            session,
            "lineup",
            filters={"lineup_format": "5x5 Roto", stale: True},
            sync_widget_keys=True,
        )
        self.assertEqual(session.get("lineup_format"), "5x5 Roto")
        self.assertNotIn(stale, session)

    def test_prepare_lineup_filters_skip_button_keys_in_snapshot(self) -> None:
        session = {
            "fantasy_state": {
                "lineup": {
                    "filters": {
                        "lineup_format": "5x5 Roto",
                        stable_trade_plan_button_key(
                            "lineup_trade_plan",
                            action="remove_trade",
                            player_key="mike trout",
                        ): True,
                    }
                }
            }
        }
        prepare_fantasy_lineup_filters(session)
        self.assertEqual(session.get("lineup_format"), "5x5 Roto")
        btn = stable_trade_plan_button_key("lineup_trade_plan", action="remove_trade", player_key="mike trout")
        self.assertNotIn(btn, session)


class TestTradePlanWorkflowIntegration(unittest.TestCase):
    def test_add_and_remove_via_pending_path(self) -> None:
        session = _session_with_targets()
        add_workflow_target(session, "live:test", TRADE_MODE_ACQUIRE, "Aaron Judge", owner_team="Rivals")
        session[pending_remove_key("lineup_trade_plan", TRADE_MODE_ACQUIRE)] = {
            "player_name": "Aaron Judge",
            "player_key": "aaron judge",
        }
        st = _mock_streamlit()

        with self.assertRaises(RuntimeError):
            render_trade_plan_section(st, session, key_prefix="lineup_trade_plan")

        ctx = session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["contexts"]["live:test"]
        names = [t["player_name"] for t in get_workflow_targets(ctx, TRADE_MODE_ACQUIRE)]
        self.assertEqual(names, ["Juan Soto"])


if __name__ == "__main__":
    unittest.main()
