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
QUEUE1C1 = "QUEUE1C1 — Playwright cannot dispatch click to bound button"
QUEUE1C2 = "QUEUE1C2 — click dispatched but no Streamlit widget/back-message"
QUEUE1C3 = "QUEUE1C3 — Streamlit message/rerun occurs but queue state does not change"
QUEUE1C4 = "QUEUE1C4 — queue state changes but DOM evidence misses it"
QUEUE1C5 = "QUEUE1C5 — button rerenders/stales during interaction"
QUEUE1C8 = "QUEUE1C8 — another exact Add-to-Queue delivery boundary"
QUEUE1D = "QUEUE1D — queue mutation visible but structured parser failed"
QUEUE1E = "QUEUE1E — fewer than required distinct players available/seeded"
QUEUE1F = "QUEUE1F — queue order cannot be established"
QUEUE1_8 = "QUEUE1_8 — another exact supported queue-seed boundary"

# Authorized-widget seed delivery boundaries (Stage1 harness; not product codes).
QUEUE1C3A2K = "QUEUE1C3A2K — authorized rec_card widget key binding failed before click"
STAGE1_QUEUE_SEED_WIDGET_CONSUMPTION_BOUNDARY = (
    "STAGE1_QUEUE_SEED_WIDGET_CONSUMPTION_BOUNDARY — click_dispatched without widget_consumption_ack"
)
STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY = (
    "STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY — widget consumed but authoritative +1 membership not proven"
)

_REC_CARD_QUEUE_KEY = re.compile(
    r"^rec_card_queue_(?P<room>[A-Za-z0-9]+)_(?P<pick>\d+)_(?P<player_id>\d+)_rec_card$"
)

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


def classify_queue1c_subcode(step: dict[str, Any]) -> str:
    """Narrow QUEUE1C using click, Streamlit transport, and mutation evidence."""
    delivery = step.get("delivery_detail") if isinstance(step.get("delivery_detail"), dict) else {}
    method = str(step.get("delivery_method") or delivery.get("delivery_method") or "")
    dispatched = bool(step.get("click_dispatched") or delivery.get("click_dispatched"))
    err = str(delivery.get("error") or step.get("error") or "").lower()
    transport = delivery.get("post_click_transport") if isinstance(delivery.get("post_click_transport"), dict) else {}
    if any(x in err for x in ("stale", "detached", "not attached", "target closed", "execution context")):
        return QUEUE1C5
    if not dispatched or method.startswith("js_"):
        if not dispatched:
            return QUEUE1C1
        return QUEUE1C2
    transport = delivery.get("post_click_transport") if isinstance(delivery.get("post_click_transport"), dict) else {}
    native = bool(transport.get("native_widget_event_observed"))
    backmsg = bool(transport.get("streamlit_backmsg_sent"))
    rerun = bool(transport.get("python_rerun_started") or transport.get("script_run_seq_changed"))
    generic_only = bool(transport.get("generic_component_traffic_only"))
    if dispatched and not native and not rerun and int(transport.get("outbound_frames_after_click") or 0) == 0:
        return QUEUE1C2
    if step.get("mutation_observed"):
        return QUEUE1C
    if step.get("structured_confirmation") and not step.get("visible_confirmation"):
        return QUEUE1C4
    if (native or generic_only or backmsg or rerun or int(transport.get("outbound_frames_after_click") or 0) > 0) and not step.get("mutation_observed"):
        try:
            from stage1_native_widget_transport import classify_queue1c3a_subcode

            dom = delivery.get("pre_click_dom_inspection") if isinstance(delivery.get("pre_click_dom_inspection"), dict) else {}
            rec = dom.get("recommended_click") if isinstance(dom.get("recommended_click"), dict) else dom
            liveness = str(
                step.get("render_trace_widget_liveness")
                or (step.get("app_render_trace") or {}).get("widget_liveness")
                or ""
            ).strip()
            sub_a = classify_queue1c3a_subcode(
                click_target=rec,
                transport=transport,
                render_trace_present=bool(step.get("render_trace_present")),
                callback_trace_present=bool(step.get("app_queue_trace")),
                callback_entered=step.get("app_callback_entered") if "app_callback_entered" in step else None,
                widget_liveness=liveness,
            )
            if sub_a.startswith("QUEUE1C3A2O"):
                return sub_a
            if sub_a.startswith("QUEUE1C3A"):
                if transport.get("run_binding_consistent") is False:
                    return "QUEUE1C3A2O1"
                return sub_a
        except ImportError:
            pass
        app_class = str(step.get("app_classification") or "").strip()
        if app_class.startswith("QUEUE1C3"):
            return app_class.split(" ")[0] if " " in app_class else app_class
        if step.get("app_callback_entered") is False:
            return "QUEUE1C3A"
        return QUEUE1C3
    if dispatched and not step.get("mutation_observed"):
        return QUEUE1C2 if not backmsg and not rerun else QUEUE1C3
    return QUEUE1C8


def classify_queue_seed_boundary(meta: dict[str, Any], *, min_players: int = 3) -> str:
    if meta.get("surface_activation_queue_mutation"):
        return QUEUE1A
    steps = list(meta.get("seed_steps") or [])
    if any(s.get("classification") == QUEUE1B for s in steps):
        return QUEUE1B
    subcodes = (
        QUEUE1C1,
        QUEUE1C2,
        QUEUE1C3,
        QUEUE1C4,
        QUEUE1C5,
        QUEUE1C8,
    )
    for sub in subcodes:
        if any(str(s.get("classification") or "").startswith(sub.split(" ")[0]) for s in steps):
            for s in steps:
                c = str(s.get("classification") or "")
                if c.startswith(sub.split(" ")[0]):
                    return c
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
    # Success is evidence-derived only via apply_queue_seed_evidence — never from a
    # stale meta["classification"] string left behind by a prior resolved generation.
    return QUEUE1_8


def queue_seed_unresolved_boundary(meta: dict[str, Any], *, min_players: int = 3) -> str:
    """First failed predicate label for precondition abort reporting (never a success label)."""
    steps = list(meta.get("seed_steps") or [])
    proven_order: list[str] = []
    for step in steps:
        if step.get("mutation_proven") and step.get("player_name"):
            name = str(step["player_name"]).strip()
            if name.lower() not in {n.lower() for n in proven_order}:
                proven_order.append(name)
    deliberate_clicks = sum(1 for s in steps if s.get("click_dispatched"))
    if deliberate_clicks < min_players:
        return "insufficient_deliberate_seed_clicks"
    if len(proven_order) < min_players:
        return "insufficient_distinct_seed_players"
    if not bool(meta.get("queue_order_established")):
        return "queue_order_not_established"
    if not bool(meta.get("pick_index_zero_after_setup", True)):
        return "pick_index_zero_after_setup"
    if not bool(meta.get("paused_state_maintained", True)):
        return "paused_state_maintained"
    classified = classify_queue_seed_boundary(meta, min_players=min_players)
    if classified == QUEUE_SEED_RESOLVED:
        return "queue_seed_evidence_unresolved"
    return str(classified or "queue_seed_evidence_unresolved")


def apply_queue_seed_evidence(
    meta: dict[str, Any],
    *,
    min_players: int = 3,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild queue_evidence and synchronize derived fields to ONE evidence generation.

    Guarantees classification/ok/queue_contains_player match the returned evidence.
    Never retains QUEUE_SEED_RESOLVED when queue_seed_resolved is false.
    """
    if bool(meta.get("surface_activation_queue_mutation")):
        if evidence is None:
            evidence = build_queue_seed_evidence(meta, min_players=min_players)
        meta["queue_evidence"] = evidence
        meta["queue_setup_proven"] = bool(evidence.get("queue_setup_proven"))
        meta["queue_contains_player"] = False
        meta["classification"] = QUEUE1A
        meta["ok"] = False
        return evidence

    if evidence is None:
        evidence = build_queue_seed_evidence(meta, min_players=min_players)
    meta["queue_evidence"] = evidence
    meta["queue_setup_proven"] = bool(evidence.get("queue_setup_proven"))
    meta["queue_contains_player"] = bool(evidence.get("queue_seed_resolved"))
    if evidence.get("queue_seed_resolved"):
        meta["classification"] = QUEUE_SEED_RESOLVED
        meta["ok"] = True
    else:
        meta["ok"] = False
        # Drop any prior success label before failure classification.
        if meta.get("classification") == QUEUE_SEED_RESOLVED:
            meta["classification"] = ""
        meta["classification"] = queue_seed_unresolved_boundary(meta, min_players=min_players)
    return evidence


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
    apply_queue_seed_evidence(meta, min_players=min_players)
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
    apply_queue_seed_evidence(meta, min_players=min_players)
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
    apply_queue_seed_evidence(meta, min_players=min_players)
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
    apply_queue_seed_evidence(meta, min_players=min_players)
    return meta


def parse_rec_card_queue_widget_key(widget_key: str) -> dict[str, Any]:
    """Parse ``rec_card_queue_{room}_{pick}_{player_id}_rec_card`` when present."""
    key = str(widget_key or "").strip()
    m = _REC_CARD_QUEUE_KEY.match(key)
    if not m:
        return {"ok": False, "widget_key": key, "room_id": "", "pick_index": None, "player_id": ""}
    return {
        "ok": True,
        "widget_key": key,
        "room_id": str(m.group("room") or "").upper(),
        "pick_index": int(m.group("pick")),
        "player_id": str(m.group("player_id") or ""),
    }


def _norm_name(value: Any) -> str:
    return str(value or "").strip()


def _name_key(value: Any) -> str:
    return _norm_name(value).lower()


def _norm_room(value: Any) -> str:
    return str(value or "").strip().upper()


def _pick_equal(a: Any, b: Any) -> bool:
    if a in (None, "") or b in (None, ""):
        return False
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def authorize_seed_widget_identity(
    step: dict[str, Any],
    *,
    candidate: dict[str, Any] | None = None,
    expected_room_id: str = "",
    expected_pick_index: Any = None,
) -> dict[str, Any]:
    """Fail closed before click unless render-trace widget key is current and correlated.

    Never authorizes on name/position/button-text alone.
    """
    failures: list[str] = []
    cand = dict(candidate or step.get("pre_click_record") or {})
    trace = step.get("app_render_trace") if isinstance(step.get("app_render_trace"), dict) else {}
    intended = _norm_name(step.get("intended_player") or step.get("player_name") or cand.get("player_name"))
    key = _norm_name(step.get("expected_widget_key") or trace.get("widget_key"))
    out: dict[str, Any] = {
        "ok": False,
        "authorized_rec_card_key": "",
        "player_name": intended,
        "player_id": str(trace.get("player_id") or ""),
        "room_id": _norm_room(trace.get("room_id")),
        "pick_index": trace.get("pick_index"),
        "widget_liveness": str(
            step.get("render_trace_widget_liveness") or trace.get("widget_liveness") or ""
        ).strip(),
        "failures": failures,
        "classification": QUEUE1C3A2K,
        "paused_compatible": True,
    }
    if not step.get("render_trace_present") and not (trace.get("widget_key") or key):
        failures.append("render_trace_missing")
    if not key:
        failures.append("widget_key_missing")
    if not intended:
        failures.append("player_name_missing")
    if _name_key(cand.get("player_name")) and _name_key(cand.get("player_name")) != _name_key(intended):
        failures.append("candidate_player_mismatch")
    if _name_key(trace.get("player_name")) and _name_key(trace.get("player_name")) != _name_key(intended):
        failures.append("trace_player_mismatch")
    live = str(out["widget_liveness"] or "").strip().lower()
    if live == "stale_retained_dom":
        failures.append("stale_widget_liveness")
    if live and live not in ("live_this_run", "live", ""):
        # Unknown non-live markers fail closed when explicitly non-live.
        if "stale" in live or "retained" in live:
            failures.append("stale_widget_liveness")
    parsed = parse_rec_card_queue_widget_key(key)
    if key and not parsed.get("ok"):
        failures.append("widget_key_unparseable")
    if parsed.get("ok"):
        if _norm_room(trace.get("room_id")) and _norm_room(trace.get("room_id")) != parsed["room_id"]:
            failures.append("widget_key_room_mismatch")
        if trace.get("pick_index") not in (None, "") and not _pick_equal(
            trace.get("pick_index"), parsed["pick_index"]
        ):
            failures.append("widget_key_pick_mismatch")
        if str(trace.get("player_id") or "").strip() and str(trace.get("player_id")).strip() != str(
            parsed["player_id"]
        ):
            failures.append("widget_key_player_id_mismatch")
        out["room_id"] = parsed["room_id"] or out["room_id"]
        out["pick_index"] = parsed["pick_index"] if parsed.get("pick_index") is not None else out["pick_index"]
        out["player_id"] = str(parsed["player_id"] or out["player_id"])
    want_room = _norm_room(expected_room_id)
    if want_room and out["room_id"] and want_room != out["room_id"]:
        failures.append("stale_room")
    if expected_pick_index not in (None, "") and out["pick_index"] not in (None, ""):
        if not _pick_equal(expected_pick_index, out["pick_index"]):
            failures.append("stale_pick")
    # Candidate must map to intended rec card when it already carries a widget_key.
    cand_key = _norm_name(cand.get("widget_key"))
    if cand_key and key and cand_key != key:
        failures.append("candidate_widget_key_mismatch")
    if failures:
        out["failures"] = failures
        return out
    out["ok"] = True
    out["authorized_rec_card_key"] = key
    out["classification"] = ""
    out["failures"] = []
    return out


def map_widget_consumption_ack(delivery: dict[str, Any] | None) -> dict[str, Any]:
    """Generic Stage1 semantic over shared Francisco-named consumption evaluator."""
    detail = dict(delivery or {})
    ack = detail.get("consumption_ack") if isinstance(detail.get("consumption_ack"), dict) else {}
    widget_ack = bool(
        ack.get("francisco_widget_consumption_ack")
        or ack.get("widget_consumption_ack")
        or ack.get("ok")
    )
    click_dispatched = bool(detail.get("click_dispatched") or ack.get("click_dispatched"))
    generic_only = bool(ack.get("generic_streamlit_traffic_observed")) and not widget_ack
    return {
        "click_dispatched": click_dispatched,
        "widget_consumption_ack": widget_ack,
        "francisco_widget_consumption_ack": bool(ack.get("francisco_widget_consumption_ack")),
        "authorized_rec_card_key": str(
            ack.get("authorized_rec_card_key") or detail.get("authorized_rec_card_key") or ""
        ),
        "generic_streamlit_traffic_observed": bool(ack.get("generic_streamlit_traffic_observed")),
        "generic_ws_satisfies_ack": False,
        "generic_only_traffic": generic_only,
        "classification": str(ack.get("classification") or ""),
        "ok": bool(click_dispatched and widget_ack),
    }


def evaluate_seed_queue_membership_delta(
    *,
    queue_before: list[Any] | None,
    session_after: list[Any] | None,
    canonical_after: list[Any] | None,
    player_name: str,
) -> dict[str, Any]:
    """Require authoritative +1 of the intended player with session==canonical and no removals."""
    before = [_norm_name(x) for x in list(queue_before or []) if _norm_name(x)]
    session = (
        [_norm_name(x) for x in list(session_after or []) if _norm_name(x)]
        if session_after is not None
        else None
    )
    canonical = (
        [_norm_name(x) for x in list(canonical_after or []) if _norm_name(x)]
        if canonical_after is not None
        else None
    )
    want = _norm_name(player_name)
    failures: list[str] = []
    if session is None or canonical is None:
        failures.append("authoritative_queues_unavailable")
    if session is not None and canonical is not None and session != canonical:
        failures.append("session_canonical_disagreement")
    after = session if session is not None else canonical
    if after is None:
        return {
            "ok": False,
            "failures": failures or ["authoritative_queues_unavailable"],
            "queue_before": before,
            "session_after": session,
            "canonical_after": canonical,
            "expected_after": before + ([want] if want else []),
        }
    expected = before + ([want] if want else [])
    if not want:
        failures.append("player_name_missing")
    if len(after) != len(before) + 1:
        failures.append("length_not_plus_one")
    added = [n for n in after if _name_key(n) not in {_name_key(x) for x in before}]
    removed = [n for n in before if _name_key(n) not in {_name_key(x) for x in after}]
    if removed:
        failures.append("unexpected_removal")
    if len(added) != 1 or _name_key(added[0]) != _name_key(want):
        failures.append("intended_player_not_sole_addition")
    if after != expected:
        # Order must preserve prior seed order then append.
        failures.append("order_not_preserved")
    # Dedup: sole addition must not already be present.
    if sum(1 for n in after if _name_key(n) == _name_key(want)) != 1:
        failures.append("duplicate_or_missing_intended")
    return {
        "ok": not failures,
        "failures": failures,
        "queue_before": before,
        "session_after": session,
        "canonical_after": canonical,
        "expected_after": expected,
        "added": added,
        "removed": removed,
    }


STAGE1_SEED_POST_WAIT_MODULE_NAME = "stage1_seed_post_wait_shared"


def load_stage1_seed_post_wait_module(*, force_reload: bool = False):
    """Load Francisco post-wait helpers with sys.modules registration before exec.

    Python 3.13 ``@dataclass`` processing requires ``sys.modules[cls.__module__]``
    to exist during ``exec_module``. Omitting registration raises
    ``'NoneType' object has no attribute '__dict__'`` (BD5F1E7C production defect).

    On failed ``exec_module``, remove the just-created ``sys.modules`` entry only when
    this loader owns that binding (same object we inserted).
    """
    import importlib.util
    import sys
    from pathlib import Path

    name = STAGE1_SEED_POST_WAIT_MODULE_NAME
    if not force_reload and name in sys.modules:
        existing = sys.modules[name]
        if callable(getattr(existing, "wait_for_authoritative_post_queue_scrape", None)) and callable(
            getattr(existing, "select_authoritative_post_queues", None)
        ):
            return existing

    root = Path(__file__).resolve().parents[1]
    path = root / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError("francisco_post_wait_module_unavailable")
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec_module — required for dataclass-bearing modules (Py3.13).
    previous = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # Cleanup only the binding we just created/overwrote with this incomplete mod.
        if sys.modules.get(name) is mod:
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous
        raise
    if not callable(getattr(mod, "wait_for_authoritative_post_queue_scrape", None)):
        if sys.modules.get(name) is mod:
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous
        raise ImportError("wait_for_authoritative_post_queue_scrape_unresolved")
    if not callable(getattr(mod, "select_authoritative_post_queues", None)):
        if sys.modules.get(name) is mod:
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous
        raise ImportError("select_authoritative_post_queues_unresolved")
    return mod


def prove_seed_membership_after_click(
    page,
    *,
    queue_before: list[str],
    player_name: str,
    room_id: str = "",
    production_sid: str = "",
    click_ts: float | None = None,
    timeout_s: float = 45.0,
    scrape_container_fn=None,
    membership_wait_fn=None,
) -> dict[str, Any]:
    """Wait for authoritative later POST (+ session/canonical agreement), not UI-sleep alone."""
    before = [_norm_name(x) for x in list(queue_before or []) if _norm_name(x)]
    if membership_wait_fn is not None:
        waited = membership_wait_fn(
            page,
            queue_before=before,
            player_name=player_name,
            room_id=room_id,
            production_sid=production_sid,
            click_ts=click_ts,
            timeout_s=timeout_s,
        )
        delta = evaluate_seed_queue_membership_delta(
            queue_before=before,
            session_after=waited.get("session_queue"),
            canonical_after=waited.get("canonical_queue"),
            player_name=player_name,
        )
        return {
            **delta,
            "post_wait": waited,
            "stale_baseline_rejected": bool(waited.get("stale_baseline_rejected")),
            "authoritative": True,
        }

    # Default: reuse Francisco proof post-wait + selection (shared architecture, not Francisco-only).
    try:
        sid = str(production_sid or "").strip()
        room = str(room_id or "").strip()
        if (not sid or not room) and page is not None:
            try:
                from live_draft_queue_state_snapshot_diag import scrape_queue_state_snapshot_from_page

                scraped0 = scrape_queue_state_snapshot_from_page(page)
                payload0 = scraped0.get("payload") if isinstance(scraped0.get("payload"), dict) else {}
                baseline0 = payload0.get("baseline") if isinstance(payload0.get("baseline"), dict) else {}
                if not sid:
                    sid = str(
                        scraped0.get("sid")
                        or baseline0.get("streamlit_session_id")
                        or ""
                    ).strip()
                if not room:
                    room = str(scraped0.get("room_id") or baseline0.get("room_id") or "").strip()
            except Exception:
                pass

        mod = load_stage1_seed_post_wait_module()
        post_wait = mod.wait_for_authoritative_post_queue_scrape(
            page,
            production_sid=sid,
            room_id=room,
            after_ts=click_ts,
            timeout_s=timeout_s,
        )
        selected = mod.select_authoritative_post_queues(
            production_sid=sid,
            room_id=room,
            after_ts=click_ts,
            snapshots=[post_wait.get("accepted_post")]
            if isinstance(post_wait.get("accepted_post"), dict)
            else None,
            ui_queue=None,
        )
        delta = evaluate_seed_queue_membership_delta(
            queue_before=before,
            session_after=selected.get("session_queue"),
            canonical_after=selected.get("canonical_queue"),
            player_name=player_name,
        )
        return {
            **delta,
            "post_wait": post_wait,
            "authoritative_post": selected,
            "stale_baseline_rejected": bool(post_wait.get("stale_baseline_only"))
            or str(selected.get("rejection") or "") == "stale_baseline_cannot_act_as_post",
            "authoritative": True,
        }
    except Exception as exc:
        # Fail closed — do not invent membership from UI-only scrape.
        ui_names: list[str] = []
        if scrape_container_fn is not None:
            try:
                snap = _snapshot_queue(page, scrape_container_fn)
                ui_names = list(snap.get("queue_names") or [])
            except Exception:
                ui_names = []
        return {
            "ok": False,
            "failures": ["authoritative_post_wait_unavailable", str(exc)[:160]],
            "queue_before": before,
            "session_after": None,
            "canonical_after": None,
            "ui_queue": ui_names,
            "stale_baseline_rejected": False,
            "authoritative": False,
        }


def seed_queue_distinct_players(
    page,
    *,
    scrape_container_fn,
    min_players: int = 3,
    mutation_wait_s: float = 5.0,
    expected_room_id: str = "",
    expected_pick_index: Any = None,
    production_sid: str = "",
    deliver_fn=None,
    discover_fn=None,
    select_fn=None,
    render_trace_fn=None,
    membership_wait_fn=None,
    membership_timeout_s: float = 45.0,
) -> dict[str, Any]:
    """Rediscover → authorize widget key → one click → consumption ack → +1 membership."""
    import os

    from stage1_add_to_queue_delivery import (
        deliver_add_to_queue_click,
        discover_bound_add_to_queue_controls,
        select_next_seed_candidate,
    )

    preferred_player = str(os.environ.get("STAGE1_SEED_PLAYER_NAME") or "").strip()
    deliver = deliver_fn or deliver_add_to_queue_click
    discover = discover_fn or discover_bound_add_to_queue_controls
    select = select_fn or select_next_seed_candidate
    t0 = time.time()
    before_all = _snapshot_queue(page, scrape_container_fn)
    # Injectable discovery ports skip the live control wait (browser-free tests / harness probes).
    if discover_fn is not None:
        control_wait = {
            "ok": True,
            "add_to_queue_button_count": max(min_players, 1),
            "injected": True,
        }
    else:
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
    proven_order: list[str] = []

    while len([s for s in seed_steps if s.get("mutation_proven")]) < min_players:
        candidates = discover(page)
        traces: list[dict[str, Any]] = []
        try:
            from stage1_add_to_queue_delivery import enrich_seed_candidates_from_render_traces
            from stage1_rec_queue_click_trace_scrape import scrape_rec_queue_render_trace_nodes

            scraped = scrape_rec_queue_render_trace_nodes(page, player_name="")
            if isinstance(scraped, list):
                traces.extend(
                    [
                        t
                        for t in scraped
                        if isinstance(t, dict) and not t.get("error") and (t.get("player_name") or t.get("player_id"))
                    ]
                )
        except Exception:
            pass
        if not traces and render_trace_fn is not None:
            # Test/harness injectables: enrich from the same render-trace authority used post-select.
            seen_names: set[str] = set()
            for c in candidates:
                name = str(c.get("player_name") or "").strip()
                if not name or name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())
                try:
                    row = render_trace_fn(page, player_name=name)
                except TypeError:
                    try:
                        row = render_trace_fn(page)
                    except Exception:
                        row = None
                except Exception:
                    row = None
                if isinstance(row, dict) and row and not row.get("error"):
                    traces.append(row)
        try:
            from stage1_add_to_queue_delivery import enrich_seed_candidates_from_render_traces

            candidates = enrich_seed_candidates_from_render_traces(candidates, traces)
        except Exception:
            pass
        discovery_snapshots.append(
            {
                "ts": time.time(),
                "control_count": len(candidates),
                "named_unique": sum(
                    1 for c in candidates if c.get("binding_confidence") == "unique" and c.get("player_name")
                ),
                "structured_eligible": sum(
                    1
                    for c in candidates
                    if c.get("binding_confidence") == "unique"
                    and str(c.get("player_id") or "").strip().isdigit()
                    and str(c.get("player_name") or "").strip()
                ),
                "candidates": candidates[:10],
            }
        )
        pick, reject = select(
            candidates,
            exclude_player_names=queued_names,
            preferred_player_name=preferred_player,
        )
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
        # Authoritative baseline for this seed slot is prior proven order (supports []→[A]→…).
        queue_before = list(proven_order) if proven_order else list(pre.get("queue_names") or [])
        step: dict[str, Any] = {
            "player_name": player_name,
            "intended_player": player_name,
            "pre_click_record": pick,
            "queue_before": queue_before,
            "started_ts": time.time(),
            "helper_invocations": 0,
            "browser_clicks": 0,
            "retry": 0,
            "playwright_only": True,
            "js_fallback_used": False,
        }
        try:
            from stage1_rec_queue_click_trace_scrape import merge_render_trace_into_step, scrape_rec_queue_render_trace

            trace_fn = render_trace_fn or scrape_rec_queue_render_trace
            merge_render_trace_into_step(step, trace_fn(page, player_name=player_name))
        except ImportError:
            pass
        try:
            expected_help = str(os.environ.get("STAGE1_REC_QUEUE_HELP_VARIANT") or "").strip().lower()
            if expected_help in ("with_help", "no_help"):
                trace = step.get("app_render_trace") if isinstance(step.get("app_render_trace"), dict) else {}
                got_variant = str(trace.get("help_variant") or step.get("render_trace_help_variant") or "").strip().lower()
                want_present = expected_help == "with_help"
                got_present_raw = trace.get("help_present", step.get("render_trace_help_present"))
                got_present = got_present_raw in (True, "1", 1, "true")
                step["help_variant_expected"] = expected_help
                step["help_variant_observed"] = got_variant
                step["help_present_observed"] = got_present
                if got_variant != expected_help or got_present != want_present:
                    step["classification"] = "ABORTED_REC_QUEUE_HELP_VARIANT"
                    step["help_variant_binding_pass"] = False
                    step["click_dispatched"] = False
                    step["mutation_proven"] = False
                    step["mutation_observed"] = False
                    step["elapsed_s"] = time.time() - float(step["started_ts"])
                    seed_steps.append(step)
                    fail_classification = "ABORTED_REC_QUEUE_HELP_VARIANT"
                    break
                step["help_variant_binding_pass"] = True
        except Exception:
            pass
        if not step.get("render_trace_present"):
            step["classification"] = "QUEUE1C3A5"
            step["click_dispatched"] = False
            step["mutation_proven"] = False
            step["mutation_observed"] = False
            step["elapsed_s"] = time.time() - float(step["started_ts"])
            seed_steps.append(step)
            fail_classification = "QUEUE1C3A5"
            break

        authz = authorize_seed_widget_identity(
            step,
            candidate=pick,
            expected_room_id=expected_room_id,
            expected_pick_index=expected_pick_index,
        )
        step["widget_authorization"] = authz
        step["authorized_rec_card_key"] = str(authz.get("authorized_rec_card_key") or "")
        if not authz.get("ok"):
            step["classification"] = QUEUE1C3A2K
            step["click_dispatched"] = False
            step["mutation_proven"] = False
            step["mutation_observed"] = False
            step["widget_consumption_ack"] = False
            step["elapsed_s"] = time.time() - float(step["started_ts"])
            seed_steps.append(step)
            fail_classification = QUEUE1C3A2K
            break

        authorized_key = str(authz["authorized_rec_card_key"])
        room_for_wait = str(authz.get("room_id") or expected_room_id or "")
        delivery = deliver(
            page,
            pick,
            playwright_only=True,
            authorized_rec_card_key=authorized_key,
        )
        step["helper_invocations"] = 1
        step["delivery_detail"] = delivery
        step["delivery_method"] = delivery.get("delivery_method") or ""
        step["click_dispatched"] = bool(delivery.get("click_dispatched"))
        step["browser_clicks"] = 1 if step["click_dispatched"] else 0
        step["js_fallback_used"] = str(step["delivery_method"]).startswith("js_")
        step["pre_click_run_binding"] = delivery.get("pre_click_run_binding")
        step["live_reacquired_before_click"] = bool(delivery.get("live_reacquired_before_click"))
        step["live_reacquisition_probe"] = delivery.get("live_reacquisition_probe")
        ack_map = map_widget_consumption_ack(delivery)
        step["consumption_ack"] = delivery.get("consumption_ack")
        step["widget_consumption_ack"] = bool(ack_map.get("widget_consumption_ack"))
        step["widget_consumption"] = ack_map

        pre_bind = step.get("pre_click_run_binding") if isinstance(step.get("pre_click_run_binding"), dict) else {}
        if pre_bind.get("run_binding_consistent") is False:
            step["classification"] = "QUEUE1C3A2O1"
            step["mutation_proven"] = False
            step["mutation_observed"] = False
            step["elapsed_s"] = time.time() - float(step["started_ts"])
            seed_steps.append(step)
            fail_classification = "QUEUE1C3A2O1"
            break
        if delivery.get("dom_capture_observability_failed"):
            step["classification"] = "QUEUE1C3A2O2"
            step["mutation_proven"] = False
            step["mutation_observed"] = False
            step["elapsed_s"] = time.time() - float(step["started_ts"])
            seed_steps.append(step)
            fail_classification = "QUEUE1C3A2O2"
            break
        if not step["click_dispatched"]:
            step["classification"] = classify_queue1c_subcode(step)
            step["mutation_proven"] = False
            step["mutation_observed"] = False
            step["elapsed_s"] = time.time() - float(step["started_ts"])
            seed_steps.append(step)
            fail_classification = step["classification"]
            break
        if not step["widget_consumption_ack"]:
            step["classification"] = STAGE1_QUEUE_SEED_WIDGET_CONSUMPTION_BOUNDARY
            step["mutation_proven"] = False
            step["mutation_observed"] = False
            step["elapsed_s"] = time.time() - float(step["started_ts"])
            seed_steps.append(step)
            fail_classification = STAGE1_QUEUE_SEED_WIDGET_CONSUMPTION_BOUNDARY
            break

        click_ts = delivery.get("click_start_ts") or delivery.get("click_end_ts") or time.time()
        membership = prove_seed_membership_after_click(
            page,
            queue_before=queue_before,
            player_name=player_name,
            room_id=room_for_wait,
            production_sid=production_sid,
            click_ts=float(click_ts) if click_ts is not None else None,
            timeout_s=membership_timeout_s,
            scrape_container_fn=scrape_container_fn,
            membership_wait_fn=membership_wait_fn,
        )
        # Keep short UI poll as corroboration only — never sole authority.
        try:
            page.wait_for_timeout(400)
            mut = _poll_queue_mutation(
                page,
                scrape_container_fn,
                queue_before=queue_before,
                player_name=player_name,
                timeout_s=max(min(mutation_wait_s, 3.0), 1.0),
            )
        except Exception:
            mut = {"mutation_observed": False, "queue_after": list(queue_before)}
        try:
            from stage1_rec_queue_click_trace_scrape import merge_app_trace_into_step, scrape_rec_queue_app_trace

            merge_app_trace_into_step(step, scrape_rec_queue_app_trace(page))
        except ImportError:
            pass
        step["membership_proof"] = membership
        step["queue_after"] = list(
            membership.get("session_after")
            or membership.get("canonical_after")
            or mut.get("queue_after")
            or []
        )
        step["visible_confirmation"] = bool(mut.get("visible_confirmation"))
        step["structured_confirmation"] = bool(mut.get("structured_confirmation"))
        step["mutation_observed"] = bool(membership.get("ok"))
        step["mutation_proven"] = bool(membership.get("ok"))
        step["stale_baseline_rejected"] = bool(membership.get("stale_baseline_rejected"))
        step["elapsed_s"] = time.time() - float(step["started_ts"])
        if not step["mutation_proven"]:
            step["classification"] = STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY
            seed_steps.append(step)
            fail_classification = STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY
            break
        proven_order = list(step["queue_after"])
        queued_names.add(player_name.lower())
        seed_steps.append(step)
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass

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
        seed_source="rediscover_authorize_deliver_ack_membership_loop",
        extra={
            "intended_players_before_clicks": [
                {
                    "player_name": s.get("player_name"),
                    "pre_click_global_index": (s.get("pre_click_record") or {}).get("global_index"),
                    "authorized_rec_card_key": s.get("authorized_rec_card_key"),
                }
                for s in seed_steps
            ],
            "candidates_discovered": discovery_snapshots[-1]["control_count"] if discovery_snapshots else 0,
            "proven_queue_order_authoritative": list(proven_order),
        },
    )
    if fail_classification and not meta.get("ok"):
        meta["classification"] = fail_classification
    return meta
