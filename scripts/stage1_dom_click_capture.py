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
    if (o.mode === 'fragment_probe') {
      return /Stage1 Recommendation Widget Probe/i.test(text) && String(btn.getAttribute('data-testid') || '').includes('stBaseButton');
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

_CLEAR_LOG_JS = """() => {
  const KEY = '__stage1DomClickCaptureLog';
  window[KEY] = [];
  return { cleared: true, len: 0 };
}"""

# Harness control IDs for isolated capture windows (one buffer per click).
CAPTURE_TARGET_PAUSE = "pause_draft"
CAPTURE_TARGET_FRAGMENT_PROBE = "fragment_widget_probe"
CAPTURE_TARGET_FRANCISCO_ADD = "francisco_add_to_queue"
CAPTURE_TARGET_FRAGMENT_MATRIX_S0 = "fragment_matrix_s0"
CAPTURE_TARGET_FRAGMENT_MATRIX_S1 = "fragment_matrix_s1"
CAPTURE_TARGET_FRAGMENT_MATRIX_D0 = "fragment_matrix_d0"
CAPTURE_TARGET_FRAGMENT_MATRIX_D1 = "fragment_matrix_d1"
CAPTURE_TARGET_CONTEXT_C0 = "fragment_context_c0"
CAPTURE_TARGET_CONTEXT_C1 = "fragment_context_c1"
CAPTURE_TARGET_CONTEXT_C2 = "fragment_context_c2"
CAPTURE_TARGET_CONTEXT_C3 = "fragment_context_c3"

_CONTEXT_CAPTURE_BY_CONTROL: dict[str, str] = {
    "C0": CAPTURE_TARGET_CONTEXT_C0,
    "C1": CAPTURE_TARGET_CONTEXT_C1,
    "C2": CAPTURE_TARGET_CONTEXT_C2,
    "C3": CAPTURE_TARGET_CONTEXT_C3,
}


def fragment_context_capture_target(control: str) -> str:
    return _CONTEXT_CAPTURE_BY_CONTROL.get(str(control or "").strip().upper(), CAPTURE_TARGET_CONTEXT_C0)


_MATRIX_CAPTURE_BY_CONTROL: dict[str, str] = {
    "S0": CAPTURE_TARGET_FRAGMENT_MATRIX_S0,
    "S1": CAPTURE_TARGET_FRAGMENT_MATRIX_S1,
    "D0": CAPTURE_TARGET_FRAGMENT_MATRIX_D0,
    "D1": CAPTURE_TARGET_FRAGMENT_MATRIX_D1,
}


def fragment_matrix_capture_target(control: str) -> str:
    return _MATRIX_CAPTURE_BY_CONTROL.get(str(control or "").strip().upper(), CAPTURE_TARGET_FRAGMENT_MATRIX_S0)


_CAPTURE_TARGET_RULES: dict[str, dict[str, Any]] = {
    CAPTURE_TARGET_PAUSE: {
        "mode": "pause",
        "button_label_re": "Pause Draft",
        "match_substrings": ("pause draft",),
        "reject_substrings": ("add to queue", "widget probe", "resume draft"),
    },
    CAPTURE_TARGET_FRAGMENT_PROBE: {
        "mode": "fragment_probe",
        "button_label_re": "Stage1 Recommendation Widget Probe",
        "match_substrings": ("stage1 recommendation widget probe",),
        "reject_substrings": ("add to queue", "pause draft"),
    },
    CAPTURE_TARGET_FRANCISCO_ADD: {
        "mode": "rec_card",
        "button_label_re": "Add to Queue",
        "match_substrings": ("add to queue",),
        "reject_substrings": ("pause draft", "widget probe", "resume draft"),
    },
    CAPTURE_TARGET_FRAGMENT_MATRIX_S0: {
        "mode": "fragment_matrix",
        "button_label_re": "Stage1 Static Fragment Probe",
        "match_substrings": ("stage1 static fragment probe",),
        "reject_substrings": ("add to queue", "pause draft", "recommendation widget probe"),
    },
    CAPTURE_TARGET_FRAGMENT_MATRIX_S1: {
        "mode": "fragment_matrix",
        "button_label_re": "Stage1 Static Timed Fragment Probe",
        "match_substrings": ("stage1 static timed fragment probe",),
        "reject_substrings": ("add to queue", "pause draft", "recommendation widget probe"),
    },
    CAPTURE_TARGET_FRAGMENT_MATRIX_D0: {
        "mode": "fragment_matrix",
        "button_label_re": "Stage1 Dynamic Fragment Probe",
        "match_substrings": ("stage1 dynamic fragment probe",),
        "reject_substrings": ("add to queue", "pause draft", "recommendation widget probe", "timed fragment probe"),
    },
    CAPTURE_TARGET_FRAGMENT_MATRIX_D1: {
        "mode": "fragment_matrix",
        "button_label_re": "Stage1 Dynamic Timed Fragment Probe",
        "match_substrings": ("stage1 dynamic timed fragment probe",),
        "reject_substrings": ("add to queue", "pause draft", "recommendation widget probe"),
    },
    CAPTURE_TARGET_CONTEXT_C0: {
        "mode": "fragment_context",
        "button_label_re": "Stage1 Top-Level Fragment Probe",
        "match_substrings": ("stage1 top-level fragment probe",),
        "reject_substrings": ("add to queue", "pause draft"),
    },
    CAPTURE_TARGET_CONTEXT_C1: {
        "mode": "fragment_context",
        "button_label_re": "Stage1 Expander Fragment Probe",
        "match_substrings": ("stage1 expander fragment probe",),
        "reject_substrings": ("add to queue", "pause draft"),
    },
    CAPTURE_TARGET_CONTEXT_C2: {
        "mode": "fragment_context",
        "button_label_re": "Stage1 Expander Normal Button Probe",
        "match_substrings": ("stage1 expander normal button probe",),
        "reject_substrings": ("add to queue", "pause draft"),
    },
    CAPTURE_TARGET_CONTEXT_C3: {
        "mode": "fragment_context",
        "button_label_re": "Stage1 Top-Level Normal Button Probe",
        "match_substrings": ("stage1 top-level normal button probe",),
        "reject_substrings": ("add to queue", "pause draft"),
    },
}


def clear_dom_click_capture_on_frame(frame) -> dict[str, Any]:
    try:
        return frame.evaluate(_CLEAR_LOG_JS) or {"cleared": False}
    except Exception as exc:
        return {"cleared": False, "error": str(exc)[:160]}


def normalize_dom_click_event(event: dict[str, Any]) -> dict[str, Any]:
    """Single schema: ``is_trusted`` only (browser ``isTrusted`` normalized at scrape)."""
    if not isinstance(event, dict):
        return {}
    out = dict(event)
    if "is_trusted" not in out or out.get("is_trusted") is None:
        if "isTrusted" in out:
            out["is_trusted"] = bool(out.get("isTrusted"))
        else:
            out["is_trusted"] = False
    else:
        out["is_trusted"] = bool(out.get("is_trusted"))
    out.pop("isTrusted", None)
    return out


def normalize_dom_click_events(events: list[Any]) -> list[dict[str, Any]]:
    return [normalize_dom_click_event(e) for e in events if isinstance(e, dict)]


def _event_text_blob(event: dict[str, Any]) -> str:
    parts = [
        str(event.get("target_text") or ""),
        str(event.get("current_target_tag") or ""),
    ]
    return " ".join(parts).lower()


def summarize_dom_click_capture(
    events: list[Any],
    *,
    capture_target: str,
) -> dict[str, Any]:
    """Grade one isolated capture window for a control target."""
    rules = _CAPTURE_TARGET_RULES.get(capture_target) or {}
    normalized = normalize_dom_click_events(list(events or []))
    match_subs = tuple(s.lower() for s in rules.get("match_substrings") or ())
    reject_subs = tuple(s.lower() for s in rules.get("reject_substrings") or ())

    def _matches_target(text: str) -> bool:
        if not match_subs:
            return True
        return any(sub in text for sub in match_subs)

    def _rejected(text: str) -> bool:
        return any(sub in text for sub in reject_subs)

    event_target_texts = [str(e.get("target_text") or "")[:120] for e in normalized]
    event_types = [str(e.get("type") or "") for e in normalized]
    unexpected: list[str] = []
    trusted_click = False
    for ev in normalized:
        blob = _event_text_blob(ev)
        if ev.get("type") == "click" and ev.get("is_trusted"):
            if _matches_target(blob) and not _rejected(blob):
                trusted_click = True
            elif blob.strip():
                unexpected.append(str(ev.get("target_text") or blob)[:80])
        elif blob.strip() and _rejected(blob):
            unexpected.append(str(ev.get("target_text") or blob)[:80])

    return {
        "capture_target": capture_target,
        "trusted_dom_click": trusted_click,
        "event_types": event_types,
        "event_target_texts": event_target_texts,
        "event_count": len(normalized),
        "unexpected_event_targets": sorted(set(unexpected)),
        "browser_dom_click_events": normalized,
    }


def prepare_isolated_dom_click_capture(
    frame,
    *,
    capture_target: str,
    frame_url_hint: str = "",
    player_name: str = "",
    button_test_id: str = "stBaseButton-secondary",
    dom_generation_ts: str = "",
) -> dict[str, Any]:
    """Clear buffer, then install listeners on the target button in this frame."""
    rules = _CAPTURE_TARGET_RULES.get(capture_target) or {}
    cleared = clear_dom_click_capture_on_frame(frame)
    install = install_dom_click_capture_on_frame(
        frame,
        frame_url_hint=frame_url_hint,
        player_name=player_name,
        button_test_id=button_test_id,
        dom_generation_ts=dom_generation_ts,
        mode=str(rules.get("mode") or "rec_card"),
        button_label_re=str(rules.get("button_label_re") or "Add to Queue"),
    )
    return {
        "capture_cleared_before_click": bool(cleared.get("cleared")),
        "capture_target": capture_target,
        "dom_click_capture_install": install,
    }


def read_and_summarize_dom_click_capture(
    frame,
    *,
    capture_target: str,
) -> dict[str, Any]:
    events = read_dom_click_capture_from_frame(frame)
    summary = summarize_dom_click_capture(events, capture_target=capture_target)
    summary["capture_cleared_before_click"] = summary.get("capture_cleared_before_click")
    return summary


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
        return normalize_dom_click_events([r for r in raw if isinstance(r, dict)])
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
    return normalize_dom_click_events(events[-48:])
