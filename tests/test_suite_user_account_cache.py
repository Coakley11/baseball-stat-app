"""Account user id cache must not leak across signed-in accounts on one worker."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import suite_storage_supabase  # noqa: F401 — ensure patch target module is loaded

from suite_user import _resolve_account_user_id_cached, get_account_user_id, reset_account_cache


class TestSuiteUserAccountCache(unittest.TestCase):
    def test_account_user_id_cache_is_keyed_by_external_id(self) -> None:
        reset_account_cache()
        mapping = {
            "daniel": "f66b85aa-1192-4f93-a669-d238bcd6858b",
            "coakley11": "961df5e0-cdde-48d7-80dd-95a8ba3f46e5",
        }
        with patch("suite_user.get_cloud_config", return_value=object()), patch(
            "suite_storage_supabase.ensure_user_row",
            side_effect=lambda ext, **_: mapping[str(ext)],
        ), patch("suite_user.get_display_name", return_value="Test"):
            self.assertEqual(
                _resolve_account_user_id_cached("daniel", "daniel.cohen11@yahoo.com"),
                mapping["daniel"],
            )
            self.assertEqual(
                _resolve_account_user_id_cached("coakley11", "coakley11@aol.com"),
                mapping["coakley11"],
            )

    def test_get_account_user_id_uses_session_external_id(self) -> None:
        reset_account_cache()
        with patch("suite_user.get_cloud_config", return_value=object()), patch(
            "suite_storage_supabase.ensure_user_row",
            side_effect=lambda ext, **_: {
                "daniel": "f66b85aa-1192-4f93-a669-d238bcd6858b",
                "coakley11": "961df5e0-cdde-48d7-80dd-95a8ba3f46e5",
            }[str(ext)],
        ), patch("suite_user.get_display_name", return_value="Test"), patch(
            "suite_user.get_external_user_id",
            side_effect=["daniel", "coakley11"],
        ), patch(
            "suite_user.get_user_email",
            side_effect=["daniel.cohen11@yahoo.com", "coakley11@aol.com"],
        ):
            self.assertEqual(get_account_user_id(), "f66b85aa-1192-4f93-a669-d238bcd6858b")
            self.assertEqual(get_account_user_id(), "961df5e0-cdde-48d7-80dd-95a8ba3f46e5")


if __name__ == "__main__":
    unittest.main()
