"""Stage1 scrape of ``#rec-queue-run-stage-ledger`` (same-run consumption forensics)."""

from __future__ import annotations

from typing import Any

RUN_STAGE_PROBE_SELECTOR = "#rec-queue-run-stage-ledger"

# Ordered consumption stages Stage1 may report as first missing (diagnostic only).
CONSUMPTION_STAGE_ORDER: tuple[str, ...] = (
    "interactive_invoke_enter",
    "cache_miss",
    "snapshot_restored",
    "rebuild_started",
    "rebuild_succeeded",
    "fallback_started",
    "fallback_succeeded",
    "interactive_invoked",
    "interactive_render_reached",
    "target_button_registered",
    "button_return_value",
    "dispatch_entered",
    "execute_entered",
)

_CONSUMPTION_STAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "interactive_invoke_enter": ("interactive_invoke_enter", "interactive_invoked"),
    "interactive_render_reached": ("interactive_render_reached", "interactive_invoked", "interactive_invoke_exit"),
    "cache_miss": ("cache_miss", "cache_hit"),
    "snapshot_restored": ("snapshot_restored",),
    "rebuild_started": ("rebuild_started",),
    "rebuild_succeeded": ("rebuild_succeeded",),
    "rebuild_failed": ("rebuild_failed",),
    "fallback_started": ("fallback_started",),
    "fallback_succeeded": ("fallback_succeeded",),
    "fallback_failed": ("fallback_failed",),
    "target_button_registered": ("target_button_registered",),
    "button_return_value": ("button_return_value",),
    "dispatch_entered": ("dispatch_entered",),
    "execute_entered": ("execute_entered",),
}


def _stage_reached(flags: dict[str, Any], stage: str) -> bool:
    aliases = _CONSUMPTION_STAGE_ALIASES.get(stage, (stage,))
    return any(bool(flags.get(a)) for a in aliases)


def first_missing_consumption_stage(
    rollup: dict[str, Any],
    *,
    order: tuple[str, ...] | None = None,
) -> str:
    """Return the first stage in ``order`` not yet reached on a rollup row."""
    flags = dict(rollup.get("flags") or {})
    stages = list(rollup.get("stages") or [])
    for stage in order or CONSUMPTION_STAGE_ORDER:
        if stage == "snapshot_restored":
            if not rollup.get("snapshot_available") and not _stage_reached(flags, stage):
                return stage
            if rollup.get("snapshot_available") and not _stage_reached(flags, stage):
                return stage
            continue
        if stage == "rebuild_succeeded":
            if _stage_reached(flags, "rebuild_failed"):
                return "rebuild_failed"
            if _stage_reached(flags, "rebuild_started") and not _stage_reached(flags, stage):
                return stage
            continue
        if stage == "fallback_succeeded":
            if _stage_reached(flags, "fallback_failed"):
                return "fallback_failed"
            if _stage_reached(flags, "fallback_started") and not _stage_reached(flags, stage):
                return stage
            continue
        if not _stage_reached(flags, stage) and stage not in stages:
            return stage
        if not _stage_reached(flags, stage):
            # flag missing but stage string present counts as reached
            if stage in stages or any(a in stages for a in _CONSUMPTION_STAGE_ALIASES.get(stage, (stage,))):
                continue
            return stage
    return ""


def wait_for_rec_run_stage_probe(
    page,
    *,
    timeout_s: float = 3.0,
    poll_s: float = 0.12,
) -> dict[str, Any]:
    """Wait briefly for ``#rec-queue-run-stage-ledger`` after app-diag seq advance."""
    import time as _time

    deadline = _time.time() + max(0.3, float(timeout_s))
    polls = 0
    last: list[dict[str, Any]] = []
    while _time.time() < deadline:
        polls += 1
        last = scrape_rec_run_stage_ledger_probes(page)
        if any(p.get("probe_found") for p in last if isinstance(p, dict)):
            return {
                "probe_available": True,
                "polls": polls,
                "waited_s": round(float(timeout_s) - max(0.0, deadline - _time.time()), 3),
                "probe_count": len([p for p in last if p.get("probe_found")]),
            }
        _time.sleep(max(0.05, float(poll_s)))
    return {
        "probe_available": False,
        "polls": polls,
        "waited_s": float(timeout_s),
        "timeout": True,
        "probe_count": 0,
    }

_SCRAPE_JS = f"""() => {{
  function roots() {{
    const r = [document];
    for (const f of document.querySelectorAll('iframe')) {{
      try {{ if (f.contentDocument) r.push(f.contentDocument); }} catch (e) {{}}
    }}
    return r;
  }}
  const out = [];
  for (const root of roots()) {{
    const href = (root.defaultView && root.defaultView.location && root.defaultView.location.href) || '';
    let idx = 0;
    for (const el of root.querySelectorAll('{RUN_STAGE_PROBE_SELECTOR}')) {{
      const flag = (name) => {{
        const v = (el.getAttribute(name) || '').trim().toLowerCase();
        return v === '1' || v === 'true' || v === 'yes' || v === 'on';
      }};
      let payload = null;
      const b64 = el.getAttribute('data-b64') || '';
      const raw = el.getAttribute('data-json') || '';
      if (b64) {{
        try {{
          const txt = atob(b64);
          payload = JSON.parse(txt);
        }} catch (e) {{
          payload = {{ parse_error: String(e), b64_len: b64.length }};
        }}
      }} else if (raw) {{
        try {{
          payload = JSON.parse(raw.replace(/'/g, '"'));
        }} catch (e) {{
          payload = {{ parse_error: String(e), raw_len: raw.length }};
        }}
      }}
      out.push({{
        probe_found: true,
        dom_index: idx++,
        frame_href: href,
        impl_rev: el.getAttribute('data-impl-rev') || '',
        run_seq: el.getAttribute('data-run-seq') || '',
        room_id: el.getAttribute('data-room-id') || '',
        widget_key: el.getAttribute('data-widget-key') || '',
        player_id: el.getAttribute('data-player-id') || '',
        cache_miss: flag('data-cache-miss'),
        snapshot_available: flag('data-snapshot-available'),
        snapshot_restored: flag('data-snapshot-restored'),
        rebuild_started: flag('data-rebuild-started'),
        rebuild_succeeded: flag('data-rebuild-succeeded'),
        rebuild_failed: flag('data-rebuild-failed'),
        fallback_started: flag('data-fallback-started'),
        fallback_succeeded: flag('data-fallback-succeeded'),
        fallback_failed: flag('data-fallback-failed'),
        interactive_invoked: flag('data-interactive-invoked'),
        target_button_registered: flag('data-target-button-registered'),
        button_return_value: flag('data-button-return-value'),
        dispatch_entered: flag('data-dispatch-entered'),
        execute_entered: flag('data-execute-entered'),
        payload: payload,
      }});
    }}
  }}
  if (!out.length) {{
    return [{{ probe_found: false, probe_absent: true, selector: '{RUN_STAGE_PROBE_SELECTOR}' }}];
  }}
  return out;
}}"""


def scrape_rec_run_stage_ledger_probes(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_SCRAPE_JS) or []
        return [r for r in raw if isinstance(r, dict)]
    except Exception as exc:
        return [{"probe_found": False, "error": str(exc)[:160]}]


def select_run_stage_rollup_for_seq(
    probes: list[dict[str, Any]],
    *,
    run_seq: int | str | None,
    room_id: str = "",
    widget_key: str = "",
) -> dict[str, Any]:
    """Pick the rollup for a specific consuming ScriptRun from scraped probe payload(s)."""
    want_seq = None
    try:
        if run_seq is not None and str(run_seq).strip() != "":
            want_seq = int(run_seq)
    except (TypeError, ValueError):
        want_seq = None
    want_room = str(room_id or "").strip().upper()[:32]
    want_key = str(widget_key or "").strip()

    found_probes = [p for p in probes if isinstance(p, dict) and p.get("probe_found")]
    if not found_probes:
        return {
            "ok": False,
            "fail_reason": "run_stage_probe_absent",
            "diagnostic_class": "probe_absent",
            "wanted_run_seq": want_seq,
        }

    # Prefer newest probe with matching payload rollup.
    last_probe_payload_seqs: list[int] = []
    for probe in reversed(found_probes):
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        recent = list(payload.get("recent_by_seq") or [])
        try:
            last_probe_payload_seqs = [int(r.get("run_seq") or 0) for r in recent if isinstance(r, dict)]
        except (TypeError, ValueError):
            last_probe_payload_seqs = []
        match = None
        for row in recent:
            if not isinstance(row, dict):
                continue
            try:
                seq = int(row.get("run_seq") or 0)
            except (TypeError, ValueError):
                continue
            if want_seq is not None and seq != want_seq:
                continue
            if want_room:
                row_room = str(row.get("room_id") or "").strip().upper()[:32]
                if row_room and row_room != want_room:
                    continue
            if want_key:
                row_key = str(row.get("widget_key") or "").strip()
                if row_key and row_key != want_key:
                    continue
            match = dict(row)
        if match is None and want_seq is None and recent:
            last = recent[-1]
            if isinstance(last, dict):
                match = dict(last)
        if match is not None:
            flags = dict(match.get("flags") or {})
            rollup = {
                "ok": True,
                "diagnostic_class": "rollup_ok",
                "wanted_run_seq": want_seq,
                "run_seq": match.get("run_seq"),
                "room_id": match.get("room_id"),
                "widget_key": match.get("widget_key"),
                "player_id": match.get("player_id"),
                "stages": list(match.get("stages") or []),
                "flags": flags,
                "snapshot_available": bool(match.get("snapshot_available")),
                "cache_miss": bool(flags.get("cache_miss")),
                "snapshot_restored": bool(flags.get("snapshot_restored")),
                "rebuild_started": bool(flags.get("rebuild_started")),
                "rebuild_succeeded": bool(flags.get("rebuild_succeeded")),
                "rebuild_failed": bool(flags.get("rebuild_failed")),
                "fallback_started": bool(flags.get("fallback_started")),
                "fallback_succeeded": bool(flags.get("fallback_succeeded")),
                "fallback_failed": bool(flags.get("fallback_failed")),
                "interactive_invoked": bool(
                    flags.get("interactive_invoked")
                    or flags.get("interactive_invoke_enter")
                    or flags.get("interactive_invoke_exit")
                ),
                "target_button_registered": bool(flags.get("target_button_registered")),
                "button_return_value": bool(match.get("button_return_value") or flags.get("button_return_value")),
                "dispatch_entered": bool(flags.get("dispatch_entered")),
                "execute_entered": bool(flags.get("execute_entered")),
                "probe_attrs": {
                    k: probe.get(k)
                    for k in (
                        "run_seq",
                        "room_id",
                        "widget_key",
                        "player_id",
                        "impl_rev",
                        "frame_href",
                    )
                },
                "recent_by_seq_count": len(recent),
            }
            rollup["last_reached_stage"] = (
                list(rollup["stages"])[-1] if rollup.get("stages") else ""
            )
            rollup["first_missing_stage"] = first_missing_consumption_stage(rollup)
            if rollup["first_missing_stage"]:
                rollup["diagnostic_class"] = "run_present_stage_missing"
            return rollup

    if want_seq is not None and last_probe_payload_seqs and want_seq not in last_probe_payload_seqs:
        return {
            "ok": False,
            "fail_reason": "run_stage_rollup_not_found_for_seq",
            "diagnostic_class": "run_not_retained",
            "wanted_run_seq": want_seq,
            "probe_count": len(found_probes),
            "probe_current_run_seqs": [p.get("run_seq") for p in found_probes],
            "recent_by_seq_seqs": last_probe_payload_seqs,
        }

    return {
        "ok": False,
        "fail_reason": "run_stage_rollup_not_found_for_seq",
        "diagnostic_class": "run_not_retained",
        "wanted_run_seq": want_seq,
        "probe_count": len(found_probes),
        "probe_current_run_seqs": [p.get("run_seq") for p in found_probes],
        "recent_by_seq_seqs": last_probe_payload_seqs,
    }


def scrape_rec_run_stage_for_consuming_run(
    page,
    *,
    run_seq: int | str | None,
    room_id: str = "",
    widget_key: str = "",
    wait_for_probe_s: float = 3.0,
) -> dict[str, Any]:
    wait_meta: dict[str, Any] = {}
    if wait_for_probe_s and float(wait_for_probe_s) > 0:
        wait_meta = wait_for_rec_run_stage_probe(page, timeout_s=float(wait_for_probe_s))
    probes = scrape_rec_run_stage_ledger_probes(page)
    rollup = select_run_stage_rollup_for_seq(
        probes,
        run_seq=run_seq,
        room_id=room_id,
        widget_key=widget_key,
    )
    if wait_meta:
        rollup["post_click_probe_wait"] = {
            k: wait_meta.get(k)
            for k in ("probe_available", "polls", "waited_s", "timeout", "probe_count")
            if k in wait_meta
        }
    return rollup
