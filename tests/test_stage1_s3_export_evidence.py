"""S3 export merge, critical ledger, wrapper integrity, authoritative classification."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_process_global(monkeypatch):
    mod = importlib.import_module("live_draft_stage1_s3_process_global_diag")
    with mod._LEDGER_LOCK:
        mod._MODULE_LEDGER_BY_STREAMLIT_SESSION.clear()
        mod._CRITICAL_LEDGER_BY_SESSION.clear()
        mod._UNROUTED_ORPHAN_LEDGER.clear()
        mod._SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION.clear()
        for k in mod._GLOBAL_WRAPPERS_INSTALLED:
            mod._GLOBAL_WRAPPERS_INSTALLED[k] = False
    yield


def test_local_longer_than_module_does_not_erase_module_rows():
    pg = importlib.import_module("live_draft_stage1_s3_process_global_diag")
    sid = "sess-merge-1"
    pg.append_module_event(sid, "APPSESSION_BACKMSG_ENTRY", pause_present=True, event_id="keep-me")
    # Simulate module tail-only view missing appsession while full module has it
    module_rows = pg.module_ledger_rows(sid)
    local_rows = [{"event_id": "local-only", "ts": 2.0, "phase": "REGISTER_ENTRY", "streamlit_session_id": sid}]
    for i in range(5):
        local_rows.append({"event_id": f"loc{i}", "ts": 3.0 + i, "phase": "REGISTER_RESULT", "streamlit_session_id": sid})
    ev = importlib.import_module("live_draft_stage1_server_evidence")
    merge = ev.merge_authoritative_server_rows(module_rows=module_rows, local_rows=local_rows)
    phases = {r.get("phase") for r in merge["merged_rows"]}
    assert "APPSESSION_BACKMSG_ENTRY" in phases
    assert merge["local_row_count"] == len(local_rows)


def test_critical_survives_noisy_registration(monkeypatch):
    pg = importlib.import_module("live_draft_stage1_s3_process_global_diag")
    sid = "sess-noisy"
    monkeypatch.setattr(pg, "streamlit_session_id_from_ctx", lambda: sid)
    for ph in (
        "APPSESSION_BACKMSG_ENTRY",
        "APPSESSION_REQUEST_RERUN_ENTRY",
        "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
        "SERVER_RECEIVE_ENTRY",
        "SERVER_STATE_APPLIED",
    ):
        pg.append_module_event(sid, ph, pause_present=True)
    for i in range(110):
        pg.append_module_event(sid, "REGISTER_ENTRY", n=i)
    crit = pg.critical_ledger_rows(sid)
    crit_phases = {r.get("phase") for r in crit}
    for ph in (
        "APPSESSION_BACKMSG_ENTRY",
        "APPSESSION_REQUEST_RERUN_ENTRY",
        "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
        "SERVER_RECEIVE_ENTRY",
        "SERVER_STATE_APPLIED",
    ):
        assert ph in crit_phases
    exp = importlib.import_module("live_draft_stage1_s3_server_diag")
    out = exp.s3_ledger_export({"_stage1_s3_server_diag_ledger": []})
    merged_phases = {r.get("phase") for r in out["merged_rows"]}
    assert "APPSESSION_BACKMSG_ENTRY" in merged_phases


def test_merge_dedupes_event_id():
    ev = importlib.import_module("live_draft_stage1_server_evidence")
    row = {"event_id": "abc", "ts": 1.0, "phase": "X"}
    m = ev.merge_authoritative_server_rows(module_rows=[row], local_rows=[dict(row)])
    assert m["merged_row_count"] == 1
    assert m["duplicate_event_id_count"] == 1


def test_merge_timestamp_order():
    ev = importlib.import_module("live_draft_stage1_server_evidence")
    m = ev.merge_authoritative_server_rows(
        module_rows=[
            {"event_id": "b", "ts": 2.0, "phase": "A"},
            {"event_id": "a", "ts": 1.0, "phase": "B"},
        ]
    )
    ts = [r["ts"] for r in m["merged_rows"]]
    assert ts == sorted(ts)


def test_appsession_export_reads_critical_ledger(monkeypatch):
    pg = importlib.import_module("live_draft_stage1_s3_process_global_diag")
    ingress = importlib.import_module("live_draft_stage1_appsession_ingress_diag")
    sid = "appsess-crit"
    monkeypatch.setattr(pg, "streamlit_session_id_from_ctx", lambda: sid)
    pg.append_module_event(sid, "APPSESSION_BACKMSG_ENTRY", pause_present=True)
    for i in range(120):
        pg.append_module_event(sid, "REGISTER_ENTRY", i=i)
    exp = ingress.appsession_ingress_export({})
    assert exp.get("source") == "critical_ledger"
    assert any(r.get("phase") == "APPSESSION_BACKMSG_ENTRY" for r in exp.get("rows") or [])


def test_runtime_backmsg_uses_explicit_session_id(monkeypatch):
    pg = importlib.import_module("live_draft_stage1_s3_process_global_diag")
    recorded: list[tuple[str, str]] = []

    def fake_append(sid, phase, **fields):
        recorded.append((sid, phase))
        return {"event_id": "rt1", "phase": phase, "streamlit_session_id": sid}

    monkeypatch.setattr(pg, "append_module_event", fake_append)
    monkeypatch.setattr(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        lambda st, session: True,
        raising=False,
    )
    rt = importlib.import_module("live_draft_stage1_runtime_backmsg_diag")
    fake_runtime = types.SimpleNamespace()
    fake_runtime.handle_backmsg = lambda self, session_id, msg: None
    fake_mod = types.ModuleType("streamlit.runtime.runtime")
    fake_mod.Runtime = type("Runtime", (), {"handle_backmsg": fake_runtime.handle_backmsg})
    monkeypatch.setitem(sys.modules, "streamlit.runtime.runtime", fake_mod)
    session = {}
    st = MagicMock()

    class Msg:
        def WhichOneof(self, _):
            return "rerun_script"

        class rerun_script:
            fragment_id = ""
            widget_states = None

            @staticmethod
            def HasField(_):
                return False

    rt.install_runtime_backmsg_probe(st, session)
    Runtime = fake_mod.Runtime
    Runtime.handle_backmsg(Runtime(), "explicit-sid-99", Msg())
    assert recorded and recorded[0][0] == "explicit-sid-99"
    assert recorded[0][1] == "RUNTIME_BACKMSG_ENTRY"


def test_runtime_pause_and_sibling_detection(monkeypatch):
    pg = importlib.import_module("live_draft_stage1_s3_process_global_diag")
    payloads: list[dict] = []

    def capture_append(sid, phase, **fields):
        payloads.append(dict(fields))
        return {"event_id": "x", "phase": phase}

    monkeypatch.setattr(pg, "append_module_event", capture_append)
    monkeypatch.setattr(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        lambda st, session: True,
        raising=False,
    )
    monkeypatch.setattr(
        pg,
        "scan_widget_states_proto",
        lambda ws: {
            "pause_present": True,
            "pause_sibling_present": True,
            "incoming_widget_count": 1,
            "activated_triggers": [],
        },
    )
    rt = importlib.import_module("live_draft_stage1_runtime_backmsg_diag")
    orig_called = []

    class Runtime:
        @staticmethod
        def handle_backmsg(self, session_id, msg):
            orig_called.append(1)

    fake_mod = types.ModuleType("streamlit.runtime.runtime")
    fake_mod.Runtime = Runtime
    monkeypatch.setitem(sys.modules, "streamlit.runtime.runtime", fake_mod)

    class RerunScript:
        fragment_id = "f1"
        widget_states = object()

        def HasField(self, name):
            return name == "widget_states"

    class Msg:
        rerun_script = RerunScript()

        def WhichOneof(self, _):
            return "rerun_script"

    rt.install_runtime_backmsg_probe(MagicMock(), {})
    Runtime.handle_backmsg(Runtime(), "s1", Msg())
    assert payloads[0].get("pause_present") is True
    assert payloads[0].get("pause_sibling_present") is True
    assert orig_called


def test_wrapper_integrity_detects_eleven_wrappers(monkeypatch):
    ev = importlib.import_module("live_draft_stage1_server_evidence")
    built: dict[tuple[str, str], type] = {}

    def fake_load(module_path: str, class_name: str):
        key = (module_path, class_name)
        if key not in built:
            built[key] = type(class_name, (), {})
        cls = built[key]
        for spec in ev._WRAPPER_SPECS:
            if spec[0] == module_path and spec[1] == class_name:
                sentinel = spec[3]
                method = spec[2]
                fn = lambda self: None
                setattr(fn, sentinel, True)
                setattr(cls, method, fn)
        return cls

    monkeypatch.setattr(ev, "_load_class", fake_load)
    snap = ev.live_server_wrapper_integrity_snapshot()
    assert snap["server_wrapper_integrity_ok"] is True
    assert len(snap["wrappers"]) == 11


def test_stale_flag_unwrapped_fails_integrity(monkeypatch):
    pg = importlib.import_module("live_draft_stage1_s3_process_global_diag")
    pg.mark_global_wrapper("runtime_handle_backmsg")
    ev = importlib.import_module("live_draft_stage1_server_evidence")
    built: dict[tuple[str, str], type] = {}

    def fake_load(module_path: str, class_name: str):
        key = (module_path, class_name)
        if key not in built:
            built[key] = type(class_name, (), {})
        cls = built[key]
        for spec in ev._WRAPPER_SPECS:
            if spec[0] == module_path and spec[1] == class_name:
                sentinel = spec[3]
                method = spec[2]
                fn = lambda self: None
                wrapped = not (class_name == "Runtime" and method == "handle_backmsg")
                setattr(fn, sentinel, wrapped)
                setattr(cls, method, fn)
        return cls

    monkeypatch.setattr(ev, "_load_class", fake_load)
    snap = ev.live_server_wrapper_integrity_snapshot()
    assert snap["server_wrapper_integrity_ok"] is False


def test_gate_classifier_uses_authoritative_merged_rows():
    clf = importlib.import_module("scripts.stage1_s3_r3_observability_classify")
    rows = [
        {"event_id": "1", "ts": 1.0, "phase": "RUNTIME_BACKMSG_ENTRY", "pause_present": True},
        {"event_id": "2", "ts": 2.0, "phase": "APPSESSION_BACKMSG_ENTRY", "pause_present": True},
        {"event_id": "3", "ts": 3.0, "phase": "APPSESSION_REQUEST_RERUN_ENTRY", "pause_present": True},
        {"event_id": "4", "ts": 4.0, "phase": "SAFE_SESSIONSTATE_RECEIVE_ENTRY", "pause_present": True},
        {"event_id": "5", "ts": 5.0, "phase": "SERVER_RECEIVE_ENTRY", "pause_present": True},
        {"event_id": "6", "ts": 6.0, "phase": "SERVER_STATE_APPLIED", "pause_present": True, "pause_trigger_from_deserialized": True},
    ]
    case, note, ev = clf.classify_s3_with_observability(
        module_rows=[],
        authoritative_rows=rows,
        pause_resolved=True,
        strict_backmsg={"activated_widget_state_present": True},
        wire_widget_id="$$ID-x",
        sibling_python_effect=False,
        register_widget_result=None,
        st_button_returned=None,
        binding_ok=True,
    )
    assert ev["pause_observability"]["ok"] is True
    assert case != clf.BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT


def test_appsession_module_plus_local_register():
    ev = importlib.import_module("live_draft_stage1_server_evidence")
    m = ev.merge_authoritative_server_rows(
        module_rows=[{"event_id": "a1", "ts": 1.0, "phase": "APPSESSION_BACKMSG_ENTRY"}],
        local_rows=[{"event_id": "r1", "ts": 2.0, "phase": "REGISTER_ENTRY"}],
    )
    phases = {r["phase"] for r in m["merged_rows"]}
    assert "APPSESSION_BACKMSG_ENTRY" in phases and "REGISTER_ENTRY" in phases


def test_pause_synthetic_chain_observability_pass():
    clf = importlib.import_module("scripts.stage1_s3_r3_observability_classify")
    rows = [
        {"event_id": str(i), "ts": float(i), "phase": ph, "pause_present": True}
        for i, ph in enumerate(
            (
                "RUNTIME_BACKMSG_ENTRY",
                "APPSESSION_BACKMSG_ENTRY",
                "APPSESSION_REQUEST_RERUN_ENTRY",
                "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
                "SERVER_RECEIVE_ENTRY",
                "SERVER_STATE_APPLIED",
            ),
            start=1,
        )
    ]
    rows[-1]["pause_trigger_from_deserialized"] = True
    obs = clf.pause_observability_chain(rows)
    assert obs["ok"] is True


def test_r3o0_browser_to_runtime_boundary():
    clf = importlib.import_module("scripts.stage1_s3_r3_observability_classify")
    case, note, _ = clf.classify_s3_with_observability(
        module_rows=[],
        authoritative_rows=[],
        pause_resolved=True,
        strict_backmsg={},
        wire_widget_id="",
        sibling_python_effect=False,
        register_widget_result=None,
        st_button_returned=None,
        binding_ok=True,
    )
    assert case == clf.BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT
    assert "browser_to_runtime" in note


def test_r3o0_runtime_to_appsession_boundary():
    clf = importlib.import_module("scripts.stage1_s3_r3_observability_classify")
    rows = [{"event_id": "1", "ts": 1.0, "phase": "RUNTIME_BACKMSG_ENTRY", "pause_present": True}]
    case, note, _ = clf.classify_s3_with_observability(
        module_rows=rows,
        authoritative_rows=rows,
        pause_resolved=True,
        strict_backmsg={},
        wire_widget_id="",
        sibling_python_effect=False,
        register_widget_result=None,
        st_button_returned=None,
        binding_ok=True,
    )
    assert case == clf.BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT
    assert "runtime_to_appsession" in note
