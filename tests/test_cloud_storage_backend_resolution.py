"""Baseball cloud writes must not route through a foreign ``suite_storage`` (lineup QA 2026-11-08).

On a machine with a sibling Command Center checkout, recording an activity put that repo on sys.path. A bare
``import suite_storage`` then resolved to Command Center's router, whose ``save_current_state`` takes neither
``skip_metrics_merge_read`` nor ``expected_updated_at``. Every full-session write raised TypeError (swallowed),
so a saved lineup stayed local and the next sign-in restored the older cloud copy.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

import suite_account
import suite_cloud_state
import suite_storage_supabase


def _foreign_router() -> types.ModuleType:
    mod = types.ModuleType("suite_storage")

    def save_current_state(app, *, page="", summary="", metrics=None):  # Command Center's narrower signature
        return None

    mod.save_current_state = save_current_state
    return mod


class BackendResolutionTests(unittest.TestCase):
    def test_with_cloud_on_a_foreign_router_on_the_path_is_ignored(self) -> None:
        with patch.dict(sys.modules, {"suite_storage": _foreign_router()}), \
                patch("suite_storage_config.cloud_storage_enabled", return_value=True):
            storage, name = suite_cloud_state._import_storage()
            self.assertIs(storage, suite_storage_supabase)
            self.assertEqual(name, "suite_storage_supabase")
            self.assertIs(suite_account._storage(), suite_storage_supabase)

    def test_the_cloud_module_accepts_the_guarded_write_arguments(self) -> None:
        import inspect

        params = inspect.signature(suite_storage_supabase.save_current_state).parameters
        self.assertIn("skip_metrics_merge_read", params)
        self.assertIn("expected_updated_at", params)

    def test_local_only_installs_still_use_the_command_center_store(self) -> None:
        router = _foreign_router()
        with patch.dict(sys.modules, {"suite_storage": router}), \
                patch("suite_storage_config.cloud_storage_enabled", return_value=False):
            storage, name = suite_cloud_state._import_storage()
            self.assertIs(storage, router)
            self.assertEqual(name, "suite_storage")
            self.assertIs(suite_account._storage(), router)

    def test_a_guarded_write_reaches_the_cloud_module_after_a_router_appears(self) -> None:
        calls = []

        def fake_save(app, *, page="", summary="", metrics=None, skip_metrics_merge_read=False,
                      expected_updated_at=None):
            calls.append({"skip_metrics_merge_read": skip_metrics_merge_read, "expected_updated_at": expected_updated_at})
            return True

        with patch.dict(sys.modules, {"suite_storage": _foreign_router()}), \
                patch("suite_storage_config.cloud_storage_enabled", return_value=True), \
                patch.object(suite_storage_supabase, "save_current_state", fake_save):
            storage, _ = suite_cloud_state._import_storage()
            ok = suite_cloud_state._save_guarded_state(
                storage, "baseball", page="Lineup", summary="s", metrics={"full_session": {}},
                skip_metrics_merge_read=True, expected_updated_at="2026-11-08T00:00:00Z")
        self.assertTrue(ok)
        self.assertEqual(calls[0]["expected_updated_at"], "2026-11-08T00:00:00Z")
        self.assertTrue(calls[0]["skip_metrics_merge_read"])


if __name__ == "__main__":
    unittest.main()
