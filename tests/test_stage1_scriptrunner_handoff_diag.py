"""Scheduler-handoff observability: ScriptRunner / ScriptRequests diagnostics."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

from live_draft_stage1_s3_process_global_diag import (  # noqa: E402
    module_ledger_rows,
    unrouted_ledger_export,
)
from live_draft_stage1_scriptrunner_handoff_diag import (  # noqa: E402
    ensure_scriptrunner_handoff_wrappers,
    record_scriptrunner_run_script_entry,
    register_scriptrequests_session,
    resolve_scriptrequests_sid,
    resolve_scriptrunner_sid,
)
from streamlit.proto.WidgetStates_pb2 import WidgetStates  # noqa: E402
from streamlit.runtime.scriptrunner.script_runner import ScriptRunner  # noqa: E402
from streamlit.runtime.scriptrunner_utils.script_requests import (  # noqa: E402
    RerunData,
    ScriptRequestType,
    ScriptRequests,
)


def _clear_ledgers() -> None:
    import live_draft_stage1_s3_process_global_diag as pg
    import live_draft_stage1_scriptrunner_handoff_diag as hd

    with pg._LEDGER_LOCK:
        pg._MODULE_LEDGER_BY_STREAMLIT_SESSION.clear()
        pg._CRITICAL_LEDGER_BY_SESSION.clear()
        pg._UNROUTED_ORPHAN_LEDGER.clear()
    with hd._MAP_LOCK:
        hd._SCRIPTREQUESTS_OID_TO_SID.clear()
        hd._SCRIPTRUNNER_OID_TO_SID.clear()


def _ws_pause() -> WidgetStates:
    ws = WidgetStates()
    w = ws.widgets.add()
    w.id = "$$ID-a-live_draft_pause"
    w.trigger_value = True
    return ws


def _ws_unrelated() -> WidgetStates:
    ws = WidgetStates()
    w = ws.widgets.add()
    w.id = "$$ID-other-some_button"
    w.trigger_value = True
    return ws


def _ws_empty() -> WidgetStates:
    return WidgetStates()


def _phases(sid: str) -> list[str]:
    return [str(r.get("phase") or "") for r in module_ledger_rows(sid)]


def _last(sid: str, phase: str) -> dict:
    rows = [r for r in module_ledger_rows(sid) if r.get("phase") == phase]
    assert rows, f"missing phase {phase} for {sid}"
    return rows[-1]


class ScriptRunnerHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_ledgers()
        ensure_scriptrunner_handoff_wrappers()

    def _fake_runner(self, sid: str) -> ScriptRunner:
        runner = object.__new__(ScriptRunner)
        runner._session_id = sid
        runner._requests = ScriptRequests()
        runner._join_wake_lock = threading.Lock()
        runner._join_wake_coordinator = None
        register_scriptrequests_session(runner._requests, sid)
        return runner

    def test_scriptrunner_accepts_pause_bearing_rerun(self) -> None:
        sid = "sid-sr-accept"
        runner = self._fake_runner(sid)
        ok = ScriptRunner.request_rerun(runner, RerunData(widget_states=_ws_pause()))
        self.assertTrue(ok)
        entry = _last(sid, "SCRIPTRUNNER_REQUEST_RERUN_ENTRY")
        result = _last(sid, "SCRIPTRUNNER_REQUEST_RERUN_RESULT")
        self.assertTrue(entry.get("pause_present"))
        self.assertTrue(result.get("accepted"))
        self.assertTrue(result.get("pause_present"))
        self.assertIn("SCRIPTREQUESTS_RERUN_STORED", _phases(sid))

    def test_initial_queue_store_retains_pause(self) -> None:
        sid = "sid-store"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
        stored = _last(sid, "SCRIPTREQUESTS_RERUN_STORED")
        self.assertTrue(stored.get("pause_present"))
        self.assertEqual(stored.get("incoming_widget_count"), 1)

    def test_coalesce_old_pause_new_none_retains_pause(self) -> None:
        """Streamlit 1.59.1 keeps activated triggers from previous pending state."""
        sid = "sid-coal-old-pause"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_empty())))
        coal = _last(sid, "SCRIPTREQUESTS_RERUN_COALESCED")
        self.assertTrue(coal.get("previous_pause_present"))
        self.assertFalse(coal.get("new_pause_present"))
        self.assertTrue(coal.get("pause_present"))
        self.assertTrue(coal.get("pause_retained_from_previous"))

    def test_coalesce_old_none_new_pause_introduces_pause(self) -> None:
        sid = "sid-coal-new-pause"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_unrelated())))
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
        coal = _last(sid, "SCRIPTREQUESTS_RERUN_COALESCED")
        self.assertFalse(coal.get("previous_pause_present"))
        self.assertTrue(coal.get("new_pause_present"))
        self.assertTrue(coal.get("pause_present"))

    def test_coalesce_old_pause_new_unrelated_retains_pause(self) -> None:
        sid = "sid-coal-unrel"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_unrelated())))
        coal = _last(sid, "SCRIPTREQUESTS_RERUN_COALESCED")
        self.assertTrue(coal.get("previous_pause_present"))
        self.assertTrue(coal.get("pause_present"))
        triggers = coal.get("activated_triggers") or []
        ids = {t.get("id") for t in triggers}
        self.assertIn("$$ID-a-live_draft_pause", ids)
        self.assertIn("$$ID-other-some_button", ids)

    def test_coalesce_fragment_appends_queue(self) -> None:
        sid = "sid-coal-frag"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(fragment_id="frag-a")))
        self.assertTrue(reqs.request_rerun(RerunData(fragment_id="frag-b")))
        coal = _last(sid, "SCRIPTREQUESTS_RERUN_COALESCED")
        self.assertEqual(coal.get("fragment_id_queue"), ["frag-a", "frag-b"])

    def test_full_rerun_clears_fragment_queue(self) -> None:
        """Full-script RerunData (no fragment_id / queue) clears queued fragments."""
        sid = "sid-coal-clear"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(fragment_id="frag-a", widget_states=_ws_pause())))
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_unrelated())))
        coal = _last(sid, "SCRIPTREQUESTS_RERUN_COALESCED")
        self.assertEqual(coal.get("fragment_id_queue"), [])
        self.assertTrue(coal.get("pause_present"))

    def test_consumption_scans_returned_rerun_data(self) -> None:
        sid = "sid-consume"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
        # Full-script pending RERUN preempts on yield.
        req = reqs.on_scriptrunner_yield()
        self.assertIsNotNone(req)
        self.assertEqual(req.type, ScriptRequestType.RERUN)
        consumed = _last(sid, "SCRIPTREQUESTS_RERUN_CONSUMED")
        self.assertTrue(consumed.get("pause_present"))
        self.assertEqual(consumed.get("consume_api"), "on_scriptrunner_yield")

    def test_consumption_via_on_scriptrunner_ready(self) -> None:
        sid = "sid-ready"
        reqs = ScriptRequests()
        register_scriptrequests_session(reqs, sid)
        self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
        req = reqs.on_scriptrunner_ready()
        self.assertEqual(req.type, ScriptRequestType.RERUN)
        consumed = _last(sid, "SCRIPTREQUESTS_RERUN_CONSUMED")
        self.assertTrue(consumed.get("pause_present"))
        self.assertEqual(consumed.get("consume_api"), "on_scriptrunner_ready")

    def test_run_script_entry_pause_present(self) -> None:
        sid = "sid-run"
        runner = self._fake_runner(sid)
        out = record_scriptrunner_run_script_entry(runner, RerunData(widget_states=_ws_pause()))
        self.assertTrue(out.get("pause_present"))
        entry = _last(sid, "SCRIPTRUNNER_RUN_SCRIPT_ENTRY")
        self.assertTrue(entry.get("pause_present"))
        self.assertEqual(entry.get("incoming_widget_count"), 1)

    def test_sid_prefers_scriptrunner_owned_over_ctx(self) -> None:
        runner = self._fake_runner("sid-owned")
        with patch(
            "live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx",
            return_value="sid-ctx-wrong",
        ):
            sid, source = resolve_scriptrunner_sid(runner)
        self.assertEqual(sid, "sid-owned")
        self.assertEqual(source, "scriptrunner_session_id")

    def test_scriptrequests_unrouted_when_sid_missing(self) -> None:
        reqs = ScriptRequests()
        with patch(
            "live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx",
            return_value="",
        ):
            sid, source = resolve_scriptrequests_sid(reqs)
            self.assertEqual(sid, "")
            self.assertEqual(source, "scriptrequests_sid_unresolved")
            self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
        unrouted = unrouted_ledger_export().get("rows") or []
        phases = [r.get("phase") for r in unrouted]
        self.assertIn("SCRIPTREQUESTS_REQUEST_RERUN_ENTRY", phases)
        reasons = {r.get("routing_failure_reason") for r in unrouted}
        self.assertTrue(any("scriptrequests" in str(x) for x in reasons))


class DownstreamOobPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_ledgers()
        ensure_scriptrunner_handoff_wrappers()
        import live_draft_stage1_s3_oob_snapshot as oob

        self.tmp = ROOT / "static" / "s3_oob" / "_test_handoff_oob"
        self.tmp.mkdir(parents=True, exist_ok=True)
        with oob._OOB_LOCK:
            oob._OOB_GENERATION_BY_TOKEN.clear()
            oob._STREAMLIT_SESSION_TO_TOKEN.clear()
        self.addCleanup(lambda: [p.unlink(missing_ok=True) for p in self.tmp.glob("*.json")])

    def test_downstream_oob_publish_sources_advance(self) -> None:
        import live_draft_stage1_s3_oob_snapshot as oob
        from live_draft_stage1_s3_oob_snapshot import (
            current_generation,
            publish_oob_snapshot,
            read_oob_snapshot_file,
            register_oob_channel,
        )
        from live_draft_stage1_s3_process_global_diag import register_sessionstate_instance
        from live_draft_stage1_s3_server_diag import _ensure_global_sessionstate_wrappers, _ensure_safe_sessionstate_wrappers
        from streamlit.runtime.state.safe_session_state import SafeSessionState
        from streamlit.runtime.state.session_state import SessionState

        sources: list[str] = []
        real_pub = oob.publish_oob_snapshot

        def tracked(streamlit_session_id, *, publish_source, session=None, diagnostic_token=""):
            sources.append(str(publish_source))
            return real_pub(
                streamlit_session_id,
                publish_source=publish_source,
                session=session,
                diagnostic_token=diagnostic_token or token,
            )

        with patch.object(oob, "oob_snapshot_root", return_value=self.tmp):
            sid = "sid-oob-down"
            channel = register_oob_channel(sid, {})
            token = channel["diagnostic_token"]
            pub0 = publish_oob_snapshot(sid, publish_source="initial_pre_click", diagnostic_token=token)
            self.assertEqual(pub0["snapshot_generation"], 1)

            reqs = ScriptRequests()
            register_scriptrequests_session(reqs, sid)
            _ensure_safe_sessionstate_wrappers()
            _ensure_global_sessionstate_wrappers()

            with patch(
                "live_draft_stage1_s3_oob_snapshot.publish_oob_snapshot",
                side_effect=tracked,
            ):
                self.assertTrue(reqs.request_rerun(RerunData(widget_states=_ws_pause())))
                reqs.on_scriptrunner_ready()
                runner = object.__new__(ScriptRunner)
                runner._session_id = sid
                runner._requests = reqs
                record_scriptrunner_run_script_entry(runner, RerunData(widget_states=_ws_pause()))

                underlying = SessionState()
                register_sessionstate_instance(underlying, sid)
                safe = SafeSessionState(underlying, lambda: None)
                register_sessionstate_instance(safe, sid)
                # Nested: Safe receive → SessionState receive → set_widgets applied
                SafeSessionState.on_script_will_rerun(safe, _ws_pause())

            self.assertIn("scriptrequests_rerun_consumed", sources)
            self.assertIn("scriptrunner_run_script_entry", sources)
            self.assertIn("safe_sessionstate_receive", sources)
            self.assertIn("sessionstate_receive", sources)
            self.assertIn("sessionstate_applied", sources)
            self.assertGreater(current_generation(token), 1)
            snap = read_oob_snapshot_file(token)
            self.assertEqual(snap.get("publish_source"), "sessionstate_applied")
            publish_oob_snapshot(sid, publish_source="runtime_handle_backmsg_finally", diagnostic_token=token)
            snap = read_oob_snapshot_file(token)
            self.assertEqual(snap.get("publish_source"), "runtime_handle_backmsg_finally")


class InstallWiringTests(unittest.TestCase):
    def test_install_s3_wires_handoff(self) -> None:
        import inspect

        from live_draft_stage1_s3_server_diag import install_s3_server_diagnostics

        src = inspect.getsource(install_s3_server_diagnostics)
        self.assertIn("ensure_scriptrunner_handoff_wrappers", src)

    def test_wrapper_sentinels_set(self) -> None:
        ensure_scriptrunner_handoff_wrappers()
        self.assertTrue(getattr(ScriptRunner.request_rerun, "_solo_scriptrunner_rerun_wrapped", False))
        self.assertTrue(getattr(ScriptRunner._run_script, "_solo_scriptrunner_run_script_wrapped", False))
        self.assertTrue(getattr(ScriptRequests.request_rerun, "_solo_scriptrequests_rerun_wrapped", False))
        self.assertTrue(getattr(ScriptRequests.on_scriptrunner_yield, "_solo_scriptrequests_yield_wrapped", False))
        self.assertTrue(getattr(ScriptRequests.on_scriptrunner_ready, "_solo_scriptrequests_ready_wrapped", False))


if __name__ == "__main__":
    unittest.main()
