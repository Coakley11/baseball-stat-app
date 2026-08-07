"""Deterministic queue seeding with per-player mutation proof (Stage 1A-QUEUE harness)."""

from __future__ import annotations

import re
import time
from typing import Any

from stage1_queue_harness_flow import (
    build_queue_evidence_hierarchy,
    visible_queue_names_from_excerpt,
)

QUEUE_SEED_RESOLVED = "QUEUE_SEED_RESOLVED"

QUEUE1A = "QUEUE1A — surface activation accidentally mutated queue"
QUEUE1B = "QUEUE1B — candidate player/button association ambiguous"
QUEUE1C = "QUEUE1C — Add-to-Queue click produced no observable mutation"
QUEUE1D = "QUEUE1D — queue mutation visible but structured parser failed"
QUEUE1E = "QUEUE1E — fewer than required distinct players available/seeded"
QUEUE1F = "QUEUE1F — queue order cannot be established"
QUEUE1_8 = "QUEUE1_8 — another exact supported queue-seed boundary"

_SKIP_LINE = re.compile(
    r"^(Draft queue|Clear Draft Queue|Watchlist|Empty|Tracked players|Recently viewed|"
    r"Command Center|keyboard_arrow|solo-deploy|Stop$|Fork$|✕|×|Saved session|Recommendations)",
    re.I,
)
_NAME_ONLY = re.compile(r"^[A-Z][A-Za-z .'-]{2,48}$")


def parse_queue_players_from_block(text: str) -> list[dict[str, Any]]:
    """Parse name-only (and optional position) rows from Draft queue block text."""
    raw = str(text or "")
    if "Draft queue" in raw:
        m = re.search(r"Draft queue\s*(.*?)(?:Clear Draft Queue|$)", raw, re.I | re.S)
        block = m.group(1) if m else raw
    else:
        block = raw
    players: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in [ln.strip() for ln in block.splitlines() if ln.strip()]:
        if _SKIP_LINE.match(line):
            continue
        pos = re.match(
            r"^([A-Za-z][A-Za-z .'-]{2,60})\s+[—\-–]\s+(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)\b",
            line,
        )
        if pos:
            name = pos.group(1).strip()
        elif _NAME_ONLY.match(line):
            name = line.strip()
        else:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        players.append({"name": name, "slot": pos.group(2) if pos else ""})
    return players


def merge_queue_player_lists(*sources: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for src in sources:
        for p in src:
            name = str(p.get("name") if isinstance(p, dict) else p or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
    return out


def queue_names_from_state(container: dict[str, Any], excerpt: str = "") -> list[str]:
    structured = parse_queue_players_from_block(str(container.get("excerpt") or excerpt or ""))
    if not structured:
        structured = [{"name": p.get("name"), "slot": p.get("slot")} for p in list(container.get("players") or [])]
    visible = visible_queue_names_from_excerpt(excerpt or str(container.get("excerpt") or ""))
    return merge_queue_player_lists(structured, [{"name": n} for n in visible])


def classify_queue_seed_boundary(meta: dict[str, Any], *, min_players: int = 3) -> str:
    if meta.get("surface_activation_queue_mutation"):
        return QUEUE1A
    steps = list(meta.get("seed_steps") or [])
    if any(s.get("classification") == QUEUE1B for s in steps):
        return QUEUE1B
    if any(s.get("classification") == QUEUE1C for s in steps):
        return QUEUE1C
    proven = list(meta.get("proven_queue_order") or [])
    clicks = sum(1 for s in steps if s.get("click_dispatched"))
    if clicks >= min_players and len(proven) < min_players:
        if meta.get("harness_scraper_observation_gap"):
            return QUEUE1D
        return QUEUE1E
    if len(proven) >= min_players and not meta.get("queue_order_established"):
        return QUEUE1F
    if meta.get("classification") == QUEUE_SEED_RESOLVED:
        return QUEUE_SEED_RESOLVED
    return QUEUE1_8


def build_queue_seed_evidence(
    meta: dict[str, Any],
    *,
    min_players: int = 3,
) -> dict[str, Any]:
    """Require distinct player identities proven — not click count alone."""
    steps = list(meta.get("seed_steps") or [])
    proven_order: list[str] = []
    for step in steps:
        if step.get("mutation_proven") and step.get("player_name"):
            name = str(step["player_name"]).strip()
            if name.lower() not in {n.lower() for n in proven_order}:
                proven_order.append(name)
    container = meta.get("queue_container") if isinstance(meta.get("queue_container"), dict) else {}
    excerpt = str(container.get("excerpt") or meta.get("queue_excerpt_before") or "")
    structured_names = [
        str(p.get("name") or "")
        for p in parse_queue_players_from_block(excerpt)
        if str(p.get("name") or "").strip()
    ]
    visible = visible_queue_names_from_excerpt(excerpt)
    deliberate_clicks = sum(1 for s in steps if s.get("click_dispatched"))
    hierarchy = build_queue_evidence_hierarchy(meta, min_players=min_players)
    identity_count = len({n.lower() for n in proven_order if n})
    resolved = (
        deliberate_clicks >= min_players
        and identity_count >= min_players
        and len(proven_order) >= min_players
        and bool(meta.get("queue_order_established"))
        and bool(meta.get("pick_index_zero_after_setup", True))
        and bool(meta.get("paused_state_maintained", True))
    )
    scraper_gap = (
        identity_count >= min_players
        and len(visible) >= min_players
        and len(structured_names) < min_players
    )
    return {
        **hierarchy,
        "proven_queue_identities": proven_order[:8],
        "proven_identity_count": identity_count,
        "deliberate_add_click_count": deliberate_clicks,
        "visible_queue_player_names": visible[:8],
        "structured_scraper_names": structured_names[:8],
        "queue_setup_proven": resolved,
        "queue_seed_resolved": resolved,
        "harness_scraper_observation_gap": scraper_gap,
        "classification_if_fails": QUEUE1D if scraper_gap else "",
    }


_DISCOVER_CANDIDATES_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const out = [];
  let frameIndex = 0;
  for (const root of roots()) {
    const frameUrl = (root.defaultView && root.defaultView.location && root.defaultView.location.href) || '';
    for (const btn of root.querySelectorAll('button')) {
      const t = String(btn.innerText||'').replace(/\\s+/g,' ').trim();
      if (!/Add to Queue/i.test(t)) continue;
      const r = btn.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      let card = btn.closest('[data-testid="stVerticalBlock"]');
      if (!card) card = btn.parentElement && btn.parentElement.parentElement;
      let name = '';
      let domId = '';
      if (card) {
        domId = card.getAttribute('data-testid') || '';
        const lines = String(card.innerText||'').split('\\n').map(x=>x.trim()).filter(Boolean);
        for (const l of lines) {
          if (/Add to Queue|Draft Player|⭐|keyboard_arrow|^#\\d+/i.test(l)) continue;
          if (/^(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)$/i.test(l)) continue;
          let ln = l.replace(/^\\*+|\\*+$/g,'').trim().replace(/^\\d+\\.\\s*/, '');
          const pos = ln.match(/^([A-Za-z][A-Za-z .\\'-]{2,60})\\s+[—\\-–]\\s+(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)\\b/);
          if (pos) { name = pos[1].trim(); break; }
          const two = ln.match(/^([A-Z][a-z]+(?: [A-Z][a-z'.\\-]+){1,3})$/);
          if (two) { name = two[1].trim(); break; }
          if (/^[A-Z][A-Za-z .\\'-]{2,48}$/.test(ln)) { name = ln.trim(); break; }
        }
      }
      if (!name) {
        let walk = btn.parentElement;
        for (let i = 0; i < 6 && walk; i++) {
          const lines = String(walk.innerText||'').split('\\n').map(x=>x.trim()).filter(Boolean);
          for (const raw of lines) {
            let l = raw.replace(/^\\*+|\\*+$/g,'').trim().replace(/^\\d+\\.\\s*/, '');
            if (/Add to Queue|Draft Player|⭐|keyboard_arrow|Watchlist|Available Players|Recommendations|^ADP\\b/i.test(l)) continue;
            if (/^(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)$/i.test(l)) continue;
            const pos = l.match(/^([A-Za-z][A-Za-z .\\'-]{2,60})\\s+[—\\-–]\\s+(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)\\b/);
            if (pos) { name = pos[1].trim(); break; }
            const two = l.match(/^([A-Z][a-z]+(?: [A-Z][a-z'.\\-]+){1,3})$/);
            if (two) { name = two[1].trim(); break; }
            if (/^[A-Z][A-Za-z .\\'-]{2,48}$/.test(l)) { name = l.trim(); break; }
          }
          if (name) break;
          walk = walk.parentElement;
        }
      }
      out.push({
        frameIndex,
        frameUrl: frameUrl.slice(0, 200),
        player_name: name,
        button_text: t,
        disabled: !!btn.disabled,
        dom_hint: domId,
        card_text_sample: card ? String(card.innerText||'').slice(0, 240) : '',
        button_index_in_frame: out.filter(x => x.frameIndex === frameIndex).length,
      });
    }
    frameIndex += 1;
  }
  return out;
}"""


_NAME_TWO = re.compile(r"^([A-Z][a-z]+(?: [A-Z][a-z.'-]+){1,3})$")


def infer_player_name_from_card_text(text: str) -> str:
    for raw in str(text or "").splitlines():
        ln = raw.strip().strip("*").strip()
        ln = re.sub(r"^\d+\.\s*", "", ln)
        if not ln or re.search(r"Add to Queue|Draft Player|Watchlist|Available", ln, re.I):
            continue
        pos = re.match(
            r"^([A-Za-z][A-Za-z .'-]{2,60})\s+[—\-–]\s+(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)\b",
            ln,
        )
        if pos:
            return pos.group(1).strip()
        if _NAME_TWO.match(ln):
            return ln
        if _NAME_ONLY.match(ln):
            return ln
    return ""


def discover_player_add_candidates(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_DISCOVER_CANDIDATES_JS) or []
        out = [x for x in raw if isinstance(x, dict)]
        for c in out:
            if not str(c.get("player_name") or "").strip():
                inferred = infer_player_name_from_card_text(str(c.get("card_text_sample") or ""))
                if inferred:
                    c["player_name"] = inferred
                    c["name_inferred_from_card"] = True
        return out
    except Exception as exc:
        return [{"error": str(exc)[:200]}]


def _frame_for_candidate(page, candidate: dict[str, Any]):
    from run_production_stage1_authenticated import _streamlit_app_frame

    try:
        idx = int(candidate.get("frameIndex"))
        frames = page.frames
        if 0 <= idx < len(frames):
            return frames[idx]
    except (TypeError, ValueError):
        pass
    return _streamlit_app_frame(page)


def _click_player_add_button(page, candidate: dict[str, Any]) -> dict[str, Any]:
    name = str(candidate.get("player_name") or "").strip()
    frame = _frame_for_candidate(page, candidate)
    out: dict[str, Any] = {"player_name": name, "click_dispatched": False}
    if not name:
        out["classification"] = QUEUE1B
        out["error"] = "missing_player_name_on_candidate"
        return out
    try:
        block = frame.locator('[data-testid="stVerticalBlock"]').filter(has_text=re.compile(re.escape(name), re.I))
        btn = block.locator("button").filter(has_text=re.compile(r"Add to Queue", re.I)).first
        btn.scroll_into_view_if_needed(timeout=8000)
        btn.click(timeout=10000)
        out["click_dispatched"] = True
        out["via"] = "player_bound_vertical_block"
    except Exception as exc:
        out["error"] = str(exc)[:200]
        out["classification"] = QUEUE1C
    return out


def _snapshot_queue(page, scrape_fn) -> dict[str, Any]:
    container = scrape_fn(page)
    excerpt = str(container.get("excerpt") or "")
    names = queue_names_from_state(container, excerpt)
    return {"container": container, "excerpt": excerpt, "queue_names": names, "ts": time.time()}


def _mutation_proven(before: list[str], after: list[str], player_name: str) -> bool:
    pn = player_name.strip().lower()
    if not pn:
        return False
    before_l = {n.lower() for n in before}
    after_l = {n.lower() for n in after}
    return pn in after_l and pn not in before_l


def _scroll_player_list(page) -> None:
    try:
        page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r; }
              for (const root of roots()) {
                try { root.defaultView && root.defaultView.scrollTo(0, 400); } catch(e){}
              }
            }"""
        )
    except Exception:
        pass


def _ensure_named_candidates(page, *, min_players: int, wait_s: float = 50.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expand player surfaces until enough named Add-to-Queue rows exist."""
    from stage1_active_queue_surface import try_activate_queue_player_surface

    attempts: list[dict[str, Any]] = []
    t_end = time.time() + wait_s
    best: list[dict[str, Any]] = []
    best_named = 0
    while time.time() < t_end:
        last = discover_player_add_candidates(page)
        unnamed = [c for c in last if not str(c.get("player_name") or "").strip()]
        named = [c for c in last if str(c.get("player_name") or "").strip()]
        by_name: dict[str, dict[str, Any]] = {}
        for c in named:
            key = str(c.get("player_name")).strip().lower()
            if key not in by_name:
                by_name[key] = c
        if len(by_name) > best_named or (len(by_name) == best_named and len(last) > len(best)):
            best = list(last)
            best_named = len(by_name)
        if len(by_name) >= min_players:
            return last, attempts
        attempts.append(
            {
                "named_count": len(by_name),
                "button_count": len(last),
                "unnamed_button_count": len(unnamed),
                "ts": time.time(),
            }
        )
        try_activate_queue_player_surface(page, record_per_step=False)
        _scroll_player_list(page)
        page.wait_for_timeout(2200)
    return best, attempts


def wait_for_min_add_to_queue_controls(
    page,
    *,
    min_controls: int = 3,
    timeout_s: float = 90.0,
    start_val: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Poll player surfaces until enough Add-to-Queue controls are visible to seed."""
    from stage1_active_queue_surface import scrape_frame_aware_active_observation, try_activate_queue_player_surface

    start_val = dict(start_val or {})
    attempts: list[dict[str, Any]] = []
    t_end = time.time() + timeout_s
    last_count = 0
    while time.time() < t_end:
        obs = scrape_frame_aware_active_observation(page, start_val=start_val)
        last_count = int(obs.get("add_to_queue_button_count") or 0)
        attempts.append(
            {
                "add_to_queue_button_count": last_count,
                "board_rows": obs.get("board_rows"),
                "ts": time.time(),
            }
        )
        if last_count >= min_controls:
            return {"ok": True, "add_to_queue_button_count": last_count, "attempts": attempts, "observation": obs}
        try_activate_queue_player_surface(page, start_val=start_val, record_per_step=False)
        _scroll_player_list(page)
        page.wait_for_timeout(2500)
    return {"ok": False, "add_to_queue_button_count": last_count, "attempts": attempts}


def _click_add_by_index(page, candidate: dict[str, Any]) -> dict[str, Any]:
    frame = _frame_for_candidate(page, candidate)
    idx = int(candidate.get("button_index_in_frame") or 0)
    out: dict[str, Any] = {"click_dispatched": False, "via": "add_to_queue_index"}
    try:
        loc = frame.locator("button").filter(has_text=re.compile(r"Add to Queue", re.I))
        btn = loc.nth(idx)
        btn.scroll_into_view_if_needed(timeout=8000)
        btn.click(timeout=10000)
        out["click_dispatched"] = True
    except Exception as exc:
        out["error"] = str(exc)[:200]
        out["classification"] = QUEUE1C
    return out


def _new_queue_names(before: list[str], after: list[str]) -> list[str]:
    before_l = {n.lower() for n in before if n}
    return [n for n in after if n and n.lower() not in before_l]


def _collect_global_button_hints(page, *, min_players: int, max_scan: int = 16) -> list[dict[str, Any]]:
    from run_production_stage1_authenticated import _queue_button_player_hint

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in range(max_scan):
        hint = _queue_button_player_hint(page, i)
        if not hint.get("found"):
            break
        name = str(hint.get("player_name") or hint.get("player_hint") or "").strip()
        if not name or len(name) < 4:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({**hint, "global_button_index": i})
        if len(out) >= min_players:
            break
    return out


def _click_global_add_index(page, button_index: int) -> dict[str, Any]:
    from run_production_stage1_authenticated import queue_add_by_button_index

    meta = queue_add_by_button_index(page, button_index)
    return {
        "click_dispatched": bool(meta.get("clicked")),
        "via": meta.get("via") or "queue_add_by_button_index",
        "player_hint": meta.get("player_hint") or "",
        "error": "" if meta.get("clicked") else "click_failed",
    }


def _seed_via_global_button_hints(
    page,
    *,
    hints: list[dict[str, Any]],
    scrape_container_fn,
    min_players: int,
    mutation_wait_s: float,
    control_wait: dict[str, Any],
    expand_attempts: list[dict[str, Any]],
    t0: float,
) -> dict[str, Any]:
    seed_steps: list[dict[str, Any]] = []
    for hint in hints[: min_players + 1]:
        if len(seed_steps) >= min_players:
            break
        name = str(hint.get("player_name") or hint.get("player_hint") or "").strip()
        bi = int(hint.get("global_button_index") or hint.get("button_index") or 0)
        pre = _snapshot_queue(page, scrape_container_fn)
        step: dict[str, Any] = {
            "intended_player": name,
            "player_name": name,
            "global_button_index": bi,
            "queue_before": list(pre.get("queue_names") or []),
            "started_ts": time.time(),
            "binding": "global_button_index_with_player_hint",
        }
        click = _click_global_add_index(page, bi)
        step.update(click)
        page.wait_for_timeout(int(mutation_wait_s * 1000))
        post = _snapshot_queue(page, scrape_container_fn)
        step["queue_after"] = list(post.get("queue_names") or [])
        step["visible_confirmation"] = _mutation_proven(step["queue_before"], step["queue_after"], name)
        after_structured = queue_names_from_state(
            post.get("container") or {}, str((post.get("container") or {}).get("excerpt") or "")
        )
        step["structured_confirmation"] = name.lower() in {n.lower() for n in after_structured}
        added = _new_queue_names(step["queue_before"], step["queue_after"])
        if not step["visible_confirmation"] and len(added) == 1:
            step["player_name"] = added[0]
            step["visible_confirmation"] = True
        step["mutation_proven"] = step["visible_confirmation"] or step["structured_confirmation"]
        step["elapsed_s"] = time.time() - float(step.get("started_ts") or time.time())
        if not step.get("click_dispatched"):
            step["classification"] = QUEUE1C
            seed_steps.append(step)
            break
        if not step["mutation_proven"]:
            step["classification"] = QUEUE1C
            seed_steps.append(step)
            break
        seed_steps.append(step)

    final = _snapshot_queue(page, scrape_container_fn)
    proven_order: list[str] = []
    for s in seed_steps:
        if s.get("mutation_proven") and s.get("player_name"):
            n = str(s["player_name"])
            if n.lower() not in {x.lower() for x in proven_order}:
                proven_order.append(n)
    order_ok = len(proven_order) >= min_players and len(proven_order) == len({n.lower() for n in proven_order})
    meta: dict[str, Any] = {
        "seed_source": "global_button_hint_bound_seed",
        "min_players_required": min_players,
        "intended_players_before_clicks": [{"player_name": h.get("player_name"), "global_button_index": h.get("global_button_index")} for h in hints[:min_players]],
        "candidate_expand_attempts": expand_attempts,
        "add_control_wait": control_wait,
        "seed_steps": seed_steps,
        "add_actions": seed_steps,
        "proven_queue_order": proven_order,
        "queue_order_established": order_ok,
        "queue_excerpt_before": final.get("excerpt"),
        "queue_container": final.get("container"),
        "queue_order": proven_order,
        "elapsed_s": time.time() - t0,
    }
    evidence = build_queue_seed_evidence(meta, min_players=min_players)
    meta["queue_evidence"] = evidence
    meta["queue_contains_player"] = bool(evidence.get("queue_seed_resolved"))
    if evidence.get("queue_seed_resolved"):
        meta["classification"] = QUEUE_SEED_RESOLVED
        meta["ok"] = True
    else:
        meta["ok"] = False
        meta["classification"] = classify_queue_seed_boundary(meta, min_players=min_players)
    return meta


def _seed_via_global_indices_with_queue_diff(
    page,
    *,
    scrape_container_fn,
    min_players: int,
    mutation_wait_s: float,
    control_wait: dict[str, Any],
    expand_attempts: list[dict[str, Any]],
    t0: float,
    start_index: int = 0,
) -> dict[str, Any]:
    """Click global Add-to-Queue indices (bind player identity from queue diff after each click)."""
    from run_production_stage1_authenticated import _queue_button_player_hint

    seed_steps: list[dict[str, Any]] = []
    first = _queue_button_player_hint(page, 0)
    total_buttons = int(first.get("total") or 0)
    if not total_buttons:
        total_buttons = int(control_wait.get("add_to_queue_button_count") or 0)
    for bi in range(start_index, max(start_index + 12, total_buttons + 1)):
        if len(seed_steps) >= min_players:
            break
        if total_buttons and bi >= total_buttons:
            break
        hint = _queue_button_player_hint(page, bi)
        if not hint.get("found"):
            if total_buttons and bi < total_buttons:
                hint = {"found": True, "button_index": bi, "total": total_buttons}
            elif total_buttons:
                continue
            else:
                break
        pre = _snapshot_queue(page, scrape_container_fn)
        step: dict[str, Any] = {
            "intended_player": str(hint.get("player_name") or hint.get("player_hint") or ""),
            "global_button_index": bi,
            "queue_before": list(pre.get("queue_names") or []),
            "started_ts": time.time(),
            "binding": "global_index_queue_diff",
            "hint_before_click": hint,
        }
        click = _click_global_add_index(page, bi)
        step.update(click)
        page.wait_for_timeout(int(mutation_wait_s * 1000))
        post = _snapshot_queue(page, scrape_container_fn)
        step["queue_after"] = list(post.get("queue_names") or [])
        added = _new_queue_names(step["queue_before"], step["queue_after"])
        if len(added) >= 1:
            step["player_name"] = added[0]
        elif step.get("intended_player"):
            step["player_name"] = step["intended_player"]
        step["visible_confirmation"] = bool(added)
        after_structured = queue_names_from_state(
            post.get("container") or {}, str((post.get("container") or {}).get("excerpt") or "")
        )
        step["structured_confirmation"] = bool(added) and any(
            a.lower() in {n.lower() for n in after_structured} for a in added
        )
        step["mutation_proven"] = bool(added)
        step["elapsed_s"] = time.time() - float(step.get("started_ts") or time.time())
        if not step.get("click_dispatched"):
            step["classification"] = QUEUE1C
            seed_steps.append(step)
            break
        if not step["mutation_proven"]:
            step["classification"] = QUEUE1C
            seed_steps.append(step)
            break
        seed_steps.append(step)

    final = _snapshot_queue(page, scrape_container_fn)
    proven_order: list[str] = []
    for s in seed_steps:
        if s.get("mutation_proven") and s.get("player_name"):
            n = str(s["player_name"])
            if n.lower() not in {x.lower() for x in proven_order}:
                proven_order.append(n)
    order_ok = len(proven_order) >= min_players and len(proven_order) == len({n.lower() for n in proven_order})
    meta: dict[str, Any] = {
        "seed_source": "global_index_queue_diff",
        "min_players_required": min_players,
        "candidate_expand_attempts": expand_attempts,
        "add_control_wait": control_wait,
        "seed_steps": seed_steps,
        "add_actions": seed_steps,
        "proven_queue_order": proven_order,
        "queue_order_established": order_ok,
        "queue_excerpt_before": final.get("excerpt"),
        "queue_container": final.get("container"),
        "queue_order": proven_order,
        "classification_hint": QUEUE1B,
        "elapsed_s": time.time() - t0,
    }
    evidence = build_queue_seed_evidence(meta, min_players=min_players)
    meta["queue_evidence"] = evidence
    meta["queue_contains_player"] = bool(evidence.get("queue_seed_resolved"))
    if evidence.get("queue_seed_resolved"):
        meta["classification"] = QUEUE_SEED_RESOLVED
        meta["ok"] = True
    else:
        meta["ok"] = False
        meta["classification"] = classify_queue_seed_boundary(meta, min_players=min_players)
    return meta


def _seed_unnamed_via_queue_diff(
    page,
    *,
    candidates: list[dict[str, Any]],
    scrape_container_fn,
    min_players: int,
    mutation_wait_s: float,
    before_all: dict[str, Any],
    control_wait: dict[str, Any],
    expand_attempts: list[dict[str, Any]],
    t0: float,
) -> dict[str, Any]:
    """When DOM names are missing, bind identity from queue mutation after each indexed click."""
    seed_steps: list[dict[str, Any]] = []
    used_indices: set[tuple[int, int]] = set()
    ordered_candidates: list[dict[str, Any]] = []
    for c in candidates:
        key = (int(c.get("frameIndex") or 0), int(c.get("button_index_in_frame") or 0))
        if key in used_indices:
            continue
        used_indices.add(key)
        ordered_candidates.append(c)
        if len(ordered_candidates) >= min_players + 2:
            break
    for c in ordered_candidates:
        if len(seed_steps) >= min_players:
            break
        pre = _snapshot_queue(page, scrape_container_fn)
        step: dict[str, Any] = {
            "intended_player": "",
            "candidate": c,
            "queue_before": list(pre.get("queue_names") or []),
            "started_ts": time.time(),
            "binding": "queue_diff_after_indexed_click",
        }
        click = _click_add_by_index(page, c)
        step.update(click)
        page.wait_for_timeout(int(mutation_wait_s * 1000))
        post = _snapshot_queue(page, scrape_container_fn)
        step["queue_after"] = list(post.get("queue_names") or [])
        added = _new_queue_names(step["queue_before"], step["queue_after"])
        if len(added) == 1:
            step["player_name"] = added[0]
            step["intended_player"] = added[0]
        elif len(added) > 1:
            step["player_name"] = added[0]
            step["intended_player"] = added[0]
            step["queue_diff_ambiguous"] = added
        step["visible_confirmation"] = bool(added)
        after_structured = queue_names_from_state(
            post.get("container") or {}, str((post.get("container") or {}).get("excerpt") or "")
        )
        step["structured_confirmation"] = bool(added) and any(
            a.lower() in {n.lower() for n in after_structured} for a in added
        )
        step["mutation_proven"] = bool(added)
        step["elapsed_s"] = time.time() - float(step.get("started_ts") or time.time())
        if not step.get("click_dispatched"):
            step["classification"] = step.get("classification") or QUEUE1C
            seed_steps.append(step)
            break
        if not step["mutation_proven"]:
            step["classification"] = QUEUE1C
            seed_steps.append(step)
            break
        seed_steps.append(step)

    final = _snapshot_queue(page, scrape_container_fn)
    proven_order: list[str] = []
    for s in seed_steps:
        if s.get("mutation_proven") and s.get("player_name"):
            n = str(s["player_name"])
            if n.lower() not in {x.lower() for x in proven_order}:
                proven_order.append(n)
    order_ok = len(proven_order) >= min_players and len(proven_order) == len({n.lower() for n in proven_order})
    meta: dict[str, Any] = {
        "seed_source": "indexed_click_queue_diff_binding",
        "min_players_required": min_players,
        "candidates_discovered": len(candidates),
        "distinct_named_candidates": 0,
        "unnamed_add_buttons": len(candidates),
        "candidate_expand_attempts": expand_attempts,
        "add_control_wait": control_wait,
        "candidate_debug": candidates[:8],
        "classification_hint": QUEUE1B,
        "seed_steps": seed_steps,
        "add_actions": seed_steps,
        "proven_queue_order": proven_order,
        "queue_order_established": order_ok,
        "queue_excerpt_before": final.get("excerpt"),
        "queue_container": final.get("container"),
        "queue_order": proven_order,
        "elapsed_s": time.time() - t0,
    }
    evidence = build_queue_seed_evidence(meta, min_players=min_players)
    meta["queue_evidence"] = evidence
    meta["queue_contains_player"] = bool(evidence.get("queue_seed_resolved"))
    if evidence.get("queue_seed_resolved"):
        meta["classification"] = QUEUE_SEED_RESOLVED
        meta["ok"] = True
    else:
        meta["ok"] = False
        meta["classification"] = classify_queue_seed_boundary(meta, min_players=min_players)
    return meta


def _poll_queue_mutation(
    page,
    scrape_fn,
    *,
    queue_before: list[str],
    player_name: str,
    timeout_s: float = 5.0,
    poll_ms: int = 400,
) -> dict[str, Any]:
    t_end = time.time() + timeout_s
    pn = player_name.strip().lower()
    last: dict[str, Any] = {"mutation_observed": False}
    while time.time() < t_end:
        snap = _snapshot_queue(page, scrape_fn)
        names = list(snap.get("queue_names") or [])
        before_l = {n.lower() for n in queue_before if n}
        added = [n for n in names if n.lower() not in before_l]
        visible_hit = pn in {n.lower() for n in names} and pn not in before_l
        structured = [
            str(p.get("name") or "") for p in parse_queue_players_from_block(str(snap.get("excerpt") or ""))
        ]
        structured_hit = pn in {n.lower() for n in structured}
        last = {
            "queue_after": names,
            "added_names": added,
            "visible_confirmation": visible_hit,
            "structured_confirmation": structured_hit,
            "mutation_observed": visible_hit or (bool(added) and pn in {a.lower() for a in added}),
        }
        if last["mutation_observed"]:
            return last
        page.wait_for_timeout(poll_ms)
    return last


def _finalize_seed_meta(
    page,
    *,
    seed_steps: list[dict[str, Any]],
    min_players: int,
    t0: float,
    scrape_container_fn,
    control_wait: dict[str, Any],
    discovery_snapshots: list[dict[str, Any]],
    seed_source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final = _snapshot_queue(page, scrape_container_fn)
    proven_order: list[str] = []
    for s in seed_steps:
        if s.get("mutation_proven") and s.get("player_name"):
            n = str(s["player_name"])
            if n.lower() not in {x.lower() for x in proven_order}:
                proven_order.append(n)
    order_ok = len(proven_order) >= min_players and len(proven_order) == len({n.lower() for n in proven_order})
    meta: dict[str, Any] = {
        "seed_source": seed_source,
        "min_players_required": min_players,
        "seed_steps": seed_steps,
        "add_actions": seed_steps,
        "proven_queue_order": proven_order,
        "queue_order_established": order_ok,
        "queue_excerpt_before": final.get("excerpt"),
        "queue_container": final.get("container"),
        "queue_order": proven_order,
        "top_queued_player": {"name": proven_order[0]} if proven_order else {},
        "add_control_wait": control_wait,
        "discovery_snapshots": discovery_snapshots,
        "elapsed_s": time.time() - t0,
    }
    if extra:
        meta.update(extra)
    evidence = build_queue_seed_evidence(meta, min_players=min_players)
    meta["queue_evidence"] = evidence
    meta["queue_contains_player"] = bool(evidence.get("queue_seed_resolved"))
    if evidence.get("queue_seed_resolved"):
        meta["classification"] = QUEUE_SEED_RESOLVED
        meta["ok"] = True
    else:
        meta["ok"] = False
        meta["classification"] = classify_queue_seed_boundary(meta, min_players=min_players)
    return meta


def seed_queue_distinct_players(
    page,
    *,
    scrape_container_fn,
    min_players: int = 3,
    mutation_wait_s: float = 5.0,
) -> dict[str, Any]:
    """Rediscover → bind player → click → prove mutation; discard bindings after each add."""
    from stage1_add_to_queue_delivery import (
        deliver_add_to_queue_click,
        discover_bound_add_to_queue_controls,
        select_next_seed_candidate,
    )

    t0 = time.time()
    before_all = _snapshot_queue(page, scrape_container_fn)
    control_wait = wait_for_min_add_to_queue_controls(page, min_controls=min_players, timeout_s=90.0)
    if not control_wait.get("ok"):
        return {
            "ok": False,
            "classification": QUEUE1E,
            "seed_steps": [],
            "add_control_wait": control_wait,
            "min_players_required": min_players,
            "queue_excerpt_before": before_all.get("excerpt"),
            "queue_container": before_all.get("container"),
            "elapsed_s": time.time() - t0,
        }

    seed_steps: list[dict[str, Any]] = []
    queued_names: set[str] = set()
    discovery_snapshots: list[dict[str, Any]] = []
    fail_classification = ""

    while len([s for s in seed_steps if s.get("mutation_proven")]) < min_players:
        candidates = discover_bound_add_to_queue_controls(page)
        discovery_snapshots.append(
            {
                "ts": time.time(),
                "control_count": len(candidates),
                "named_unique": sum(
                    1 for c in candidates if c.get("binding_confidence") == "unique" and c.get("player_name")
                ),
                "candidates": candidates[:10],
            }
        )
        pick, reject = select_next_seed_candidate(candidates, exclude_player_names=queued_names)
        if not pick:
            if reject == "ambiguous_binding":
                fail_classification = QUEUE1B
            elif reject == "missing_binding":
                fail_classification = (
                    QUEUE1B
                    if int(control_wait.get("add_to_queue_button_count") or 0) >= min_players
                    else QUEUE1E
                )
            else:
                fail_classification = QUEUE1E
            break

        player_name = str(pick.get("player_name") or "").strip()
        pre = _snapshot_queue(page, scrape_container_fn)
        step: dict[str, Any] = {
            "player_name": player_name,
            "intended_player": player_name,
            "pre_click_record": pick,
            "queue_before": list(pre.get("queue_names") or []),
            "started_ts": time.time(),
        }
        delivery = deliver_add_to_queue_click(page, pick)
        step["click_dispatched"] = bool(delivery.get("click_dispatched"))
        step["delivery_method"] = delivery.get("delivery_method") or ""
        step["delivery_detail"] = delivery
        if not step["click_dispatched"]:
            step["classification"] = QUEUE1C
            step["mutation_proven"] = False
            step["mutation_observed"] = False
            step["elapsed_s"] = time.time() - float(step["started_ts"])
            seed_steps.append(step)
            fail_classification = QUEUE1C
            break

        mut = _poll_queue_mutation(
            page,
            scrape_container_fn,
            queue_before=step["queue_before"],
            player_name=player_name,
            timeout_s=max(mutation_wait_s, 4.0),
        )
        step["queue_after"] = list(mut.get("queue_after") or [])
        step["visible_confirmation"] = bool(mut.get("visible_confirmation"))
        step["structured_confirmation"] = bool(mut.get("structured_confirmation"))
        step["mutation_observed"] = bool(mut.get("mutation_observed"))
        step["mutation_proven"] = step["mutation_observed"]
        step["elapsed_s"] = time.time() - float(step["started_ts"])
        if not step["mutation_proven"]:
            step["classification"] = QUEUE1C
            seed_steps.append(step)
            fail_classification = QUEUE1C
            break
        queued_names.add(player_name.lower())
        seed_steps.append(step)
        page.wait_for_timeout(900)

    extra: dict[str, Any] = {}
    if fail_classification and not seed_steps:
        return {
            "ok": False,
            "classification": fail_classification,
            "seed_steps": [],
            "add_control_wait": control_wait,
            "discovery_snapshots": discovery_snapshots,
            "min_players_required": min_players,
            "queue_excerpt_before": before_all.get("excerpt"),
            "queue_container": before_all.get("container"),
            "elapsed_s": time.time() - t0,
        }

    meta = _finalize_seed_meta(
        page,
        seed_steps=seed_steps,
        min_players=min_players,
        t0=t0,
        scrape_container_fn=scrape_container_fn,
        control_wait=control_wait,
        discovery_snapshots=discovery_snapshots,
        seed_source="rediscover_bind_deliver_mutation_loop",
        extra={
            "intended_players_before_clicks": [
                {"player_name": s.get("player_name"), "pre_click_global_index": (s.get("pre_click_record") or {}).get("global_index")}
                for s in seed_steps
            ],
            "candidates_discovered": discovery_snapshots[-1]["control_count"] if discovery_snapshots else 0,
        },
    )
    if fail_classification and not meta.get("ok"):
        meta["classification"] = fail_classification
    return meta
