"""Auth capture observability: bind Start UI surface to ledger/session identity (harness only)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

AUTH_OBSERVABILITY1 = "AUTH_OBSERVABILITY1"
AUTH_OBSERVABILITY2 = "AUTH_OBSERVABILITY2"
AUTH_OBSERVABILITY3 = "AUTH_OBSERVABILITY3"
AUTH_OBSERVABILITY4 = "AUTH_OBSERVABILITY4"
AUTH_OBSERVABILITY5 = "AUTH_OBSERVABILITY5"
AUTH_OBSERVABILITY6 = "AUTH_OBSERVABILITY6"
AUTH_OBSERVABILITY8 = "AUTH_OBSERVABILITY8"

CAPTURE_FAIL_OBSERVABILITY = "auth_observability_ledger_binding_failed"

_START_IN_FRAME_JS = """
() => {
  for (const b of document.querySelectorAll('button')) {
    const t = (b.innerText || '').replace(/\\s+/g, ' ').trim();
    if (/Start New Live Draft/i.test(t)) {
      const r = b.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        return { visible: true, disabled: !!b.disabled };
      }
    }
  }
  return { visible: false, disabled: true };
}
"""

_PROBE_LEDGER_META_IN_FRAME_JS = """
() => {
  const PROBE_ID = "solo-stage1-production-ledger";
  function metaFrom(el) {
    if (!el) return null;
    return {
      streamlit_session_id: el.getAttribute("data-streamlit-session-id") || "",
      diagnostic_run_id: el.getAttribute("data-diagnostic-run-id") || el.getAttribute("data-run-id") || "",
      script_run_seq: parseInt(el.getAttribute("data-script-run-seq") || "0", 10) || 0,
      row_count_attr: parseInt(el.getAttribute("data-row-count") || el.getAttribute("data-rows") || "0", 10) || 0,
      probe_checkpoint: el.getAttribute("data-probe-checkpoint") || "",
      deploy_sha: "",
    };
  }
  const el = document.getElementById(PROBE_ID);
  const dep = document.querySelector("#solo-deploy-build");
  const m = metaFrom(el);
  if (m) {
    if (dep) m.deploy_sha = (dep.getAttribute("data-sha") || "").slice(0, 7);
    return m;
  }
  if (dep) {
    return {
      streamlit_session_id: "",
      diagnostic_run_id: "",
      script_run_seq: 0,
      row_count_attr: 0,
      probe_checkpoint: "",
      deploy_sha: (dep.getAttribute("data-sha") || "").slice(0, 7),
    };
  }
  return null;
}
"""

SESSION_BINDING_FAIL = "session_binding_identity_mismatch"


def suite_sid_from_url(url: str) -> str:
    try:
        return str(parse_qs(urlparse(url).query).get("suite_sid", [""])[0] or "").strip()
    except Exception:
        return ""


def diagnostic_query_flags(url: str) -> dict[str, Any]:
    try:
        q = parse_qs(urlparse(url).query)
    except Exception:
        q = {}
    active = str(q.get("active_page", [""])[0] or "")
    return {
        "suite_sid_present": bool(str(q.get("suite_sid", [""])[0] or "").strip()),
        "solo_component_diag": str(q.get("solo_component_diag", [""])[0] or "") == "1",
        "solo_stage1_parent_boundary": str(q.get("solo_stage1_parent_boundary", [""])[0] or "") == "1",
        "live_draft_room_active": "live" in active.lower() and "draft" in active.lower(),
    }


def find_start_control_surface(page) -> dict[str, Any]:
    """Start button surface including Playwright frame index."""
    out: dict[str, Any] = {
        "visible": False,
        "enabled": False,
        "disabled": True,
        "frame_index": 0,
        "frame_url": "",
        "page_url": "",
        "suite_sid": "",
        "playwright_page_id": "",
        "selected_page_reason": "top_level_page",
    }
    try:
        out["page_url"] = str(page.url or "")[:512]
        out["suite_sid"] = suite_sid_from_url(out["page_url"])
        out["playwright_page_id"] = hex(id(page))[:14]
    except Exception:
        pass
    try:
        for i, fr in enumerate(page.frames):
            scan = fr.evaluate(_START_IN_FRAME_JS)
            if isinstance(scan, dict) and scan.get("visible"):
                out["visible"] = True
                out["disabled"] = bool(scan.get("disabled"))
                out["enabled"] = out["visible"] and not out["disabled"]
                out["frame_index"] = i
                out["frame_url"] = str(fr.url or "")[:400]
                out["selected_page_reason"] = "start_button_frame" if i > 0 else "start_button_main_frame"
                break
    except Exception:
        pass
    return out


def _probe_ledger_meta_on_frame(fr) -> dict[str, Any]:
    try:
        raw = fr.evaluate(_PROBE_LEDGER_META_IN_FRAME_JS)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def probe_dom_current_state_checkpoint(page, *, start_surface: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read-only identity checkpoint from DOM on the Start frame (no secrets)."""
    ss = start_surface or find_start_control_surface(page)
    dom: dict[str, Any] = {}
    fi = int(ss.get("frame_index") or 0)
    try:
        frames = page.frames
        if 0 <= fi < len(frames):
            dom = _probe_ledger_meta_on_frame(frames[fi])
        if not dom.get("streamlit_session_id") and not dom.get("diagnostic_run_id"):
            for fr in frames:
                dom = dom or _probe_ledger_meta_on_frame(fr)
                if dom.get("streamlit_session_id") or dom.get("diagnostic_run_id"):
                    break
    except Exception:
        pass
    flags = diagnostic_query_flags(str(page.url or ""))
    return {
        "streamlit_session_id": str(dom.get("streamlit_session_id") or "")[:36],
        "diagnostic_run_id": str(dom.get("diagnostic_run_id") or "")[:64],
        "script_run_seq": int(dom.get("script_run_seq") or 0),
        "suite_sid_prefix": str(ss.get("suite_sid") or "")[:8],
        "start_visible": bool(ss.get("visible")),
        "start_enabled": bool(ss.get("enabled")),
        "start_frame_index": fi,
        "start_frame_url_host": urlparse(str(ss.get("frame_url") or "")).netloc[:80],
        "deploy_sha": str(dom.get("deploy_sha") or "")[:7],
        "ledger_row_count_attr": int(dom.get("row_count_attr") or 0),
        "probe_checkpoint": str(dom.get("probe_checkpoint") or "")[:40],
        "diagnostic_query_flags": flags,
        "restore_blocked_reason": "",
        "is_authenticated": None,
        "auth_session_complete": None,
        "session_flag_present": None,
    }


def scrape_ledger_with_surface_binding(page, *, start_surface: dict[str, Any] | None = None) -> dict[str, Any]:
    from stage1_ledger_browser_extract import extract_stage1_ledger_from_page

    ss = start_surface or find_start_control_surface(page)
    fi = int(ss.get("frame_index") or 0)
    ext = extract_stage1_ledger_from_page(page, preferred_frame_index=fi)
    rows = list(ext.get("rows") or [])
    fi = int(ss.get("frame_index") or 0)
    candidates = [c for c in (ext.get("candidates") or []) if isinstance(c, dict)]
    frame_cands = [c for c in candidates if int(c.get("frame_index") or -1) == fi]
    ledger_frame_index = ext.get("selected_frame_index")
    same_frame_as_start = ledger_frame_index is not None and int(ledger_frame_index) == fi
    ledger_session = ""
    ledger_run = ""
    for c in frame_cands:
        ledger_session = ledger_session or str(c.get("data_streamlit_session_id") or "")
        ledger_run = ledger_run or str(c.get("data_run_id") or c.get("run_id") or "")
    auth_rows = [
        r
        for r in rows
        if str(r.get("event") or "")
        in (
            "production_stage1_auth_prestart_hydration",
            "production_stage1_auth_state_before_start_control",
        )
    ]
    before_start = next(
        (r for r in reversed(rows) if str(r.get("event") or "") == "production_stage1_auth_state_before_start_control"),
        None,
    )
    return {
        "rows": rows,
        "row_count": len(rows),
        "auth_row_count": len(auth_rows),
        "extract_meta": {
            "selected_frame_index": ledger_frame_index,
            "selected_frame_url": str(ext.get("selected_frame_url") or "")[:200],
            "selected_source": str(ext.get("selected_source") or ""),
            "first_scrape_boundary": str(ext.get("first_scrape_boundary") or ""),
            "pipeline_canary_present": bool(ext.get("pipeline_canary_present")),
            "diagnostic_run_ids": ext.get("diagnostic_run_ids") or [],
        },
        "start_surface": ss,
        "ledger_same_frame_as_start": same_frame_as_start,
        "ledger_streamlit_session_id": str(
            (before_start or {}).get("streamlit_session_id") or ledger_session or ""
        )[:36],
        "ledger_diagnostic_run_id": str(
            (before_start or {}).get("diagnostic_run_id")
            or (before_start or {}).get("run_id")
            or ledger_run
            or ext.get("run_id")
            or ""
        )[:64],
        "before_start_observed": before_start is not None,
        "before_start_row": before_start,
    }


def tri_state_from_row(row: dict[str, Any] | None, key: str) -> bool | None:
    if not row:
        return None
    if key not in row:
        return None
    return bool(row.get(key))


def session_binding_report(
    checkpoint: dict[str, Any],
    ledger_bind: dict[str, Any],
    *,
    harness_sid: str,
) -> dict[str, Any]:
    ui_sid = str(checkpoint.get("suite_sid_prefix") or "")
    url_sid = suite_sid_from_url(str(ledger_bind.get("start_surface", {}).get("page_url") or ""))
    dom_sid = str(harness_sid or "")[:8]
    ui_st = str(checkpoint.get("streamlit_session_id") or "")
    led_st = str(ledger_bind.get("ledger_streamlit_session_id") or "")
    ui_run = str(checkpoint.get("diagnostic_run_id") or "")
    led_run = str(ledger_bind.get("ledger_diagnostic_run_id") or "")
    return {
        "harness_suite_sid_prefix": dom_sid,
        "url_suite_sid_match": bool(harness_sid and url_sid == harness_sid),
        "ui_ledger_streamlit_session_match": (not ui_st or not led_st or ui_st == led_st),
        "ui_ledger_run_match": (not ui_run or not led_run or ui_run == led_run),
        "start_enabled": bool(checkpoint.get("start_enabled")),
        "ledger_row_count": int(ledger_bind.get("row_count") or 0),
        "auth_hydration_row_count": int(ledger_bind.get("auth_row_count") or 0),
        "ledger_same_frame_as_start": bool(ledger_bind.get("ledger_same_frame_as_start")),
        "start_frame_index": int(checkpoint.get("start_frame_index") or 0),
        "ledger_selected_frame_index": ledger_bind.get("extract_meta", {}).get("selected_frame_index"),
        "diagnostic_flags_after_sign_in": checkpoint.get("diagnostic_query_flags") or {},
    }


def classify_auth_observability(
    *,
    start_surface: dict[str, Any],
    checkpoint: dict[str, Any],
    ledger_bind: dict[str, Any],
    binding: dict[str, Any],
    strict_failure: str = "",
) -> tuple[str, str, dict[str, Any]]:
    """Return (classification, detail, evidence)."""
    evidence = {
        "start_surface": {
            k: start_surface.get(k)
            for k in ("page_url", "frame_url", "frame_index", "enabled", "visible", "suite_sid", "selected_page_reason")
        },
        "binding": binding,
        "extract": ledger_bind.get("extract_meta"),
    }
    start_on = bool(start_surface.get("enabled"))
    auth_rows = int(ledger_bind.get("auth_row_count") or 0)
    row_count = int(ledger_bind.get("row_count") or 0)
    flags = checkpoint.get("diagnostic_query_flags") or {}
    if start_on and not flags.get("suite_sid_present"):
        return AUTH_OBSERVABILITY3, "diagnostic_suite_sid_missing_from_url", evidence
    if start_on and not flags.get("solo_component_diag"):
        return AUTH_OBSERVABILITY3, "diagnostic_solo_component_diag_missing", evidence
    if start_on and row_count == 0:
        if int(start_surface.get("frame_index") or 0) > 0 and not ledger_bind.get("ledger_same_frame_as_start"):
            return AUTH_OBSERVABILITY2, "start_in_iframe_ledger_from_other_frame", evidence
        if not checkpoint.get("streamlit_session_id") and not checkpoint.get("diagnostic_run_id"):
            return AUTH_OBSERVABILITY5, "ledger_and_dom_identity_payload_missing", evidence
        return AUTH_OBSERVABILITY1, "start_enabled_ledger_empty_or_unscoped", evidence
    if start_on and auth_rows == 0 and row_count > 0:
        if not binding.get("ui_ledger_run_match") or not binding.get("ui_ledger_streamlit_session_match"):
            return AUTH_OBSERVABILITY4, "ledger_rows_present_session_filter_excluded_auth", evidence
        return AUTH_OBSERVABILITY5, "ledger_without_auth_prestart_events", evidence
    if start_on and not binding.get("ui_ledger_streamlit_session_match"):
        return AUTH_OBSERVABILITY2, "dom_streamlit_session_id_mismatch_ledger", evidence
    if start_on and not binding.get("ui_ledger_run_match"):
        return AUTH_OBSERVABILITY4, "dom_diagnostic_run_id_mismatch_ledger", evidence
    if strict_failure == "streamlit_auth_incomplete" and start_on:
        return AUTH_OBSERVABILITY8, "start_enabled_strict_incomplete_unclassified", evidence
    return AUTH_OBSERVABILITY8, "no_observability_boundary", evidence


def observability_aware_preflight_failure(
    *,
    start_enabled: bool,
    ledger_bind: dict[str, Any],
    binding: dict[str, Any],
    prior_failure: str,
) -> str:
    if start_enabled and int(ledger_bind.get("auth_row_count") or 0) == 0:
        return CAPTURE_FAIL_OBSERVABILITY
    if prior_failure == "streamlit_auth_incomplete" and start_enabled:
        return CAPTURE_FAIL_OBSERVABILITY
    return prior_failure


def session_binding_mismatch(binding: dict[str, Any], checkpoint: dict[str, Any]) -> str:
    """Exact session-binding failure when DOM and ledger identities conflict."""
    ui_st = str(checkpoint.get("streamlit_session_id") or "")
    ui_run = str(checkpoint.get("diagnostic_run_id") or "")
    if not checkpoint.get("start_enabled"):
        return ""
    if ui_st and ui_run and not binding.get("ui_ledger_streamlit_session_match"):
        return "dom_streamlit_session_id_mismatch_ledger"
    if ui_st and ui_run and not binding.get("ui_ledger_run_match"):
        return "dom_diagnostic_run_id_mismatch_ledger"
    if (
        checkpoint.get("start_enabled")
        and int(binding.get("ledger_row_count") or 0) > 0
        and not binding.get("ledger_same_frame_as_start")
        and int(checkpoint.get("start_frame_index") or 0) > 0
    ):
        return "start_frame_differs_from_ledger_export_frame"
    return ""


def enrich_checkpoint_from_ledger(checkpoint: dict[str, Any], ledger_bind: dict[str, Any]) -> dict[str, Any]:
    """Only set auth fields from explicit before_start row on bound ledger."""
    cp = dict(checkpoint)
    row = ledger_bind.get("before_start_row")
    if isinstance(row, dict):
        cp["is_authenticated"] = tri_state_from_row(row, "is_authenticated")
        cp["auth_session_complete"] = tri_state_from_row(row, "auth_session_complete")
        prot = row.get("protected_keys")
        if isinstance(prot, dict) and "session_flag_present" in prot:
            cp["session_flag_present"] = bool(prot.get("session_flag_present"))
        elif "session_flag_present" in row:
            cp["session_flag_present"] = bool(row.get("session_flag_present"))
        cp["restore_blocked_reason"] = str(row.get("restore_blocked_reason") or "")[:80]
    return cp


def gather_page_observability(
    page,
    *,
    harness_sid: str,
    strict_failure: str = "",
) -> dict[str, Any]:
    """Bind Start UI to ledger scrape; classify observability boundary."""
    start_surface = find_start_control_surface(page)
    checkpoint = probe_dom_current_state_checkpoint(page, start_surface=start_surface)
    ledger_bind = scrape_ledger_with_surface_binding(page, start_surface=start_surface)
    checkpoint = enrich_checkpoint_from_ledger(checkpoint, ledger_bind)
    binding = session_binding_report(checkpoint, ledger_bind, harness_sid=harness_sid)
    bind_fail = session_binding_mismatch(binding, checkpoint)
    classification, detail, evidence = classify_auth_observability(
        start_surface=start_surface,
        checkpoint=checkpoint,
        ledger_bind=ledger_bind,
        binding=binding,
        strict_failure=strict_failure,
    )
    override_failure = ""
    if bind_fail:
        override_failure = SESSION_BINDING_FAIL
    elif start_surface.get("enabled") and strict_failure in (
        "streamlit_auth_incomplete",
        "strict_capture_incomplete",
        CAPTURE_FAIL_OBSERVABILITY,
    ):
        if classification.startswith("AUTH_OBSERVABILITY"):
            override_failure = CAPTURE_FAIL_OBSERVABILITY
    return {
        "start_surface": start_surface,
        "checkpoint": checkpoint,
        "ledger_bind": {
            "row_count": ledger_bind.get("row_count"),
            "auth_row_count": ledger_bind.get("auth_row_count"),
            "before_start_observed": ledger_bind.get("before_start_observed"),
            "ledger_same_frame_as_start": ledger_bind.get("ledger_same_frame_as_start"),
            "ledger_streamlit_session_id": ledger_bind.get("ledger_streamlit_session_id"),
            "ledger_diagnostic_run_id": ledger_bind.get("ledger_diagnostic_run_id"),
            "extract_meta": ledger_bind.get("extract_meta"),
        },
        "binding": binding,
        "session_binding_failure": bind_fail,
        "auth_observability_classification": classification,
        "auth_observability_detail": detail,
        "auth_observability_evidence": evidence,
        "override_failure": override_failure,
        "ledger_rows_for_eval": list(ledger_bind.get("rows") or []),
    }


def apply_observability_to_strict_summary(
    strict: dict[str, Any],
    obs: dict[str, Any],
) -> dict[str, Any]:
    """Preserve missing-vs-false when ledger did not prove auth state."""
    out = dict(strict)
    cp = obs.get("checkpoint") or {}
    if not obs.get("ledger_bind", {}).get("before_start_observed"):
        if out.get("start_enabled"):
            out["is_authenticated"] = cp.get("is_authenticated")
            out["auth_session_complete"] = cp.get("auth_session_complete")
            out["session_flag_present"] = cp.get("session_flag_present")
            out["auth_state_observability"] = "not_observed"
    return out
