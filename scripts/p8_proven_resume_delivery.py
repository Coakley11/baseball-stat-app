"""Frame-aware Resume Draft delivery for Stage 1A-QUEUE (mirrors proven Pause frame order)."""

from __future__ import annotations

import re
import time
from typing import Any, Callable

# Product control: live_draft_control_center_ui.py — st.button("▶ Resume Draft", key="live_draft_resume")
RESUME_BUTTON_LABEL = "Resume Draft"
RESUME_BUTTON_KEY = "live_draft_resume"
# Sidebar navigation — NOT timer resume authority
SIDEBAR_RESUME_LABEL = "Resume Live Draft"

RESUME_DELIVERY_RESOLVED = "RESUME_DELIVERY_RESOLVED"
RESUME_CONTROL_NOT_FOUND = "resume_control_not_found"
RESUME_CONTROL_DISABLED = "resume_control_disabled"
RESUME_WRONG_ROOM = "resume_wrong_room"
RESUME_NOT_PAUSED = "resume_not_paused"
RESUME_POSTCONDITION_NOT_PROVEN = "resume_postcondition_not_proven"
RESUME_QUEUE_SEED_NOT_RESOLVED = "resume_queue_seed_not_resolved"
RESUME_AMBIGUOUS_CONTROLS = "resume_ambiguous_controls"
RESUME_PAGE_CLOSED = "resume_page_closed"
# Alias retained for artifact continuity with prior abort string
NO_RESUME_CONTROL = "no_resume_control"

# Canonical timer-resume matcher: "Resume Draft" / "▶ Resume Draft"; exclude sidebar.
_RESUME_NAME_RE = re.compile(r"(?:^|[^a-zA-Z])Resume Draft\b", re.I)
_SIDEBAR_RESUME_RE = re.compile(r"Resume Live Draft", re.I)

_RESUME_PROBE_JS = """() => {
  const resumeRe = /Resume Draft/i;
  const sidebarRe = /Resume Live Draft/i;
  function probeDoc(doc, frameUrl, frameIndex) {
    let resumeCount = 0, resumeEnabled = 0, resumeDisabled = 0;
    let sidebarResumeCount = 0;
    const candidates = [];
    for (const b of doc.querySelectorAll('button')) {
      const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!t) continue;
      if (sidebarRe.test(t)) {
        sidebarResumeCount += 1;
        continue;
      }
      if (!resumeRe.test(t)) continue;
      const r = b.getBoundingClientRect();
      const visible = r.width > 0 && r.height > 0;
      if (!visible) continue;
      resumeCount += 1;
      const disabled = !!b.disabled;
      if (disabled) resumeDisabled += 1;
      else resumeEnabled += 1;
      candidates.push({ text: t.slice(0, 80), disabled: disabled, visible: true });
    }
    const hasLedger = !!doc.querySelector(
      '#solo-stage1-current-run-diag, #solo-stage1-production-ledger, #solo-production-ledger-diag'
    );
    const isAppFrame = String(frameUrl || '').includes('/~/+/');
    return {
      frameIndex,
      frameUrl: frameUrl || '',
      resumeCount,
      resumeEnabled,
      resumeDisabled,
      sidebarResumeCount,
      candidates,
      hasLedger,
      isAppFrame,
    };
  }
  const out = [probeDoc(document, location.href || '', 0)];
  let idx = 1;
  for (const f of document.querySelectorAll('iframe')) {
    try {
      if (f.contentDocument) out.push(probeDoc(f.contentDocument, f.src || '', idx));
    } catch (e) {}
    idx += 1;
  }
  return out;
}"""


def is_timer_resume_label(text: str) -> bool:
    """True for product timer Resume; false for sidebar 'Resume Live Draft'."""
    t = str(text or "").replace("\u25b6", "").replace("▶", "").strip()
    if _SIDEBAR_RESUME_RE.search(t):
        return False
    return bool(re.search(r"Resume Draft", t, re.I))


def inventory_resume_controls_from_probes(probes: list[dict[str, Any]]) -> dict[str, Any]:
    """Safe pre-click inventory from frame probes (no secrets)."""
    frames_out: list[dict[str, Any]] = []
    total_enabled = 0
    total_disabled = 0
    total_sidebar = 0
    for p in probes or []:
        if not isinstance(p, dict):
            continue
        en = int(p.get("resumeEnabled") or 0)
        dis = int(p.get("resumeDisabled") or 0)
        side = int(p.get("sidebarResumeCount") or 0)
        total_enabled += en
        total_disabled += dis
        total_sidebar += side
        frames_out.append(
            {
                "frame_index": p.get("frameIndex"),
                "frame_url": str(p.get("frameUrl") or "")[:200],
                "isAppFrame": bool(p.get("isAppFrame")),
                "hasLedger": bool(p.get("hasLedger")),
                "resumeCount": int(p.get("resumeCount") or 0),
                "resumeEnabled": en,
                "resumeDisabled": dis,
                "sidebarResumeCount": side,
                "candidates": list(p.get("candidates") or [])[:8],
            }
        )
    return {
        "frame_probes": frames_out,
        "resume_enabled_total": total_enabled,
        "resume_disabled_total": total_disabled,
        "sidebar_resume_total": total_sidebar,
        "app_iframe_resume_enabled": sum(
            int(f.get("resumeEnabled") or 0) for f in frames_out if f.get("isAppFrame") or f.get("hasLedger")
        ),
        "main_shell_resume_enabled": sum(
            int(f.get("resumeEnabled") or 0)
            for f in frames_out
            if not f.get("isAppFrame") and not f.get("hasLedger")
        ),
    }


def select_authoritative_resume_probe(probes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Prefer app iframe / ledger frame with exactly one enabled timer-Resume control.
    Fail closed on ambiguity across multiple enabled app-frame controls without authority.
    """
    out: dict[str, Any] = {
        "ok": False,
        "boundary": RESUME_CONTROL_NOT_FOUND,
        "preferred": None,
        "inventory": inventory_resume_controls_from_probes(probes),
    }
    enabled_app: list[dict[str, Any]] = []
    enabled_any: list[dict[str, Any]] = []
    disabled_only_app: list[dict[str, Any]] = []
    for p in probes or []:
        if not isinstance(p, dict):
            continue
        en = int(p.get("resumeEnabled") or 0)
        dis = int(p.get("resumeDisabled") or 0)
        appish = bool(p.get("isAppFrame") or p.get("hasLedger"))
        if en > 0:
            enabled_any.append(p)
            if appish:
                enabled_app.append(p)
        elif dis > 0 and appish:
            disabled_only_app.append(p)

    if not enabled_any and disabled_only_app:
        out["boundary"] = RESUME_CONTROL_DISABLED
        out["preferred"] = disabled_only_app[0]
        return out
    if not enabled_any:
        out["boundary"] = RESUME_CONTROL_NOT_FOUND
        # Preserve historical alias for missing control
        out["resume_error"] = NO_RESUME_CONTROL
        return out

    # Never treat shell-only as sufficient when an app frame exists in inventory
    pool = enabled_app if enabled_app else []
    if not pool:
        # Shell has a match but no app iframe candidate — fail closed (main-frame-only trap)
        out["boundary"] = RESUME_CONTROL_NOT_FOUND
        out["resume_error"] = NO_RESUME_CONTROL
        out["reject_reason"] = "main_shell_only_resume_rejected"
        return out

    # Prefer ledger-bearing app frame
    ledger = [p for p in pool if p.get("hasLedger")]
    chosen_pool = ledger if ledger else pool

    # Ambiguity: multiple frames each with enabled resume
    if len(chosen_pool) > 1:
        # Deterministic: prefer highest resumeEnabled on isAppFrame, then first
        chosen_pool = sorted(
            chosen_pool,
            key=lambda p: (int(p.get("resumeEnabled") or 0), 1 if p.get("isAppFrame") else 0),
            reverse=True,
        )
    preferred = chosen_pool[0]
    # Within one frame, more than one enabled Resume is ambiguous
    if int(preferred.get("resumeEnabled") or 0) > 1:
        out["boundary"] = RESUME_AMBIGUOUS_CONTROLS
        out["preferred"] = preferred
        return out

    out["ok"] = True
    out["boundary"] = ""
    out["preferred"] = preferred
    return out


def _ordered_resume_click_frames(page, preferred_probe: dict[str, Any] | None = None):
    """
    Deterministic frame order for Resume click — mirrors pause helper structure.

    Reuses pause's ``_ordered_pause_click_frames`` URL-preference pattern when a
    preferred resume frame URL is known; otherwise falls back to app-iframe-first
    ordering from Playwright frame list.
    """
    from p8_proven_pause_delivery import _ordered_pause_click_frames

    preferred_url = str((preferred_probe or {}).get("frameUrl") or "")
    frames = list(page.frames)
    if preferred_url:
        # Same URL-prefix preferencing as pause
        matched = [f for f in frames if preferred_url.split("?")[0] in (f.url or "")]
        rest = [f for f in frames if f not in matched]
        return matched + rest

    # App iframe first, then remaining (never treat shell-only as sufficient by default)
    appish = [f for f in frames if "/~/+/" in (f.url or "")]
    rest = [f for f in frames if f not in appish]
    if appish:
        return appish + rest
    # Fall back to pause ordering (ledger preference) when no ~/+/ URL
    return _ordered_pause_click_frames(page)


def scrape_resume_frame_probes(page) -> list[dict[str, Any]]:
    try:
        return list(page.evaluate(_RESUME_PROBE_JS) or [])
    except Exception:
        return []


def inventory_resume_controls(page) -> dict[str, Any]:
    return inventory_resume_controls_from_probes(scrape_resume_frame_probes(page))


def _legacy_main_frame_only_resume_click(page) -> dict[str, Any]:
    """Historical defective path — main frame only. Kept for regression fixtures."""
    out: dict[str, Any] = {"attempted": True, "resumed": False, "legacy_main_frame_only": True}
    for label in (r"Resume Draft", r"Resume", r"Unpause"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=4000)
            out["resumed"] = True
            out["resume_label"] = label
            return out
        except Exception:
            continue
    out["resume_error"] = NO_RESUME_CONTROL
    out["resume_boundary"] = RESUME_CONTROL_NOT_FOUND
    return out


def _postcondition_resume_ok(
    *,
    pre: dict[str, Any],
    post: dict[str, Any],
    expected_room_id: str,
    pre_queue: list[str] | None,
    post_queue: list[str] | None,
) -> dict[str, Any]:
    """
    Require: same room, left paused, timer running evidence, pick unchanged, queue unchanged.
    """
    exp = str(expected_room_id or "").strip().upper()
    pre_room = str(pre.get("room_id") or "").strip().upper()
    post_room = str(post.get("room_id") or "").strip().upper()
    if exp and post_room and post_room != exp:
        return {"ok": False, "boundary": RESUME_WRONG_ROOM, "detail": "post_room_mismatch"}
    if exp and pre_room and pre_room != exp:
        return {"ok": False, "boundary": RESUME_WRONG_ROOM, "detail": "pre_room_mismatch"}
    if pre_room and post_room and pre_room != post_room:
        return {"ok": False, "boundary": RESUME_WRONG_ROOM, "detail": "room_changed"}

    # Left paused: resume enabled should drop OR pause should become available OR explicit status
    still_paused = bool(post.get("paused"))
    if still_paused and post.get("status") not in ("in_progress", "running", ""):
        if post.get("status") == "paused" or (
            int(post.get("resume_enabled") or 0) >= 1 and int(post.get("pause_enabled") or 0) == 0
        ):
            return {"ok": False, "boundary": RESUME_POSTCONDITION_NOT_PROVEN, "detail": "still_paused"}

    if post.get("status") == "paused":
        return {"ok": False, "boundary": RESUME_POSTCONDITION_NOT_PROVEN, "detail": "status_still_paused"}

    # Timer running: deadline/remaining/timer field present after resume
    timer_ok = bool(
        post.get("timer_running")
        or post.get("timer")
        or post.get("deadline")
        or post.get("diag_deadline")
        or post.get("countdown_or_timer_present")
    )
    if not timer_ok and post.get("require_timer", True):
        # Soft: if status in_progress explicit, accept; else fail
        if post.get("status") not in ("in_progress", "running"):
            return {"ok": False, "boundary": RESUME_POSTCONDITION_NOT_PROVEN, "detail": "timer_not_running"}

    pre_pick = pre.get("pick_index")
    post_pick = post.get("pick_index")
    if pre_pick is not None and post_pick is not None and pre_pick != post_pick:
        return {"ok": False, "boundary": RESUME_POSTCONDITION_NOT_PROVEN, "detail": "pick_changed"}

    if pre_queue is not None and post_queue is not None:
        if list(pre_queue) != list(post_queue):
            return {"ok": False, "boundary": RESUME_POSTCONDITION_NOT_PROVEN, "detail": "queue_mutated"}

    return {"ok": True, "boundary": RESUME_DELIVERY_RESOLVED}


def proven_resume_single_click(
    page,
    *,
    expected_room_id: str = "",
    queue_seed_resolved: bool = True,
    paused: bool = True,
    authenticated: bool = True,
    pre_queue: list[str] | None = None,
    pre_pick_index: Any = 0,
    scrape_pre_state: Callable[[Any], dict[str, Any]] | None = None,
    scrape_post_state: Callable[[Any], dict[str, Any]] | None = None,
    scrape_queue: Callable[[Any], list[str]] | None = None,
    settle_ms: int = 1500,
) -> dict[str, Any]:
    """
    Frame-aware one-click Resume Draft with pre-click inventory and postcondition proof.

    Does NOT use JS synthetic click. Does NOT retry click. Does NOT mutate session/timer directly.
    """
    out: dict[str, Any] = {
        "attempted": True,
        "resumed": False,
        "resume_error": "",
        "resume_boundary": "",
        "click_dispatched": False,
        "trusted_playwright_click": False,
        "retry_click": False,
        "js_synthetic_click": False,
        "product_control": {
            "label": f"▶ {RESUME_BUTTON_LABEL}",
            "key": RESUME_BUTTON_KEY,
            "role": "button",
        },
    }

    if page is None:
        out["resume_boundary"] = RESUME_PAGE_CLOSED
        out["resume_error"] = RESUME_PAGE_CLOSED
        return out
    try:
        if getattr(page, "is_closed", lambda: False)():
            out["resume_boundary"] = RESUME_PAGE_CLOSED
            out["resume_error"] = RESUME_PAGE_CLOSED
            return out
    except Exception:
        pass

    if not queue_seed_resolved:
        out["resume_boundary"] = RESUME_QUEUE_SEED_NOT_RESOLVED
        out["resume_error"] = RESUME_QUEUE_SEED_NOT_RESOLVED
        return out
    if not paused:
        out["resume_boundary"] = RESUME_NOT_PAUSED
        out["resume_error"] = RESUME_NOT_PAUSED
        return out
    if not authenticated:
        out["resume_boundary"] = "resume_auth_invalid"
        out["resume_error"] = "resume_auth_invalid"
        return out

    probes = scrape_resume_frame_probes(page)
    selection = select_authoritative_resume_probe(probes)
    out["pre_click_inventory"] = selection.get("inventory") or inventory_resume_controls_from_probes(probes)
    out["selection"] = {
        "ok": selection.get("ok"),
        "boundary": selection.get("boundary"),
        "preferred_frame_url": str((selection.get("preferred") or {}).get("frameUrl") or "")[:200],
        "preferred_isAppFrame": bool((selection.get("preferred") or {}).get("isAppFrame")),
    }
    if not selection.get("ok"):
        boundary = str(selection.get("boundary") or RESUME_CONTROL_NOT_FOUND)
        out["resume_boundary"] = boundary
        out["resume_error"] = str(selection.get("resume_error") or boundary)
        return out

    preferred = selection.get("preferred") or {}
    # Room check via injectable / scrape_pre_state
    pre_state: dict[str, Any] = {
        "room_id": expected_room_id,
        "pick_index": pre_pick_index,
        "paused": True,
    }
    if scrape_pre_state is not None:
        try:
            pre_state.update(dict(scrape_pre_state(page) or {}))
        except Exception as exc:
            out["pre_state_error"] = str(exc)[:160]
    exp = str(expected_room_id or "").strip().upper()
    seen_room = str(pre_state.get("room_id") or "").strip().upper()
    if exp and seen_room and seen_room != exp:
        out["resume_boundary"] = RESUME_WRONG_ROOM
        out["resume_error"] = RESUME_WRONG_ROOM
        return out

    name_re = re.compile(r"Resume Draft", re.I)
    click_frame = None
    click_errors: list[str] = []
    for frame in _ordered_resume_click_frames(page, preferred):
        try:
            loc = frame.get_by_role("button", name=name_re)
            # Filter sidebar if Playwright exposes accessible name including Live
            count = int(loc.count())
            if count < 1:
                continue
            # Prefer first non-disabled matching timer resume (not sidebar)
            target = None
            for i in range(count):
                btn = loc.nth(i)
                try:
                    label = str(btn.inner_text(timeout=500) or "")
                except Exception:
                    label = ""
                if not is_timer_resume_label(label) and label:
                    # If empty text, still allow role name match from get_by_role(Resume Draft)
                    if _SIDEBAR_RESUME_RE.search(label):
                        continue
                if not is_timer_resume_label(label) and label and "Resume Draft" not in label.replace("▶", ""):
                    continue
                if _SIDEBAR_RESUME_RE.search(label):
                    continue
                try:
                    if btn.is_disabled():
                        out.setdefault("disabled_candidates", []).append(label[:80] or "Resume Draft")
                        continue
                except Exception:
                    pass
                target = btn
                out["resume_label"] = label[:80] or RESUME_BUTTON_LABEL
                break
            if target is None:
                if out.get("disabled_candidates"):
                    # Found only disabled in this frame — keep searching other frames
                    continue
                continue
            try:
                target.scroll_into_view_if_needed(timeout=8000)
            except Exception:
                pass
            # Exactly one trusted Playwright click — no force retry, no JS click
            target.click(timeout=12000)
            out["click_dispatched"] = True
            out["trusted_playwright_click"] = True
            out["click_frame_url"] = (frame.url or "")[:200]
            try:
                out["click_frame_index"] = page.frames.index(frame) if frame in page.frames else -1
            except Exception:
                out["click_frame_index"] = -1
            click_frame = frame
            break
        except Exception as exc:
            click_errors.append(str(exc)[:160])
            continue

    if click_errors:
        out["frame_skip_errors"] = click_errors[:8]
    if not out.get("click_dispatched"):
        if out.get("disabled_candidates") and not (
            (out.get("pre_click_inventory") or {}).get("resume_enabled_total") or 0
        ):
            out["resume_boundary"] = RESUME_CONTROL_DISABLED
            out["resume_error"] = RESUME_CONTROL_DISABLED
        else:
            out["resume_boundary"] = RESUME_CONTROL_NOT_FOUND
            out["resume_error"] = NO_RESUME_CONTROL
        return out

    # Settle for Streamlit rerun — observation only (not a click retry)
    try:
        page.wait_for_timeout(int(settle_ms))
    except Exception:
        time.sleep(max(0.0, settle_ms / 1000.0))

    post_queue = None
    if scrape_queue is not None:
        try:
            post_queue = list(scrape_queue(page) or [])
        except Exception:
            post_queue = None
    post_state: dict[str, Any] = {"require_timer": True}
    if scrape_post_state is not None:
        try:
            post_state.update(dict(scrape_post_state(page) or {}))
        except Exception as exc:
            out["post_state_error"] = str(exc)[:160]
            out["resume_boundary"] = RESUME_POSTCONDITION_NOT_PROVEN
            out["resume_error"] = RESUME_POSTCONDITION_NOT_PROVEN
            return out
    else:
        # Default lightweight DOM post-proof via resume inventory + timer scrape hooks
        try:
            from run_production_solo_soak import scrape_state, dom_counts

            st = scrape_state(page) or {}
            counts = dom_counts(page) or {}
            post_inv = inventory_resume_controls(page)
            post_state.update(
                {
                    "room_id": expected_room_id or pre_state.get("room_id"),
                    "pick_index": st.get("pick") if st.get("pick") is not None else pre_pick_index,
                    "timer": st.get("timer"),
                    "timer_running": bool(st.get("timer")),
                    "countdown_or_timer_present": bool(st.get("timer")),
                    "resume_enabled": int(post_inv.get("resume_enabled_total") or 0),
                    "pause_enabled": int(counts.get("Pause Draft") or 0),
                    "paused": int(post_inv.get("resume_enabled_total") or 0) >= 1
                    and int(counts.get("Pause Draft") or 0) == 0,
                    "status": "in_progress"
                    if int(counts.get("Pause Draft") or 0) >= 1
                    else ("paused" if int(post_inv.get("resume_enabled_total") or 0) >= 1 else ""),
                }
            )
        except Exception as exc:
            out["post_state_error"] = str(exc)[:160]
            out["resume_boundary"] = RESUME_POSTCONDITION_NOT_PROVEN
            out["resume_error"] = RESUME_POSTCONDITION_NOT_PROVEN
            return out

    proof = _postcondition_resume_ok(
        pre=pre_state,
        post=post_state,
        expected_room_id=expected_room_id,
        pre_queue=pre_queue,
        post_queue=post_queue,
    )
    out["postcondition"] = proof
    out["post_state"] = {
        k: post_state.get(k)
        for k in (
            "room_id",
            "pick_index",
            "status",
            "paused",
            "timer",
            "timer_running",
            "resume_enabled",
            "pause_enabled",
        )
        if k in post_state
    }
    if not proof.get("ok"):
        out["resumed"] = False
        out["resume_boundary"] = str(proof.get("boundary") or RESUME_POSTCONDITION_NOT_PROVEN)
        out["resume_error"] = out["resume_boundary"]
        return out

    out["resumed"] = True
    out["resume_boundary"] = RESUME_DELIVERY_RESOLVED
    out["resume_error"] = ""
    _ = click_frame  # retained for diagnostics if needed later
    return out
