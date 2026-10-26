"""Side-effect-free league reads: same answer as the page resolvers, session untouched."""

from __future__ import annotations

import copy
import pickle
import tempfile
import unittest
from collections.abc import MutableMapping
from pathlib import Path
from unittest import mock

from fantasy_league_context import get_active_league_context
from fantasy_league_peek import (
    isolated_session_view,
    peek_active_league_context,
    peek_resolved_fantasy_context,
    view_writes,
)
from fantasy_season_ledger import configure_season_calendar
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from resolved_fantasy_context import RESOLVED_CACHE_KEY, resolve_fantasy_context_for_page
from tests.test_team_control_and_local_saves import _as, _league


class ProxyLikeSession(MutableMapping):
    """Stands in for Streamlit's SessionStateProxy: a MutableMapping that is not a dict."""

    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __delitem__(self, key):
        del self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


def _frozen(session) -> bytes:
    return pickle.dumps({k: session[k] for k in sorted(session, key=str)})


def _comparable(resolved):
    diag = resolved.to_diag()
    diag.pop("cache_hit", None)
    return diag, resolved.league_rosters


class PeekTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        _league(self.session)
        with _as("local:qa"):
            ctx = get_active_league_context(self.session)
            configure_season_calendar(ctx, first_day="2026-04-06", period_count=2)
            from fantasy_league_context import upsert_league_context

            upsert_league_context(self.session, ctx)

    def tearDown(self):
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_peek_matches_the_page_resolver_and_writes_nothing(self):
        before = _frozen(self.session)
        keys_before = set(self.session)
        control = copy.deepcopy(self.session)
        with _as("local:qa"):
            peeked = peek_resolved_fantasy_context(self.session)
            expected = resolve_fantasy_context_for_page(control)
        self.assertIn(RESOLVED_CACHE_KEY, control)  # the page resolver does write caches...
        self.assertEqual(_frozen(self.session), before)  # ...the peek does not
        self.assertEqual(set(self.session), keys_before)
        self.assertNotIn(RESOLVED_CACHE_KEY, self.session)
        self.assertTrue(peeked.coherent, peeked.coherence_error)
        self.assertEqual(_comparable(peeked), _comparable(expected))
        self.assertEqual(peeked.active_team_name, "Team A")
        self.assertEqual(sorted(peeked.team_names), ["Team A", "Team B", "Team C"])

    def test_peek_active_league_is_a_private_copy(self):
        before = _frozen(self.session)
        with _as("local:qa"):
            ctx = peek_active_league_context(self.session)
            saved_only = peek_active_league_context(self.session, respect_source_priority=False)
        self.assertEqual(ctx["league_context_id"], get_active_league_context(copy.deepcopy(self.session))["league_context_id"])
        self.assertEqual(saved_only["league_context_id"], ctx["league_context_id"])
        self.assertIn("season_ledger", ctx["workflow"])
        ctx["league_rosters"]["Team A"]["players"].clear()
        ctx["workflow"]["season_ledger"]["periods"].clear()
        self.assertEqual(_frozen(self.session), before)
        self.assertTrue(get_active_league_context(copy.deepcopy(self.session))["league_rosters"]["Team A"]["players"])

    def test_non_dict_session_like_production(self):
        proxy = ProxyLikeSession(self.session)
        before = _frozen(self.session)
        with _as("local:qa"):
            peeked = peek_resolved_fantasy_context(proxy)
            expected = resolve_fantasy_context_for_page(ProxyLikeSession(copy.deepcopy(self.session)))
        self.assertEqual(_frozen(self.session), before)
        self.assertEqual(_comparable(peeked), _comparable(expected))

    def test_no_shared_store_sync_or_stats_fetch(self):
        with _as("local:qa"), \
                mock.patch("fantasy_shared_league_store.sync_context_with_shared_store", side_effect=AssertionError("network")), \
                mock.patch("fantasy_period_stats.fetch_period_hitting_stats", side_effect=AssertionError("network")), \
                mock.patch("fantasy_position_eligibility.fetch_current_season_fielding", side_effect=AssertionError("network")):
            self.assertTrue(peek_resolved_fantasy_context(self.session).coherent)
            self.assertIsNotNone(peek_active_league_context(self.session))

    def test_empty_session(self):
        empty: dict = {}
        resolved = peek_resolved_fantasy_context(empty)
        self.assertEqual(resolved.coherence_error, "no_active_context")
        self.assertIsNone(peek_active_league_context(empty))
        self.assertEqual(empty, {})


class IsolatedViewTests(unittest.TestCase):
    def test_reads_are_copies_and_writes_stay_in_the_view(self):
        source = {"a": {"x": [1, 2]}, "b": 1}
        view = isolated_session_view(source)
        self.assertIsInstance(view, dict)
        view["a"]["x"].append(3)
        view["c"] = 5
        view.setdefault("d", []).append(1)
        self.assertEqual(view.pop("b"), 1)
        self.assertNotIn("b", view)
        self.assertEqual(sorted(view), ["a", "c", "d"])
        self.assertEqual(dict(view)["a"], {"x": [1, 2, 3]})
        self.assertEqual(source, {"a": {"x": [1, 2]}, "b": 1})
        self.assertEqual(view_writes(view), {"b", "c", "d"})

    def test_proxy_view_is_not_a_dict(self):
        view = isolated_session_view(ProxyLikeSession({"k": [1]}))
        self.assertNotIsInstance(view, dict)
        view["k"].append(2)
        view["new"] = 1
        self.assertEqual(view["k"], [1, 2])
        self.assertIn("new", view)


if __name__ == "__main__":
    unittest.main()
