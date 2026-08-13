"""Out-of-band S3 diagnostic snapshot tests."""

from __future__ import annotations

import json
import sys
import unittest
from collections.abc import MutableMapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from live_draft_stage1_s3_oob_snapshot import (  # noqa: E402
    S3_OOB_CHANNEL_SESSION_KEY,
    S3_OOB_IMPL_REV,
    S3_OOB_TOKEN_SESSION_KEY,
    current_generation,
    oob_channel_export,
    publish_initial_oob_snapshot,
    publish_oob_snapshot,
    read_oob_snapshot_file,
    register_oob_channel,
    resolve_token_for_streamlit_session,
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

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_g_mixed_tail_eviction_preserves_downstream_critical(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        from live_draft_stage1_s3_process_global_diag import (
            _CRITICAL_EVENTS_PER_PHASE,
            append_module_event,
            critical_ledger_by_phase,
        )

        sid = "sid-flood"
        session: dict = {}
        channel = register_oob_channel(sid, session)
        for phase, eid in (
            ("SCRIPTREQUESTS_RERUN_CONSUMED", "cons-keep"),
            ("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", "run-keep"),
            ("SAFE_SESSIONSTATE_RECEIVE_ENTRY", "safe-keep"),
            ("SERVER_RECEIVE_ENTRY", "recv-keep"),
            ("SERVER_STATE_APPLIED", "apply-keep"),
        ):
            append_module_event(sid, phase, event_id_override=eid, pause_present=True)
        for i in range(80):
            append_module_event(
                sid,
                "SCRIPTREQUESTS_RERUN_COALESCED",
                pause_present=False,
                fragment_id=f"auto-{i}",
            )
            append_module_event(sid, "SCRIPTRUNNER_REQUEST_RERUN_RESULT", accepted=True)
        pub = publish_oob_snapshot(sid, publish_source="runtime_handle_backmsg_finally", session=session, diagnostic_token=channel["diagnostic_token"])
        snap = read_oob_snapshot_file(channel["diagnostic_token"])
        crit = list(snap.get("critical_ledger_rows") or [])
        by_phase = snap.get("critical_ledger_by_phase") or {}
        crit_phases = {r.get("phase") for r in crit}
        for ph in (
            "SCRIPTREQUESTS_RERUN_CONSUMED",
            "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
            "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
            "SERVER_RECEIVE_ENTRY",
            "SERVER_STATE_APPLIED",
        ):
            self.assertIn(ph, crit_phases, (ph, crit_phases, pub))
            self.assertTrue(by_phase.get(ph), ph)
        self.assertLessEqual(len(by_phase.get("SCRIPTREQUESTS_RERUN_COALESCED") or []), _CRITICAL_EVENTS_PER_PHASE)
        live = critical_ledger_by_phase(sid)
        self.assertLessEqual(len(live.get("SCRIPTREQUESTS_RERUN_COALESCED") or []), _CRITICAL_EVENTS_PER_PHASE)

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_dict_token_reuse_and_process_global(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        session: dict = {}
        first = register_oob_channel("sid-reuse", session)
        second = register_oob_channel("sid-reuse", session)
        self.assertTrue(first.get("registered"))
        self.assertEqual(first["diagnostic_token"], second["diagnostic_token"])
        self.assertEqual(resolve_token_for_streamlit_session("sid-reuse"), first["diagnostic_token"])
        pub = publish_oob_snapshot("sid-reuse", publish_source="runtime_handle_backmsg_finally")
        self.assertTrue(pub.get("published"))
        self.assertEqual(pub.get("diagnostic_token"), first["diagnostic_token"])

    def test_m_per_phase_retention_bounded(self) -> None:
        from live_draft_stage1_s3_process_global_diag import (
            _CRITICAL_EVENTS_PER_PHASE,
            append_module_event,
            critical_ledger_by_phase,
        )

        sid = "sid-bound"
        for i in range(20):
            append_module_event(sid, "SCRIPTREQUESTS_RERUN_CONSUMED", consume_api="on_scriptrunner_ready")
        by_phase = critical_ledger_by_phase(sid)
        self.assertLessEqual(len(by_phase.get("SCRIPTREQUESTS_RERUN_CONSUMED") or []), _CRITICAL_EVENTS_PER_PHASE)
        self.assertEqual(len(by_phase.get("SCRIPTREQUESTS_RERUN_CONSUMED") or []), _CRITICAL_EVENTS_PER_PHASE)


class _FakeSessionStateProxy(MutableMapping[str, Any]):
    """Streamlit SessionStateProxy-like mapping: MutableMapping but not a dict."""

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _fresh_streamlit_session_state_proxy() -> MutableMapping[str, Any]:
    import streamlit.runtime.state.session_state_proxy as ssp
    from streamlit.runtime.state.safe_session_state import SafeSessionState
    from streamlit.runtime.state.session_state import SessionState
    from streamlit.runtime.state.session_state_proxy import SessionStateProxy

    ssp._mock_session_state = SafeSessionState(SessionState(), lambda: None)
    proxy = SessionStateProxy()
    assert not isinstance(proxy, dict)
    assert isinstance(proxy, MutableMapping)
    return proxy


class OobSessionPersistenceFixTests(unittest.TestCase):
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

    def _assert_channel_ready(self, channel: dict[str, Any], *, sid: str) -> None:
        self.assertTrue(channel.get("registered"), channel)
        token = str(channel.get("diagnostic_token") or "")
        path = str(channel.get("static_url_path") or "")
        self.assertTrue(token)
        self.assertTrue(path)
        self.assertEqual(path, static_url_path_for_token(token))
        self.assertEqual(channel.get("streamlit_session_id"), sid)
        self.assertEqual(channel.get("impl_rev"), S3_OOB_IMPL_REV)

    def _assert_session_persisted(self, session: MutableMapping[str, Any], *, sid: str, token: str) -> None:
        self.assertEqual(session.get(S3_OOB_TOKEN_SESSION_KEY), token)
        stored = dict(session.get(S3_OOB_CHANNEL_SESSION_KEY) or {})
        self.assertTrue(stored.get("registered"))
        self.assertEqual(stored.get("diagnostic_token"), token)
        self.assertEqual(stored.get("static_url_path"), static_url_path_for_token(token))
        self.assertEqual(resolve_token_for_streamlit_session(sid), token)

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_proxy_like_register_export_readiness(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        sid = "sid-proxy-reg"
        session = _FakeSessionStateProxy()
        self.assertFalse(isinstance(session, dict))
        self.assertTrue(isinstance(session, MutableMapping))
        channel = register_oob_channel(sid, session)
        self._assert_channel_ready(channel, sid=sid)
        token = str(channel["diagnostic_token"])
        self._assert_session_persisted(session, sid=sid, token=token)
        exported = oob_channel_export(session)
        self.assertTrue(exported.get("registered"), exported)
        self.assertEqual(exported.get("diagnostic_token"), token)
        self.assertEqual(exported.get("static_url_path"), static_url_path_for_token(token))
        from live_draft_stage1_s3_server_diag import build_s3_readiness_payload

        readiness = build_s3_readiness_payload(session)
        oob_ch = dict(readiness.get("oob_channel") or {})
        self.assertTrue(oob_ch.get("registered"), oob_ch)
        self.assertEqual(oob_ch.get("diagnostic_token"), token)
        self.assertTrue(oob_ch.get("static_url_path"))
        self.assertEqual(oob_ch.get("impl_rev"), S3_OOB_IMPL_REV)

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_real_session_state_proxy_register_export(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        sid = "sid-real-proxy"
        session = _fresh_streamlit_session_state_proxy()
        channel = register_oob_channel(sid, session)
        self._assert_channel_ready(channel, sid=sid)
        token = str(channel["diagnostic_token"])
        self._assert_session_persisted(session, sid=sid, token=token)
        exported = oob_channel_export(session)
        self.assertTrue(exported.get("registered"), exported)
        self.assertEqual(exported.get("diagnostic_token"), token)

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_dict_register_export_readiness_after_fix(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        sid = "sid-dict-reg"
        session: dict = {}
        channel = register_oob_channel(sid, session)
        self._assert_channel_ready(channel, sid=sid)
        token = str(channel["diagnostic_token"])
        self._assert_session_persisted(session, sid=sid, token=token)
        exported = oob_channel_export(session)
        self.assertTrue(exported.get("registered"), exported)
        self.assertEqual(exported.get("diagnostic_token"), token)
        from live_draft_stage1_s3_server_diag import build_s3_readiness_payload

        readiness = build_s3_readiness_payload(session)
        oob_ch = dict(readiness.get("oob_channel") or {})
        self.assertTrue(oob_ch.get("registered"), oob_ch)
        self.assertEqual(oob_ch.get("impl_rev"), S3_OOB_IMPL_REV)

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_proxy_initial_publication_end_to_end(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        sid = "sid-proxy-init"
        session = _FakeSessionStateProxy({"diagnostic_run_id": "run-proxy"})
        pub = publish_initial_oob_snapshot(sid, session)
        self.assertTrue(pub.get("registered"), pub)
        self.assertTrue(pub.get("published"), pub)
        token = str(pub.get("diagnostic_token") or "")
        path = str(pub.get("static_url_path") or "")
        self.assertTrue(token)
        self.assertTrue(path)
        self.assertGreaterEqual(int(pub.get("snapshot_generation") or 0), 1)
        exported = oob_channel_export(session)
        self.assertTrue(exported.get("registered"), exported)
        self.assertEqual(exported.get("diagnostic_token"), token)
        self.assertEqual(exported.get("static_url_path"), path)
        snap = read_oob_snapshot_file(token)
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap.get("diagnostic_token"), token)
        self.assertEqual(snap.get("snapshot_generation"), pub.get("snapshot_generation"))
        self.assertEqual(snap.get("impl_rev"), S3_OOB_IMPL_REV)
        self.assertTrue(snapshot_path_for_token(token).is_file())

    def test_arbitrary_object_not_mutated(self) -> None:
        obj = SimpleNamespace()
        channel = register_oob_channel("sid-ns", obj)  # type: ignore[arg-type]
        self.assertTrue(channel.get("registered"))
        self.assertFalse(hasattr(obj, S3_OOB_TOKEN_SESSION_KEY))
        self.assertFalse(hasattr(obj, S3_OOB_CHANNEL_SESSION_KEY))
        self.assertEqual(resolve_token_for_streamlit_session("sid-ns"), channel["diagnostic_token"])
        self.assertFalse(oob_channel_export(obj).get("registered"))  # type: ignore[arg-type]

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_yield_flood_keeps_readiness_and_critical_registered(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        from live_draft_stage1_s3_process_global_diag import (
            critical_ledger_by_phase,
            module_ledger_rows,
        )
        from live_draft_stage1_s3_server_diag import (
            build_s3_readiness_payload,
            initialize_oob_channel_safely,
        )

        sid = "sid-yield-flood"
        session = _FakeSessionStateProxy()
        with patch("live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx", return_value=sid):
            phase = initialize_oob_channel_safely(session, sid)
        self.assertEqual(phase, "S3_OOB_CHANNEL_REGISTERED")
        readiness_before = build_s3_readiness_payload(session)
        self.assertTrue(dict(readiness_before.get("oob_channel") or {}).get("registered"))
        for i in range(60):
            append_module_event(sid, "SCRIPTREQUESTS_ON_YIELD_ENTRY", n=i)
            append_module_event(sid, "SCRIPTREQUESTS_ON_YIELD_RESULT", n=i)
        mixed_phases = {str(r.get("phase") or "") for r in module_ledger_rows(sid)}
        self.assertNotIn("S3_OOB_CHANNEL_REGISTERED", mixed_phases)
        by_phase = critical_ledger_by_phase(sid)
        self.assertTrue(by_phase.get("S3_OOB_CHANNEL_REGISTERED"), by_phase.keys())
        readiness_after = build_s3_readiness_payload(session)
        oob_ch = dict(readiness_after.get("oob_channel") or {})
        self.assertTrue(oob_ch.get("registered"), oob_ch)
        self.assertTrue(oob_ch.get("diagnostic_token"))
        self.assertTrue(oob_ch.get("static_url_path"))

    def test_s3_oob_dom_priority_preserves_registered_row(self) -> None:
        from live_draft_stage1_s3_server_diag import _bound_row_list, _is_priority_row

        self.assertTrue(_is_priority_row({"phase": "S3_OOB_CHANNEL_REGISTERED"}))
        self.assertTrue(_is_priority_row({"phase": "S3_OOB_CHANNEL_INIT_FAILURE"}))
        rows = [{"phase": "NOISE", "event_id": f"n{i}"} for i in range(200)]
        rows.insert(0, {"phase": "S3_OOB_CHANNEL_REGISTERED", "event_id": "oob-keep"})
        bounded = _bound_row_list(rows, 96, label="ledger.rows", bounds_log=[])
        self.assertIn("oob-keep", {str(r.get("event_id") or "") for r in bounded})

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_init_exception_emits_failure_not_success(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        from live_draft_stage1_s3_process_global_diag import critical_ledger_by_phase
        from live_draft_stage1_s3_server_diag import (
            build_s3_readiness_payload,
            initialize_oob_channel_safely,
        )

        sid = "sid-init-exc"
        session = _FakeSessionStateProxy()
        with (
            patch("live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx", return_value=sid),
            patch(
                "live_draft_stage1_s3_oob_snapshot.publish_initial_oob_snapshot",
                side_effect=RuntimeError("oob boom"),
            ),
        ):
            phase = initialize_oob_channel_safely(session, sid)
        self.assertEqual(phase, "S3_OOB_CHANNEL_INIT_FAILURE")
        by_phase = critical_ledger_by_phase(sid)
        fail_rows = list(by_phase.get("S3_OOB_CHANNEL_INIT_FAILURE") or [])
        self.assertTrue(fail_rows, by_phase.keys())
        self.assertEqual(fail_rows[-1].get("exception_type"), "RuntimeError")
        self.assertIn("oob boom", str(fail_rows[-1].get("exception_message") or ""))
        self.assertEqual(fail_rows[-1].get("session_type"), "_FakeSessionStateProxy")
        self.assertTrue(fail_rows[-1].get("session_is_mutable_mapping"))
        self.assertFalse(by_phase.get("S3_OOB_CHANNEL_REGISTERED"))
        readiness = build_s3_readiness_payload(session)
        self.assertFalse(dict(readiness.get("oob_channel") or {}).get("registered"))

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_non_exception_init_failure_not_classified_success(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        from live_draft_stage1_s3_process_global_diag import critical_ledger_by_phase
        from live_draft_stage1_s3_server_diag import initialize_oob_channel_safely

        sid = "sid-init-false"
        session = _FakeSessionStateProxy()
        with (
            patch("live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx", return_value=sid),
            patch(
                "live_draft_stage1_s3_oob_snapshot.publish_initial_oob_snapshot",
                return_value={"registered": False, "published": False, "reason": "channel_not_registered"},
            ),
        ):
            phase = initialize_oob_channel_safely(session, sid)
        self.assertEqual(phase, "S3_OOB_CHANNEL_INIT_FAILURE")
        by_phase = critical_ledger_by_phase(sid)
        fail_rows = list(by_phase.get("S3_OOB_CHANNEL_INIT_FAILURE") or [])
        self.assertTrue(fail_rows)
        self.assertFalse(fail_rows[-1].get("registered"))
        self.assertFalse(fail_rows[-1].get("published"))
        self.assertEqual(fail_rows[-1].get("reason"), "channel_not_registered")
        self.assertFalse(by_phase.get("S3_OOB_CHANNEL_REGISTERED"))

    @patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root")
    def test_published_false_without_raise_is_failure(self, root_fn) -> None:
        root_fn.return_value = self.tmp
        from live_draft_stage1_s3_process_global_diag import critical_ledger_by_phase
        from live_draft_stage1_s3_server_diag import initialize_oob_channel_safely

        sid = "sid-pub-false"
        session = _FakeSessionStateProxy()
        with (
            patch("live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx", return_value=sid),
            patch(
                "live_draft_stage1_s3_oob_snapshot.publish_initial_oob_snapshot",
                return_value={
                    "registered": True,
                    "published": False,
                    "reason": "missing_sid_or_token",
                    "diagnostic_token": "",
                    "static_url_path": "",
                },
            ),
        ):
            phase = initialize_oob_channel_safely(session, sid)
        self.assertEqual(phase, "S3_OOB_CHANNEL_INIT_FAILURE")
        self.assertFalse(critical_ledger_by_phase(sid).get("S3_OOB_CHANNEL_REGISTERED"))


if __name__ == "__main__":
    unittest.main()
