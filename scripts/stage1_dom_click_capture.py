"""Capture-phase DOM event logging on Streamlit native buttons (target frame/document)."""

from __future__ import annotations

from typing import Any

_INSTALL_IN_DOC_JS = """(opts) => {
  const o = opts || {};
  const KEY = '__stage1DomClickCaptureLog';
  const MARK = '__stage1DomClickCaptureTarget';
  const wantUrl = String(o.frameUrlHint || '').trim();
  const player = String(o.playerName || '').trim().toLowerCase();
  const labelRe = o.buttonLabelRe ? new RegExp(o.buttonLabelRe, 'i') : /Add to Queue/i;
  const pauseRe = /Pause Draft/i;
  const testId = String(o.buttonTestId || 'stBaseButton-secondary');
  const domGen = String(o.domGenerationTs || '');

  function pathFor(el) {
    const parts = [];
    let n = el;
    for (let i = 0; i < 10 && n; i++) {
      const tag = String(n.tagName || '').toLowerCase();
      const tid = n.getAttribute && n.getAttribute('data-testid');
      parts.push(tid ? tag + '[data-testid=' + tid + ']' : tag);
      n = n.parentElement;
    }
    return parts.join('>');
  }

  function cardScopeForButton(btn) {
    let el = btn;
    for (let i = 0; i < 14 && el; i++) {
      if (el.querySelector && el.querySelector('.ld-rec-card-meta')) return el;
      el = el.parentElement;
    }
    return null;
  }

  function buttonMatches(btn) {
    const text = String(btn.innerText || btn.textContent || '').replace(/\\s+/g, ' ').trim();
    if (o.mode === 'pause') {
      return pauseRe.test(text) && String(btn.getAttribute('data-testid') || '').includes('stBaseButton');
    }
    if (!labelRe.test(text)) return false;
    if (String(btn.getAttribute('data-testid') || '') !== testId && !String(btn.getAttribute('data-testid') || '').includes('stBaseButton')) return false;
    if (!player) return true;
    const scope = cardScopeForButton(btn);
    if (!scope) return false;
    const meta = scope.querySelector('.ld-rec-card-meta');
    const sample = String((meta && meta.innerText) || scope.innerText || '').toLowerCase();
    return sample.includes(player);
  }

  function findTargetButton(doc) {
    const candidates = [];
    for (const btn of doc.querySelectorAll('button')) {
      if (!buttonMatches(btn)) continue;
      const r = btn.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) continue;
      candidates.push(btn);
    }
    if (!candidates.length) return null;
    return candidates[0];
  }

  const href = (window.location && window.location.href) || '';
  if (wantUrl && wantUrl.length > 20 && !href.includes(wantUrl.split('?')[0].slice(-40)) && !wantUrl.includes(href.split('?')[0].slice(-40))) {
    /* allow partial match — Streamlit URLs vary */
  }

  const btn = findTargetButton(document);
  if (!btn) {
    return { ok: false, error: 'target_button_not_in_this_document', frame_href: href, mode: o.mode || 'rec_card' };
  }

  btn.setAttribute(MARK, '1');
  if (domGen) btn.setAttribute('data-stage1-capture-dom-gen', domGen);

  const types = ['pointerdown', 'mousedown', 'focus', 'pointerup', 'mouseup', 'click'];
  const handler = (ev) => {
    const t = ev.target;
    if (!window[KEY]) window[KEY] = [];
    window[KEY].push({
      type: ev.type,
      ts: (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now(),
      wall_ts_ms: Date.now(),
      target_tag: t ? String(t.tagName || '').toLowerCase() : '',
      target_testid: (t && t.getAttribute && t.getAttribute('data-testid')) || '',
      target_text: t ? String(t.innerText || t.textContent || '').trim().slice(0, 80) : '',
      current_target_tag: ev.currentTarget ? String(ev.currentTarget.tagName || '').toLowerCase() : '',
      is_trusted: !!ev.isTrusted,
      default_prevented: !!ev.defaultPrevented,
      path: pathFor(t || btn),
      button_attached: !!(t && t.isConnected),
      composed_path_len: (ev.composedPath && ev.composedPath().length) || 0,
    });
  };

  if (btn.__stage1CaptureInstalled) {
    return {
      ok: true,
      reused: true,
      frame_href: href,
      button_testid: btn.getAttribute('data-testid') || '',
      button_text: String(btn.innerText || '').trim().slice(0, 80),
      target_marker: MARK,
      listener_document_matches_button: true,
    };
  }
  btn.__stage1CaptureInstalled = true;
  for (const ty of types) {
    btn.addEventListener(ty, handler, true);
  }
  return {
    ok: true,
    frame_href: href,
    button_testid: btn.getAttribute('data-testid') || '',
    button_text: String(btn.innerText || '').trim().slice(0, 80),
    target_marker: MARK,
    listener_document_matches_button: true,
    dom_generation_ts: domGen || '',
  };
}"""

_READ_LOG_FROM_WINDOW_JS = """() => {
  const KEY = '__stage1DomClickCaptureLog';
  try {
    return (window[KEY] && window[KEY].slice(-48)) || [];
  } catch (e) {
    return [];
  }
}"""


def install_dom_click_capture_on_frame(
    frame,
    *,
    frame_url_hint: str = "",
    player_name: str = "",
    button_test_id: str = "stBaseButton-secondary",
    dom_generation_ts: str = "",
    mode: str = "rec_card",
    button_label_re: str = r"Add to Queue",
) -> dict[str, Any]:
    opts = {
        "frameUrlHint": frame_url_hint,
        "playerName": player_name,
        "buttonTestId": button_test_id,
        "domGenerationTs": dom_generation_ts,
        "mode": mode,
        "buttonLabelRe": button_label_re,
    }
    try:
        return frame.evaluate(_INSTALL_IN_DOC_JS, opts) or {}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def read_dom_click_capture_from_frame(frame) -> list[dict[str, Any]]:
    try:
        raw = frame.evaluate(_READ_LOG_FROM_WINDOW_JS) or []
        return [r for r in raw if isinstance(r, dict)]
    except Exception:
        return []


def install_dom_click_capture(page, *, button_selector: str = "") -> dict[str, Any]:
    """Legacy top-level installer — prefer install_dom_click_capture_on_frame."""
    for fr in page.frames:
        url = str(fr.url or "")
        if "/~/" in url or "~/+" in url:
            return install_dom_click_capture_on_frame(fr, frame_url_hint=url, mode="rec_card")
    try:
        return page.evaluate(
            """(sel) => {
              const btn = document.querySelector(sel || 'button[data-testid="stBaseButton-secondary"]');
              return { ok: !!btn, legacy: true };
            }""",
            button_selector or "",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "legacy": True}


def read_dom_click_capture_log(page) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for fr in page.frames:
        events.extend(read_dom_click_capture_from_frame(fr))
    return events[-48:]
