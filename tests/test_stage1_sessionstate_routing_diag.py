"""SessionState / SafeSessionState diagnostic routing tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from live_draft_stage1_s3_process_global_diag import (
    append_module_event,
    append_module_event_for_underlying_sessionstate,
    build_routing_provenance,
    module_ledger_rows,
    register_sessionstate_from_appsession_owner,
    register_sessionstate_instance,
    register_sessionstate_pair_from_wrapper,
    resolve_sessionstate_objects,
    resolve_sessionstate_routing,
    resolve_sessionstate_streamlit_session_id,
    s3_diag_binding_snapshot,
    unrouted_ledger_export,
)


class FakeSessionState:
    def __init__(self) -> None:
        self._new_widget_state = SimpleNamespace(states={})


class FakeSafeSessionState:
    def __init__(self, state: FakeSessionState) -> None:
        object.__setattr__(self, "_state", state)


class SessionStateRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        import live_draft_stage1_s3_process_global_diag as pg

        with pg._LEDGER_LOCK:
            pg._MODULE_LEDGER_BY_STREAMLIT_SESSION.clear()
            pg._CRITICAL_LEDGER_BY_SESSION.clear()
            pg._UNROUTED_ORPHAN_LEDGER.clear()
            pg._SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION.clear()

    def test_wrapper_and_underlying_distinct_ids(self) -> None:
        underlying = FakeSessionState()
        wrapper = FakeSafeSessionState(underlying)
        resolved = resolve_sessionstate_objects(wrapper)
        self.assertNotEqual(resolved["wrapper_object_id"], resolved["underlying_object_id"])
        self.assertFalse(resolved["wrapper_and_underlying_same_object"])

    def test_wrapper_only_registration_not_authoritative(self) -> None:
        underlying = FakeSessionState()
        wrapper = FakeSafeSessionState(underlying)
        register_sessionstate_instance(wrapper, "sid-a")
        with patch(
            "live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx",
            return_value="sid-a",
        ):
            snap = s3_diag_binding_snapshot(wrapper)
        self.assertTrue(snap["sessionstate_wrapper_binding_ok"])
        self.assertFalse(snap["sessionstate_binding_ok"])

    def test_underlying_registration_authoritative(self) -> None:
        underlying = FakeSessionState()
        wrapper = FakeSafeSessionState(underlying)
        register_sessionstate_pair_from_wrapper(wrapper, "sid-a")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(underlying), "sid-a")
        with patch(
            "live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx",
            return_value="sid-a",
        ):
            snap = s3_diag_binding_snapshot(wrapper)
        self.assertTrue(snap["sessionstate_binding_ok"])

    def test_two_sessions_isolated(self) -> None:
        u1 = FakeSessionState()
        w1 = FakeSafeSessionState(u1)
        u2 = FakeSessionState()
        w2 = FakeSafeSessionState(u2)
        register_sessionstate_pair_from_wrapper(w1, "sid-1")
        register_sessionstate_pair_from_wrapper(w2, "sid-2")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(w1._state), "sid-1")  # noqa: SLF001
        self.assertEqual(resolve_sessionstate_streamlit_session_id(w2._state), "sid-2")  # noqa: SLF001

    def test_underlying_receive_routed(self) -> None:
        underlying = FakeSessionState()
        wrapper = FakeSafeSessionState(underlying)
        register_sessionstate_pair_from_wrapper(wrapper, "sid-routed")
        append_module_event_for_underlying_sessionstate(underlying, "SERVER_RECEIVE_ENTRY", pause_present=True)
        rows = module_ledger_rows("sid-routed")
        self.assertTrue(any(r.get("phase") == "SERVER_RECEIVE_ENTRY" for r in rows))

    def test_unmapped_goes_to_orphan_ledger(self) -> None:
        underlying = FakeSessionState()
        append_module_event_for_underlying_sessionstate(underlying, "SERVER_RECEIVE_ENTRY", pause_present=True)
        orphan = unrouted_ledger_export()
        self.assertTrue(any(r.get("phase") == "SERVER_RECEIVE_ENTRY" for r in orphan.get("rows") or []))

    def test_empty_sid_module_event_orphan(self) -> None:
        append_module_event("", "TEST_PHASE", marker=1)
        orphan = unrouted_ledger_export()
        self.assertTrue(len(orphan.get("rows") or []) >= 1)

    def test_appsession_owner_registers_underlying(self) -> None:
        underlying = FakeSessionState()
        wrapper = FakeSafeSessionState(underlying)
        app = SimpleNamespace(id="appsession-sid-1", _session_state=wrapper)
        owner = register_sessionstate_from_appsession_owner(app)
        self.assertTrue(owner.get("registered"))
        self.assertEqual(owner.get("mapping_source"), "appsession_owner")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(underlying), "appsession-sid-1")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(wrapper), "appsession-sid-1")

    def test_same_object_mapped_lookup_succeeds(self) -> None:
        underlying = FakeSessionState()
        register_sessionstate_instance(underlying, "sid-mapped")
        sid, source, prov = resolve_sessionstate_routing(underlying)
        self.assertEqual(sid, "sid-mapped")
        self.assertEqual(source, "sessionstate_instance_map")
        self.assertEqual(prov.get("routing_source"), "sessionstate_instance_map")

    def test_unmapped_stays_unrouted_without_ctx(self) -> None:
        underlying = FakeSessionState()
        with patch(
            "live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx",
            return_value="",
        ):
            append_module_event_for_underlying_sessionstate(underlying, "SERVER_RECEIVE_ENTRY")
        orphan = unrouted_ledger_export()
        self.assertTrue(any(r.get("routing_failure_reason") == "underlying_sessionstate_not_mapped" for r in orphan["rows"]))
        self.assertFalse(module_ledger_rows("any"))

    def test_ctx_secondary_routes_when_unmapped(self) -> None:
        underlying = FakeSessionState()
        with patch(
            "live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx",
            return_value="ctx-sid-secondary",
        ):
            row = append_module_event_for_underlying_sessionstate(underlying, "SERVER_RECEIVE_ENTRY")
        self.assertEqual(row.get("routing_source"), "script_run_context")
        rows = module_ledger_rows("ctx-sid-secondary")
        self.assertTrue(any(r.get("phase") == "SERVER_RECEIVE_ENTRY" for r in rows))

    def test_replacement_instance_detected_via_map(self) -> None:
        old = FakeSessionState()
        new = FakeSessionState()
        register_sessionstate_instance(old, "sid-one")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(old), "sid-one")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(new), "")
        register_sessionstate_instance(new, "sid-two")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(old), "sid-one")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(new), "sid-two")

    def test_no_cross_session_attribution(self) -> None:
        u1 = FakeSessionState()
        u2 = FakeSessionState()
        register_sessionstate_instance(u1, "sid-1")
        register_sessionstate_instance(u2, "sid-2")
        append_module_event_for_underlying_sessionstate(u1, "SERVER_RECEIVE_ENTRY", pause_present=True)
        append_module_event_for_underlying_sessionstate(u2, "SERVER_RECEIVE_ENTRY", pause_present=True)
        self.assertEqual(len(module_ledger_rows("sid-1")), 1)
        self.assertEqual(len(module_ledger_rows("sid-2")), 1)
        self.assertFalse(module_ledger_rows("sid-3"))

    def test_routing_provenance_fields(self) -> None:
        prov = build_routing_provenance(
            routing_sid="sid-a",
            routing_source="runtime_explicit_session_id",
            lookup_object_id=123,
            ctx_sid="sid-a",
            runtime_sid="sid-a",
        )
        self.assertTrue(prov["routing_ids_agree"])
        self.assertEqual(prov["routing_source"], "runtime_explicit_session_id")


class RuntimeRoutingProvenanceTests(unittest.TestCase):
    def test_runtime_wrapper_uses_explicit_session_id(self) -> None:
        import inspect

        from live_draft_stage1_runtime_backmsg_diag import install_runtime_backmsg_probe

        src = inspect.getsource(install_runtime_backmsg_probe)
        self.assertIn("runtime_explicit_session_id", src)
        self.assertIn("session_id", src)


class AppSessionOwnerRoutingTests(unittest.TestCase):
    def test_appsession_record_registers_owner(self) -> None:
        import inspect

        from live_draft_stage1_appsession_ingress_diag import _record_backmsg

        src = inspect.getsource(_record_backmsg)
        self.assertIn("register_sessionstate_from_appsession_owner", src)
        self.assertIn("appsession_self_id", src)
        self.assertNotIn("get_script_run_ctx", src)


class PositiveControlChainTest(unittest.TestCase):
    def setUp(self) -> None:
        import live_draft_stage1_s3_process_global_diag as pg

        with pg._LEDGER_LOCK:
            pg._MODULE_LEDGER_BY_STREAMLIT_SESSION.clear()
            pg._CRITICAL_LEDGER_BY_SESSION.clear()

    def test_appsession_to_underlying_pause_propagation_synthetic(self) -> None:
        underlying = FakeSessionState()
        wrapper = FakeSafeSessionState(underlying)
        register_sessionstate_pair_from_wrapper(wrapper, "sid-chain")
        append_module_event("sid-chain", "RUNTIME_BACKMSG_ENTRY", pause_present=True)
        append_module_event("sid-chain", "APPSESSION_BACKMSG_ENTRY", pause_present=True)
        append_module_event("sid-chain", "APPSESSION_REQUEST_RERUN_ENTRY", pause_present=True)
        append_module_event("sid-chain", "SAFE_SESSIONSTATE_RECEIVE_ENTRY", pause_present=True)
        append_module_event_for_underlying_sessionstate(
            underlying, "SERVER_RECEIVE_ENTRY", pause_present=True, routing_resolved=True
        )
        append_module_event_for_underlying_sessionstate(
            underlying,
            "SERVER_STATE_APPLIED",
            pause_present=True,
            pause_trigger_from_deserialized=True,
        )
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from stage1_s3_r3_observability_classify import pause_observability_chain

        rows = module_ledger_rows("sid-chain")
        obs = pause_observability_chain(rows)
        self.assertTrue(obs["ok"])


if __name__ == "__main__":
    unittest.main()
