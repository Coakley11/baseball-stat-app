"""S3 DOM payload export: valid JSON, bounded evidence, readiness surface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pytest

from live_draft_stage1_s3_server_diag import (  # noqa: E402
    S3_DOM_PAYLOAD_SCHEMA_REV,
    build_s3_dom_payload,
    build_s3_readiness_payload,
    serialize_s3_dom_json,
)
from stage1_s3_server_registry_scrape import (  # noqa: E402
    _parse_dom_json_attr,
    reconcile_s3_readiness_vs_ledger,
    resolve_authoritative_s3_setup_from_scrapes,
)
from stage1_s3_setup_localize import (  # noqa: E402
    ABORTED_S3_LEDGER_PAYLOAD_INVALID,
    ABORTED_S3_POST_REGISTRATION_NOT_READY,
    classify_setup_failure,
    classify_s3_ledger_scrape_issues,
)


def _fat_session(*, row_count: int = 400) -> dict:
    pg = __import__("live_draft_stage1_s3_process_global_diag", fromlist=["append_module_event"])
    sid = "dom-export-sid"
    for i in range(row_count):
        pg.append_module_event(sid, "REGISTER_ENTRY", n=i)
    post = {
        "registered_widget_id": "$$ID-deadbeef-stage1_pause_sibling_return_ROOM01_diag",
        "user_key": "stage1_pause_sibling_return_ROOM01_diag",
    }
    binding = {
        "sessionstate_binding_ok": True,
        "server_wrapper_integrity_ok": True,
        "streamlit_session_id": sid,
    }
    return {
        "_stage1_pause_sibling_post_registration": post,
        "_stage1_pause_sibling_pre_declaration": {"widget_key": "stage1_pause_sibling_return_ROOM01_diag"},
        "_stage1_s3_diag_binding": binding,
        "_stage1_s3_server_watch_user_key": "stage1_pause_sibling_return_ROOM01_diag",
        "_stage1_s3_server_diag_ledger": [],
    }


def test_large_export_produces_valid_json_above_old_cap(monkeypatch):
    s3_mod = __import__("live_draft_stage1_s3_server_diag", fromlist=["build_s3_dom_payload"])
    monkeypatch.setattr("live_draft_stage1_s3_server_diag._streamlit_session_id", lambda: "dom-export-sid")
    for key in ("module_rows", "local_rows", "merged_rows", "ledger_rows"):
        monkeypatch.setitem(s3_mod._S3_DOM_ROW_LIMITS, key, 1200)
    huge = [{"event_id": f"e{i}", "ts": float(i), "phase": "REGISTER_ENTRY"} for i in range(2500)]
    export = {
        "streamlit_session_id": "dom-export-sid",
        "event_count": len(huge),
        "rows": huge,
        "module_rows": huge,
        "local_rows": huge,
        "critical_server_rows": [{"event_id": "crit1", "ts": 1.0, "phase": "APPSESSION_BACKMSG_ENTRY"}],
        "merged_rows": huge,
        "merge_stats": {"merged_row_count": len(huge)},
        "module_row_count_before_tail": len(huge),
        "impl_rev": "stage1_s3_server_diag_v6",
    }
    session = _fat_session(row_count=0)
    payload = build_s3_dom_payload(session, export=export)
    text = serialize_s3_dom_json(payload)
    assert len(text) > 36000
    parsed = json.loads(text)
    assert parsed["export_meta"]["payload_truncated"] is False
    assert parsed["export_meta"]["payload_complete"] is True
    assert isinstance(parsed["post_registration"], dict)
    assert str(parsed["post_registration"].get("registered_widget_id", "")).startswith("$$ID-")


def test_post_registration_and_binding_survive_volume(monkeypatch):
    monkeypatch.setattr("live_draft_stage1_s3_server_diag._streamlit_session_id", lambda: "dom-export-sid")
    huge = [{"event_id": f"e{i}", "ts": float(i), "phase": "REGISTER_ENTRY"} for i in range(700)]
    export = {
        "streamlit_session_id": "dom-export-sid",
        "event_count": len(huge),
        "rows": huge,
        "module_rows": huge,
        "local_rows": huge,
        "critical_server_rows": [],
        "merged_rows": huge,
        "merge_stats": {},
        "module_row_count_before_tail": len(huge),
        "impl_rev": "stage1_s3_server_diag_v6",
    }
    session = _fat_session(row_count=0)
    payload = build_s3_dom_payload(session, export=export)
    assert payload["s3_diag_binding"]["server_wrapper_integrity_ok"] is True
    assert payload["post_registration"]["registered_widget_id"].startswith("$$ID-")
    assert payload["payload_schema_rev"] == S3_DOM_PAYLOAD_SCHEMA_REV
    meta = payload["export_meta"]
    assert meta["row_counts_before_bounding"]["ledger.module_rows"] >= meta["row_counts_exported"]["ledger.module_rows"]


def test_critical_phases_can_remain_after_bounding(monkeypatch):
    pg = __import__("live_draft_stage1_s3_process_global_diag", fromlist=["append_module_event"])
    sid = "crit-sid"
    monkeypatch.setattr(pg, "streamlit_session_id_from_ctx", lambda: sid)
    monkeypatch.setattr("live_draft_stage1_s3_server_diag._streamlit_session_id", lambda: sid)
    pg.append_module_event(sid, "APPSESSION_BACKMSG_ENTRY", pause_present=True)
    for i in range(300):
        pg.append_module_event(sid, "REGISTER_ENTRY", i=i)
    session = _fat_session(row_count=0)
    payload = build_s3_dom_payload(session)
    merged_phases = {r.get("phase") for r in payload["ledger"]["merged_rows"]}
    assert "APPSESSION_BACKMSG_ENTRY" in merged_phases


def test_malformed_json_classified_payload_invalid_not_post_reg():
    scrape = {"found": True, "parse_ok": False, "parse_error": "JSONDecodeError", "payload": None}
    case, note = classify_s3_ledger_scrape_issues(s3_ledger_scrape=scrape)
    assert case == ABORTED_S3_LEDGER_PAYLOAD_INVALID
    assert "parse_failed" in note
    layers = {
        "sibling_callsite_found": True,
        "sibling_import_ok": True,
        "sibling_entry_found": True,
        "sibling_diag_enabled": True,
        "sibling_button_found": True,
        "sibling_ledger_found": True,
        "sibling_pre_button_reached": True,
        "sibling_post_button_return_reached": True,
        "sibling_button_call_returned_reached": True,
        "sibling_post_registration_returned_reached": True,
        "sibling_setup_export_complete_reached": True,
    }
    case2, _ = classify_setup_failure(
        pause_ready={"ready": True},
        sibling_layers=layers,
        s3_ledger_scrape=scrape,
        post_registration={},
        binding={},
    )
    assert case2 == ABORTED_S3_LEDGER_PAYLOAD_INVALID
    assert case2 != ABORTED_S3_POST_REGISTRATION_NOT_READY


def test_readiness_and_ledger_agree():
    reg = "$$ID-abc-stage1_pause_sibling_return_X_diag"
    ledger = {
        "found": True,
        "parse_ok": True,
        "payload": {
            "post_registration": {"registered_widget_id": reg},
            "s3_diag_binding": {"server_wrapper_integrity_ok": True},
        },
    }
    readiness = {
        "found": True,
        "parse_ok": True,
        "payload": {
            "post_registration": {"registered_widget_id": reg},
            "s3_diag_binding": {"server_wrapper_integrity_ok": True},
        },
    }
    rec = reconcile_s3_readiness_vs_ledger(ledger_scrape=ledger, readiness_scrape=readiness)
    assert rec["mismatch"] is False
    resolved = resolve_authoritative_s3_setup_from_scrapes(ledger, readiness)
    assert resolved["post_registration"]["registered_widget_id"] == reg


def test_readiness_mismatch_detected():
    ledger = {
        "found": True,
        "parse_ok": True,
        "payload": {
            "post_registration": {"registered_widget_id": "$$ID-a"},
            "s3_diag_binding": {"server_wrapper_integrity_ok": True},
        },
    }
    readiness = {
        "found": True,
        "parse_ok": True,
        "payload": {
            "post_registration": {"registered_widget_id": "$$ID-b"},
            "s3_diag_binding": {"server_wrapper_integrity_ok": True},
        },
    }
    rec = reconcile_s3_readiness_vs_ledger(ledger_scrape=ledger, readiness_scrape=readiness)
    assert rec["mismatch"] is True
    case, note = classify_s3_ledger_scrape_issues(s3_ledger_scrape=ledger, readiness_scrape=readiness)
    assert case == ABORTED_S3_LEDGER_PAYLOAD_INVALID
    assert "mismatch" in note


def test_parse_dom_json_reports_error():
    payload, err = _parse_dom_json_attr('{"post_registration": ')
    assert payload is None
    assert err


def test_readiness_payload_compact():
    session = _fat_session(row_count=10)
    r = build_s3_readiness_payload(session)
    assert r["post_registration"]["registered_widget_id"].startswith("$$ID-")
    assert r["s3_diag_binding"]["server_wrapper_integrity_ok"] is True
