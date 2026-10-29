"""A Baseball deploy has no ``suite_storage.py``: account settings and AMI saved items still sync.

``suite_account`` used to import ``suite_storage`` bare, so on the deployed app every account
preference read/write and every AMI saved-item scan raised and quietly came back empty. The suite
store in cloud mode is ``suite_storage_supabase``; these tests stand in for its HTTP layer with an
in-memory, user_id-scoped table, the way Supabase scopes every row.
"""

from __future__ import annotations

import sys
import unittest
from unittest import mock

import suite_account
import suite_storage_supabase as sss


class FakeTables:
    def __init__(self) -> None:
        self.settings: dict[tuple[str, str], dict] = {}
        self.items: dict[tuple[str, str, str, str], dict] = {}
        self.user = "uuid-a"

    def request(self, method, table, *, params=None, json_body=None, prefer=None, **_kw):
        params = params or {}
        if table == sss._TABLE_SETTINGS:
            if method == "POST":
                self.settings[(json_body["user_id"], json_body["app"])] = dict(json_body)
                return None
            uid = params["user_id"].split("eq.", 1)[1]
            row = self.settings.get((uid, params["app"].split("eq.", 1)[1]))
            return [row] if row else []
        raise AssertionError(f"unexpected table {table}")


class SuiteAccountFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tables = FakeTables()
        patches = [
            mock.patch.dict(sys.modules, {"suite_storage": None}),          # not deployed
            mock.patch.object(sss, "_request", side_effect=self.tables.request),
            mock.patch.object(sss, "_scoped_user_id", side_effect=lambda: self.tables.user),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_store_is_the_supabase_module_when_suite_storage_is_absent(self) -> None:
        self.assertIs(suite_account._storage(), sss)

    def test_account_settings_round_trip_and_stay_with_their_account(self) -> None:
        suite_account.save_settings("baseball__qa_a_account_prefs", {"active_league_context_id": "L2"})
        self.assertEqual(suite_account.load_settings("baseball__qa_a_account_prefs"),
                         {"active_league_context_id": "L2"})
        self.tables.user = "uuid-b"                                   # another account, same key
        self.assertEqual(suite_account.load_settings("baseball__qa_a_account_prefs"), {})

    def test_ami_question_context_is_found_again_through_the_scan(self) -> None:
        import suite_analytical_question as saq

        rows = [{"item_key": "q123", "payload": {"question": "Is Judge a Hall of Famer?", "source_state": {}}}]
        with mock.patch.object(sss, "load_saved_items", return_value=rows) as load:
            payload = saq.load_analytical_question_payload("q123")
        self.assertEqual(payload.get("question"), "Is Judge a Hall of Famer?")
        self.assertTrue(load.called)


if __name__ == "__main__":
    unittest.main()
