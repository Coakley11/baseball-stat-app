"""Out-of-band S3 diagnostic snapshot tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from live_draft_stage1_s3_oob_snapshot import (  # noqa: E402
    current_generation,
    publish_initial_oob_snapshot,
    publish_oob_snapshot,
    read_oob_snapshot_file,
    register_oob_channel,
    snapshot_path_for_token,
    static_url_path_for_token,
)
from live_draft_stage1_s3_process_global_diag import append_module_event  # noqa: E402
from stage1_s3_oob_readback import compare_oob_freshness, extract_oob_freshness_from_snapshot  # noqa: E402
from stage1_s3_r2_subclassify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED,
    classify_sibling_oob_r2_from_snapshot,
)
from stage1_s3_r3_observability_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
    BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_PAUSE,
    BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_UNAVAILABLE,
    classify_oob_channel_unavailable,
    classify_oob_freshness_after_pause,
    classify_oob_freshness_after_sibling,
    classify_s3_with_observability,
)


class OobSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        import live_draft_stage1_s3_oob_snapshot as oob
        import live_draft_stage1_s3_process_global_diag as pg

        self.tmp = ROOT / "static" / "s3_oob" / "_test_tmp"
        self.tmp.mkdir(parents=True, exist_ok=True)
        with pg._LEDGER_LOCK:
            pg._MODULE_LEDGER_BY_STREAMLIT_SESSION.clear()
            pg._CRITICAL_LEDGER_BY_SESSION.clear()
            pg._UNROUTED_ORPHAN_LEDGER.clear()
        with oob._OOB_LOCK:
            oob._OOB_GENERATION_BY_TOKEN.clear()
            oob._STREAMLIT_SESSION_TO_TOKEN.clear()
        self.addCleanup(lambda: [p.unlink(missing_ok=True) for p in self.tmp.glob("*.json")])

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_generation_increments_and_atomic_publish(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        session: dict = {}
        channel = register_oob_channel("sid-a", session)
        pub1 = publish_oob_snapshot("sid-a", publish_source="initial_pre_click", session=session, diagnostic_token=channel["diagnostic_token"])
        pub2 = publish_oob_snapshot("sid-a", publish_source="runtime_handle_backmsg_finally", session=session, diagnostic_token=channel["diagnostic_token"])
        self.assertEqual(pub1["snapshot_generation"], 1)
        self.assertEqual(pub2["snapshot_generation"], 2)
        snap = read_oob_snapshot_file(channel["diagnostic_token"])
        self.assertEqual(snap.get("snapshot_generation"), 2)
        self.assertEqual(snap.get("publish_source"), "runtime_handle_backmsg_finally")
        self.assertNotIn("access_token", json.dumps(snap))

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_no_cross_session_token_collision(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        c1 = register_oob_channel("sid-one", {})
        c2 = register_oob_channel("sid-two", {})
        self.assertNotEqual(c1["diagnostic_token"], c2["diagnostic_token"])
        self.assertEqual(static_url_path_for_token(c1["diagnostic_token"]), f"/app/static/s3_oob/{c1['diagnostic_token']}.json")

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_runtime_finally_publication_source(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        import inspect
        from live_draft_stage1_runtime_backmsg_diag import install_runtime_backmsg_probe

        src = inspect.getsource(install_runtime_backmsg_probe)
        self.assertIn("runtime_handle_backmsg_finally", src)
        self.assertIn("finally", src)

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_initial_snapshot_registers_channel(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        out = publish_initial_oob_snapshot("sid-init", {"diagnostic_run_id": "run-1"})
        self.assertTrue(out.get("published"))
        self.assertEqual(current_generation(out["diagnostic_token"]), 1)
        path = snapshot_path_for_token(out["diagnostic_token"])
        self.assertTrue(path.is_file())

    def test_freshness_compare_without_clock(self) -> None:
        before = extract_oob_freshness_from_snapshot({"snapshot_generation": 1, "latest_ingress_summaries": {"runtime_backmsg": {"total_count": 0, "latest_event_id": ""}}})
        after = extract_oob_freshness_from_snapshot({"snapshot_generation": 2, "latest_ingress_summaries": {"runtime_backmsg": {"total_count": 1, "latest_event_id": "abc"}}})
        delta = compare_oob_freshness(before, after)
        self.assertTrue(delta["generation_advanced"])
        self.assertTrue(delta["counts_advanced"]["runtime_backmsg"])

    def test_stale_oob_pause_classification(self) -> None:
        stale = classify_oob_freshness_after_pause(
            pause_resolved=True,
            pre_pause_generation=2,
            post_pause_freshness={"snapshot_generation": 2},
        )
        self.assertEqual(stale[0], BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_PAUSE)

    def test_stale_oob_sibling_classification(self) -> None:
        stale = classify_oob_freshness_after_sibling(pre_sibling_generation=1, post_sibling_freshness={"snapshot_generation": 1})
        self.assertIsNotNone(stale)
        self.assertIn("OOB", stale[0])

    def test_oob_channel_unavailable(self) -> None:
        unavailable = classify_oob_channel_unavailable(
            channel={"registered": True, "static_url_path": "/app/static/s3_oob/abc.json"},
            initial_fetch={"ok": False, "status": 404},
        )
        self.assertEqual(unavailable[0], BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_UNAVAILABLE)

    def test_authoritative_rows_merge(self) -> None:
        from stage1_s3_oob_readback import authoritative_rows_from_oob_snapshot

        rows = authoritative_rows_from_oob_snapshot(
            {
                "module_ledger_rows": [{"phase": "A", "ts": 1.0, "event_id": "e1"}],
                "critical_ledger_rows": [{"phase": "B", "ts": 2.0, "event_id": "e2"}],
            }
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["phase"], "B")

    def test_fetch_oob_snapshot_uses_cache_bust_query(self) -> None:
        from stage1_s3_oob_readback import fetch_oob_snapshot_via_page

        captured: dict[str, str] = {}

        class FakeResponse:
            status = 200

            @property
            def headers(self):
                return {"content-type": "application/json"}

            @staticmethod
            def text():
                return json.dumps({"snapshot_generation": 1, "streamlit_session_id": "sid", "diagnostic_token": "tok", "publish_source": "initial_pre_click"})

            @staticmethod
            def json():
                return {"snapshot_generation": 1}

        class FakeRequest:
            @staticmethod
            def get(url, timeout=0):
                captured["url"] = url
                return FakeResponse()

        page = SimpleNamespace(
            evaluate=lambda _js: "https://example.test",
            request=FakeRequest(),
        )
        out = fetch_oob_snapshot_via_page(page, "/app/static/s3_oob/tok123.json", cache_bust=True)
        self.assertTrue(out["ok"])
        self.assertIn("?cb=", captured["url"])
        self.assertTrue(captured["url"].startswith("https://example.test/app/static/s3_oob/tok123.json"))

    def test_empty_path_fetch_aborts_without_http(self) -> None:
        from stage1_s3_oob_readback import fetch_oob_snapshot_via_page

        page = SimpleNamespace(
            evaluate=lambda _js: "https://example.test",
            request=SimpleNamespace(get=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch"))),
        )
        out = fetch_oob_snapshot_via_page(page, "")
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "empty_static_url_path")

    def test_sibling_oob_r2_pattern(self) -> None:
        snap = {
            "snapshot_generation": 2,
            "module_ledger_rows": [
                {"phase": "RUNTIME_BACKMSG_ENTRY", "wire_rerun_target_fragment_id": "wire-frag"},
                {"phase": "APPSESSION_BACKMSG_ENTRY", "target_fragment_exists": False, "would_fail_streamlit_fragment_storage_guard": True},
                {"phase": "APPSESSION_REQUEST_RERUN_ENTRY", "target_fragment_exists": False},
            ],
        }
        case, note, _ = classify_sibling_oob_r2_from_snapshot(
            oob_snapshot=snap,
            wire_rerun_target_fragment_id="wire-frag",
            owner_fragment_id="owner-frag",
            wire_target_in_preclick_fragment_storage=False,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id="$$ID-x",
            post_registration={"registered_widget_id": "$$ID-x"},
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED)

    def test_r3o0_classifier_unchanged_with_fresh_rows(self) -> None:
        rows = [
            {"phase": "RUNTIME_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_REQUEST_RERUN_ENTRY", "pause_present": True},
            {"phase": "SAFE_SESSIONSTATE_RECEIVE_ENTRY", "pause_present": True},
            {"phase": "SERVER_RECEIVE_ENTRY", "pause_present": True},
            {"phase": "SERVER_STATE_APPLIED", "pause_present": True, "pause_trigger_from_deserialized": True},
        ]
        case, _, _ = classify_s3_with_observability(
            module_rows=rows,
            authoritative_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id="$$ID-x-stage1_pause_sibling_return_R_diag",
            sibling_python_effect=False,
            register_widget_result=False,
            st_button_returned=False,
            binding_ok=True,
        )
        self.assertNotEqual(case, BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT)


if __name__ == "__main__":
    unittest.main()
