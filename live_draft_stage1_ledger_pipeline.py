"""Diagnostic-only Stage 1 ledger pipeline canary (producer → DOM → harness)."""

from __future__ import annotations

import inspect
import json
import time
from typing import Any

PIPELINE_CANARY_EVENT = "production_stage1_cloud_ledger_pipeline_canary"
PIPELINE_CANARY_ID = "solo-stage1-ledger-pipeline-canary-v1"
PIPELINE_PROBE_DOM_ID = "solo-stage1-ledger-pipeline-canary"
PIPELINE_STATE_KEY = "_solo_stage1_ledger_pipeline_state"
PIPELINE_P1_COUNTER_KEY = "_solo_stage1_ledger_pipeline_p1_count"

STAGE_P1 = "LEDGER-P1"
STAGE_P2 = "LEDGER-P2"
STAGE_P3 = "LEDGER-P3"
STAGE_P4 = "LEDGER-P4"
STAGE_P5 = "LEDGER-P5"
STAGE_P6 = "LEDGER-P6"
STAGE_P7 = "LEDGER-P7"


def _fn_identity(fn: Any) -> str:
    try:
        mod = getattr(fn, "__module__", "") or ""
        name = getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn)))
        return f"{mod}.{name}"[:200]
    except Exception:
        return repr(fn)[:200]


def _pipeline_state(session: dict[str, Any]) -> dict[str, Any]:
    state = dict(session.get(PIPELINE_STATE_KEY) or {})
    state.setdefault("canary_id", PIPELINE_CANARY_ID)
    state.setdefault("stages", {})
    return state


def _save_pipeline_state(session: dict[str, Any], state: dict[str, Any]) -> None:
    session[PIPELINE_STATE_KEY] = state


def record_pipeline_stage(session: dict[str, Any], stage: str, **extra: Any) -> None:
    state = _pipeline_state(session)
    stages = dict(state.get("stages") or {})
    stages[str(stage)] = {"ts": time.time(), **extra}
    state["stages"] = stages
    _save_pipeline_state(session, state)


def bump_pipeline_p1_counter(session: dict[str, Any]) -> int:
    n = int(session.get(PIPELINE_P1_COUNTER_KEY) or 0) + 1
    session[PIPELINE_P1_COUNTER_KEY] = n
    return n


def diagnostic_context_snapshot(st: Any | None, session: dict[str, Any]) -> dict[str, Any]:
    qp: dict[str, str] = {}
    try:
        if st is not None and hasattr(st, "query_params"):
            for k in (
                "solo_component_diag",
                "solo_delivery_diag",
                "solo_delivery_case",
                "active_page",
            ):
                qp[k] = str(st.query_params.get(k) or "")[:120]
    except Exception:
        pass
    try:
        from live_draft_stage1_production_ledger import (
            STAGE1_LEDGER_KEY,
            STAGE1_LEDGER_MERGED_KEY,
            STAGE1_RUN_ID_KEY,
            STAGE1_SCRIPT_SEQ_KEY,
            ensure_stage1_run_id,
        )

        run_id = ensure_stage1_run_id(session)
        ledger_len = len(list(session.get(STAGE1_LEDGER_KEY) or []))
        merged_len = len(list(session.get(STAGE1_LEDGER_MERGED_KEY) or []))
    except ImportError:
        run_id = str(session.get("_solo_stage1_run_id") or "")[:32]
        ledger_len = 0
        merged_len = 0
        STAGE1_LEDGER_KEY = "_solo_stage1_production_ledger"
        STAGE1_LEDGER_MERGED_KEY = "_solo_stage1_production_ledger_merged"
        STAGE1_RUN_ID_KEY = "_solo_stage1_run_id"
        STAGE1_SCRIPT_SEQ_KEY = "_solo_stage1_script_run_seq"
    ss_id = ""
    try:
        if st is not None and getattr(st, "session_state", None) is not None:
            ss_id = str(id(st.session_state))
    except Exception:
        pass
    return {
        "canary_id": PIPELINE_CANARY_ID,
        "diagnostic_run_id": run_id,
        "session_object_id": ss_id,
        "session_dict_id": str(id(session)),
        "script_run_seq": int(session.get(STAGE1_SCRIPT_SEQ_KEY) or 0),
        "ledger_namespace_primary": STAGE1_LEDGER_KEY,
        "ledger_namespace_merged": STAGE1_LEDGER_MERGED_KEY,
        "ledger_row_count": ledger_len,
        "ledger_merged_count": merged_len,
        "query_params": qp,
        "solo_component_diag": qp.get("solo_component_diag") or str(session.get("_solo_component_diag_enabled") or ""),
        "solo_delivery_case": qp.get("solo_delivery_case") or "",
        "diagnostic_surface": "case_a_control" if qp.get("solo_delivery_case", "").upper() == "A" else "",
        "p1_counter": int(session.get(PIPELINE_P1_COUNTER_KEY) or 0),
    }


def emitter_identity_report() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from live_draft_prod_on_change_observability import _emit_row as canonical

        out["canonical_emit_row"] = _fn_identity(canonical)
    except ImportError:
        out["canonical_emit_row"] = ""
    try:
        import live_draft_streamlit_registration_hooks as hooks_mod

        out["registration_hooks_emit"] = _fn_identity(getattr(hooks_mod, "_emit", None))
    except ImportError:
        out["registration_hooks_emit"] = ""
    try:
        import live_draft_streamlit_widget_metadata_diag as meta_mod

        out["widget_metadata_diag_emit"] = _fn_identity(getattr(meta_mod, "_emit", None))
    except ImportError:
        out["widget_metadata_diag_emit"] = ""
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        out["note_stage1_event"] = _fn_identity(note_stage1_event)
    except ImportError:
        out["note_stage1_event"] = ""
    aliases_match = (
        out.get("registration_hooks_emit") == out.get("widget_metadata_diag_emit")
        and out.get("widget_metadata_diag_emit") != ""
    )
    out["hooks_and_metadata_emit_same_object"] = aliases_match
    return out


def emit_cloud_ledger_pipeline_canary(st: Any | None, session: dict[str, Any]) -> dict[str, Any]:
    """Emit deterministic canary immediately after diagnostic bootstrap."""
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return {}
    except ImportError:
        return {}

    p1 = bump_pipeline_p1_counter(session)
    ctx = diagnostic_context_snapshot(st, session)
    record_pipeline_stage(
        session,
        STAGE_P1,
        producer="live_draft_stage1_ledger_pipeline.emit_cloud_ledger_pipeline_canary",
        p1_count=p1,
        **ctx,
    )

    extra = {
        **ctx,
        "emitter_module": "live_draft_stage1_ledger_pipeline",
        "emitter_callable": "emit_cloud_ledger_pipeline_canary",
        "emitter_identities": emitter_identity_report(),
    }
    try:
        from live_draft_prod_on_change_observability import _emit_row

        record_pipeline_stage(session, STAGE_P2, emitter=_fn_identity(_emit_row))
        row = _emit_row(
            session,
            PIPELINE_CANARY_EVENT,
            st=st,
            room=None,
            widget_key="ledger_pipeline_canary",
            extra=extra,
        )
        record_pipeline_stage(session, STAGE_P2, entered=True, event=PIPELINE_CANARY_EVENT)
        try:
            from live_draft_stage1_production_ledger import STAGE1_LEDGER_KEY

            after = len(list(session.get(STAGE1_LEDGER_KEY) or []))
            record_pipeline_stage(
                session,
                STAGE_P3,
                stored=True,
                ledger_row_count=after,
                canary_in_ledger=any(
                    isinstance(r, dict) and r.get("event") == PIPELINE_CANARY_EVENT
                    for r in list(session.get(STAGE1_LEDGER_KEY) or [])
                ),
            )
        except ImportError:
            record_pipeline_stage(session, STAGE_P3, stored=False, reason="ledger_module_missing")
        return row
    except ImportError:
        record_pipeline_stage(session, STAGE_P2, entered=False, reason="emit_row_missing")
        return {}


def finalize_stage1_ledger_for_scrape(st: Any, session: dict[str, Any]) -> None:
    """Render ledger + pipeline probes after diagnostic work (before st.stop)."""
    try:
        from live_draft_stage1_production_ledger import (
            ledger_rows_for_export,
            render_stage1_production_ledger_probe,
            stage1_production_ledger_enabled,
        )

        if not stage1_production_ledger_enabled(st, session):
            return
        rows = ledger_rows_for_export(session)
        canary_present = any(
            isinstance(r, dict) and r.get("event") == PIPELINE_CANARY_EVENT for r in rows
        )
        record_pipeline_stage(
            session,
            STAGE_P4,
            export_row_count=len(rows),
            canary_present=canary_present,
            survives_filter=True,
        )
        render_stage1_production_ledger_probe(st, session)
        record_pipeline_stage(
            session,
            STAGE_P5,
            rendered=True,
            probe_id="solo-stage1-production-ledger",
            export_row_count=len(rows),
        )
    except ImportError:
        record_pipeline_stage(session, STAGE_P5, rendered=False, reason="render_import_error")
    render_pipeline_canary_probe(st, session)


def render_pipeline_canary_probe(st: Any, session: dict[str, Any]) -> None:
    state = _pipeline_state(session)
    stages = dict(state.get("stages") or {})
    ctx = diagnostic_context_snapshot(st, session)
    payload = json.dumps(
        {
            "canary_id": PIPELINE_CANARY_ID,
            "stages": stages,
            "context": ctx,
            "emitter_identities": emitter_identity_report(),
        },
        default=str,
    )[:12000]
    p1 = STAGE_P1 in stages
    p2 = STAGE_P2 in stages
    p3 = stages.get(STAGE_P3, {}).get("stored") is True
    p4 = STAGE_P4 in stages
    p5 = stages.get(STAGE_P5, {}).get("rendered") is True
    esc = payload.replace('"', "'")
    st.markdown(
        f'<div id="{PIPELINE_PROBE_DOM_ID}" '
        f'data-canary-id="{PIPELINE_CANARY_ID}" '
        f'data-p1="{1 if p1 else 0}" '
        f'data-p2="{1 if p2 else 0}" '
        f'data-p3="{1 if p3 else 0}" '
        f'data-p4="{1 if p4 else 0}" '
        f'data-p5="{1 if p5 else 0}" '
        f'data-p1-counter="{int(session.get(PIPELINE_P1_COUNTER_KEY) or 0)}" '
        f'data-run-id="{ctx.get("diagnostic_run_id") or ""}" '
        f'data-json="{esc}"></div>',
        unsafe_allow_html=True,
    )


def classify_first_ledger_pipeline_failure(
    *,
    pipeline_dom: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    artifact_has_canary: bool,
    raw_p6_capture_pass: bool | None = None,
    filtered_p6_capture_pass: bool | None = None,
) -> dict[str, Any]:
    """Return first missing P stage and LEDGER1–LEDGER10 classification."""
    dom_p = {
        "p1": int(pipeline_dom.get("p1") or 0),
        "p2": int(pipeline_dom.get("p2") or 0),
        "p3": int(pipeline_dom.get("p3") or 0),
        "p4": int(pipeline_dom.get("p4") or 0),
        "p5": int(pipeline_dom.get("p5") or 0),
    }
    p6_row = any(r.get("event") == PIPELINE_CANARY_EVENT for r in ledger_rows)
    p6 = bool(raw_p6_capture_pass) if raw_p6_capture_pass is not None else p6_row
    p7 = artifact_has_canary or p6
    if p6 and not p7:
        p7 = p6
    order = [
        (STAGE_P1, dom_p["p1"] or int(pipeline_dom.get("p1_counter") or 0) > 0),
        (STAGE_P2, dom_p["p2"]),
        (STAGE_P3, dom_p["p3"]),
        (STAGE_P4, dom_p["p4"]),
        (STAGE_P5, dom_p["p5"]),
        (STAGE_P6, p6),
        (STAGE_P7, p7),
    ]
    first_missing = ""
    for name, ok in order:
        if not ok:
            first_missing = name
            break
    classification = ""
    if first_missing == STAGE_P1:
        classification = "LEDGER10 — OTHER"
    elif first_missing == STAGE_P2:
        classification = "LEDGER1 — EMITTER_ALIAS_POINTS_TO_STALE_FUNCTION"
    elif first_missing == STAGE_P3:
        classification = "LEDGER2 — EVENTS_WRITTEN_TO_DIFFERENT_STORE"
    elif first_missing == STAGE_P4:
        classification = "LEDGER3 — DIAGNOSTIC_RUN_ID_FILTER_MISMATCH"
    elif first_missing == STAGE_P5:
        classification = "LEDGER6 — EARLY_RETURN_SKIPS_LEDGER_RENDERER"
    elif first_missing == STAGE_P6:
        classification = "LEDGER8 — DOM_RENDER_SUCCEEDS_BUT_PLAYWRIGHT_EXTRACTION_OR_DECODING_FAILS"
    elif first_missing == STAGE_P7:
        classification = "LEDGER9 — PLAYWRIGHT_CAPTURES_BEFORE_RENDER_COMPLETES"
    elif not first_missing:
        classification = "LEDGER_PIPELINE_OK"
    scrape_boundary = ""
    if first_missing == STAGE_P6 and filtered_p6_capture_pass is False and raw_p6_capture_pass:
        scrape_boundary = "SCRAPE8 — WRONG_RUN_OR_SESSION_FILTER_AFTER_CAPTURE"
    return {
        "first_missing_stage": first_missing,
        "classification": classification,
        "dom_p": dom_p,
        "p6_playwright_canary_in_rows": p6,
        "p7_artifact_canary": p7,
        "raw_p6_capture_pass": raw_p6_capture_pass,
        "filtered_p6_capture_pass": filtered_p6_capture_pass,
        "post_capture_filter_boundary": scrape_boundary,
    }
