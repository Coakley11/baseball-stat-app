"""Scrape layered pause-sibling setup diagnostics from Streamlit app frame."""

from __future__ import annotations

import json
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame

SIBLING_BUTTON_LABEL = "Stage1 Pause-Sibling Return Probe"
SIBLING_BUTTON_LABEL_NORMALIZED = SIBLING_BUTTON_LABEL
DECL_PRE_EVENT = "SIBLING_BUTTON_DECLARATION_ENTRY"
DECL_POST_EVENT = "SIBLING_BUTTON_DECLARATION_RESULT"


_SETUP_LAYERS_JS = """() => {
  const DECL_SEL = '#solo-stage1-pause-sibling-declaration-pre, #solo-stage1-pause-sibling-declaration-post, #solo-stage1-pause-sibling-declaration, .solo-stage1-pause-sibling-declaration';
  const callsiteNodes = document.querySelectorAll('#solo-stage1-pause-sibling-callsite');
  const entry = document.querySelector('#solo-stage1-pause-sibling-entry');
  const declNodes = document.querySelectorAll(DECL_SEL);
  const checkpointNodes = document.querySelectorAll('#solo-stage1-pause-sibling-setup-checkpoint, .solo-stage1-pause-sibling-setup-checkpoint');
  const ledger = document.querySelector('#solo-stage1-pause-sibling-ledger');
  function parseJson(el) {
    if (!el) return null;
    const raw = el.getAttribute('data-json') || '';
    if (!raw) return null;
    try { return JSON.parse(raw.replace(/'/g, '"')); } catch (e) { return null; }
  }
  function normText(s) {
    return String(s || '').replace(/\\s+/g, ' ').trim();
  }
  const declaration_candidates = [];
  declNodes.forEach((el, idx) => {
    const j = parseJson(el);
    declaration_candidates.push({
      dom_index: idx,
      data_event: el.getAttribute('data-event') || '',
      declaration_reached: el.getAttribute('data-declaration-reached') || '',
      data_phase: el.getAttribute('data-sibling-declaration-phase') || '',
      json: j,
    });
  });
  const setup_checkpoint_candidates = [];
  checkpointNodes.forEach((el, idx) => {
    const j = parseJson(el);
    setup_checkpoint_candidates.push({
      dom_index: idx,
      data_event: el.getAttribute('data-event') || '',
      json: j,
    });
  });
  const button_inventory = [];
  const buttons = document.querySelectorAll('button');
  buttons.forEach((b, idx) => {
    const t = normText(b.innerText || b.textContent || '');
    const aria = normText(b.getAttribute('aria-label') || '');
    const outer = (b.outerHTML || '').slice(0, 240);
    button_inventory.push({
      index: idx,
      normalized_text: t,
      aria_label: aria,
      disabled: !!b.disabled,
      type: b.getAttribute('type') || '',
      outer_html_trunc: outer,
      exact_label_match: t === 'Stage1 Pause-Sibling Return Probe',
      contains_pause_sibling: /Pause-Sibling/i.test(t),
      contains_stage1: /Stage1/i.test(t),
    });
  });
  let button = null;
  for (const b of buttons) {
    const t = normText(b.innerText || b.textContent || '');
    if (t === 'Stage1 Pause-Sibling Return Probe') { button = b; break; }
  }
  const candidates = [];
  callsiteNodes.forEach((el, idx) => {
    const j = parseJson(el);
    candidates.push({
      dom_index: idx,
      import_attempted_attr: el.getAttribute('data-import-attempted') || '',
      import_ok_attr: el.getAttribute('data-import-ok') || '',
      json: j,
    });
  });
  const en = parseJson(entry);
  return {
    callsite_count: callsiteNodes.length,
    callsite_candidates_raw: candidates,
    sibling_callsite_found: callsiteNodes.length > 0,
    sibling_entry_found: !!entry,
    sibling_diag_enabled_attr: entry ? (entry.getAttribute('data-diag-enabled') || '') : '',
    sibling_button_found: !!button,
    sibling_ledger_found: !!ledger,
    entry_json: en,
    declaration_candidates,
    setup_checkpoint_candidates,
    button_inventory,
    button_inventory_count: button_inventory.length,
    probe_found: !!ledger,
  };
}"""


def _parse_json_blob(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return None
    try:
        return json.loads(str(raw).replace("'", '"'))
    except Exception:
        return None


def _coerce_bool_attr(val: str) -> bool | None:
    s = str(val or "").strip()
    if s == "1":
        return True
    if s == "0":
        return False
    return None


def normalize_declaration_candidate(raw: dict[str, Any], *, dom_index: int) -> dict[str, Any]:
    j = _parse_json_blob(raw.get("json")) or {}
    event = str(raw.get("data_event") or j.get("event") or "")[:80]
    ts = j.get("ts")
    try:
        ts_f = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_f = None
    return {
        "dom_index": dom_index,
        "data_event": event,
        "declaration_reached": _coerce_bool_attr(str(raw.get("declaration_reached") or "")),
        "json": j,
        "room_id": str(j.get("room_id") or "")[:32],
        "widget_key": str(j.get("widget_key") or "")[:80],
        "returned_value": j.get("returned_value"),
        "registered_widget_id": str(j.get("registered_widget_id") or "")[:96],
        "thread_state_fragment_id": str(j.get("thread_state_fragment_id") or "")[:64],
        "ts": ts_f,
    }


def select_authoritative_declaration(
    candidates: list[dict[str, Any]],
    *,
    event: str,
) -> dict[str, Any] | None:
    normalized = [
        normalize_declaration_candidate(c, dom_index=int(c.get("dom_index") or i))
        for i, c in enumerate(candidates)
    ]
    matches = [c for c in normalized if c.get("data_event") == event]
    if not matches:
        return None
    best_ts = max((c.get("ts") or 0.0) for c in matches)
    tied = [c for c in matches if (c.get("ts") or 0.0) == best_ts]
    return max(tied, key=lambda c: int(c.get("dom_index") or 0))


def normalize_setup_checkpoint(raw: dict[str, Any], *, dom_index: int) -> dict[str, Any]:
    j = _parse_json_blob(raw.get("json")) or {}
    event = str(raw.get("data_event") or j.get("event") or "")[:80]
    ts = j.get("ts")
    try:
        ts_f = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_f = None
    return {"dom_index": dom_index, "data_event": event, "json": j, "ts": ts_f}


def select_setup_checkpoint(candidates: list[dict[str, Any]], *, event: str) -> dict[str, Any] | None:
    normalized = [
        normalize_setup_checkpoint(c, dom_index=int(c.get("dom_index") or i))
        for i, c in enumerate(candidates)
    ]
    matches = [c for c in normalized if c.get("data_event") == event]
    if not matches:
        return None
    return max(matches, key=lambda c: (c.get("ts") or 0.0, int(c.get("dom_index") or 0)))


def normalize_callsite_candidate(raw: dict[str, Any], *, dom_index: int) -> dict[str, Any]:
    j = _parse_json_blob(raw.get("json")) or {}
    attempted_attr = _coerce_bool_attr(str(raw.get("import_attempted_attr") or ""))
    ok_attr = _coerce_bool_attr(str(raw.get("import_ok_attr") or ""))
    import_attempted = bool(j.get("import_attempted")) if "import_attempted" in j else attempted_attr
    if import_attempted is None:
        import_attempted = False
    import_ok = j.get("import_ok") if "import_ok" in j else ok_attr
    if import_ok is not None:
        import_ok = bool(import_ok)
    ts = j.get("ts")
    try:
        ts_f = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_f = None
    return {
        "dom_index": dom_index,
        "import_attempted": bool(import_attempted),
        "import_ok": import_ok,
        "room_id": str(j.get("room_id") or "")[:32],
        "streamlit_session_id": str(j.get("streamlit_session_id") or "")[:64],
        "ts": ts_f,
        "full_app_run_seq": j.get("full_app_run_seq"),
        "thread_fragment_id": str(j.get("thread_state_fragment_id") or "")[:64],
        "json": j,
    }


def select_authoritative_callsite(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick post-import callsite; newest ts; last DOM index on tie."""
    normalized = [normalize_callsite_candidate(c, dom_index=int(c.get("dom_index") or i)) for i, c in enumerate(candidates)]
    post = [c for c in normalized if c.get("import_attempted")]
    strategy = "none"
    selected_index = -1
    selected: dict[str, Any] | None = None
    if post:
        strategy = "newest_post_import_ts_then_last_dom"
        best_ts = max((c.get("ts") or 0.0) for c in post)
        tied = [c for c in post if (c.get("ts") or 0.0) == best_ts]
        selected = max(tied, key=lambda c: int(c.get("dom_index") or 0))
        selected_index = int(selected.get("dom_index") or 0)
    elif normalized:
        strategy = "pre_import_only_fallback"
        selected = normalized[-1]
        selected_index = int(selected.get("dom_index") or len(normalized) - 1)
    out_json = dict(selected.get("json") or {}) if selected else {}
    import_ok = selected.get("import_ok") if selected else None
    return {
        "callsite_candidates": normalized,
        "selected_callsite_index": selected_index,
        "selected_callsite_strategy": strategy,
        "selected_callsite_json": out_json,
        "sibling_import_ok_direct": import_ok,
    }


def build_downstream_import_success_evidence(
    layers: dict[str, Any],
    *,
    s3_ledger_found: bool,
    post_registration_ready: bool,
    binding_ok: bool,
) -> dict[str, Any]:
    return {
        "sibling_entry_found": bool(layers.get("sibling_entry_found")),
        "sibling_diag_enabled": layers.get("sibling_diag_enabled") is True,
        "sibling_declaration_reached": bool(layers.get("sibling_pre_button_reached")),
        "sibling_button_found": bool(layers.get("sibling_button_found")),
        "sibling_ledger_found": bool(layers.get("sibling_ledger_found")),
        "s3_ledger_found": bool(s3_ledger_found),
        "post_registration_ready": bool(post_registration_ready),
        "binding_ok": bool(binding_ok),
    }


def compute_import_evidence_consistent(
    *,
    sibling_import_ok_direct: bool | None,
    import_effective_ok: bool,
    downstream: dict[str, Any],
) -> bool:
    entry = bool(downstream.get("sibling_entry_found"))
    button = bool(downstream.get("sibling_button_found"))
    ledger = bool(downstream.get("sibling_ledger_found"))
    if sibling_import_ok_direct is True and entry:
        return True
    if sibling_import_ok_direct is False and (entry or button or ledger):
        return False
    if sibling_import_ok_direct is None and entry:
        return True
    if sibling_import_ok_direct is False and not (entry or button or ledger):
        return True
    return True


def resolve_import_effective(
    *,
    sibling_import_ok_direct: bool | None,
    sibling_entry_found: bool,
    downstream: dict[str, Any],
) -> tuple[bool, str]:
    if sibling_import_ok_direct is True:
        return True, "post_import_callsite"
    if sibling_import_ok_direct is False:
        if sibling_entry_found or downstream.get("sibling_button_found") or downstream.get("sibling_ledger_found"):
            return False, "contradiction_pending"
        return False, "post_import_callsite_explicit_false"
    if sibling_entry_found:
        return True, "downstream_function_entry"
    return False, "import_unknown_no_entry"


def finalize_sibling_import_evidence(
    layers: dict[str, Any],
    *,
    s3_ledger_found: bool,
    post_registration_ready: bool,
    binding_ok: bool,
) -> dict[str, Any]:
    out = dict(layers)
    downstream = build_downstream_import_success_evidence(
        out,
        s3_ledger_found=s3_ledger_found,
        post_registration_ready=post_registration_ready,
        binding_ok=binding_ok,
    )
    out["downstream_import_success_evidence"] = downstream
    direct = out.get("sibling_import_ok_direct")
    if direct is None and "sibling_import_ok" in out and out.get("sibling_import_ok") in (True, False):
        direct = out.get("sibling_import_ok")
    effective, source = resolve_import_effective(
        sibling_import_ok_direct=direct if direct in (True, False, None) else None,
        sibling_entry_found=bool(out.get("sibling_entry_found")),
        downstream=downstream,
    )
    consistent = compute_import_evidence_consistent(
        sibling_import_ok_direct=direct if direct in (True, False, None) else None,
        import_effective_ok=effective,
        downstream=downstream,
    )
    out["import_evidence_consistent"] = consistent
    out["import_effective_ok"] = effective
    out["import_effective_source"] = source
    out["sibling_import_ok"] = effective
    return out


def _apply_dom_scrape_raw(out: dict[str, Any]) -> dict[str, Any]:
    raw_candidates = list(out.pop("callsite_candidates_raw", []) or [])
    out["callsite_count"] = int(out.get("callsite_count") or len(raw_candidates))
    selection = select_authoritative_callsite(raw_candidates)
    out.update(selection)
    out["callsite_json"] = dict(out.get("selected_callsite_json") or {})
    direct = out.get("sibling_import_ok_direct")
    out["sibling_import_ok"] = direct

    decl_raw = list(out.pop("declaration_candidates", []) or [])
    out["declaration_candidate_count"] = len(decl_raw)
    pre = select_authoritative_declaration(decl_raw, event=DECL_PRE_EVENT)
    post = select_authoritative_declaration(decl_raw, event=DECL_POST_EVENT)
    out["declaration_pre_json"] = dict((pre or {}).get("json") or {})
    out["declaration_post_json"] = dict((post or {}).get("json") or {})
    out["declaration_json"] = dict(out["declaration_pre_json"])
    out["sibling_pre_button_reached"] = bool(pre and (pre.get("json") or {}).get("declaration_reached"))
    out["sibling_post_button_return_reached"] = bool(post and (post.get("json") or {}).get("declaration_reached"))
    rv = (post or {}).get("returned_value")
    if rv is None and post:
        rv = (post.get("json") or {}).get("returned_value")
    out["sibling_post_button_return_value"] = rv
    out["sibling_post_button_registered_widget_id"] = str((post or {}).get("registered_widget_id") or "")[:96]
    out["sibling_declaration_reached"] = bool(out["sibling_pre_button_reached"])

    ck_raw = list(out.pop("setup_checkpoint_candidates", []) or [])
    out["setup_checkpoint_candidate_count"] = len(ck_raw)
    ck_events = (
        "SIBLING_BUTTON_CALL_EXCEPTION",
        "SIBLING_BUTTON_CALL_RETURNED",
        "SIBLING_POST_REGISTRATION_EXCEPTION",
        "SIBLING_POST_REGISTRATION_RETURNED",
        "SIBLING_SETUP_EXPORT_COMPLETE",
        "SIBLING_RENDER_EXCEPTION",
    )
    for ev in ck_events:
        hit = select_setup_checkpoint(ck_raw, event=ev)
        out[f"checkpoint_{ev.lower()}"] = dict((hit or {}).get("json") or {}) if hit else None
    out["sibling_button_call_returned_reached"] = bool(out.get("checkpoint_sibling_button_call_returned"))
    out["sibling_post_registration_returned_reached"] = bool(out.get("checkpoint_sibling_post_registration_returned"))
    out["sibling_setup_export_complete_reached"] = bool(out.get("checkpoint_sibling_setup_export_complete"))

    inv = list(out.pop("button_inventory", []) or [])
    out["button_inventory"] = inv
    out["button_inventory_count"] = int(out.pop("button_inventory_count", len(inv)) or len(inv))
    out["button_candidates_exact"] = [b for b in inv if b.get("exact_label_match")]
    out["button_candidates_contains_pause_sibling"] = [b for b in inv if b.get("contains_pause_sibling")]
    out["button_candidates_contains_stage1"] = [b for b in inv if b.get("contains_stage1")]

    de = str(out.pop("sibling_diag_enabled_attr", "") or "")
    if de == "1":
        out["sibling_diag_enabled"] = True
    elif de == "0":
        out["sibling_diag_enabled"] = False
    else:
        en = out.get("entry_json") if isinstance(out.get("entry_json"), dict) else {}
        if "solo_diag_enabled_final" in en:
            out["sibling_diag_enabled"] = bool(en.get("solo_diag_enabled_final"))
        else:
            out["sibling_diag_enabled"] = None
    out["sibling_button_label"] = SIBLING_BUTTON_LABEL
    return out


def scrape_sibling_setup_layers(page, frame=None) -> dict[str, Any]:
    fr = frame if frame is not None else resolve_streamlit_app_frame(page)
    frame_url = str(fr.url or "")[:240]
    try:
        raw = fr.evaluate(_SETUP_LAYERS_JS)
    except Exception as exc:
        return {"frame_url": frame_url, "error": str(exc)[:200]}
    if not isinstance(raw, dict):
        return {"frame_url": frame_url}
    out = dict(raw)
    out["frame_url"] = frame_url
    return _apply_dom_scrape_raw(out)


def merge_layers_from_dom_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Test helper: apply selection logic without Playwright."""
    return _apply_dom_scrape_raw(dict(raw))
