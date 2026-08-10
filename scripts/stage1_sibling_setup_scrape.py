"""Scrape layered pause-sibling setup diagnostics from Streamlit app frame."""

from __future__ import annotations

import json
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame

SIBLING_BUTTON_LABEL = "Stage1 Pause-Sibling Return Probe"

_SETUP_LAYERS_JS = """() => {
  const callsiteNodes = document.querySelectorAll('#solo-stage1-pause-sibling-callsite');
  const entry = document.querySelector('#solo-stage1-pause-sibling-entry');
  const decl = document.querySelector('#solo-stage1-pause-sibling-declaration');
  const ledger = document.querySelector('#solo-stage1-pause-sibling-ledger');
  let button = null;
  for (const b of document.querySelectorAll('button')) {
    const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
    if (t === 'Stage1 Pause-Sibling Return Probe') { button = b; break; }
  }
  function parseJson(el) {
    if (!el) return null;
    const raw = el.getAttribute('data-json') || '';
    if (!raw) return null;
    try { return JSON.parse(raw.replace(/'/g, '"')); } catch (e) { return null; }
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
  const dc = parseJson(decl);
  return {
    callsite_count: callsiteNodes.length,
    callsite_candidates_raw: candidates,
    sibling_callsite_found: callsiteNodes.length > 0,
    sibling_entry_found: !!entry,
    sibling_diag_enabled_attr: entry ? (entry.getAttribute('data-diag-enabled') || '') : '',
    sibling_button_found: !!button,
    sibling_ledger_found: !!ledger,
    entry_json: en,
    declaration_json: dc,
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
        "thread_fragment_id": str(j.get("thread_fragment_id") or "")[:64],
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
        "sibling_declaration_reached": bool(layers.get("sibling_declaration_reached")),
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
    decl = out.get("declaration_json") if isinstance(out.get("declaration_json"), dict) else {}
    out["sibling_declaration_reached"] = bool(decl.get("declaration_reached"))
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
