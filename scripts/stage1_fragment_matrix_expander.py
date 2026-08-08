"""Open Stage1 fragment identity matrix Streamlit expander for production gate."""

from __future__ import annotations

import time
from typing import Any

MATRIX_EXPANDER_LABEL = "Stage1 fragment identity matrix (diag)"
S0_BUTTON_LABEL = "Stage1 Static Fragment Probe"

_FIND_EXPANDER_JS = """(exactLabel) => {
  const want = String(exactLabel || '').trim().toLowerCase();
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) {
    try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
  }
  let best = null;
  for (const doc of docs) {
    for (const details of doc.querySelectorAll('details')) {
      const summary = details.querySelector(':scope > summary');
      if (!summary) continue;
      const text = String(summary.innerText || '').replace(/\\s+/g, ' ').trim();
      const lower = text.toLowerCase();
      if (lower !== want && !lower.includes(want)) continue;
      const exact = lower === want;
      const rect = summary.getBoundingClientRect();
      const candidate = {
        found: true,
        exact_label_match: exact,
        open: details.hasAttribute('open'),
        summary_text: text.slice(0, 160),
        summary_visible: rect.width > 0 && rect.height > 0,
        frame_hint: doc.location ? String(doc.location.href || '').slice(0, 200) : '',
      };
      if (!best || (exact && !best.exact_label_match)) best = candidate;
    }
    const expanders = doc.querySelectorAll('[data-testid="stExpander"]');
    for (const exp of expanders) {
      const summary = exp.querySelector('summary');
      if (!summary) continue;
      const text = String(summary.innerText || '').replace(/\\s+/g, ' ').trim();
      const lower = text.toLowerCase();
      if (lower !== want && !lower.includes(want)) continue;
      const exact = lower === want;
      const rect = summary.getBoundingClientRect();
      const candidate = {
        found: true,
        exact_label_match: exact,
        open: exp.hasAttribute('open') || exp.open === true,
        summary_text: text.slice(0, 160),
        summary_visible: rect.width > 0 && rect.height > 0,
        frame_hint: doc.location ? String(doc.location.href || '').slice(0, 200) : '',
        via: 'stExpander',
      };
      if (!best || (exact && !best.exact_label_match)) best = candidate;
    }
  }
  return best || { found: false };
}"""

_CLICK_SUMMARY_JS = """(exactLabel) => {
  const want = String(exactLabel || '').trim().toLowerCase();
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) {
    try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
  }
  for (const doc of docs) {
    for (const details of doc.querySelectorAll('details')) {
      const summary = details.querySelector(':scope > summary');
      if (!summary) continue;
      const lower = String(summary.innerText || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      if (lower !== want && !lower.includes(want)) continue;
      summary.scrollIntoView({ block: 'center', inline: 'nearest' });
      summary.click();
      return {
        clicked: true,
        open_after: details.hasAttribute('open'),
        summary_text: String(summary.innerText || '').slice(0, 160),
      };
    }
  }
  return { clicked: false, reason: 'summary_not_found' };
}"""


def _app_frame(page):
    for fr in page.frames:
        if "/~/" in str(fr.url or ""):
            return fr
    return page.main_frame


def _probe_expander(page) -> dict[str, Any]:
    merged: dict[str, Any] = {"found": False}
    for fr in page.frames:
        if "/~/" not in str(fr.url or "") and fr != page.main_frame:
            continue
        try:
            row = fr.evaluate(_FIND_EXPANDER_JS, MATRIX_EXPANDER_LABEL) or {}
        except Exception as exc:
            row = {"error": str(exc)[:160]}
        if isinstance(row, dict) and row.get("found"):
            merged = dict(row)
            merged["frame_url"] = str(fr.url or "")[:240]
            if row.get("exact_label_match"):
                break
    if not merged.get("found"):
        try:
            row = page.evaluate(_FIND_EXPANDER_JS, MATRIX_EXPANDER_LABEL) or {}
            if isinstance(row, dict) and row.get("found"):
                merged = dict(row)
        except Exception:
            pass
    return merged


def _s0_visible(page, *, timeout_ms: int = 500) -> bool:
    fr = _app_frame(page)
    try:
        loc = fr.get_by_role("button", name=S0_BUTTON_LABEL, exact=True)
        if loc.count() == 0:
            loc = page.get_by_role("button", name=S0_BUTTON_LABEL, exact=True)
        loc.first.wait_for(state="visible", timeout=timeout_ms)
        return loc.first.is_visible() and loc.first.is_enabled()
    except Exception:
        return False


def open_fragment_identity_matrix_expander(page, *, wait_after_open_ms: int = 1500) -> dict[str, Any]:
    """Locate matrix expander, open via summary click if needed, confirm S0 visible."""
    out: dict[str, Any] = {
        "label": MATRIX_EXPANDER_LABEL,
        "matrix_expander_found": False,
        "matrix_expander_initially_open": False,
        "matrix_expander_click_dispatched": False,
        "matrix_expander_open_after": False,
        "s0_visible_after_open": False,
        "started_ts": time.time(),
    }
    probe = _probe_expander(page)
    out["matrix_expander_probe"] = probe
    out["matrix_expander_found"] = bool(probe.get("found"))
    if not out["matrix_expander_found"]:
        out["error"] = "matrix_expander_not_found"
        out["finished_ts"] = time.time()
        return out

    out["matrix_expander_initially_open"] = bool(probe.get("open"))
    out["s0_visible_after_open"] = _s0_visible(page, timeout_ms=800)

    if out["matrix_expander_initially_open"] and out["s0_visible_after_open"]:
        out["matrix_expander_open_after"] = True
        out["finished_ts"] = time.time()
        return out

    if not out["matrix_expander_initially_open"]:
        clicked = False
        fr = _app_frame(page)
        try:
            row = fr.evaluate(_CLICK_SUMMARY_JS, MATRIX_EXPANDER_LABEL) or {}
            clicked = bool(row.get("clicked"))
            out["summary_click_eval"] = row
        except Exception as exc:
            out["summary_click_eval"] = {"clicked": False, "error": str(exc)[:160]}
        if not clicked:
            try:
                loc = fr.locator("details").filter(has_text=MATRIX_EXPANDER_LABEL)
                if loc.count() == 0:
                    loc = page.locator("details").filter(has_text=MATRIX_EXPANDER_LABEL)
                summary = loc.first.locator("summary")
                summary.scroll_into_view_if_needed(timeout=8000)
                summary.click(timeout=8000)
                clicked = True
            except Exception as exc:
                out["summary_click_playwright_error"] = str(exc)[:200]
        out["matrix_expander_click_dispatched"] = clicked
        if clicked:
            page.wait_for_timeout(wait_after_open_ms)

    probe_after = _probe_expander(page)
    out["matrix_expander_probe_after"] = probe_after
    out["matrix_expander_open_after"] = bool(probe_after.get("open")) or out["matrix_expander_initially_open"]
    out["s0_visible_after_open"] = _s0_visible(page, timeout_ms=8000)
    if out["s0_visible_after_open"]:
        out["matrix_expander_open_after"] = True
    out["finished_ts"] = time.time()
    return out
