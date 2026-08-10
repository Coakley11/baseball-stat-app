"""Scrape layered pause-sibling setup diagnostics from Streamlit app frame."""

from __future__ import annotations

import json
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame

SIBLING_BUTTON_LABEL = "Stage1 Pause-Sibling Return Probe"

_SETUP_LAYERS_JS = """() => {
  const callsite = document.querySelector('#solo-stage1-pause-sibling-callsite');
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
  const cs = parseJson(callsite);
  const en = parseJson(entry);
  const dc = parseJson(decl);
  return {
    sibling_callsite_found: !!callsite,
    sibling_import_ok: callsite ? callsite.getAttribute('data-import-ok') : '',
    sibling_entry_found: !!entry,
    sibling_diag_enabled: entry ? entry.getAttribute('data-diag-enabled') : '',
    sibling_button_found: !!button,
    sibling_ledger_found: !!ledger,
    callsite_json: cs,
    entry_json: en,
    declaration_json: dc,
    probe_found: !!ledger,
  };
}"""


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
    iok = str(out.get("sibling_import_ok") or "")
    if iok == "1":
        out["sibling_import_ok"] = True
    elif iok == "0":
        out["sibling_import_ok"] = False
    else:
        cs = out.get("callsite_json") if isinstance(out.get("callsite_json"), dict) else {}
        if cs.get("import_ok") is True:
            out["sibling_import_ok"] = True
        elif cs.get("import_ok") is False:
            out["sibling_import_ok"] = False
        elif not out.get("sibling_callsite_found"):
            out["sibling_import_ok"] = None
        else:
            out["sibling_import_ok"] = None
    de = str(out.get("sibling_diag_enabled") or "")
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
