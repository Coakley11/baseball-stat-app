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
        if is_recommendation_badge_label(name) or not is_valid_seed_player_name(name):
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
  function isRecBadgeLabel(name) {
    const n = String(name || '').trim();
    if (!n) return true;
    // Known recommendation badge/chip labels (live_draft_rec_badges.py) that match
    // the two-word name heuristic and must never become seed player identity.
    if (/^(Why Recommended|Draft Player|Draft|Queued|Available Players|Watchlist|Recommendations|On Clock|keyboard_arrow|Clear Draft Queue|Draft Queue|Empty|Tracked players)$/i.test(n)) return true;
    if (/^(Best Value|Best Overall|Second Best|Third Best|Market Discount|ADP Bargain|Scarcity Rising|Power Upgrade|Speed Upgrade|Average Stabilizer|Run Production Boost|Runs Boost|On-Base Boost|Contact Boost)$/i.test(n)) return true;
    if (/^Best Remaining\\s+\\S+/i.test(n)) return true;
    if (/^Fills\\s+\\d+\\s+OF\\s+Slots$/i.test(n)) return true;
    if (/^Fills\\s+\\S+\\s+Slot$/i.test(n)) return true;
    if (/\\bScarcity Rising$/i.test(n)) return true;
    if (/^Category Boost:/i.test(n)) return true;
    return false;
  }
  function extractNames(lines) {
    const names = [];
    const seen = new Set();
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
      if (isRecBadgeLabel(name)) continue;
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
        const attrPid = String(meta.getAttribute('data-player-id') || '').trim();
        const attrName = String(meta.getAttribute('data-player-name') || '').trim();
        const nameEl = meta.querySelector('div');
        const raw = attrName || (nameEl ? String(nameEl.innerText || '').trim() : String(meta.innerText || '').split('\\n')[0].trim());
        const names = extractNames([raw]);
        if (names.length === 1) {
          const out = {
            confidence: 'unique',
            player_name: names[0],
            names,
            container_depth: depth,
            container_sample: raw.slice(0, 280),
            binding_via: 'ld_rec_card_meta',
          };
          if (/^\\d+$/.test(attrPid)) {
            out.player_id = attrPid;
            out.structured_identity_source = 'ld_rec_card_meta';
          }
          return out;
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
      const row = {
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
      };
      if (bind.player_id) {
        row.player_id = String(bind.player_id);
      }
      if (bind.structured_identity_source) {
        row.structured_identity_source = String(bind.structured_identity_source);
      }
      out.push(row);
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

# Badge / chip labels from live_draft_rec_badges.py that match the two-word name heuristic.
REC_SEED_BADGE_LABELS = frozenset(
    {
        "best value",
        "best overall",
        "second best",
        "third best",
        "market discount",
        "adp bargain",
        "scarcity rising",
        "power upgrade",
        "speed upgrade",
        "average stabilizer",
        "run production boost",
        "runs boost",
        "on-base boost",
        "contact boost",
    }
)

_REC_BADGE_DYNAMIC_RE = (
    re.compile(r"^best remaining\s+\S+", re.I),
    re.compile(r"^fills\s+\d+\s+of\s+slots$", re.I),
    re.compile(r"^fills\s+\S+\s+slot$", re.I),
    re.compile(r"\bscarcity rising$", re.I),
    re.compile(r"^category boost:", re.I),
)

# Binding vias that may authorize a deliberate seed once player_id is also present.
STRUCTURED_SEED_BINDING_VIAS = frozenset(
    {
        "ld_rec_card_meta",
        "button_help_title",
        "stButton_help_title",
        "render_trace",
    }
)

# Visible-text / shallow-ancestor vias: observability only — never sufficient alone for seed delivery.
VISIBLE_TEXT_ONLY_SEED_BINDING_VIAS = frozenset(
    {
        "single_visible_add_ancestor",
        "ancestor_walk",
        "row_text_before_add_button",
        "stColumn_left",
        "horizontal_previous_column",
        "horizontal_column",
        "previous_sibling_block",
        "ld_rec_card_header",
    }
)


def is_recommendation_badge_label(name: str) -> bool:
    """True when text is a recommendation badge/chip, not a player identity."""
    n = str(name or "").strip()
    if not n:
        return True
    if n.lower() in REC_SEED_BADGE_LABELS:
        return True
    return any(pat.search(n) for pat in _REC_BADGE_DYNAMIC_RE)


def is_valid_seed_player_name(name: str) -> bool:
    n = str(name or "").strip()
    if not n or _REJECT_PLAYER_NAME.match(n) or is_recommendation_badge_label(n):
        return False
    return bool(_NAME_TWO.match(n) or _NAME_ONLY.match(n))


def _seed_player_id(value: Any) -> str:
    pid = str(value or "").strip()
    return pid if pid.isdigit() else ""


def has_structured_seed_identity(candidate: dict[str, Any] | None) -> bool:
    """Deliberate seed delivery requires real player_name + player_id from structured authority.

    Visible-text-only bindings (e.g. single_visible_add_ancestor) never authorize alone.
    Render-trace enrichment that attaches player_id counts as structured authority.
    """
    c = dict(candidate or {})
    name = str(c.get("player_name") or "").strip()
    if not is_valid_seed_player_name(name):
        return False
    pid = _seed_player_id(c.get("player_id"))
    if not pid:
        return False
    via = str(c.get("binding_via") or "").strip()
    source = str(c.get("structured_identity_source") or "").strip().lower()
    if via in VISIBLE_TEXT_ONLY_SEED_BINDING_VIAS and "render_trace" not in source and via not in STRUCTURED_SEED_BINDING_VIAS:
        # Shallow/visible-text binding is ineligible unless render-trace enrichment supplied player_id.
        if "render_trace" not in source:
            return False
    if via in STRUCTURED_SEED_BINDING_VIAS:
        return True
    if "render_trace" in source or source in {"ld_rec_card_meta", "ld_rec_card_meta+render_trace"}:
        return True
    if via in VISIBLE_TEXT_ONLY_SEED_BINDING_VIAS:
        return False
    # Unknown via: still require player_id (already checked) and treat as structured if marked.
    return bool(source)


def enrich_seed_candidates_from_render_traces(
    candidates: list[dict[str, Any]],
    traces: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Attach player_id / widget_key from render-trace rows matched by player_name."""
    by_name: dict[str, dict[str, Any]] = {}
    for raw in traces or []:
        if not isinstance(raw, dict) or raw.get("error"):
            continue
        key = str(raw.get("player_name") or "").strip().lower()
        if not key:
            continue
        by_name[key] = raw
    out: list[dict[str, Any]] = []
    for cand in candidates:
        c = dict(cand)
        name_key = str(c.get("player_name") or "").strip().lower()
        trace = by_name.get(name_key)
        if trace:
            tid = _seed_player_id(trace.get("player_id"))
            if tid:
                c["player_id"] = tid
            wk = str(trace.get("widget_key") or "").strip()
            if wk:
                c["widget_key"] = wk
            via = str(c.get("binding_via") or "").strip()
            if via == "ld_rec_card_meta":
                c["structured_identity_source"] = "ld_rec_card_meta+render_trace"
            else:
                c["structured_identity_source"] = "render_trace"
            c["render_trace_player_name"] = str(trace.get("player_name") or "")
            c["render_trace_player_id"] = str(trace.get("player_id") or "")
        out.append(c)
    return out


def select_next_seed_candidate(
    candidates: list[dict[str, Any]],
    *,
    exclude_player_names: set[str],
    exclude_global_indices: set[int] | None = None,
    preferred_player_name: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Pick next uniquely-bound structured player not yet queued.

    Rejects badge labels and visible-text-only identities that lack player_id /
    structured card/render-trace authority. Returns (candidate, reject_reason).
    """
    exclude_global_indices = exclude_global_indices or set()
    viable: list[dict[str, Any]] = []
    saw_unique_name = False
    saw_structured_gap = False
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
        saw_unique_name = True
        if not has_structured_seed_identity(c):
            saw_structured_gap = True
            continue
        viable.append(c)
    if not viable:
        ambiguous = [c for c in candidates if c.get("binding_confidence") == BINDING_AMBIGUOUS]
        if ambiguous and not saw_unique_name:
            return None, "ambiguous_binding"
        unnamed = [c for c in candidates if c.get("binding_confidence") == BINDING_MISSING]
        if unnamed and not saw_unique_name:
            return None, "missing_binding"
        if saw_structured_gap:
            return None, "missing_structured_identity"
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


def scrape_click_transport_evidence(
    page,
    *,
    click_ts: float,
    pre_script_run_seq: str = "",
    pre_run_binding: dict[str, Any] | None = None,
    frame_url_hint: str = "",
) -> dict[str, Any]:
    try:
        from stage1_native_widget_transport import scrape_native_widget_transport_evidence

        return scrape_native_widget_transport_evidence(
            page,
            click_ts=click_ts,
            pre_script_run_seq=pre_script_run_seq,
            pre_run_binding=pre_run_binding,
            frame_url_hint=frame_url_hint,
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
    authorized_rec_card_key: str = "",
) -> dict[str, Any]:
    """Delivery hierarchy: scroll → stable visible → Playwright click → optional JS fallback.

    ``click_dispatched`` means Playwright completed a browser click only.
    When ``authorized_rec_card_key`` is provided, post-click consumption ack correlates
    Streamlit traffic to that exact Stage-A button key (never treats dispatch as callback).
    """
    name = str(candidate.get("player_name") or "").strip()
    frame_index = int(candidate.get("frameIndex") or 0)
    expected_key = str(authorized_rec_card_key or candidate.get("widget_key") or "").strip()
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
        "authorized_rec_card_key": expected_key,
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
            from stage1_run_binding import capture_run_binding_snapshot

            from stage1_run_binding import BINDING_MODE_RECOMMENDATION_WIDGET

            snap = capture_run_binding_snapshot(
                page,
                frame_url_hint=str(candidate.get("frameUrl") or ""),
                lifecycle_render_trace=None,
                phase="pre_click",
                binding_mode=BINDING_MODE_RECOMMENDATION_WIDGET,
            )
            grade = snap.get("ledger_transport_grade_script_run_seq")
            return str(grade) if grade is not None else ""
        except ImportError:
            pass
        try:
            from p8_production_start_harness import scrape_stage1_ledger_rows

            rows = scrape_stage1_ledger_rows(page) or []
            if rows:
                return str(rows[-1].get("script_run_seq") or "")
        except Exception:
            pass
        return ""

    def _finish_playwright_click(
        method: str,
        *,
        pre_seq: str = "",
        pre_binding: dict | None = None,
        dom_inspection: dict | None = None,
        click_frame=None,
    ) -> dict[str, Any]:
        out["click_end_ts"] = time.time()
        out["streamlit_identity_after"] = scrape_streamlit_identity(page)
        dom_events: list[dict[str, Any]] = []
        dom_summary: dict[str, Any] = {}
        try:
            from stage1_dom_click_capture import (
                CAPTURE_TARGET_FRANCISCO_ADD,
                read_and_summarize_dom_click_capture,
                read_dom_click_capture_from_frame,
                read_dom_click_capture_log,
            )

            if click_frame is not None:
                dom_summary = read_and_summarize_dom_click_capture(
                    click_frame,
                    capture_target=CAPTURE_TARGET_FRANCISCO_ADD,
                )
                dom_events = list(dom_summary.get("browser_dom_click_events") or [])
            if not dom_events:
                dom_events = read_dom_click_capture_log(page)
                if dom_events:
                    dom_summary = read_and_summarize_dom_click_capture(
                        click_frame or page.main_frame,
                        capture_target=CAPTURE_TARGET_FRANCISCO_ADD,
                    )
        except ImportError:
            pass
        out["dom_click_capture"] = dom_summary
        out["browser_dom_click_events"] = dom_events
        out["trusted_dom_click"] = bool(dom_summary.get("trusted_dom_click"))
        install_meta = out.get("dom_click_capture_install") if isinstance(out.get("dom_click_capture_install"), dict) else {}
        if install_meta.get("ok") and not dom_events:
            out["dom_capture_observability_failed"] = True
        out["post_click_transport"] = scrape_click_transport_evidence(
            page,
            click_ts=float(out.get("click_start_ts") or out["click_end_ts"]),
            pre_script_run_seq=pre_seq,
            pre_run_binding=pre_binding if isinstance(pre_binding, dict) else None,
            frame_url_hint=str(candidate.get("frameUrl") or ""),
        )
        if out.get("dom_capture_observability_failed"):
            out["post_click_transport"]["dom_capture_observability_failed"] = True
        if dom_inspection:
            out["pre_click_dom_inspection"] = dom_inspection
        out["click_dispatched"] = True
        out["delivery_method"] = method
        try:
            from stage1_francisco_native_click_consumption import (
                evaluate_francisco_native_click_consumption_ack,
            )

            out["consumption_ack"] = evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=expected_key,
                post_click_transport=out.get("post_click_transport")
                if isinstance(out.get("post_click_transport"), dict)
                else {},
                callback_entered_observed=False,
                trusted_dom_click=bool(out.get("trusted_dom_click")),
            )
        except ImportError:
            out["consumption_ack"] = {
                "click_dispatched": True,
                "francisco_widget_consumption_ack": False,
                "click_dispatch_alone_proves_callback": False,
                "click_dispatch_alone_proves_mutation": False,
                "classification": "FRANCISCO_NATIVE_CLICK_DISPATCHED_WITHOUT_WIDGET_ACK",
            }
        return out

    pre_seq = _ledger_seq()
    pre_binding: dict[str, Any] = {}
    try:
        from stage1_rec_queue_click_trace_scrape import scrape_rec_queue_render_trace
        from stage1_run_binding import capture_run_binding_snapshot

        render_trace = scrape_rec_queue_render_trace(page, player_name=name)
        from stage1_run_binding import BINDING_MODE_RECOMMENDATION_WIDGET

        pre_binding = capture_run_binding_snapshot(
            page,
            frame_url_hint=str(candidate.get("frameUrl") or ""),
            lifecycle_render_trace=render_trace,
            phase="pre_click",
            binding_mode=BINDING_MODE_RECOMMENDATION_WIDGET,
            expected_room_id=str(render_trace.get("room_id") or ""),
        )
        out["pre_click_run_binding"] = pre_binding
    except ImportError:
        render_trace = {}
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
        # Live reacquisition: bind metadata → real st.button immediately before the one click.
        if expected_key:
            try:
                probe_key = frame.evaluate(
                    """(args) => {
                      const name = String(args.playerName || '');
                      const want = String(args.widgetKey || '');
                      const esc = name.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
                      const re = new RegExp(esc, 'i');
                      const metas = Array.from(document.querySelectorAll('.ld-rec-card-meta'))
                        .filter((m) => re.test(String(m.innerText || '')));
                      if (!metas.length) return { found: false };
                      const scope = metas[0].closest('[data-testid=\"stVerticalBlock\"]') || metas[0].parentElement;
                      if (!scope) return { found: false };
                      const probe = scope.querySelector('.rec-fragment-exec-probe-card[data-widget-key]');
                      const got = probe ? String(probe.getAttribute('data-widget-key') || '') : '';
                      const native = scope.querySelector(
                        '[data-testid=\"stButton\"] button[data-testid=\"stBaseButton-secondary\"]'
                      );
                      return {
                        found: true,
                        probe_widget_key: got,
                        probe_present: !!probe,
                        native_st_button_present: !!native,
                        key_match: !want || !got || got === want,
                      };
                    }""",
                    {"playerName": name, "widgetKey": expected_key},
                )
                out["live_reacquisition_probe"] = probe_key if isinstance(probe_key, dict) else {}
                probe_row = out["live_reacquisition_probe"]
                if (
                    isinstance(probe_row, dict)
                    and probe_row.get("probe_present")
                    and probe_row.get("key_match") is False
                ):
                    out["error"] = "live_exec_probe_widget_key_mismatch"
                    out["classification"] = "QUEUE1C1"
                    out["click_dispatched"] = False
                    return out
                if isinstance(probe_row, dict) and probe_row.get("native_st_button_present") is False:
                    out["error"] = "live_native_st_button_missing_after_reacquire"
                    out["classification"] = "QUEUE1C1"
                    out["click_dispatched"] = False
                    return out
            except Exception as probe_exc:
                out["live_reacquisition_probe_error"] = str(probe_exc)[:160]
        st_btn = card_scope.locator('[data-testid="stButton"]').filter(has_text=re.compile(r"Add to Queue", re.I)).first
        btn = st_btn.locator('button[data-testid="stBaseButton-secondary"]').first
        btn.wait_for(state="attached", timeout=pw_timeout)
        btn.wait_for(state="visible", timeout=pw_timeout)
        if not btn.is_enabled():
            out["error"] = "button_not_enabled"
            out["classification"] = "QUEUE1C1"
            return out
        out["click_start_ts"] = time.time()
        out["live_reacquired_before_click"] = True
        btn.scroll_into_view_if_needed(timeout=pw_timeout)
        page.wait_for_timeout(350)
        try:
            from stage1_dom_click_capture import CAPTURE_TARGET_FRANCISCO_ADD, prepare_isolated_dom_click_capture

            dom_gen = str(candidate.get("dom_generation_ts") or "")
            prep = prepare_isolated_dom_click_capture(
                frame,
                capture_target=CAPTURE_TARGET_FRANCISCO_ADD,
                frame_url_hint=str(frame.url or candidate.get("frameUrl") or ""),
                player_name=name,
                dom_generation_ts=dom_gen,
            )
            out["dom_click_capture_prep"] = prep
            out["dom_click_capture_install"] = prep.get("dom_click_capture_install") or {}
            install_href = str(out["dom_click_capture_install"].get("frame_href") or "")
            target_href = str(frame.url or "")
            if install_href and target_href and install_href.split("?")[0] not in target_href and target_href.split("?")[0] not in install_href:
                out["dom_click_capture_install"]["frame_url_mismatch"] = True
        except ImportError:
            pass
        btn.click(timeout=pw_timeout)
        return _finish_playwright_click(
            "playwright_ld_rec_card_meta_native_stbutton",
            pre_seq=pre_seq,
            pre_binding=pre_binding,
            dom_inspection=dom_inspection if isinstance(dom_inspection, dict) else None,
            click_frame=frame,
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
