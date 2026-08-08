"""Capture-phase DOM event logging on Streamlit native buttons (harness diagnostics)."""

from __future__ import annotations

from typing import Any

_CAPTURE_INSTALL_JS = """(buttonSelector) => {
  const KEY = '__stage1DomClickCaptureLog';
  function roots() {
    const r = [document];
    for (const f of document.querySelectorAll('iframe')) {
      try { if (f.contentDocument) r.push(f.contentDocument); } catch (e) {}
    }
    return r;
  }
  function pathFor(el) {
    const parts = [];
    let n = el;
    for (let i = 0; i < 8 && n; i++) {
      const tag = String(n.tagName || '').toLowerCase();
      const tid = n.getAttribute && n.getAttribute('data-testid');
      parts.push(tid ? tag + '[data-testid=' + tid + ']' : tag);
      n = n.parentElement;
    }
    return parts.join('>');
  }
  function findButton() {
    for (const doc of roots()) {
      let btn = null;
      if (buttonSelector) {
        try { btn = doc.querySelector(buttonSelector); } catch (e) {}
      }
      if (!btn) {
        btn = doc.querySelector('button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-primary"]');
      }
      if (btn) return { doc, btn };
    }
    return null;
  }
  const found = findButton();
  if (!found) return { ok: false, error: 'button_not_found' };
  const { doc, btn } = found;
  const win = doc.defaultView || window;
  if (!win[KEY]) win[KEY] = [];
  const types = ['pointerdown', 'mousedown', 'focus', 'pointerup', 'mouseup', 'click'];
  const handler = (ev) => {
    const t = ev.target;
    const attached = !!(t && t.isConnected);
    win[KEY].push({
      type: ev.type,
      ts: (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now(),
      wall_ts_ms: Date.now(),
      target_tag: t ? String(t.tagName || '').toLowerCase() : '',
      target_testid: (t && t.getAttribute && t.getAttribute('data-testid')) || '',
      current_target_tag: ev.currentTarget ? String(ev.currentTarget.tagName || '').toLowerCase() : '',
      is_trusted: !!ev.isTrusted,
      default_prevented: !!ev.defaultPrevented,
      path: pathFor(t || btn),
      button_attached: attached,
    });
  };
  if (btn.__stage1CaptureInstalled) {
    return { ok: true, reused: true, button_testid: btn.getAttribute('data-testid') || '' };
  }
  btn.__stage1CaptureInstalled = true;
  for (const ty of types) {
    btn.addEventListener(ty, handler, true);
    if (btn.parentElement) btn.parentElement.addEventListener(ty, handler, true);
  }
  return {
    ok: true,
    button_testid: btn.getAttribute('data-testid') || '',
    button_text: String(btn.innerText || '').trim().slice(0, 80),
    frame_href: (win.location && win.location.href) || '',
  };
}"""

_READ_LOG_JS = """() => {
  function collect(win) {
    const KEY = '__stage1DomClickCaptureLog';
    try {
      if (win[KEY] && win[KEY].length) return win[KEY].slice(-40);
    } catch (e) {}
    return [];
  }
  let out = collect(window);
  for (const f of document.querySelectorAll('iframe')) {
    try {
      if (f.contentWindow) {
        const sub = collect(f.contentWindow);
        if (sub.length) out = out.concat(sub);
      }
    } catch (e) {}
  }
  return out.slice(-40);
}"""


def install_dom_click_capture(page, *, button_selector: str = "") -> dict[str, Any]:
    try:
        return page.evaluate(_CAPTURE_INSTALL_JS, button_selector or "") or {}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def read_dom_click_capture_log(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_READ_LOG_JS) or []
        return [r for r in raw if isinstance(r, dict)]
    except Exception:
        return []
