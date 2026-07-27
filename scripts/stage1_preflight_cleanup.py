"""Stage 1A preflight — detect and tear down stale Solo drafts before a graded run."""

from __future__ import annotations

import re
import time
from typing import Any

SCAN_BUTTONS_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const out = [];
  for (const root of roots()) {
    for (const b of root.querySelectorAll('button')) {
      const rect = b.getBoundingClientRect();
      const t = String(b.innerText||'').replace(/\\s+/g,' ').trim();
      if (!t) continue;
      out.push({
        text: t.slice(0,120),
        visible: rect.width > 0 && rect.height > 0,
        disabled: !!b.disabled,
      });
    }
  }
  return out;
}"""

SCRAPE_LOBBY_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const text = roots().map(x => x.body ? x.body.innerText : '').join('\\n');
  let wake = {};
  for (const root of roots()) {
    const w = root.querySelector('#solo-persistent-wake-lifecycle-diag');
    if (w) {
      wake = {
        phase: w.getAttribute('data-phase')||'',
        token: w.getAttribute('data-token')||'',
        actionable: w.getAttribute('data-actionable')||'',
      };
    }
  }
  let python_room_id = '';
  let python_room_present = '';
  for (const root of roots()) {
    const ko = root.querySelector('#solo-key-ownership-diag');
    if (!ko) continue;
    const b64 = ko.getAttribute('data-key-ownership-b64')||'';
    if (!b64) continue;
    try {
      const pad = b64 + '==='.slice((4 - b64.length % 4) % 4);
      const payload = JSON.parse(atob(pad));
      const rows = payload.rows || [];
      const last = rows.length ? rows[rows.length-1] : payload;
      python_room_id = String(last.live_draft_room_id || last.room_id || '').trim();
      python_room_present = last.live_draft_room_present === true || last.live_draft_room_present === 'true' ? '1' : '0';
    } catch(e) {}
  }
  const roomMatch = text.match(/Room ID\\s+([A-F0-9]+)/i);
  return {
    text_head: text.slice(0, 1200),
    wake,
    python_room_id,
    python_room_present,
    visible_room_id: roomMatch ? roomMatch[1].toUpperCase() : '',
    has_start_new: /Start New Live Draft/i.test(text),
    has_pause: /Pause Draft/i.test(text),
    has_end_delete: /End\\/Delete Draft/i.test(text),
    has_delete_permanently: /Delete Draft Permanently/i.test(text),
    has_confirm_end_delete: /Confirm End\\/Delete/i.test(text),
    has_continue_saved: /Continue Saved Draft/i.test(text),
    has_deleting: /Deleting draft/i.test(text),
    has_keep_draft: /Keep Draft/i.test(text),
  };
}"""


def _visible_buttons(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(SCAN_BUTTONS_JS)
        return [b for b in (raw or []) if isinstance(b, dict) and b.get("visible")]
    except Exception:
        return []


def _click_label(page, label: str, *, wait_ms: int = 5000) -> dict[str, Any]:
    try:
        result = page.evaluate(
            """(label) => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const matches = [];
                for (const b of root.querySelectorAll('button')) {
                  const r=b.getBoundingClientRect();
                  if (r.width <= 0 || r.height <= 0) continue;
                  if (b.disabled) continue;
                  const t=(b.innerText||'').replace(/\\s+/g,' ').trim();
                  if (t.includes(label)) matches.push(b);
                }
                if (matches.length >= 1) {
                  matches[0].scrollIntoView({block:'center', inline:'nearest'});
                  matches[0].click();
                  return { clicked: true, match_count: matches.length, label: label };
                }
              }
              return { clicked: false, match_count: 0, label: label };
            }""",
            label,
        )
        page.wait_for_timeout(wait_ms)
        return result if isinstance(result, dict) else {"clicked": False, "label": label}
    except Exception as exc:
        return {"clicked": False, "label": label, "error": str(exc)[:300]}


def _scrape_lobby(page) -> dict[str, Any]:
    from run_production_solo_soak import dom_counts

    try:
        raw = page.evaluate(SCRAPE_LOBBY_JS)
    except Exception as exc:
        raw = {"error": str(exc)[:300]}
    if not isinstance(raw, dict):
        raw = {}
    counts = dom_counts(page)
    raw["pause_draft_count"] = int(counts.get("Pause Draft") or 0)
    raw["end_delete_count"] = int(counts.get("End/Delete Draft") or 0)
    return raw


def _infer_status(snap: dict[str, Any]) -> str:
    if snap.get("has_deleting"):
        return "deleting"
    if int(snap.get("pause_draft_count") or 0) >= 1 or snap.get("has_pause"):
        return "in_progress"
    if snap.get("visible_room_id") and not snap.get("has_start_new"):
        return "active_room_visible"
    if snap.get("has_continue_saved") and snap.get("has_start_new"):
        return "setup_with_saved_slot"
    if snap.get("has_start_new") and int(snap.get("pause_draft_count") or 0) == 0:
        if snap.get("visible_room_id") or snap.get("python_room_id"):
            return "setup_stale_room_hint"
        return "setup_lobby"
    if snap.get("has_end_delete") or snap.get("has_delete_permanently"):
        return "setup_discard_pending"
    return "unknown"


def _python_room_active(snap: dict[str, Any]) -> bool:
    if str(snap.get("python_room_present") or "") == "1":
        return True
    phase = str((snap.get("wake") or {}).get("phase") or "").lower()
    if phase in ("active", "paused"):
        return True
    tok = str((snap.get("wake") or {}).get("token") or "").strip()
    if tok and "|" in tok:
        return True
    return False


def is_clean_setup_lobby(snap: dict[str, Any]) -> bool:
    if not snap.get("has_start_new"):
        return False
    if int(snap.get("pause_draft_count") or 0) >= 1 or snap.get("has_pause"):
        return False
    if snap.get("visible_room_id"):
        return False
    if _python_room_active(snap):
        return False
    if snap.get("has_confirm_end_delete") and snap.get("has_keep_draft"):
        return False
    return True


def _alert_snippets(snap: dict[str, Any]) -> list[str]:
    text = str(snap.get("text_head") or "")
    out: list[str] = []
    for pat in (
        r"Permanently delete[^\n]{0,120}",
        r"Deleting draft[^\n]{0,80}",
        r"Could not[^\n]{0,120}",
        r"failed[^\n]{0,80}",
        r"error[^\n]{0,80}",
    ):
        m = re.search(pat, text, re.I)
        if m:
            out.append(m.group(0).strip())
    return out[:8]


def run_stage1_preflight_cleanup(page, *, max_wait_s: int = 180) -> dict[str, Any]:
    """Return to a provably clean setup lobby or fail with forensic steps."""
    from run_production_solo_soak import dom_counts

    t0 = time.time()
    initial = _scrape_lobby(page)
    initial_status = _infer_status(initial)
    detected_room = str(initial.get("visible_room_id") or initial.get("python_room_id") or "").upper()
    steps: list[dict[str, Any]] = []

    if is_clean_setup_lobby(initial):
        return {
            "ok": True,
            "reason": "already_clean",
            "initial_status": initial_status,
            "detected_room_id": detected_room,
            "final_status": initial_status,
            "steps": steps,
            "initial_snapshot": _public_snapshot(initial),
            "final_snapshot": _public_snapshot(initial),
            "elapsed_s": round(time.time() - t0, 1),
        }

    last_url = page.url

    def snap_and_maybe_finish() -> dict[str, Any] | None:
        nonlocal last_url
        cur = _scrape_lobby(page)
        if is_clean_setup_lobby(cur):
            return {
                "ok": True,
                "reason": "clean_lobby_confirmed",
                "initial_status": initial_status,
                "detected_room_id": detected_room,
                "final_status": _infer_status(cur),
                "steps": steps,
                "initial_snapshot": _public_snapshot(initial),
                "final_snapshot": _public_snapshot(cur),
                "elapsed_s": round(time.time() - t0, 1),
            }
        return None

    while time.time() - t0 < max_wait_s:
        before = _scrape_lobby(page)
        url_before = page.url
        status = _infer_status(before)

        if is_clean_setup_lobby(before):
            done = snap_and_maybe_finish()
            if done:
                return done

        if before.get("has_deleting"):
            page.wait_for_timeout(3000)
            continue

        action = ""
        click: dict[str, Any] = {"clicked": False}

        if int(before.get("pause_draft_count") or 0) >= 1 or before.get("has_confirm_end_delete"):
            if before.get("has_confirm_end_delete"):
                action = "confirm_end_delete_active"
                click = _click_label(page, "Confirm End/Delete", wait_ms=8000)
            else:
                action = "end_delete_for_everyone"
                click = _click_label(page, "End/Delete Draft", wait_ms=8000)
        elif before.get("has_delete_permanently"):
            action = "delete_draft_permanently"
            click = _click_label(page, "Delete Draft Permanently", wait_ms=8000)
        elif before.get("has_end_delete") or int(before.get("end_delete_count") or 0) >= 1:
            action = "end_delete_setup"
            click = _click_label(page, "End/Delete Draft", wait_ms=8000)
        elif before.get("has_continue_saved") and before.get("has_start_new"):
            action = "disregard_saved_draft"
            click = _click_label(page, "Disregard Saved Draft and Start New", wait_ms=6000)
            if not click.get("clicked"):
                click = _click_label(page, "Disregard Saved Draft", wait_ms=6000)
        else:
            page.wait_for_timeout(2500)
            after = _scrape_lobby(page)
            if is_clean_setup_lobby(after):
                done = snap_and_maybe_finish()
                if done:
                    return done
            if _infer_status(after) == status:
                break
            continue

        page.wait_for_timeout(2000)
        after = _scrape_lobby(page)
        url_after = page.url
        step = {
            "ts": time.time(),
            "action": action,
            "click": click,
            "room_id_before": before.get("visible_room_id") or before.get("python_room_id") or "",
            "room_id_after": after.get("visible_room_id") or after.get("python_room_id") or "",
            "status_before": status,
            "status_after": _infer_status(after),
            "pause_before": before.get("pause_draft_count"),
            "pause_after": after.get("pause_draft_count"),
            "url_changed": url_before != url_after,
            "alerts_after": _alert_snippets(after),
            "visible_buttons": [b.get("text") for b in _visible_buttons(page)[:40]],
            "click_accepted": bool(click.get("clicked")),
        }
        steps.append(step)
        last_url = url_after

        done = snap_and_maybe_finish()
        if done:
            return done

        # Wait for server-visible transition after destructive clicks.
        if click.get("clicked") and action in (
            "confirm_end_delete_active",
            "delete_draft_permanently",
            "end_delete_for_everyone",
        ):
            wait_deadline = time.time() + 45
            while time.time() < wait_deadline:
                mid = _scrape_lobby(page)
                if is_clean_setup_lobby(mid):
                    done = snap_and_maybe_finish()
                    if done:
                        return done
                if int(mid.get("pause_draft_count") or 0) == 0 and mid.get("has_start_new"):
                    if not mid.get("visible_room_id") and not _python_room_active(mid):
                        done = snap_and_maybe_finish()
                        if done:
                            return done
                if mid.get("has_deleting"):
                    page.wait_for_timeout(2000)
                    continue
                page.wait_for_timeout(2000)

    final = _scrape_lobby(page)
    counts = dom_counts(page)
    return {
        "ok": False,
        "reason": _failure_reason(final, steps),
        "initial_status": initial_status,
        "detected_room_id": detected_room,
        "final_status": _infer_status(final),
        "steps": steps,
        "initial_snapshot": _public_snapshot(initial),
        "final_snapshot": _public_snapshot(final),
        "visible_buttons": [b.get("text") for b in _visible_buttons(page)[:50]],
        "alerts": _alert_snippets(final),
        "pause_draft_count": counts.get("Pause Draft"),
        "elapsed_s": round(time.time() - t0, 1),
        "last_url": last_url,
    }


def _public_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    wake = dict(snap.get("wake") or {})
    if wake.get("token"):
        wake["token"] = str(wake["token"])[:80]
    return {
        "visible_room_id": snap.get("visible_room_id") or "",
        "python_room_id": snap.get("python_room_id") or "",
        "python_room_present": snap.get("python_room_present") or "",
        "pause_draft_count": snap.get("pause_draft_count"),
        "has_start_new": snap.get("has_start_new"),
        "has_pause": snap.get("has_pause"),
        "has_end_delete": snap.get("has_end_delete"),
        "has_delete_permanently": snap.get("has_delete_permanently"),
        "has_confirm_end_delete": snap.get("has_confirm_end_delete"),
        "has_continue_saved": snap.get("has_continue_saved"),
        "has_deleting": snap.get("has_deleting"),
        "wake_phase": wake.get("phase") or "",
        "wake_actionable": wake.get("actionable") or "",
    }


def _failure_reason(final: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "no_cleanup_action_matched_visible_controls"
    last = steps[-1]
    if not last.get("click_accepted"):
        return f"click_not_accepted:{last.get('action')}"
    if final.get("has_confirm_end_delete"):
        return "confirmation_dialog_still_open"
    if int(final.get("pause_draft_count") or 0) >= 1:
        return "pause_draft_still_visible_after_cleanup"
    if final.get("visible_room_id"):
        return "room_id_still_visible_after_cleanup"
    if _python_room_active(final):
        return "python_room_still_active_after_cleanup"
    if not final.get("has_start_new"):
        return "start_new_live_draft_not_visible"
    return "setup_lobby_not_reached_after_cleanup"
