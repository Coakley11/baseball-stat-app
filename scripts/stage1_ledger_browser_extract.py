"""Authoritative Stage 1 production ledger extraction from Playwright (harness only)."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from typing import Any

from stage1_harness_observability import decode_ledger_b64_padded

PIPELINE_CANARY_EVENT = "production_stage1_cloud_ledger_pipeline_canary"
PROBE_ID = "solo-stage1-production-ledger"
CASE_A_SURFACE = "case_a_control"

_COLLECT_CANDIDATES_JS = """
() => {
  const PROBE_ID = "solo-stage1-production-ledger";
  const CANARY = "production_stage1_cloud_ledger_pipeline_canary";
  function decodeAttempt(b64) {
    const meta = {
      b64_length: 0,
      decoded_length: 0,
      row_count: 0,
      run_id: "",
      max_script_run_seq: 0,
      diagnostic_run_ids: [],
      pipeline_canary_present: false,
      parse_ok: false,
      decode_error: "",
      content_hash: "",
    };
    if (!b64) {
      meta.decode_error = "empty_b64";
      return meta;
    }
    let s = String(b64).replace(/\\s/g, "");
    meta.b64_length = s.length;
    try {
      while (s.length % 4) s += "=";
      const raw = atob(s);
      meta.decoded_length = raw.length;
      const p = JSON.parse(raw);
      const rows = Array.isArray(p.rows) ? p.rows : [];
      meta.row_count = rows.length;
      meta.run_id = String(p.run_id || "");
      meta.parse_ok = true;
      const runIds = new Set();
      let maxSeq = 0;
      for (const r of rows) {
        if (!r || typeof r !== "object") continue;
        const rid = String(r.run_id || "");
        if (rid) runIds.add(rid);
        const seq = parseInt(r.script_run_seq || r.registration_script_run_sequence || 0, 10) || 0;
        if (seq > maxSeq) maxSeq = seq;
        if (String(r.event || "") === CANARY) meta.pipeline_canary_present = true;
      }
      meta.max_script_run_seq = maxSeq;
      meta.diagnostic_run_ids = Array.from(runIds).slice(0, 12);
      try {
        meta.content_hash = raw.slice(0, 64) + "..." + raw.slice(-32);
      } catch (e) {}
      return meta;
    } catch (e) {
      meta.decode_error = String(e && e.message ? e.message : e);
      return meta;
    }
  }
  function pushCandidate(list, source, b64, extra) {
    const dec = decodeAttempt(b64);
    list.push({
      source,
      frame_url: String(location.href || "").slice(0, 400),
      connected: document.body ? document.body.isConnected : true,
      visibility: document.visibilityState || "",
      b64: b64 ? String(b64).slice(0, 800000) : "",
      ...dec,
      ...(extra || {}),
    });
  }
  const candidates = [];
  try {
    if (window.__soloStage1LedgerB64Chunks && Array.isArray(window.__soloStage1LedgerB64Chunks)) {
      const joined = window.__soloStage1LedgerB64Chunks.join("");
      pushCandidate(candidates, "window.__soloStage1LedgerB64Chunks", joined, {
        chunk_join: true,
        authority_rank: 1,
      });
    }
  } catch (e2b) {}
  try {
    if (window.__soloStage1LedgerB64) {
      pushCandidate(candidates, "window.__soloStage1LedgerB64", window.__soloStage1LedgerB64, {
        window_b64: true,
        authority_rank: 2,
      });
    }
  } catch (e1) {}
  try {
    if (!window.__soloStage1LedgerB64) {
      const scripts = document.querySelectorAll("script");
      for (const sc of scripts) {
        const t = sc.textContent || "";
        const m = t.match(/window\\.__soloStage1LedgerB64\\s*=\\s*("(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*')/);
        if (m) {
          let lit = m[1];
          try { lit = JSON.parse(lit); } catch (e) { lit = lit.slice(1, -1); }
          pushCandidate(candidates, "script.window.__soloStage1LedgerB64", lit, {
            script_literal: true,
            authority_rank: 2,
          });
          break;
        }
      }
    }
  } catch (e2c) {}
  function chunkCountAttr(el) {
    return parseInt(
      el.getAttribute("data-b64-chunk-count") || el.getAttribute("data-chunk-count") || "0",
      10
    ) || 0;
  }
  function reassembleProbeB64(el) {
    const n = chunkCountAttr(el);
    const expected = parseInt(el.getAttribute("data-payload-b64-len") || "0", 10) || 0;
    if (n > 1) {
      let s = "";
      for (let i = 0; i < n; i++) {
        s += el.getAttribute("data-b64-chunk-" + i) || "";
      }
      return {
        b64: s,
        reassembly: expected && s.length !== expected ? "chunk_partial" : "chunk_full",
        expected_len: expected,
        actual_len: s.length,
      };
    }
    const single = el.getAttribute("data-b64") || "";
    return { b64: single, reassembly: "single_attr", expected_len: expected, actual_len: single.length };
  }
  const nodes = [];
  try {
    const byId = document.getElementById(PROBE_ID);
    if (byId) nodes.push(byId);
    document.querySelectorAll('[id="' + PROBE_ID + '"]').forEach(el => nodes.push(el));
    document.querySelectorAll("[data-b64]").forEach(el => {
      if (el.id === PROBE_ID || (el.getAttribute("data-b64") || "").length > 100) nodes.push(el);
    });
  } catch (e3) {}
  const seen = new Set();
  let domIndex = 0;
  for (const el of nodes) {
    if (!el || seen.has(el)) continue;
    seen.add(el);
    domIndex += 1;
    const asm = reassembleProbeB64(el);
    const b64 = asm.b64 || "";
    const domRank = asm.reassembly === "chunk_full" ? 3 : asm.reassembly === "single_attr" ? 4 : 3;
    pushCandidate(candidates, "dom#" + PROBE_ID + "[" + domIndex + "]", b64, {
      dom_index: domIndex,
      data_rows_attr: parseInt(el.getAttribute("data-row-count") || el.getAttribute("data-rows") || "0", 10) || 0,
      data_run_id: el.getAttribute("data-diagnostic-run-id") || el.getAttribute("data-run-id") || "",
      data_script_run_seq: parseInt(el.getAttribute("data-script-run-seq") || "0", 10) || 0,
      data_diagnostic_surface: el.getAttribute("data-diagnostic-surface") || "",
      payload_json_len_expected: parseInt(el.getAttribute("data-payload-json-len") || "0", 10) || 0,
      payload_sha256_expected: el.getAttribute("data-payload-sha256") || "",
      element_connected: el.isConnected,
      b64_reassembly: asm.reassembly,
      payload_b64_len_expected: asm.expected_len,
      payload_b64_len_actual: asm.actual_len,
      authority_rank: domRank,
    });
  }
  try {
    const store = window.__soloStage1HarnessLedgerStore;
    if (store && store.best_b64) {
      pushCandidate(candidates, "window.__soloStage1HarnessLedgerStore.best_b64", store.best_b64, {
        harness_max_rows: store.max_rows || 0,
        harness_stale: true,
        authority_rank: 99,
      });
    }
  } catch (e2) {}
  return { frame_url: String(location.href || "").slice(0, 400), candidates };
}
"""


def reassemble_b64_from_chunk_attrs(attrs: dict[str, str]) -> tuple[str, str]:
    """Join data-b64-chunk-* attributes; return (b64, reassembly_kind)."""
    n = int(attrs.get("data-b64-chunk-count") or attrs.get("data-chunk-count") or "0") or 0
    expected = int(attrs.get("data-payload-b64-len") or "0") or 0
    if n > 1:
        parts = [str(attrs.get(f"data-b64-chunk-{i}") or "") for i in range(n)]
        joined = "".join(parts)
        kind = "chunk_partial" if expected and len(joined) != expected else "chunk_full"
        return joined, kind
    return str(attrs.get("data-b64") or ""), "single_attr"


def normalize_b64(raw: str) -> str:
    s = html.unescape(str(raw or "").strip())
    s = re.sub(r"\s+", "", s)
    s = s.replace("-", "+").replace("_", "/")
    pad = (4 - len(s) % 4) % 4
    return s + ("=" * pad)


def decode_ledger_payload(b64: str) -> dict[str, Any]:
    """Decode ledger JSON with padding + HTML entity normalization."""
    norm = normalize_b64(b64)
    if not norm:
        return {"ok": False, "error": "empty_b64", "rows": [], "run_id": ""}
    try:
        decoded = base64.b64decode(norm.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            return {"ok": False, "error": "not_object", "rows": [], "run_id": ""}
        rows = [dict(r) for r in (payload.get("rows") or []) if isinstance(r, dict)]
        raw_bytes = decoded.encode("utf-8")
        return {
            "ok": True,
            "error": "",
            "rows": rows,
            "run_id": str(payload.get("run_id") or ""),
            "script_run_seq": int(payload.get("script_run_seq") or 0),
            "decoded_length": len(decoded),
            "json_byte_length": len(raw_bytes),
            "b64_length": len(norm),
            "content_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        }
    except Exception as exc:
        fallback = decode_ledger_b64_padded(b64)
        if fallback:
            rows = [dict(r) for r in (fallback.get("rows") or []) if isinstance(r, dict)]
            return {
                "ok": True,
                "error": "",
                "rows": rows,
                "run_id": str(fallback.get("run_id") or ""),
                "script_run_seq": int(fallback.get("script_run_seq") or 0),
                "decoded_length": 0,
                "json_byte_length": 0,
                "b64_length": len(str(b64)),
                "content_sha256": "",
                "decode_path": "legacy_padded",
            }
        return {"ok": False, "error": type(exc).__name__, "rows": [], "run_id": ""}


def verify_decoded_payload_integrity(
    dec: dict[str, Any],
    cand: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    if not dec.get("ok"):
        issues.append("decode_failed")
    exp_b64 = int(cand.get("payload_b64_len_expected") or 0)
    if exp_b64 and int(dec.get("b64_length") or 0) != exp_b64:
        issues.append("b64_len_mismatch")
    exp_json = int(cand.get("payload_json_len_expected") or 0)
    if exp_json and int(dec.get("json_byte_length") or 0) != exp_json:
        issues.append("json_len_mismatch")
    exp_sha = str(cand.get("payload_sha256_expected") or "").strip().lower()
    got_sha = str(dec.get("content_sha256") or "").strip().lower()
    if exp_sha and got_sha and exp_sha != got_sha:
        issues.append("sha256_mismatch")
    exp_rows = int(cand.get("data_rows_attr") or 0)
    if exp_rows and len(dec.get("rows") or []) != exp_rows:
        issues.append("row_count_mismatch")
    reasm = str(cand.get("b64_reassembly") or "")
    if reasm == "chunk_partial":
        issues.append("chunk_partial")
    return {"integrity_ok": not issues, "integrity_issues": issues}


def _row_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    run_ids: set[str] = set()
    max_seq = 0
    canary = False
    for r in rows:
        rid = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
        if rid:
            run_ids.add(rid[:32])
        seq = int(r.get("script_run_seq") or r.get("registration_script_run_sequence") or 0)
        max_seq = max(max_seq, seq)
        if str(r.get("event") or "") == PIPELINE_CANARY_EVENT:
            canary = True
    return {
        "row_count": len(rows),
        "diagnostic_run_ids": sorted(run_ids)[:12],
        "max_script_run_seq": max_seq,
        "pipeline_canary_present": canary,
    }


def _candidate_score(c: dict[str, Any], *, preferred_run_id: str = "") -> tuple[int, ...]:
    """Higher is better."""
    integrity = 1 if c.get("integrity_ok") else 0
    parse_ok = 1 if c.get("parse_ok") or c.get("ok") else 0
    canary = 1 if c.get("pipeline_canary_present") else 0
    rows = int(c.get("row_count") or 0)
    max_seq = int(c.get("max_script_run_seq") or 0)
    run_match = 1 if preferred_run_id and str(c.get("run_id") or "") == preferred_run_id[:32] else 0
    surface_match = 1 if str(c.get("data_diagnostic_surface") or CASE_A_SURFACE) == CASE_A_SURFACE else 0
    if not c.get("data_diagnostic_surface"):
        surface_match = 1
    connected = 1 if c.get("connected", c.get("element_connected", True)) else 0
    harness_penalty = 1 if "HarnessLedgerStore" in str(c.get("source") or "") else 0
    auth_rank = 100 - int(c.get("authority_rank") or 50)
    return (integrity, parse_ok, canary, run_match, surface_match, rows, max_seq, auth_rank, connected, -harness_penalty)


def classify_scrape_boundary(
    *,
    candidates: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    raw_canary: bool,
) -> str:
    if raw_canary:
        return ""
    if not candidates:
        return "SCRAPE1 — WRONG_FRAME"
    parsed_any = [c for c in candidates if c.get("parse_ok") or c.get("ok")]
    if not parsed_any:
        b64_any = [c for c in candidates if int(c.get("b64_length") or 0) > 0]
        if not b64_any:
            return "SCRAPE3 — WINDOW_GLOBAL_NOT_READ"
        for c in b64_any:
            err = str(c.get("decode_error") or c.get("error") or "")
            if "JSON" in err or err == "not_object":
                return "SCRAPE6 — JSON_DECODE_ERROR"
            if "atob" in err.lower() or "base64" in err.lower() or "InvalidCharacterError" in err:
                return "SCRAPE5 — BASE64_PADDING_OR_NORMALIZATION_ERROR"
        dom_rows = [c for c in candidates if str(c.get("source") or "").startswith("dom#")]
        if dom_rows:
            attr_rows = max(int(c.get("data_rows_attr") or 0) for c in dom_rows)
            if attr_rows > 0 and max(int(c.get("row_count") or 0) for c in dom_rows) == 0:
                return "SCRAPE4 — ATTRIBUTE_OR_TEXT_TRUNCATED"
        chunk_bad = [c for c in candidates if c.get("b64_reassembly") == "chunk_partial"]
        if chunk_bad:
            return "SCRAPE7 — CHUNK_ORDER_OR_CHUNK_LOSS"
        return "SCRAPE5 — BASE64_PADDING_OR_NORMALIZATION_ERROR"
    with_canary_dom = [c for c in parsed_any if c.get("pipeline_canary_present")]
    if with_canary_dom:
        sel_has = bool(selected and selected.get("pipeline_canary_present"))
        if not sel_has:
            return "SCRAPE2 — STALE_DUPLICATE_ELEMENT_SELECTED"
    if parsed_any and not with_canary_dom:
        stale = len([c for c in candidates if str(c.get("source") or "").startswith("dom#")]) > 1
        if stale:
            return "SCRAPE2 — STALE_DUPLICATE_ELEMENT_SELECTED"
        return "SCRAPE10 — OTHER"
    return "SCRAPE10 — OTHER"


def extract_stage1_ledger_from_page(page, *, preferred_run_id: str = "") -> dict[str, Any]:
    """Evaluate all frames; pick newest authoritative ledger payload."""
    all_candidates: list[dict[str, Any]] = []
    frame_reports: list[dict[str, Any]] = []
    for frame_index, fr in enumerate(page.frames):
        try:
            block = fr.evaluate(_COLLECT_CANDIDATES_JS)
        except Exception as exc:
            frame_reports.append({"frame_index": frame_index, "error": type(exc).__name__})
            continue
        if not isinstance(block, dict):
            continue
        for c in block.get("candidates") or []:
            if not isinstance(c, dict):
                continue
            cand = dict(c)
            cand["frame_index"] = frame_index
            b64_raw = str(cand.get("b64") or "")
            dec: dict[str, Any] = {}
            if b64_raw:
                dec = decode_ledger_payload(b64_raw)
                cand["ok"] = dec.get("ok")
                if dec.get("ok"):
                    stats = _row_stats(dec["rows"])
                    cand.update(stats)
                    cand["run_id"] = dec.get("run_id") or cand.get("run_id") or cand.get("data_run_id")
                    cand["rows"] = dec["rows"]
                    cand["parse_ok"] = True
                    cand["decode_error"] = ""
                    cand["decoded_length"] = dec.get("decoded_length")
                    cand["json_byte_length"] = dec.get("json_byte_length")
                    cand["content_sha256"] = dec.get("content_sha256")
                else:
                    cand["parse_ok"] = False
                    cand["decode_error"] = dec.get("error") or cand.get("decode_error")
                    cand["rows"] = []
                integrity = verify_decoded_payload_integrity(dec, cand)
                cand.update(integrity)
            b64_len = int(cand.get("b64_length") or len(b64_raw))
            cand["b64_length"] = b64_len
            cand.pop("b64", None)
            all_candidates.append(cand)
        frame_reports.append(
            {
                "frame_index": frame_index,
                "frame_url": block.get("frame_url"),
                "candidate_count": len(block.get("candidates") or []),
            }
        )

    selected: dict[str, Any] = {}
    if all_candidates:
        ranked = sorted(
            all_candidates,
            key=lambda c: _candidate_score(c, preferred_run_id=preferred_run_id),
            reverse=True,
        )
        selected = ranked[0]
        if not selected.get("pipeline_canary_present") or not selected.get("integrity_ok"):
            for c in ranked:
                if c.get("pipeline_canary_present") and c.get("parse_ok") and c.get("integrity_ok"):
                    selected = c
                    break

    rows = list(selected.get("rows") or []) if selected else []
    raw_canary = bool(
        selected.get("pipeline_canary_present")
        and selected.get("integrity_ok")
        and any(r.get("event") == PIPELINE_CANARY_EVENT for r in rows)
    )
    scrape_class = classify_scrape_boundary(
        candidates=all_candidates,
        selected=selected or None,
        raw_canary=raw_canary,
    )
    return {
        "frame_reports": frame_reports,
        "candidates": all_candidates,
        "selected_source": str(selected.get("source") or ""),
        "selected_frame_index": selected.get("frame_index"),
        "selected_frame_url": str(selected.get("frame_url") or "")[:400],
        "raw_length": int(selected.get("b64_length") or 0),
        "decoded_length": int(selected.get("decoded_length") or 0),
        "json_byte_length": int(selected.get("json_byte_length") or 0),
        "row_count": len(rows),
        "diagnostic_run_ids": selected.get("diagnostic_run_ids") or _row_stats(rows).get("diagnostic_run_ids"),
        "max_script_run_seq": int(selected.get("max_script_run_seq") or 0),
        "pipeline_canary_present": raw_canary,
        "raw_p6_capture_pass": raw_canary,
        "integrity_ok": bool(selected.get("integrity_ok")),
        "integrity_issues": list(selected.get("integrity_issues") or []),
        "rows": rows,
        "run_id": str(selected.get("run_id") or ""),
        "first_scrape_boundary": scrape_class,
        "content_sha256": str(selected.get("content_sha256") or ""),
        "payload_sha256_expected": str(selected.get("payload_sha256_expected") or ""),
    }


def filter_rows_for_run(
    rows: list[dict[str, Any]],
    *,
    run_id: str = "",
    diagnostic_surface: str = CASE_A_SURFACE,
) -> dict[str, Any]:
    rid = str(run_id or "").strip()
    surface = str(diagnostic_surface or "").strip()
    kept = list(rows)
    rejected = 0
    if rid:
        before = len(kept)
        kept = [r for r in kept if str(r.get("run_id") or "") == rid or not str(r.get("run_id") or "")]
        rejected += before - len(kept)
    if surface:
        before = len(kept)
        kept = [
            r
            for r in kept
            if not str(r.get("diagnostic_surface") or "").strip()
            or str(r.get("diagnostic_surface") or "") == surface
        ]
        rejected += before - len(kept)
    return {
        "filtered_rows": kept,
        "filtered_p6_capture_pass": any(r.get("event") == PIPELINE_CANARY_EVENT for r in kept),
        "rejected_count": rejected,
        "filter_run_id": rid,
        "filter_diagnostic_surface": surface,
    }
