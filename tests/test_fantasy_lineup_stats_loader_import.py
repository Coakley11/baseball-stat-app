"""Regression: fantasy_lineup_stats_loader must not re-enter streamlit_app."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class FantasyLineupStatsLoaderImportTests(unittest.TestCase):
    def test_loader_source_has_no_streamlit_app_reference(self) -> None:
        text = (ROOT / "fantasy_lineup_stats_loader.py").read_text(encoding="utf-8")
        self.assertNotIn("streamlit_app", text)

    def test_import_loader_subprocess_does_not_load_streamlit_app(self) -> None:
        code = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(ROOT)!r})
            assert "streamlit_app" not in sys.modules
            import fantasy_lineup_stats_loader  # noqa: F401
            assert "streamlit_app" not in sys.modules
            print("ok")
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_ensure_lineup_with_restored_stats_no_streamlit_app(self) -> None:
        code = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(ROOT)!r})
            import pandas as pd
            from fantasy_lineup_stats_loader import ensure_lineup_page_hitter_stats
            session = {{
                "_fantasy_current_hitter_stats": pd.DataFrame([{{"Player": "Juan Soto", "HR": 20}}]),
                "_fantasy_standings_stats_source": "restored",
            }}
            result = ensure_lineup_page_hitter_stats(session, None)
            assert result["ok"] is True
            assert "streamlit_app" not in sys.modules
            print("ok")
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_mlb_fetch_fallback_uses_pure_module(self) -> None:
        sample = pd.DataFrame([{"Player": "Test Player", "HR": 5, "RBI": 10, "R": 8, "SB": 1, "BA": 0.250}])
        with patch("mlb_hitter_stats.fetch_mlb_api_hitter_stats", return_value=sample) as mock_fetch:
            from fantasy_lineup_stats_loader import ensure_lineup_page_hitter_stats

            session: dict = {"standings_api_season": 2026}
            result = ensure_lineup_page_hitter_stats(session, None)
        mock_fetch.assert_called_once_with(2026)
        self.assertTrue(result["ok"])
        self.assertFalse(result["hitter_stats"].empty)

    def test_name_normalization_extracted_helper(self) -> None:
        from player_name_normalization import normalize_player_name_for_merge

        self.assertEqual(normalize_player_name_for_merge("José Ramírez Jr."), "jose ramirez")

    def test_simulated_render_does_not_create_sidebar_radio(self) -> None:
        code = textwrap.dedent(
            f"""
            import sys
            from unittest.mock import MagicMock

            radio_calls = []

            def fake_radio(*args, **kwargs):
                radio_calls.append({{"args": args, "kwargs": kwargs}})
                return None

            st = MagicMock()
            st.radio = fake_radio
            st.session_state = {{}}
            st.cache_data = lambda **kw: (lambda fn: fn)
            sys.modules["streamlit"] = st
            sys.path.insert(0, {str(ROOT)!r})

            import fantasy_lineup_stats_loader as loader
            import pandas as pd

            session = {{
                "_fantasy_current_hitter_stats": pd.DataFrame([{{"Player": "Aaron Judge", "HR": 30}}]),
            }}
            loader.ensure_lineup_page_hitter_stats(session, {{"league_rosters": {{}}}})
            assert len(radio_calls) == 0
            assert "streamlit_app" not in sys.modules
            print("ok")
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main()
