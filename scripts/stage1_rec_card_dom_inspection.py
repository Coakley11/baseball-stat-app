"""DOM inspection for recommendation-card Add-to-Queue native Streamlit button targets."""

from __future__ import annotations

import re
from typing import Any


_INSPECT_DOM_JS = r"""
(args) => {
  const playerName = String(args.playerName || '').trim();
  const frameUrlHint = String(args.frameUrl || '').trim();
  function roots() {
    const r = [document];
    for (const f of document.querySelectorAll('iframe')) {
      try { if (f.contentDocument) r.push(f.contentDocument); } catch (e) {}
    }
    return r.filter(Boolean);
  }
  function domPath(el, maxDepth) {
    const parts = [];
    let n = el;
    for (let i = 0; i < (maxDepth || 12) && n; i++) {
      let seg = (n.tagName || '').toLowerCase();
      const tid = n.getAttribute && n.getAttribute('data-testid');
      if (tid) seg += '[data-testid=' + tid + ']';
      parts.unshift(seg);
      n = n.parentElement;
    }
    return parts.join('>');
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const st = el.ownerDocument.defaultView.getComputedStyle(el);
    return st && st.visibility !== 'hidden' && st.display !== 'none' && st.pointerEvents !== 'none';
  }
  function describeButton(btn) {
    const r = btn.getBoundingClientRect();
    const path = domPath(btn, 12);
    const inTooltip = !!(btn.closest('[data-testid="stTooltipIcon"], [data-testid="stTooltipHoverTarget"]'));
    const stButton = btn.closest('[data-testid="stButton"]');
    const testId = btn.getAttribute('data-testid') || '';
    return {
      tag: (btn.tagName || '').toLowerCase(),
      role: btn.getAttribute('role') || 'button',
      text: String(btn.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80),
      aria_label: String(btn.getAttribute('aria-label') || '').slice(0, 120),
      test_id: testId,
      dom_path: path,
      inside_st_tooltip: inTooltip,
      inside_st_button: !!stButton,
      is_st_base_button: testId === 'stBaseButton-secondary' || testId === 'stBaseButton-primary',
      click_non_native_element: (btn.tagName || '').toLowerCase() !== 'button',
      visible: isVisible(btn),
      bbox: { x: r.x, y: r.y, width: r.width, height: r.height },
    };
  }
  for (const root of roots()) {
    const href = (root.defaultView && root.defaultView.location && root.defaultView.location.href) || '';
    if (frameUrlHint && href && !href.includes(frameUrlHint.slice(0, 40)) && frameUrlHint.length > 20) {
      continue;
    }
    let meta = null;
    if (playerName) {
      const metas = Array.from(root.querySelectorAll('.ld-rec-card-meta')).filter((m) =>
        new RegExp(playerName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(String(m.innerText || ''))
      );
      if (metas.length) meta = metas[0];
    }
    if (!meta) continue;
    const cardScope = meta.closest('[data-testid="stVerticalBlock"]') || meta.parentElement;
    const stButtons = cardScope ? Array.from(cardScope.querySelectorAll('[data-testid="stButton"]')) : [];
    const addStButtons = stButtons.filter((sb) => /Add to Queue/i.test(String(sb.innerText || '')));
    const allButtons = cardScope ? Array.from(cardScope.querySelectorAll('button')).filter((b) =>
      /Add to Queue/i.test(String(b.innerText || ''))
    ) : [];
    const visibleButtons = allButtons.filter(isVisible);
    const nativeCandidates = visibleButtons.filter((b) => {
      const tid = b.getAttribute('data-testid') || '';
      return tid === 'stBaseButton-secondary' || tid === 'stBaseButton-primary';
    });
    const primaryNative = nativeCandidates.find((b) => !b.closest('[data-testid="stTooltipHoverTarget"]'))
      || nativeCandidates[0]
      || visibleButtons[0]
      || null;
    return {
      frame_url: href.slice(0, 220),
      player_name: playerName,
      ld_rec_card_meta_found: true,
      st_button_wrapper_count: addStButtons.length,
      button_count_in_card: allButtons.length,
      visible_button_count_in_card: visibleButtons.length,
      native_st_base_button_count: nativeCandidates.length,
      recommended_click: primaryNative ? describeButton(primaryNative) : null,
      all_visible_buttons: visibleButtons.slice(0, 6).map(describeButton),
      playwright_legacy_path_note:
        'card_scope button filter may resolve first visible button; check inside_st_tooltip vs is_st_base_button',
    };
  }
  return { ld_rec_card_meta_found: false, player_name: playerName };
}
"""


def inspect_rec_card_add_to_queue_dom(page, *, player_name: str, frame_url: str = "") -> dict[str, Any]:
    try:
        raw = page.evaluate(_INSPECT_DOM_JS, {"playerName": player_name, "frameUrl": frame_url})
    except Exception as exc:
        return {"error": str(exc)[:200]}
    return dict(raw) if isinstance(raw, dict) else {}


def compare_control_button_dom(page, *, label_pattern: str) -> dict[str, Any]:
    """Snapshot Start/Pause-style native button structure for comparison."""
    try:
        raw = page.evaluate(
            """(pat) => {
              const re = new RegExp(pat, 'i');
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r; }
              function domPath(el) {
                const parts = []; let n = el;
                for (let i=0;i<10&&n;i++) {
                  let s=(n.tagName||'').toLowerCase();
                  const t=n.getAttribute&&n.getAttribute('data-testid');
                  if (t) s+='[data-testid='+t+']';
                  parts.unshift(s); n=n.parentElement;
                }
                return parts.join('>');
              }
              for (const root of roots()) {
                for (const btn of root.querySelectorAll('button')) {
                  const t=String(btn.innerText||'').trim();
                  if (!re.test(t)) continue;
                  const tid=btn.getAttribute('data-testid')||'';
                  return {
                    label: t.slice(0,60),
                    test_id: tid,
                    dom_path: domPath(btn),
                    inside_st_tooltip: !!(btn.closest('[data-testid="stTooltipIcon"]')),
                    inside_st_button: !!(btn.closest('[data-testid="stButton"]')),
                  };
                }
              }
              return {};
            }""",
            label_pattern,
        )
    except Exception as exc:
        return {"error": str(exc)[:160]}
    return dict(raw) if isinstance(raw, dict) else {}
