"""Scrape S3 server diag DOM + pause sibling POST registration."""

from __future__ import annotations

import json
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame


def scrape_s3_server_diag_ledger(page, frame=None) -> dict[str, Any]:
    fr = frame if frame is not None else resolve_streamlit_app_frame(page)
    js = """() => {
      const el = document.querySelector('#solo-stage1-s3-server-diag-ledger');
      if (!el) return { found: false };
      const raw = el.getAttribute('data-json') || '';
      return { found: true, json: raw, impl_rev: el.getAttribute('data-impl-rev') || '' };
    }"""
    try:
        raw = fr.evaluate(js)
    except Exception as exc:
        return {"found": False, "error": str(exc)[:200]}
    if not isinstance(raw, dict) or not raw.get("found"):
        return {"found": False}
    out: dict[str, Any] = {"found": True, "impl_rev": raw.get("impl_rev")}
    try:
        out["payload"] = json.loads(str(raw.get("json") or "").replace("'", '"'))
    except Exception:
        out["payload"] = None
    return out


def extract_post_registration(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    post = payload.get("post_registration")
    return dict(post) if isinstance(post, dict) else {}


def extract_s3_diag_binding(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    binding = payload.get("s3_diag_binding")
    return dict(binding) if isinstance(binding, dict) else {}


def scrape_frame_dom_diagnostics(page) -> dict[str, Any]:
    from streamlit_app_frame import describe_page_frames, resolve_streamlit_app_frame

    frames = describe_page_frames(page)
    fr = resolve_streamlit_app_frame(page)
    app_url = str(fr.url or "")[:240]
    probe_js = """() => {
      const pauseLabel = 'Pause Draft';
      const siblingLabel = 'Stage1 Pause-Sibling Return Probe';
      function scan(doc) {
        let pause = false, sibling = false, ledger = false, callsite = false, entry = false;
        for (const b of doc.querySelectorAll('button')) {
          const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
          if (t === pauseLabel) pause = true;
          if (t === siblingLabel) sibling = true;
        }
        ledger = !!doc.querySelector('#solo-stage1-s3-server-diag-ledger');
        callsite = !!doc.querySelector('#solo-stage1-pause-sibling-callsite');
        entry = !!doc.querySelector('#solo-stage1-pause-sibling-entry');
        const sibLedger = !!doc.querySelector('#solo-stage1-pause-sibling-ledger');
        return { pause, sibling, ledger, callsite, entry, sibling_ledger: sibLedger };
      }
      const main = scan(document);
      const out = { main, frames: [] };
      for (const f of document.querySelectorAll('iframe')) {
        try {
          if (f.contentDocument) out.frames.push({ url: String(f.src||'').slice(0,200), ...scan(f.contentDocument) });
        } catch (e) {}
      }
      return out;
    }"""
    try:
        dom_probe = fr.evaluate(probe_js)
    except Exception as exc:
        dom_probe = {"error": str(exc)[:200]}
    return {
        "app_frame_url": app_url,
        "frame_inventory": frames,
        "dom_probe_in_app_frame": dom_probe,
    }


def evaluate_post_registration_from_ledger(s3_ledger_scrape: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = s3_ledger_scrape.get("payload") if isinstance(s3_ledger_scrape.get("payload"), dict) else {}
    post = extract_post_registration(payload)
    binding = extract_s3_diag_binding(payload)
    pre = payload.get("pre_declaration") if isinstance(payload.get("pre_declaration"), dict) else {}
    return post, binding, dict(pre) if isinstance(pre, dict) else {}


def load_authoritative_wire_id_from_strict_artifact(path: str) -> tuple[str, str]:
    """Return (wire_widget_id, wire_fragment_id) from last strict backmsg gate if present."""
    try:
        import json as _json
        from pathlib import Path

        p = Path(path)
        if not p.is_file():
            return "", ""
        doc = _json.loads(p.read_text(encoding="utf-8"))
        sib = (doc.get("strict_evidence_table") or {}).get("sibling") or {}
        ids = list(sib.get("triggered_widget_ids") or [])
        frag = str(sib.get("fragment_id") or "")
        wire = str(ids[0] if ids else "")
        sibling_step = doc.get("sibling_pre_pause_transport") or {}
        strict = (sibling_step.get("streamlit_transport") or {}).get("strict_backmsg") or {}
        frames = strict.get("decoded_outbound_frames") or []
        for fr in frames:
            dec = fr.get("decode") or {}
            cs = dec.get("client_state") if isinstance(dec.get("client_state"), dict) else {}
            if cs.get("fragment_id"):
                frag = str(cs.get("fragment_id") or frag)
        return wire, frag
    except Exception:
        return "", ""
