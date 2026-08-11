"""Scrape S3 server diag DOM + pause sibling POST registration."""

from __future__ import annotations

import json
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame

S3_LEDGER_DOM_SELECTOR = "#solo-stage1-s3-server-diag-ledger"
S3_READINESS_DOM_SELECTOR = "#solo-stage1-s3-server-diag-readiness"


def _parse_dom_json_attr(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    text = str(raw or "")
    if not text.strip():
        return None, "empty_json_attribute"
    try:
        parsed = json.loads(text.replace("'", '"'))
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"[:200]
    return dict(parsed) if isinstance(parsed, dict) else None, "payload_not_object"


def _scrape_dom_marker(page, frame, *, selector: str) -> dict[str, Any]:
    fr = frame if frame is not None else resolve_streamlit_app_frame(page)
    js = """(sel) => {
      const el = document.querySelector(sel);
      if (!el) return { found: false };
      const raw = el.getAttribute('data-json') || '';
      return {
        found: true,
        json: raw,
        impl_rev: el.getAttribute('data-impl-rev') || '',
        streamlit_session_id: el.getAttribute('data-streamlit-session-id') || '',
        export_generation: el.getAttribute('data-export-generation') || '',
        export_generated_server_ts: el.getAttribute('data-export-generated-server-ts') || '',
      };
    }"""
    try:
        raw = fr.evaluate(js, selector)
    except Exception as exc:
        return {"found": False, "error": str(exc)[:200]}
    if not isinstance(raw, dict) or not raw.get("found"):
        return {"found": False}
    json_text = str(raw.get("json") or "")
    payload, parse_error = _parse_dom_json_attr(json_text)
    out: dict[str, Any] = {
        "found": True,
        "impl_rev": raw.get("impl_rev"),
        "streamlit_session_id": raw.get("streamlit_session_id"),
        "export_generation": raw.get("export_generation"),
        "export_generated_server_ts": raw.get("export_generated_server_ts"),
        "raw_json_length": len(json_text),
        "parse_ok": payload is not None,
        "parse_error": parse_error or "",
        "payload": payload,
    }
    if payload is not None:
        out["top_level_keys"] = sorted(payload.keys())
    return out


def _readiness_candidate_inventory(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            continue
        json_text = str(raw.get("json") or "")
        payload, parse_error = _parse_dom_json_attr(json_text)
        oob = payload.get("oob_channel") if isinstance(payload, dict) else {}
        oob = dict(oob) if isinstance(oob, dict) else {}
        payload_sid = str((payload or {}).get("streamlit_session_id") or "")
        dom_sid = str(raw.get("streamlit_session_id") or "")
        candidates.append(
            {
                "dom_index": idx,
                "found": True,
                "impl_rev": raw.get("impl_rev"),
                "dom_streamlit_session_id": dom_sid[:64],
                "streamlit_session_id": (payload_sid or dom_sid)[:64],
                "export_generation": raw.get("export_generation"),
                "export_generated_server_ts": raw.get("export_generated_server_ts"),
                "raw_json_length": len(json_text),
                "parse_ok": payload is not None,
                "parse_error": parse_error or "",
                "oob_channel_registered": bool(oob.get("registered")),
                "diagnostic_token": str(oob.get("diagnostic_token") or "")[:32],
                "static_url_path": str(oob.get("static_url_path") or "")[:120],
                "snapshot_generation": oob.get("snapshot_generation"),
                "published": bool(oob.get("published")),
                "payload": payload,
            }
        )
    return candidates


def _scrape_readiness_markers(page, frame, *, selector: str) -> dict[str, Any]:
    fr = frame if frame is not None else resolve_streamlit_app_frame(page)
    js = """(sel) => {
      const nodes = Array.from(document.querySelectorAll(sel));
      if (!nodes.length) return { found: false, candidate_count: 0, nodes: [] };
      return {
        found: true,
        candidate_count: nodes.length,
        nodes: nodes.map((el, idx) => ({
          dom_index: idx,
          json: el.getAttribute('data-json') || '',
          impl_rev: el.getAttribute('data-impl-rev') || '',
          streamlit_session_id: el.getAttribute('data-streamlit-session-id') || '',
          export_generation: el.getAttribute('data-export-generation') || '',
          export_generated_server_ts: el.getAttribute('data-export-generated-server-ts') || '',
        })),
      };
    }"""
    try:
        raw = fr.evaluate(js, selector)
    except Exception as exc:
        return {"found": False, "error": str(exc)[:200], "candidate_count": 0, "candidates": []}
    if not isinstance(raw, dict) or not raw.get("found"):
        return {"found": False, "candidate_count": 0, "candidates": []}
    candidates = _readiness_candidate_inventory(list(raw.get("nodes") or []))
    return {
        "found": True,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def scrape_s3_server_diag_ledger(page, frame=None) -> dict[str, Any]:
    return _scrape_dom_marker(page, frame, selector=S3_LEDGER_DOM_SELECTOR)


def scrape_s3_server_diag_readiness(
    page,
    frame=None,
    *,
    expected_streamlit_session_id: str = "",
) -> dict[str, Any]:
    from stage1_s3_oob_readback import select_valid_readiness_candidate

    inventory = _scrape_readiness_markers(page, frame, selector=S3_READINESS_DOM_SELECTOR)
    candidates = list(inventory.get("candidates") or [])
    selected, selection_reason = select_valid_readiness_candidate(
        candidates, expected_streamlit_sid=expected_streamlit_session_id
    )
    out: dict[str, Any] = {
        "found": bool(inventory.get("found")),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_candidate_index": selected.get("dom_index") if isinstance(selected, dict) else None,
        "selection_reason": selection_reason,
        "selected_candidate": dict(selected) if isinstance(selected, dict) else {},
    }
    if isinstance(selected, dict):
        payload = selected.get("payload") if isinstance(selected.get("payload"), dict) else {}
        out.update(
            {
                "impl_rev": selected.get("impl_rev"),
                "streamlit_session_id": selected.get("streamlit_session_id"),
                "export_generation": selected.get("export_generation"),
                "export_generated_server_ts": selected.get("export_generated_server_ts"),
                "raw_json_length": selected.get("raw_json_length"),
                "parse_ok": bool(selected.get("parse_ok")),
                "parse_error": selected.get("parse_error") or "",
                "payload": payload,
            }
        )
        if payload:
            out["top_level_keys"] = sorted(payload.keys())
    elif candidates:
        first = candidates[0]
        out.update(
            {
                "impl_rev": first.get("impl_rev"),
                "streamlit_session_id": first.get("streamlit_session_id"),
                "export_generation": first.get("export_generation"),
                "export_generated_server_ts": first.get("export_generated_server_ts"),
                "raw_json_length": first.get("raw_json_length"),
                "parse_ok": bool(first.get("parse_ok")),
                "parse_error": first.get("parse_error") or "",
                "payload": first.get("payload"),
            }
        )
    else:
        out["parse_ok"] = False
        out["parse_error"] = "no_readiness_candidates"
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


def payload_has_setup_metadata(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("post_registration"), dict):
        return False
    if not isinstance(payload.get("s3_diag_binding"), dict):
        return False
    return True


def registered_widget_id_from_post(post: dict[str, Any]) -> str:
    return str(post.get("registered_widget_id") or "")[:120]


def reconcile_s3_readiness_vs_ledger(
    *,
    ledger_scrape: dict[str, Any],
    readiness_scrape: dict[str, Any],
) -> dict[str, Any]:
    """Compare compact readiness surface vs large ledger payload when both parse."""
    out: dict[str, Any] = {
        "readiness_found": bool(readiness_scrape.get("found")),
        "ledger_found": bool(ledger_scrape.get("found")),
        "readiness_parse_ok": bool(readiness_scrape.get("parse_ok")),
        "ledger_parse_ok": bool(ledger_scrape.get("parse_ok")),
        "mismatch": False,
        "mismatch_reason": "",
    }
    if not out["readiness_parse_ok"] or not out["ledger_parse_ok"]:
        return out
    r_payload = readiness_scrape.get("payload") if isinstance(readiness_scrape.get("payload"), dict) else {}
    l_payload = ledger_scrape.get("payload") if isinstance(ledger_scrape.get("payload"), dict) else {}
    r_post = extract_post_registration(r_payload)
    l_post = extract_post_registration(l_payload)
    r_id = registered_widget_id_from_post(r_post)
    l_id = registered_widget_id_from_post(l_post)
    out["readiness_registered_widget_id"] = r_id
    out["ledger_registered_widget_id"] = l_id
    if r_id and l_id and r_id != l_id:
        out["mismatch"] = True
        out["mismatch_reason"] = "registered_widget_id_differs"
    r_bind = extract_s3_diag_binding(r_payload)
    l_bind = extract_s3_diag_binding(l_payload)
    r_wrap = r_bind.get("server_wrapper_integrity_ok")
    l_wrap = l_bind.get("server_wrapper_integrity_ok")
    if r_wrap is not None and l_wrap is not None and r_wrap != l_wrap:
        out["mismatch"] = True
        out["mismatch_reason"] = out["mismatch_reason"] or "wrapper_integrity_differs"
    return out


def resolve_authoritative_s3_setup_from_scrapes(
    ledger_scrape: dict[str, Any],
    readiness_scrape: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prefer parsed ledger payload; fall back to readiness surface for setup fields."""
    readiness_scrape = readiness_scrape or {}
    ledger_payload = ledger_scrape.get("payload") if isinstance(ledger_scrape.get("payload"), dict) else {}
    readiness_payload = (
        readiness_scrape.get("payload") if isinstance(readiness_scrape.get("payload"), dict) else {}
    )
    post = extract_post_registration(ledger_payload)
    binding = extract_s3_diag_binding(ledger_payload)
    pre = ledger_payload.get("pre_declaration") if isinstance(ledger_payload.get("pre_declaration"), dict) else {}
    source = "ledger_payload"
    if not post and readiness_payload:
        post = extract_post_registration(readiness_payload)
        source = "readiness_surface"
    if not binding and readiness_payload:
        binding = extract_s3_diag_binding(readiness_payload)
        if source == "ledger_payload" and binding:
            source = "readiness_binding_fallback"
    reconcile = reconcile_s3_readiness_vs_ledger(ledger_scrape=ledger_scrape, readiness_scrape=readiness_scrape)
    return {
        "post_registration": post,
        "s3_diag_binding": binding,
        "pre_declaration": dict(pre) if isinstance(pre, dict) else {},
        "authoritative_source": source,
        "reconcile": reconcile,
        "ledger_scrape": ledger_scrape,
        "readiness_scrape": readiness_scrape,
    }


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
        const readiness = !!doc.querySelector('#solo-stage1-s3-server-diag-readiness');
        callsite = !!doc.querySelector('#solo-stage1-pause-sibling-callsite');
        entry = !!doc.querySelector('#solo-stage1-pause-sibling-entry');
        const sibLedger = !!doc.querySelector('#solo-stage1-pause-sibling-ledger');
        return { pause, sibling, ledger, readiness, callsite, entry, sibling_ledger: sibLedger };
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
    resolved = resolve_authoritative_s3_setup_from_scrapes(s3_ledger_scrape, {})
    post = dict(resolved.get("post_registration") or {})
    binding = dict(resolved.get("s3_diag_binding") or {})
    pre = dict(resolved.get("pre_declaration") or {})
    return post, binding, pre


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
