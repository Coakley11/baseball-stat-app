"""Stage 1A-QUEUE harness ordering and evidence (no app behavior changes)."""

from __future__ import annotations

import re
from typing import Any

# Authoritative harness step order after Start/latch succeeds.
QUEUE_SETUP_ORDER_AFTER_START: tuple[str, ...] = (
    "room_latch_proof",
    "immediate_pause",
    "active_page_gate_while_paused",
    "queue_seed_while_paused",
    "queue_verification_while_paused",
    "pick_index_zero_confirm",
    "resume_after_queue_proven",
    "wait_real_expiration",
)


def parse_pick_index_from_expire_token(token: str) -> int | None:
    tok = str(token or "").strip()
    if "|" not in tok:
        return None
    parts = tok.split("|")
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except (TypeError, ValueError):
        return None


def visible_queue_names_from_excerpt(excerpt: str) -> list[str]:
    """Name-only lines in Draft queue UI (harness; not structured scraper)."""
    lines = [ln.strip() for ln in str(excerpt or "").splitlines() if ln.strip()]
    skip = re.compile(
        r"^(Draft queue|Clear Draft Queue|Watchlist|Empty|Tracked players|Recently viewed|"
        r"Command Center|keyboard_arrow|solo-deploy|Stop$|Fork$|✕|×|Saved session)",
        re.I,
    )
    name_only = re.compile(r"^[A-Z][A-Za-z .'-]{2,48}$")
    out: list[str] = []
    in_queue = False
    for ln in lines:
        if re.match(r"^Draft queue", ln, re.I):
            in_queue = True
            continue
        if in_queue and re.match(r"^Clear Draft Queue", ln, re.I):
            break
        if not in_queue:
            continue
        if skip.match(ln):
            continue
        if name_only.match(ln):
            out.append(ln)
    return out


def build_queue_evidence_hierarchy(
    queue_meta: dict[str, Any],
    *,
    min_players: int = 3,
) -> dict[str, Any]:
    """Separate deliberate clicks, visible queue text, and structured scraper."""
    adds = list(queue_meta.get("add_actions") or [])
    click_count = sum(1 for a in adds if a.get("clicked"))
    excerpt = str(queue_meta.get("queue_excerpt_before") or queue_meta.get("queue_excerpt") or "")
    visible = visible_queue_names_from_excerpt(excerpt)
    structured = [str(n or "").strip() for n in (queue_meta.get("queue_order") or []) if str(n or "").strip()]
    container = queue_meta.get("queue_container") if isinstance(queue_meta.get("queue_container"), dict) else {}
    if not structured:
        structured = [
            str(p.get("name") or "").strip()
            for p in list(container.get("players") or [])
            if str(p.get("name") or "").strip()
        ]
    deliberate_ok = click_count >= min_players
    visible_ok = len(visible) >= min_players
    structured_ok = len(structured) >= min_players
    proven = deliberate_ok and (visible_ok or structured_ok)
    scraper_gap = deliberate_ok and visible_ok and not structured_ok
    return {
        "deliberate_add_clicks_succeeded": deliberate_ok,
        "deliberate_add_click_count": click_count,
        "min_players_required": min_players,
        "visible_queue_player_names": visible[:8],
        "visible_queue_satisfied": visible_ok,
        "structured_scraper_names": structured[:8],
        "structured_scraper_satisfied": structured_ok,
        "queue_setup_proven": proven,
        "harness_scraper_observation_gap": scraper_gap,
        "classification_if_fails": "HARNESS_SCRAPER_GAP" if scraper_gap else "",
    }


def pick_index_zero_from_observation(obs: dict[str, Any]) -> bool:
    try:
        pick_i = int(obs.get("pick_index")) if obs.get("pick_index") not in (None, "") else None
    except (TypeError, ValueError):
        pick_i = None
    if pick_i == 0:
        return True
    tok = str(obs.get("pick0_token_ui") or "")
    parsed = parse_pick_index_from_expire_token(tok)
    return parsed == 0
