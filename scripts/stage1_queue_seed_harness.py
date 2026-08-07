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
        name = lines.find(l => /^[A-Z][A-Za-z .'-]{2,48}$/.test(l) && !/Add to Queue|Draft Player|⭐/i.test(l)) || '';
      }
      out.push({
        frameIndex,
        frameUrl: frameUrl.slice(0, 200),
        player_name: name,
        button_text: t,
        disabled: !!btn.disabled,
        dom_hint: domId,
        button_index_in_frame: out.filter(x => x.frameIndex === frameIndex).length,
      });
    }
    frameIndex += 1;
  }
  return out;
}"""


def discover_player_add_candidates(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_DISCOVER_CANDIDATES_JS) or []
        return [x for x in raw if isinstance(x, dict)]
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
        btn = block.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).first
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


def seed_queue_distinct_players(
    page,
    *,
    scrape_container_fn,
    min_players: int = 3,
    mutation_wait_s: float = 4.0,
) -> dict[str, Any]:
    """Identify distinct players, click once each, prove mutation before continuing."""
    t0 = time.time()
    before_all = _snapshot_queue(page, scrape_container_fn)
    candidates = discover_player_add_candidates(page)
    by_name: dict[str, dict[str, Any]] = {}
    ambiguous: list[dict[str, Any]] = []
    for c in candidates:
        name = str(c.get("player_name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in by_name:
            ambiguous.append({"player_name": name, "reason": "duplicate_candidate"})
            continue
        by_name[key] = c
    distinct = list(by_name.values())
    if len(distinct) < min_players:
        return {
            "ok": False,
            "classification": QUEUE1E,
            "seed_steps": [],
            "candidates_discovered": len(candidates),
            "distinct_named_candidates": len(distinct),
            "min_players_required": min_players,
            "queue_excerpt_before": before_all.get("excerpt"),
            "queue_container": before_all.get("container"),
            "elapsed_s": time.time() - t0,
        }
    seed_steps: list[dict[str, Any]] = []
    queue_names = list(before_all.get("queue_names") or [])
    intended: list[dict[str, Any]] = []
    for c in distinct[: min_players + 2]:
        if len(intended) >= min_players:
            break
        pre = _snapshot_queue(page, scrape_container_fn)
        step: dict[str, Any] = {
            "intended_player": c.get("player_name"),
            "candidate": c,
            "queue_before": list(pre.get("queue_names") or []),
            "started_ts": time.time(),
        }
        intended.append(c)
        click = _click_player_add_button(page, c)
        step.update(click)
        page.wait_for_timeout(int(mutation_wait_s * 1000))
        post = _snapshot_queue(page, scrape_container_fn)
        step["queue_after"] = list(post.get("queue_names") or [])
        pname = str(c.get("player_name") or "")
        step["visible_confirmation"] = _mutation_proven(step["queue_before"], step["queue_after"], pname)
        after_structured = queue_names_from_state(
            post.get("container") or {}, str((post.get("container") or {}).get("excerpt") or "")
        )
        step["structured_confirmation"] = pname.strip().lower() in {n.lower() for n in after_structured}
        step["mutation_proven"] = step["visible_confirmation"] or step["structured_confirmation"]
        step["elapsed_s"] = time.time() - float(step.get("started_ts") or time.time())
        if not step.get("click_dispatched"):
            step["classification"] = step.get("classification") or QUEUE1C
            seed_steps.append(step)
            break
        if not step["mutation_proven"]:
            step["classification"] = QUEUE1C
            seed_steps.append(step)
            break
        queue_names = list(step["queue_after"])
        step["player_name"] = c.get("player_name")
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
        "seed_source": "player_bound_distinct_seed",
        "min_players_required": min_players,
        "candidates_discovered": len(candidates),
        "distinct_named_candidates": len(distinct),
        "ambiguous_candidates": ambiguous,
        "intended_players_before_clicks": [{"player_name": c.get("player_name"), "frameIndex": c.get("frameIndex")} for c in intended],
        "seed_steps": seed_steps,
        "add_actions": seed_steps,
        "proven_queue_order": proven_order,
        "queue_order_established": order_ok,
        "queue_excerpt_before": final.get("excerpt"),
        "queue_container": final.get("container"),
        "queue_order": proven_order,
        "queue_players_before": [{"name": n, "slot": ""} for n in proven_order],
        "top_queued_player": {"name": proven_order[0]} if proven_order else {},
        "elapsed_s": time.time() - t0,
    }
    if ambiguous:
        meta["classification_hint"] = QUEUE1B
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
