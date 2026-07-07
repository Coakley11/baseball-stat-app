"""suite_account must work on standalone Streamlit deploys without suite_storage."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch


class SuiteAccountStorageFallbackTests(unittest.TestCase):
    def test_load_saved_items_uses_supabase_when_suite_storage_missing(self) -> None:
        supabase = MagicMock()
        supabase.load_saved_items.return_value = [{"item_key": "x1"}]
        with patch.dict(sys.modules, {"suite_storage": None}):
            import suite_account

            with patch.object(suite_account, "_import_storage", return_value=supabase):
                rows = suite_account.load_saved_items(app="baseball", item_type="applied_math_insight", limit=5)
        self.assertEqual(rows, [{"item_key": "x1"}])
        supabase.load_saved_items.assert_called_once()

    def test_remember_saved_item_uses_supabase_when_suite_storage_missing(self) -> None:
        supabase = MagicMock()
        supabase.upsert_saved_item.return_value = {"write_mode": "upsert"}
        with patch.dict(sys.modules, {"suite_storage": None}):
            import suite_account

            with patch.object(suite_account, "_import_storage", return_value=supabase):
                out = suite_account.remember_saved_item(
                    "baseball",
                    "applied_math_insight",
                    "insight-1",
                    title="Test",
                    payload={"insight_id": "insight-1"},
                )
        self.assertEqual(out.get("write_mode"), "upsert")


if __name__ == "__main__":
    unittest.main()
