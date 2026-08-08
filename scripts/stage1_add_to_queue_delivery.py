"""Shared Add-to-Queue discovery, player binding, and click delivery (Stage 1A-QUEUE harness)."""

from __future__ import annotations

import re
import time
from typing import Any

BINDING_UNIQUE = "unique"
BINDING_AMBIGUOUS = "ambiguous"
BINDING_MISSING = "missing"

_NAME_ONLY = re.compile(r"^[A-Z][A-Za-z .'-]{2,48}$")
_NAME_TWO = re.compile(r"^([A-Z][a-z]+(?: [A-Z][a-z.'-]+){1,3})$")
_SKIP_LINE = re.compile(
    r"Add to Queue|Draft Player|Draft Queue|Clear Draft|Watchlist|Available Players|"
    r"Recommendations|keyboard_arrow|⭐|^\s*$",
    re.I,
)


def extract_player_names_from_lines(lines: list[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        ln = raw.strip().strip("*").strip()
        ln = re.sub(r"^\d+\.\s*", "", ln)
        if not ln or _SKIP_LINE.search(ln):
            continue
        if re.match(r"^(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)$", ln, re.I):
            continue
        pos = re.match(
            r"^([A-Za-z][A-Za-z .'-]{2,60})\s+[—\-–]\s+(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)\b",
            ln,
        )
        if pos:
            name = pos.group(1).strip()
        elif _NAME_TWO.match(ln):
            name = ln
        elif _NAME_ONLY.match(ln):
            name = ln
        else:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def classify_name_binding(names: list[str]) -> tuple[str, str]:
    if not names:
        return BINDING_MISSING, ""
    if len(names) == 1:
        return BINDING_UNIQUE, names[0]
    return BINDING_AMBIGUOUS, ""


_QUEUE_HELP_TITLE_RE = re.compile(r"Add\s+(.+?)\s+to\s+your\s+draft\s+queue", re.I)


def parse_player_from_queue_help(text: str) -> str:
    m = _QUEUE_HELP_TITLE_RE.search(str(text or ""))
    return m.group(1).strip() if m else ""


_DISCOVER_BOUND_CONTROLS_JS = """() => {
  function roots() {
    const r = [document];
    for (const f of document.querySelectorAll('iframe')) {
      try { if (f.contentDocument) r.push(f.contentDocument); } catch (e) {}
    }
    return r.filter(Boolean);
  }
  function extractNames(lines) {
    const names = [];
    const seen = new Set();
    const rejectName = /^(Why Recommended|Draft Player|Draft|Queued|Available Players|Watchlist|Recommendations|On Clock|keyboard_arrow|Clear Draft Queue|Draft Queue|Empty|Tracked players)/i;
    const posRe = /^([A-Za-z][A-Za-z .\\'-]{2,60})\\s+[—\\-–]\\s+(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)\\b/;
    const twoRe = /^([A-Z][a-z]+(?: [A-Z][a-z'.\\-]+){1,3})$/;
    const oneRe = /^[A-Z][A-Za-z .\\'-]{2,48}$/;
    const skipLine = /Add to Queue|Draft Queue|Clear Draft|keyboard_arrow|⭐|^\\s*$/i;
    for (const raw of lines) {
      let ln = String(raw||'').trim().replace(/^\\*+|\\*+$/g,'').replace(/^\\d+\\.\\s*/, '');
      if (!ln || skipLine.test(ln)) continue;
      if (/^(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)$/i.test(ln)) continue;
      let name = '';
      const pos = ln.match(posRe);
      if (pos) name = pos[1].trim();
      else if (twoRe.test(ln)) name = ln;
      else if (oneRe.test(ln)) name = ln;
      if (!name) continue;
      if (rejectName.test(name)) continue;
      const k = name.toLowerCase();
      if (seen.has(k)) continue;
      seen.add(k);
      names.push(name);
    }
    return names;
  }
  function isVisibleButton(btn) {
    const r = btn.getBoundingClientRect();
    return r.width >= 10 && r.height >= 10;
  }
  function countVisibleAddQueueIn(el) {
    let n = 0;
    for (const b of el.querySelectorAll('button')) {
      if (!/Add to Queue/i.test(String(b.innerText || ''))) continue;
      if (isVisibleButton(b)) n += 1;
    }
    return n;
  }
  function bindFromButtonHelp(btn) {
    let el = btn;
    for (let i = 0; i < 8 && el; i++) {
      const title = String(el.getAttribute('title') || el.getAttribute('aria-label') || '');
      const m = title.match(/Add\\s+(.+?)\\s+to\\s+your\\s+draft\\s+queue/i);
      if (m) {
        const names = extractNames([m[1].trim()]);
        if (names.length === 1) {
          return {
            confidence: 'unique',
            player_name: names[0],
            names,
            container_depth: -1,
            container_sample: title.slice(0, 280),
            binding_via: 'button_help_title',
          };
        }
      }
      const stBtn = el.closest && el.closest('[data-testid="stButton"]');
      if (stBtn) {
        const stTitle = String(stBtn.getAttribute('title') || stBtn.getAttribute('aria-label') || '');
        const m2 = stTitle.match(/Add\\s+(.+?)\\s+to\\s+your\\s+draft\\s+queue/i);
        if (m2) {
          const names = extractNames([m2[1].trim()]);
          if (names.length === 1) {
            return {
              confidence: 'unique',
              player_name: names[0],
              names,
              container_depth: -1,
              container_sample: stTitle.slice(0, 280),
              binding_via: 'stButton_help_title',
            };
          }
        }
      }
      el = el.parentElement;
    }
    return null;
  }
  function bindFromRecCardScope(btn) {
    let walk = btn;
    for (let depth = 0; depth < 18 && walk; depth++) {
      walk = walk.parentElement;
      if (!walk) break;
      if (countVisibleAddQueueIn(walk) !== 1) continue;
      const meta = walk.querySelector('.ld-rec-card-meta');
      if (meta) {
        const nameEl = meta.querySelector('div');
        const raw = nameEl ? String(nameEl.innerText || '').trim() : String(meta.innerText || '').split('\\n')[0].trim();
        const names = extractNames([raw]);
        if (names.length === 1) {
          return {
            confidence: 'unique',
            player_name: names[0],
            names,
            container_depth: depth,
            container_sample: raw.slice(0, 280),
            binding_via: 'ld_rec_card_meta',
          };
        }
      }
      const header = walk.querySelector('.ld-rec-card-header');
      if (header) {
        const names = extractNames(String(header.innerText || '').split('\\n').map((x) => x.trim()).filter(Boolean));
        if (names.length === 1) {
          return {
            confidence: 'unique',
            player_name: names[0],
            names,
            container_depth: depth,
            container_sample: String(header.innerText || '').slice(0, 280),
            binding_via: 'ld_rec_card_header',
          };
        }
        if (names.length > 1) {
          return {
            confidence: 'ambiguous',
            player_name: '',
            names,
            container_depth: depth,
            container_sample: String(header.innerText || '').slice(0, 280),
            binding_via: 'ld_rec_card_header',
          };
        }
      }
      const t = String(walk.innerText || '');
      if (!/Add to Queue/i.test(t)) continue;
      const lines = t.split('\\n').map((x) => x.trim()).filter(Boolean);
      const names = extractNames(lines);
      if (names.length === 1) {
        return {
          confidence: 'unique',
          player_name: names[0],
          names,
          container_depth: depth,
          container_sample: t.slice(0, 280),
          binding_via: 'single_visible_add_ancestor',
        };
      }
      if (names.length > 1) {
        return {
          confidence: 'ambiguous',
          player_name: '',
          names,
          container_depth: depth,
          container_sample: t.slice(0, 280),
          binding_via: 'single_visible_add_ancestor',
        };
      }
    }
    return null;
  }
  function bindFromRowTextBeforeButton(btn) {
    const row = btn.closest('[data-testid="stHorizontalBlock"]');
    if (!row) return null;
    if (countVisibleAddQueueIn(row) > 1) return null;
    const full = String(row.innerText || '');
    const parts = full.split(/\\u2b50\\s*Add to Queue|Add to Queue/i);
    const head = (parts[0] || '').trim();
    if (!head) return null;
    const names = extractNames(head.split('\\n').map((x) => x.trim()).filter(Boolean));
    if (names.length === 1) {
      return {
        confidence: 'unique',
        player_name: names[0],
        names,
        container_depth: -1,
        container_sample: head.slice(0, 280),
        binding_via: 'row_text_before_add_button',
      };
    }
    return null;
  }
  function bindFromColumn(btn) {
    const col = btn.closest('[data-testid="stColumn"]');
    if (!col || !col.parentElement) return null;
    const cols = Array.from(col.parentElement.children).filter(
      (c) => c.getAttribute && c.getAttribute('data-testid') === 'stColumn'
    );
    const idx = cols.indexOf(col);
    if (idx <= 0) return null;
    for (let i = idx - 1; i >= 0; i--) {
      const t = String(cols[i].innerText || '');
      const names = extractNames(t.split('\\n').map((x) => x.trim()).filter(Boolean));
      if (names.length === 1) {
        return {
          confidence: 'unique',
          player_name: names[0],
          names,
          container_depth: -1,
          container_sample: t.slice(0, 280),
          binding_via: 'stColumn_left',
        };
      }
      if (names.length > 1) break;
    }
    return null;
  }
  function bindPlayerName(btn) {
    let best = { confidence: 'missing', player_name: '', names: [], container_depth: -1, container_sample: '' };
    const helpBind = bindFromButtonHelp(btn);
    if (helpBind) return helpBind;
    const cardBind = bindFromRecCardScope(btn);
    if (cardBind) return cardBind;
    const rowBind = bindFromRowTextBeforeButton(btn);
    if (rowBind) return rowBind;
    const colBind = bindFromColumn(btn);
    if (colBind) return colBind;
    const row = btn.closest('[data-testid="stHorizontalBlock"]');
    if (row) {
      const cols = Array.from(row.querySelectorAll('[data-testid="stVerticalBlock"]'));
      const btnCol = btn.closest('[data-testid="stVerticalBlock"]');
      const idx = cols.indexOf(btnCol);
      if (idx > 0) {
        const t = String(cols[idx - 1].innerText || '');
        const names = extractNames(t.split('\\n').map(x => x.trim()).filter(Boolean));
        if (names.length === 1) {
          return {
            confidence: 'unique',
            player_name: names[0],
            names,
            container_depth: -1,
            container_sample: t.slice(0, 280),
            binding_via: 'horizontal_previous_column',
          };
        }
      }
    }
    const horiz = btn.closest('[data-testid="stHorizontalBlock"]');
    if (horiz) {
      for (const col of horiz.querySelectorAll('[data-testid="stVerticalBlock"]')) {
        const t = String(col.innerText||'');
        if (/Add to Queue/i.test(t)) continue;
        const names = extractNames(t.split('\\n').map(x => x.trim()).filter(Boolean));
        if (names.length === 1) {
          return {
            confidence: 'unique',
            player_name: names[0],
            names,
            container_depth: -1,
            container_sample: t.slice(0, 280),
            binding_via: 'horizontal_column',
          };
        }
      }
    }
    const card = btn.closest('[data-testid="stVerticalBlock"]');
    if (card && card.previousElementSibling) {
      const prevLines = String(card.previousElementSibling.innerText||'').split('\\n').map(x => x.trim()).filter(Boolean);
      const prevNames = extractNames(prevLines);
      if (prevNames.length === 1) {
        return {
          confidence: 'unique',
          player_name: prevNames[0],
          names: prevNames,
          container_depth: -1,
          container_sample: String(card.previousElementSibling.innerText||'').slice(0, 280),
          binding_via: 'previous_sibling_block',
        };
      }
    }
    let walk = btn;
    for (let depth = 0; depth < 12 && walk; depth++) {
      walk = walk.parentElement;
      if (!walk) break;
      const t = String(walk.innerText||'');
      if (!/Add to Queue/i.test(t)) continue;
      if (countVisibleAddQueueIn(walk) > 1) continue;
      const lines = t.split('\\n').map(x => x.trim()).filter(Boolean);
      const names = extractNames(lines);
      if (names.length === 1) {
        return {
          confidence: 'unique',
          player_name: names[0],
          names,
          container_depth: depth,
          container_sample: t.slice(0, 280),
          binding_via: 'ancestor_walk',
        };
      }
      if (names.length > 1) {
        best = {
          confidence: 'ambiguous',
          player_name: '',
          names,
          container_depth: depth,
          container_sample: t.slice(0, 280),
          binding_via: 'ancestor_walk',
        };
      }
    }
    return best;
  }
  function domPath(el, maxDepth) {
    const parts = [];
    let n = el;
    for (let i = 0; i < (maxDepth || 8) && n; i++) {
      let seg = (n.tagName || '').toLowerCase();
      const tid = n.getAttribute && n.getAttribute('data-testid');
      if (tid) seg += '[data-testid=' + tid + ']';
      parts.unshift(seg);
      n = n.parentElement;
    }
    return parts.join('>');
  }
  const out = [];
  let globalIndex = 0;
  let frameIndex = 0;
  for (const root of roots()) {
    const frameUrl = (root.defaultView && root.defaultView.location && root.defaultView.location.href) || '';
    let indexInFrame = 0;
    for (const btn of root.querySelectorAll('button')) {
      const t = String(btn.innerText||'').replace(/\\s+/g,' ').trim();
      if (!/Add to Queue/i.test(t)) continue;
      const r = btn.getBoundingClientRect();
      const style = root.defaultView ? root.defaultView.getComputedStyle(btn) : null;
      const visible = isVisibleButton(btn);
      const bind = bindPlayerName(btn);
      const attached = !!(btn.isConnected);
      let covered = false;
      try {
        if (root.elementFromPoint && visible) {
          const cx = r.left + r.width / 2;
          const cy = r.top + r.height / 2;
          const topEl = root.elementFromPoint(cx, cy);
          covered = topEl && topEl !== btn && !btn.contains(topEl);
        }
      } catch (e) {}
      out.push({
        global_index: globalIndex,
        frameIndex,
        frameUrl: frameUrl.slice(0, 220),
        index_in_frame: indexInFrame,
        player_name: bind.player_name || '',
        binding_confidence: bind.confidence,
        binding_via: bind.binding_via || '',
        candidate_names: bind.names || [],
        container_depth: bind.container_depth,
        container_sample: bind.container_sample || '',
        button_text: t,
        disabled: !!btn.disabled,
        aria_label: String(btn.getAttribute('aria-label')||'').slice(0, 120),
        dom_path: domPath(btn, 10),
        bounding_box: { x: r.x, y: r.y, width: r.width, height: r.height },
        attached_to_dom: attached,
        visible,
        enabled: !btn.disabled,
        possibly_covered: covered,
        dom_generation_ts: Date.now(),
      });
      globalIndex += 1;
      indexInFrame += 1;
    }
    frameIndex += 1;
  }
  return out;
}"""


def _compile_deliver_bound_click_js() -> str:
    start = _DISCOVER_BOUND_CONTROLS_JS.index("  function roots()")
    end = _DISCOVER_BOUND_CONTROLS_JS.index("  function domPath")
    helpers = _DISCOVER_BOUND_CONTROLS_JS[start:end]
    return (
        "({ frameIndex, playerName, indexInFrame }) => {\n"
        + helpers
        + """
  function addQueueButtons(root) {
    const out = [];
    for (const btn of root.querySelectorAll('button')) {
      const t = String(btn.innerText||'').replace(/\\s+/g,' ').trim();
      if (/Add to Queue/i.test(t)) out.push(btn);
    }
    return out;
  }
  const root = roots()[frameIndex];
  if (!root) return { ok: false, reason: 'frame_missing' };
  const want = String(playerName||'').trim().toLowerCase();
  if (!want) return { ok: false, reason: 'missing_player_name' };
  const buttons = addQueueButtons(root);
  let target = null;
  const idx = Number(indexInFrame);
  if (Number.isFinite(idx) && idx >= 0 && idx < buttons.length) {
    const bindAt = bindPlayerName(buttons[idx]);
    if (bindAt.confidence === 'unique' && String(bindAt.player_name||'').toLowerCase() === want) {
      target = buttons[idx];
    }
  }
  if (!target) {
    for (const btn of buttons) {
      if (!isVisibleButton(btn)) continue;
      const bind = bindPlayerName(btn);
      if (bind.confidence === 'unique' && String(bind.player_name||'').toLowerCase() === want) {
        target = btn;
        break;
      }
    }
  }
  if (!target) return { ok: false, reason: 'no_matching_bound_button' };
  target.scrollIntoView({ block: 'center', inline: 'nearest' });
  target.click();
  const bound = bindPlayerName(target);
  return {
    ok: true,
    method: 'js_bind_player_name_exact',
    bound_name: bound.player_name || '',
    binding_via: bound.binding_via || '',
  };
}"""
    )


_DELIVER_BOUND_CLICK_JS = _compile_deliver_bound_click_js()


def discover_bound_add_to_queue_controls(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_DISCOVER_BOUND_CONTROLS_JS) or []
        return [x for x in raw if isinstance(x, dict)]
    except Exception as exc:
        return [{"error": str(exc)[:200]}]


_REJECT_PLAYER_NAME = re.compile(
    r"^(Why Recommended|Draft Player|Draft|Queued|Available Players|Watchlist|Recommendations|On Clock|"
    r"keyboard_arrow|Clear Draft Queue|Draft Queue|Empty|Tracked players)",
    re.I,
)


def is_valid_seed_player_name(name: str) -> bool:
    n = str(name or "").strip()
    if not n or _REJECT_PLAYER_NAME.match(n):
        return False
    return bool(_NAME_TWO.match(n) or _NAME_ONLY.match(n))


def select_next_seed_candidate(
    candidates: list[dict[str, Any]],
    *,
    exclude_player_names: set[str],
    exclude_global_indices: set[int] | None = None,
    preferred_player_name: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Pick next uniquely-bound player not yet queued. Returns (candidate, reject_reason)."""
    exclude_global_indices = exclude_global_indices or set()
    viable: list[dict[str, Any]] = []
    for c in candidates:
        if c.get("error"):
            continue
        if c.get("visible") is False:
            continue
        conf = str(c.get("binding_confidence") or "")
        name = str(c.get("player_name") or "").strip()
        gi = int(c.get("global_index") if c.get("global_index") is not None else -1)
        if gi in exclude_global_indices:
            continue
        if conf == BINDING_AMBIGUOUS:
            continue
        if conf != BINDING_UNIQUE or not name or not is_valid_seed_player_name(name):
            continue
        if name.lower() in {n.lower() for n in exclude_player_names}:
            continue
        viable.append(c)
    if not viable:
        ambiguous = [c for c in candidates if c.get("binding_confidence") == BINDING_AMBIGUOUS]
        if ambiguous:
            return None, "ambiguous_binding"
        unnamed = [c for c in candidates if c.get("binding_confidence") == BINDING_MISSING]
        if unnamed and not viable:
            return None, "missing_binding"
        return None, "no_viable_candidate"
    want = str(preferred_player_name or "").strip().lower()
    if want:
        for c in viable:
            if str(c.get("player_name") or "").strip().lower() == want:
                return c, ""
        return None, "preferred_player_not_found"
    viable.sort(key=lambda x: int(x.get("global_index") or 0))
    return viable[0], ""


def _frame_for_index(page, frame_index: int, frame_url: str = ""):
    from run_production_stage1_authenticated import _streamlit_app_frame

    url_hint = str(frame_url or "").strip()
    if url_hint:
        for frame in page.frames:
            fu = str(frame.url or "")
            if fu and (fu == url_hint or url_hint in fu or fu in url_hint):
                return frame
    app = _streamlit_app_frame(page)
    if app and app.url and ("/~/" in app.url or "~/+" in app.url):
        return app
    try:
        frames = page.frames
        if 0 <= frame_index < len(frames):
            return frames[frame_index]
    except (TypeError, ValueError):
        pass
    return app or page.main_frame


def scrape_click_transport_evidence(page, *, click_ts: float, pre_script_run_seq: str = "") -> dict[str, Any]:
    try:
        from stage1_native_widget_transport import scrape_native_widget_transport_evidence

        return scrape_native_widget_transport_evidence(
            page, click_ts=click_ts, pre_script_run_seq=pre_script_run_seq
        )
    except ImportError:
        pass
    try:
        from p8_proven_start_delivery import aggregate_ws_boundary_log

        raw_log = aggregate_ws_boundary_log(page)
        outbound = [e for e in raw_log if isinstance(e, dict) and e.get("direction") == "outbound"]
        after = [e for e in outbound if float(e.get("wall_ts_ms") or 0) >= (click_ts * 1000.0 - 50.0)]
        backmsg_sent = False
        for entry in after[:16]:
            hint = str(entry.get("frame_type_hint") or "").lower()
            if hint == "widget_state_backmsg_hint" or entry.get("widget_key_bytes_present"):
                backmsg_sent = True
        return {
            "outbound_frames_after_click": len(after),
            "streamlit_backmsg_sent": backmsg_sent,
            "python_rerun_started": False,
            "native_widget_event_observed": backmsg_sent,
            "ws_log_sample": after[:5],
        }
    except Exception as exc:
        return {"error": str(exc)[:160]}


def scrape_streamlit_identity(page) -> dict[str, Any]:
    try:
        return (
            page.evaluate(
                """() => {
                  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r; }
                  for (const root of roots()) {
                    const el = root.querySelector('[data-testid="stApp"], [data-testid="stToolbar"]');
                    if (!el) continue;
                    const run = root.querySelector('[data-testid="stStatusWidget"]');
                    return {
                      frame_href: (root.defaultView && root.defaultView.location && root.defaultView.location.href) || '',
                      app_present: !!root.querySelector('[data-testid="stApp"]'),
                    };
                  }
                  return { frame_href: '', app_present: false };
                }"""
            )
            or {}
        )
    except Exception as exc:
        return {"error": str(exc)[:120]}


def deliver_add_to_queue_click(
    page,
    candidate: dict[str, Any],
    *,
    playwright_only: bool = False,
) -> dict[str, Any]:
    """Delivery hierarchy: scroll → stable visible → Playwright click → optional JS fallback."""
    name = str(candidate.get("player_name") or "").strip()
    frame_index = int(candidate.get("frameIndex") or 0)
    out: dict[str, Any] = {
        "player_name": name,
        "click_dispatched": False,
        "delivery_method": "",
        "binding_method": str(candidate.get("binding_via") or ""),
        "button_text": str(candidate.get("button_text") or ""),
        "button_help": str(candidate.get("aria_label") or ""),
        "bounding_box": dict(candidate.get("bounding_box") or {}),
        "frame_index": frame_index,
        "playwright_only": playwright_only,
        "pre_click_diagnostics": dict(candidate),
        "streamlit_identity_before": scrape_streamlit_identity(page),
    }
    if not name:
        out["classification"] = "QUEUE1B"
        out["error"] = "click_blocked_missing_player_binding"
        return out
    if str(candidate.get("binding_confidence") or "") != BINDING_UNIQUE:
        out["classification"] = "QUEUE1B"
        out["error"] = "click_blocked_non_unique_binding"
        return out

    frame = _frame_for_index(page, frame_index, str(candidate.get("frameUrl") or ""))
    out["playwright_frame_url"] = str(frame.url or "")[:220]
    escaped = re.escape(name)
    pw_error = ""
    index_in_frame = int(candidate.get("index_in_frame") if candidate.get("index_in_frame") is not None else -1)
    pw_timeout = 5000

    def _ledger_seq() -> str:
        try:
            from p8_production_start_harness import scrape_stage1_ledger_rows

            rows = scrape_stage1_ledger_rows(page) or []
            if rows:
                return str(rows[-1].get("script_run_seq") or "")
        except Exception:
            pass
        return ""

    def _finish_playwright_click(method: str, *, pre_seq: str = "", dom_inspection: dict | None = None) -> dict[str, Any]:
        out["click_end_ts"] = time.time()
        out["streamlit_identity_after"] = scrape_streamlit_identity(page)
        out["post_click_transport"] = scrape_click_transport_evidence(
            page, click_ts=float(out.get("click_start_ts") or out["click_end_ts"]), pre_script_run_seq=pre_seq
        )
        if dom_inspection:
            out["pre_click_dom_inspection"] = dom_inspection
        out["click_dispatched"] = True
        out["delivery_method"] = method
        return out

    pre_seq = _ledger_seq()
    try:
        from stage1_rec_card_dom_inspection import inspect_rec_card_add_to_queue_dom

        dom_inspection = inspect_rec_card_add_to_queue_dom(
            page, player_name=name, frame_url=str(candidate.get("frameUrl") or "")
        )
        out["pre_click_dom_inspection"] = dom_inspection
    except ImportError:
        dom_inspection = {}

    try:
        meta = frame.locator(".ld-rec-card-meta").filter(has_text=re.compile(escaped, re.I)).first
        card_scope = meta.locator("xpath=ancestor::div[@data-testid='stVerticalBlock'][1]")
        st_btn = card_scope.locator('[data-testid="stButton"]').filter(has_text=re.compile(r"Add to Queue", re.I)).first
        btn = st_btn.locator('button[data-testid="stBaseButton-secondary"]').first
        btn.wait_for(state="attached", timeout=pw_timeout)
        btn.wait_for(state="visible", timeout=pw_timeout)
        if not btn.is_enabled():
            out["error"] = "button_not_enabled"
            out["classification"] = "QUEUE1C1"
            return out
        out["click_start_ts"] = time.time()
        btn.scroll_into_view_if_needed(timeout=pw_timeout)
        page.wait_for_timeout(350)
        btn.click(timeout=pw_timeout)
        return _finish_playwright_click(
            "playwright_ld_rec_card_meta_native_stbutton",
            pre_seq=pre_seq,
            dom_inspection=dom_inspection if isinstance(dom_inspection, dict) else None,
        )
    except Exception as exc:
        pw_error = str(exc)[:240]

    try:
        meta = frame.locator(".ld-rec-card-meta").filter(has_text=re.compile(escaped, re.I)).first
        card_scope = meta.locator("xpath=ancestor::div[@data-testid='stVerticalBlock'][1]")
        btn = card_scope.locator("button").filter(has_text=re.compile(r"Add to Queue", re.I)).first
        btn.wait_for(state="attached", timeout=pw_timeout)
        btn.wait_for(state="visible", timeout=pw_timeout)
        if not btn.is_enabled():
            out["error"] = "button_not_enabled"
            out["classification"] = "QUEUE1C1"
            return out
        out["click_start_ts"] = time.time()
        btn.scroll_into_view_if_needed(timeout=pw_timeout)
        page.wait_for_timeout(350)
        btn.click(timeout=pw_timeout)
        return _finish_playwright_click("playwright_ld_rec_card_meta_scope", pre_seq=pre_seq)
    except Exception as exc:
        pw_error = str(exc)[:240]

    try:
        buttons = frame.locator("button").filter(has_text=re.compile(r"Add to Queue", re.I))
        if 0 <= index_in_frame < buttons.count():
            btn = buttons.nth(index_in_frame)
            btn.wait_for(state="attached", timeout=pw_timeout)
            btn.wait_for(state="visible", timeout=pw_timeout)
            if not btn.is_enabled():
                out["error"] = "button_not_enabled"
                out["classification"] = "QUEUE1C1"
                return out
            out["click_start_ts"] = time.time()
            btn.scroll_into_view_if_needed(timeout=pw_timeout)
            page.wait_for_timeout(350)
            btn.click(timeout=pw_timeout)
            return _finish_playwright_click("playwright_index_in_frame_after_bind")
    except Exception as exc:
        pw_error = str(exc)[:240]

    try:
        row = frame.locator('[data-testid="stHorizontalBlock"]').filter(has_text=re.compile(escaped, re.I))
        btn = row.locator("button").filter(has_text=re.compile(r"Add to Queue", re.I)).first
        btn.wait_for(state="attached", timeout=pw_timeout)
        btn.wait_for(state="visible", timeout=pw_timeout)
        if not btn.is_enabled():
            out["error"] = "button_not_enabled"
            out["classification"] = "QUEUE1C1"
            return out
        out["click_start_ts"] = time.time()
        btn.scroll_into_view_if_needed(timeout=pw_timeout)
        page.wait_for_timeout(350)
        btn.click(timeout=pw_timeout)
        return _finish_playwright_click("playwright_stHorizontalBlock_player_row")
    except Exception as exc:
        pw_error = str(exc)[:240]

    bbox = candidate.get("bounding_box") or {}
    try:
        if float(bbox.get("width") or 0) >= 10 and float(bbox.get("height") or 0) >= 10:
            buttons = frame.locator("button").filter(has_text=re.compile(r"Add to Queue", re.I))
            if 0 <= index_in_frame < buttons.count():
                btn = buttons.nth(index_in_frame)
                out["click_start_ts"] = time.time()
                btn.scroll_into_view_if_needed(timeout=pw_timeout)
                btn.click(timeout=pw_timeout, force=True)
                return _finish_playwright_click("playwright_force_index_in_frame")
    except Exception as exc:
        pw_error = str(exc)[:240]

    if playwright_only:
        out["error"] = pw_error or "playwright_only_no_dispatch"
        out["classification"] = "QUEUE1C1"
        out["js_skipped"] = True
        return out

    try:
        js = page.evaluate(
            _DELIVER_BOUND_CLICK_JS,
            {
                "frameIndex": frame_index,
                "playerName": name,
                "indexInFrame": index_in_frame,
            },
        )
        if isinstance(js, dict) and js.get("ok"):
            out["click_start_ts"] = time.time()
            out["click_end_ts"] = time.time()
            out["click_dispatched"] = True
            out["delivery_method"] = str(js.get("method") or "js_bound_exact_element")
            out["js_delivery"] = js
            out["post_click_transport"] = scrape_click_transport_evidence(page, click_ts=float(out["click_end_ts"]))
            out["streamlit_identity_after"] = scrape_streamlit_identity(page)
            return out
        out["js_delivery"] = js
    except Exception as exc:
        out["js_error"] = str(exc)[:200]

    out["error"] = pw_error or "delivery_failed"
    out["classification"] = "QUEUE1C"
    return out
