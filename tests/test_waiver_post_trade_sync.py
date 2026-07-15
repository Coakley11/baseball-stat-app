"""Waiver Wire FA pool must use post-trade shared league rosters."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_waiver_wire import build_waiver_pool, resolve_waiver_league_context


def _stats_pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "José Ramírez", "Primary Position": "3B", "HR": 30, "RBI": 90, "AVG": 0.280},
            {"Player": "Jose Ramirez", "Primary Position": "3B", "HR": 30, "RBI": 90, "AVG": 0.280},
            {"Player": "Matt Olson", "Primary Position": "1B", "HR": 35, "RBI": 100, "AVG": 0.250},
            {"Player": "Vladimir Guerrero Jr.", "Primary Position": "1B", "HR": 28, "RBI": 85, "AVG": 0.290},
        ]
    )


class PostTradeWaiverPoolTests(unittest.TestCase):
    def test_stale_local_context_hydrates_from_shared_rosters(self) -> None:
        """Team X local lost José but never saw him on Team Y — shared has the truth."""
        # Stale local (Daniel): José not on any team → used to incorrectly mark him FA.
        stale_local = {
            "league_context_id": "ctx:xy",
            "my_team_name": "Team X",
            "metadata": {"league_id": "league:xy", "shared_revision": 1},
            "roster_settings": {"roster_slots": {"1B": 1, "3B": 1}},
            "league_rosters": {
                "Team X": {
                    "players": [
                        {"player_name": "Vladimir Guerrero Jr.", "player_key": "vladimir guerrero jr."},
                    ]
                },
                "Team Y": {"players": []},
            },
        }
        shared_doc = {
            "league_id": "league:xy",
            "revision": 5,
            "league_rosters": {
                "Team X": {
                    "players": [
                        {"player_name": "Vladimir Guerrero Jr.", "player_key": "vladimir guerrero jr."},
                    ]
                },
                "Team Y": {
                    "players": [
                        {"player_name": "José Ramírez", "player_key": "josé ramírez"},
                    ]
                },
            },
            "team_ownership": {},
            "trade_proposals": [],
            "league_invites": [],
            "league_activity": [],
        }
        session: dict = {
            "fantasy_league_context_state": {
                "active_league_context_id": "ctx:xy",
                "contexts": {"ctx:xy": stale_local},
            }
        }

        with patch(
            "fantasy_shared_league_store.load_shared_league",
            return_value=shared_doc,
        ), patch(
            "fantasy_shared_league_store.invalidate_shared_league_doc_cache",
        ), patch(
            "fantasy_league_identity.resolve_canonical_league_id",
            return_value="league:xy",
        ):
            # Ensure get_active returns stale local.
            with patch(
                "fantasy_league_context.get_active_league_context",
                return_value=dict(stale_local),
            ), patch(
                "fantasy_league_context.upsert_league_context",
                side_effect=lambda _s, ctx, **_k: ctx,
            ):
                hydrated = resolve_waiver_league_context(session)

        self.assertIsNotNone(hydrated)
        assert hydrated is not None
        y_names = {
            str(p.get("player_name") or "")
            for p in ((hydrated.get("league_rosters") or {}).get("Team Y") or {}).get("players") or []
            if isinstance(p, dict)
        }
        self.assertIn("José Ramírez", y_names)

        pool = build_waiver_pool(_stats_pool(), hydrated)
        names = set(pool["Player"].astype(str))
        self.assertNotIn("José Ramírez", names)
        self.assertNotIn("Jose Ramirez", names)
        self.assertIn("Matt Olson", names)

    def test_build_pool_excludes_when_jose_only_on_opponent(self) -> None:
        context = {
            "my_team_name": "Team X",
            "league_rosters": {
                "Team X": {"players": [{"player_name": "Vladimir Guerrero Jr."}]},
                "Team Y": {"players": [{"player_name": "José Ramírez"}]},
            },
            "roster_settings": {"roster_slots": {"1B": 1, "3B": 1}},
        }
        pool = build_waiver_pool(_stats_pool(), context)
        names = set(pool["Player"].astype(str))
        self.assertNotIn("José Ramírez", names)
        self.assertNotIn("Jose Ramirez", names)


if __name__ == "__main__":
    unittest.main()
