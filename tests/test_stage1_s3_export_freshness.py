"""S3 export generation and freshness correlation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from live_draft_stage1_s3_process_global_diag import (  # noqa: E402
    append_module_event,
    build_latest_ingress_summaries,
    current_s3_export_generation,
    next_s3_export_generation,
    register_sessionstate_from_appsession_owner,
    resolve_sessionstate_routing,
)
from live_draft_stage1_s3_server_diag import build_s3_dom_payload, emit_s3_dom_ledger  # noqa: E402
from stage1_s3_export_freshness import (  # noqa: E402
    compare_export_freshness,
    extract_export_freshness_from_scrape,
)
from stage1_s3_r3_observability_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R3O0_SERVER_EXPORT_NOT_REFRESHED_AFTER_PAUSE,
    BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
    classify_export_freshness_after_pause,
    classify_s3_with_observability,
)


class FakeSessionState:
    def __init__(self) -> None:
        self._new_widget_state = SimpleNamespace(states={})


class FakeSafeSessionState:
    def __init__(self, state: FakeSessionState) -> None:
        object.__setattr__(self, "_state", state)


class ExportGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        import live_draft_stage1_s3_process_global_diag as pg

        with pg._LEDGER_LOCK:
            pg._MODULE_LEDGER_BY_STREAMLIT_SESSION.clear()
            pg._CRITICAL_LEDGER_BY_SESSION.clear()
            pg._UNROUTED_ORPHAN_LEDGER.clear()
            pg._SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION.clear()
        with pg._EXPORT_GENERATION_LOCK:
            pg._S3_EXPORT_GENERATION = 0

    def test_export_generation_increments(self) -> None:
        g1 = next_s3_export_generation()
        g2 = next_s3_export_generation()
        self.assertEqual(g2, g1 + 1)
        self.assertEqual(current_s3_export_generation(), g2)

    def test_emit_increments_generation_in_payload(self) -> None:
        session = {"_stage1_s3_diag_binding": {}, "_stage1_pause_sibling_post_registration": {}}
        st = SimpleNamespace(markdown=lambda *a, **k: None)
        with patch("live_draft_stage1_s3_server_diag._streamlit_session_id", return_value="sid-emit"):
            emit_s3_dom_ledger(st, session)
            emit_s3_dom_ledger(st, session)
        self.assertEqual(current_s3_export_generation(), 2)
        with patch("live_draft_stage1_s3_server_diag._streamlit_session_id", return_value="sid-emit"):
            payload = build_s3_dom_payload(session, export_generation=2, export_generated_server_ts=100.0)
        self.assertEqual(payload.get("export_generation"), 2)
        self.assertEqual(payload["export_meta"]["export_generation"], 2)
        self.assertIn("latest_ingress_summaries", payload)

    def test_latest_ingress_summaries_track_event_ids(self) -> None:
        sid = "sid-summary"
        append_module_event(
            sid,
            "RUNTIME_BACKMSG_ENTRY",
            event_id="rt1",
            routing_sid=sid,
            routing_source="runtime_explicit_session_id",
        )
        append_module_event(
            sid,
            "APPSESSION_BACKMSG_ENTRY",
            event_id="app1",
            routing_sid=sid,
            routing_source="appsession_self_id",
        )
        summaries = build_latest_ingress_summaries(sid)
        self.assertEqual(summaries["runtime_backmsg"]["latest_event_id"], "rt1")
        self.assertEqual(summaries["runtime_backmsg"]["total_count"], 1)
        self.assertEqual(summaries["appsession_backmsg"]["latest_event_id"], "app1")


class FreshnessHarnessTests(unittest.TestCase):
    def test_extract_and_compare_generation(self) -> None:
        scrape = {
            "found": True,
            "parse_ok": True,
            "export_generation": "3",
            "export_generated_server_ts": "1000.5",
            "streamlit_session_id": "sid-a",
            "payload": {
                "export_generation": 3,
                "export_generated_server_ts": 1000.5,
                "latest_ingress_summaries": {
                    "runtime_backmsg": {
                        "total_count": 2,
                        "latest_event_id": "abc",
                        "latest_server_ts": 999.0,
                        "latest_routing_sid": "sid-a",
                        "latest_routing_source": "runtime_explicit_session_id",
                    }
                },
                "unrouted_events": {"event_count": 1},
            },
        }
        before = extract_export_freshness_from_scrape(scrape, local_scrape_ts=1000.0)
        after_scrape = {
            **scrape,
            "export_generation": "4",
            "payload": {
                **scrape["payload"],
                "export_generation": 4,
                "latest_ingress_summaries": {
                    "runtime_backmsg": {
                        "total_count": 3,
                        "latest_event_id": "def",
                        "latest_server_ts": 1001.0,
                        "latest_routing_sid": "sid-a",
                        "latest_routing_source": "runtime_explicit_session_id",
                    }
                },
            },
        }
        after = extract_export_freshness_from_scrape(after_scrape, local_scrape_ts=1001.0)
        delta = compare_export_freshness(before, after)
        self.assertTrue(delta["generation_advanced"])
        self.assertTrue(delta["latest_event_ids_changed"]["runtime_backmsg"])
        self.assertAlmostEqual(before["server_local_ts_offset"], 0.5)

    def test_stale_export_after_pause_classification(self) -> None:
        stale = classify_export_freshness_after_pause(
            pause_resolved=True,
            pre_pause_export_generation=5,
            post_pause_freshness={"export_generation": 5},
        )
        self.assertIsNotNone(stale)
        self.assertEqual(stale[0], BUTTON_DISPATCH_S3_R3O0_SERVER_EXPORT_NOT_REFRESHED_AFTER_PAUSE)

    def test_fresh_export_permits_r3_observability(self) -> None:
        stale = classify_export_freshness_after_pause(
            pause_resolved=True,
            pre_pause_export_generation=5,
            post_pause_freshness={"export_generation": 6},
        )
        self.assertIsNone(stale)
        case, _, _ = classify_s3_with_observability(
            module_rows=[],
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id="$$ID-x-stage1_pause_sibling_return_R_diag",
            sibling_python_effect=False,
            register_widget_result=False,
            st_button_returned=False,
            binding_ok=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT)


class RoutingSafetyTests(unittest.TestCase):
    def test_conflicting_ids_do_not_ctx_route(self) -> None:
        underlying = FakeSessionState()
        with patch(
            "live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx",
            return_value="ctx-sid",
        ):
            sid, source, prov = resolve_sessionstate_routing(
                underlying,
                appsession_sid="appsession-sid",
            )
        self.assertEqual(sid, "")
        self.assertEqual(source, "unresolved")
        self.assertFalse(prov.get("routing_ids_agree"))

    def test_appsession_owner_registration(self) -> None:
        import live_draft_stage1_s3_process_global_diag as pg

        with pg._LEDGER_LOCK:
            pg._SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION.clear()
        underlying = FakeSessionState()
        wrapper = FakeSafeSessionState(underlying)
        app = SimpleNamespace(id="owner-sid", _session_state=wrapper)
        owner = register_sessionstate_from_appsession_owner(app)
        self.assertTrue(owner.get("registered"))
        self.assertEqual(owner.get("mapping_source"), "appsession_owner")


if __name__ == "__main__":
    unittest.main()
