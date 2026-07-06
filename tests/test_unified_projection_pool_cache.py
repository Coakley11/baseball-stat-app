"""Regression: get_cached_unified_projection_pool call sites match cache signature."""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_APP_PATH = _ROOT / "streamlit_app.py"


def _parse_app() -> ast.Module:
    return ast.parse(_APP_PATH.read_text(encoding="utf-8"))


def _pool_cache_calls(source: str, tree: ast.Module) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "get_cached_unified_projection_pool":
            calls.append(node)
    return calls


class UnifiedProjectionPoolCacheTests(unittest.TestCase):
    def test_function_signature_includes_ml_min_games_for_signal(self) -> None:
        tree = _parse_app()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_cached_unified_projection_pool":
                arg_names = [a.arg for a in node.args.args]
                self.assertEqual(
                    arg_names,
                    [
                        "lahman_max_year",
                        "draft_window",
                        "fantasy_format",
                        "projection_style",
                        "use_ml_blend",
                        "ml_blend_weight",
                        "ml_min_games_for_signal",
                    ],
                )
                return
        self.fail("get_cached_unified_projection_pool definition not found")

    def test_call_sites_do_not_pass_dataframe_positional_args(self) -> None:
        source = _APP_PATH.read_text(encoding="utf-8")
        tree = _parse_app()
        bad: list[str] = []
        banned_first_args = {"yearly_df", "market_df_live", "lab_market_df"}
        for call in _pool_cache_calls(source, tree):
            if call.args and isinstance(call.args[0], ast.Name):
                if call.args[0].id in banned_first_args:
                    bad.append(f"line {call.lineno}: first arg {call.args[0].id!r}")
            for kw in call.keywords:
                if kw.arg in {
                    "draft_window",
                    "fantasy_format",
                    "projection_style",
                    "use_ml_blend",
                    "ml_blend_weight",
                    "ml_min_games_for_signal",
                }:
                    bad.append(f"line {call.lineno}: unexpected keyword {kw.arg!r}")
        self.assertEqual(bad, [])

    def test_live_draft_and_draft_lab_call_patterns_are_invocable(self) -> None:
        """Execute cache body with the same 7 positional args used by call sites."""
        source = _APP_PATH.read_text(encoding="utf-8")
        tree = _parse_app()
        fn_node = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "get_cached_unified_projection_pool"
        )
        fn_src = ast.get_source_segment(source, fn_node)
        assert fn_src is not None
        mock_build = MagicMock(return_value=pd.DataFrame([{"fullName": "Test Player"}]))
        ns: dict = {
            "pd": pd,
            "yearly_df": pd.DataFrame([{"playerID": "p1"}]),
            "load_fantasypros_market_data": MagicMock(return_value=pd.DataFrame()),
            "build_unified_draft_player_pool": mock_build,
        }
        exec(fn_src, ns)  # noqa: S102 — isolated function body from app source
        fn = ns["get_cached_unified_projection_pool"]
        sig = inspect.signature(fn)
        self.assertEqual(len(sig.parameters), 7)

        out = fn(2024, 3, "5x5 Roto", "Balanced", False, 0.12, 50)
        self.assertFalse(out.empty)
        mock_build.assert_called_once()
        self.assertEqual(mock_build.call_args.kwargs["ml_min_games_for_signal"], 50)


if __name__ == "__main__":
    unittest.main()
