"""Hosted installs pass Streamlit's SessionStateProxy (a MutableMapping, not a dict).

Regression: current_user_id only read the signed-in id from dict sessions, so on a hosted
install a signed-in owner resolved to "nobody" and could not save their own lineup.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import MutableMapping
from pathlib import Path
from unittest import mock

from fantasy_league_context import get_active_league_context, upsert_league_context
from fantasy_league_team_ownership import assign_team_owner_to_context
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_team_control import MODE_NONE, MODE_OWNER, current_user_id, resolve_team_control
from tests.test_team_control_and_local_saves import _as, _league


class ProxyLikeSession(MutableMapping):
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


class HostedSessionIdentityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.data: dict = {}
        _league(self.data)
        with _as("uuid-a", auth=True, session=self.data):
            ctx = assign_team_owner_to_context(get_active_league_context(self.data), "Team A", user_id="uuid-a", email="a@qa")
            ctx = assign_team_owner_to_context(ctx, "Team B", user_id="uuid-b", email="b@qa")
            upsert_league_context(self.data, ctx)
        self.data["_suite_auth_user_id"] = "uuid-a"
        self.session = ProxyLikeSession(self.data)

    def tearDown(self):
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_signed_in_id_is_read_from_a_non_dict_session(self):
        with mock.patch("fantasy_team_control.auth_required", return_value=True):
            self.assertEqual(current_user_id(self.session), "uuid-a")
            self.assertEqual(current_user_id(ProxyLikeSession({})), "")  # hosted, not signed in

    def test_hosted_owner_manages_their_team_and_not_others(self):
        ctx = get_active_league_context(self.data)
        with mock.patch("fantasy_team_control.auth_required", return_value=True), \
                mock.patch("fantasy_league_team_ownership._resolve_user_id", return_value="uuid-a"):
            self.assertEqual(resolve_team_control(self.session, ctx, "Team A").mode, MODE_OWNER)
            self.assertEqual(resolve_team_control(self.session, ctx, "Team B").mode, MODE_NONE)

    def test_hosted_owner_lineup_write_check_passes(self):
        from fantasy_weekly_lineup import _assert_lineup_team_write

        ctx = get_active_league_context(self.data)
        with mock.patch("fantasy_team_control.auth_required", return_value=True), \
                mock.patch("fantasy_league_team_ownership._resolve_user_id", return_value="uuid-a"):
            err_b = _assert_lineup_team_write(self.session, ctx, "Team B")
            control_a = resolve_team_control(self.session, ctx, "Team A")
        self.assertTrue(control_a.can_manage)
        self.assertIn("managed by", err_b or "")


if __name__ == "__main__":
    unittest.main()
