"""Narrow diagnostics for recommendation-card Add-to-Queue (QUEUE1C3 app path)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

TRACE_LEDGER_KEY = "_live_draft_rec_queue_click_trace_ledger"
TRACE_LAST_KEY = "_live_draft_rec_queue_click_trace_last"
WIDGET_REGISTRY_KEY = "_live_draft_rec_queue_widget_registry"
RENDER_TRACE_REGISTRY_KEY = "_live_draft_rec_queue_render_trace_registry"
REC_QUEUE_CALLBACK_ID = "execute_rec_card_queue_click"
REC_QUEUE_CALLBACK_VERSION = "v2_return_value"
DISPATCH_LAYER_KEY = "_live_draft_rec_queue_dispatch_layers"
RENDER_TRACE_PROBE_ELEMENT_ID = "rec-card-queue-render-trace"
PER_CARD_RENDER_TRACE_CLASS = "rec-card-queue-render-trace-card"
REC_QUEUE_RENDER_TRACE_IMPL_REV = "rec_queue_render_trace_v5_queue_gate"
WIDGET_LIFECYCLE_KEY = "_live_draft_rec_queue_widget_lifecycle"
MAX_LEDGER = 24
MAX_RENDER_REGISTRY = 32


def _script_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _heavy_paint_done(session: dict[str, Any]) -> bool:
    try:
        from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY

        return bool(session.get(HEAVY_PAINT_DONE_KEY))
    except ImportError:
        return bool(session.get("_live_draft_heavy_paint_done"))


def _lifecycle_map(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(WIDGET_LIFECYCLE_KEY)
    if not isinstance(raw, dict):
        raw = {}
        session[WIDGET_LIFECYCLE_KEY] = raw
    return raw


def lifecycle_for_widget(session: dict[str, Any], widget_key: str) -> dict[str, Any]:
    reg = _lifecycle_map(session)
    row = reg.get(str(widget_key))
    return dict(row) if isinstance(row, dict) else {}


def _merge_lifecycle_dom_attrs(session: dict[str, Any], widget_key: str, *, probe_source: str = "") -> dict[str, Any]:
    """Snapshot for DOM markers — distinguishes actual st.button render vs registry re-emit."""
    lc = lifecycle_for_widget(session, widget_key)
    current_seq = _script_run_seq(session)
    last_render_seq = int(lc.get("widget_last_rendered_run_seq") or lc.get("actual_card_render_run_seq") or 0)
    rendered_this_run = bool(lc.get("widget_rendered_this_run"))
    stale_vs_current = bool(last_render_seq and current_seq and last_render_seq < current_seq and not rendered_this_run)
    paint = session.get("_solo_stage1_last_recommendation_paint")
    paint_via = ""
    if isinstance(paint, dict):
        paint_via = str(paint.get("via") or "").strip()
    paint_via = str(lc.get("paint_via_at_render") or paint_via or "").strip()
    owner = str(
        lc.get("interactive_owner")
        or session.get("_live_draft_rec_queue_interactive_owner")
        or ""
    ).strip()
    out: dict[str, Any] = {
        "actual_card_render_run_seq": lc.get("actual_card_render_run_seq"),
        "actual_card_render_ts": lc.get("actual_card_render_ts"),
        "probe_emit_run_seq": lc.get("probe_emit_run_seq"),
        "probe_emit_ts": lc.get("probe_emit_ts"),
        "probe_source": probe_source or lc.get("probe_source") or "",
        "current_script_run_seq": current_seq,
        "current_fragment_run_seq": lc.get("current_fragment_run_seq"),
        "heavy_paint_done": _heavy_paint_done(session),
        "heavy_paint_done_at_render": lc.get("heavy_paint_done_at_render"),
        "widget_rendered_this_run": rendered_this_run,
        "widget_last_rendered_run_seq": last_render_seq or lc.get("widget_last_rendered_run_seq"),
        "widget_liveness": "live_this_run" if rendered_this_run else ("stale_retained_dom" if stale_vs_current else "unknown"),
        "interactive_owner": owner,
        "paint_via": paint_via,
        "inside_fragment": bool(lc.get("inside_fragment")),
        "fragment_run_every": lc.get("fragment_run_every"),
        "server_registered": bool(lc.get("server_registered")),
        "callback_attached": bool(lc.get("callback_attached") or lc.get("server_registered")),
        "callback_id": lc.get("callback_id") or REC_QUEUE_CALLBACK_ID,
        "dispatch_kind": lc.get("dispatch_kind") or "button_return_value",
    }
    return out


def note_rec_queue_dispatch_layer(
    session: dict[str, Any],
    *,
    layer: str,
    widget_key: str = "",
    player_id: str = "",
    player_name: str = "",
) -> None:
    """Record which callable layer entered (return-value branch vs execute body)."""
    row = {
        "ts": time.time(),
        "layer": str(layer or "").strip(),
        "widget_key": str(widget_key or "").strip(),
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip(),
        "script_run_seq": _script_run_seq(session),
        "interactive_owner": str(session.get("_live_draft_rec_queue_interactive_owner") or "").strip(),
        "paint_via": str(
            (session.get("_solo_stage1_last_recommendation_paint") or {}).get("via") or ""
        ).strip()
        if isinstance(session.get("_solo_stage1_last_recommendation_paint"), dict)
        else "",
    }
    book = list(session.get(DISPATCH_LAYER_KEY) or [])
    book.append(row)
    session[DISPATCH_LAYER_KEY] = book[-48:]
    session["_live_draft_rec_queue_dispatch_layer_last"] = dict(row)


def note_rec_queue_widget_button_rendered(
    session: dict[str, Any],
    *,
    widget_key: str,
    dispatch_kind: str = "button_return_value",
) -> None:
    """Call immediately after st.button(...) for Add-to-Queue — proves widget ran this script pass."""
    wk = str(widget_key or "").strip()
    if not wk:
        return
    try:
        from live_draft_rec_live_paint import note_rec_run_stage

        note_rec_run_stage(session, "target_button_registered", widget_key=wk, dispatch_kind=dispatch_kind)
    except ImportError:
        pass
    reg = _lifecycle_map(session)
    now = time.time()
    seq = _script_run_seq(session)
    prev = dict(reg.get(wk) or {})
    owner = str(session.get("_live_draft_rec_queue_interactive_owner") or "").strip()
    paint = session.get("_solo_stage1_last_recommendation_paint")
    paint_via = ""
    if isinstance(paint, dict):
        paint_via = str(paint.get("via") or "").strip()
    inside_fragment = bool(session.get("_solo_stage1_in_fragment_run"))
    # run_every only applies when this registration happened under the heavy-paint fragment path
    fragment_run_every: int | None = 1 if (inside_fragment and paint_via == "fragment") else None
    if owner in ("script_run_no_run_every",) or paint_via == "full_page_interactive_live":
        fragment_run_every = None
        inside_fragment = False
    reg[wk] = {
        **prev,
        "widget_key": wk,
        "actual_card_render_run_seq": seq,
        "actual_card_render_ts": now,
        "widget_last_rendered_run_seq": seq,
        "widget_rendered_this_run": True,
        "probe_source": "actual_card_render",
        "current_script_run_seq_at_render": seq,
        "heavy_paint_done_at_render": _heavy_paint_done(session),
        "interactive_owner": owner or (
            "fragment_run_every" if fragment_run_every else "script_run_unknown"
        ),
        "paint_via_at_render": paint_via,
        "inside_fragment": inside_fragment,
        "fragment_run_every": fragment_run_every,
        "callback_id": REC_QUEUE_CALLBACK_ID,
        "callback_attached": True,
        "server_registered": True,
        "dispatch_kind": str(dispatch_kind or "button_return_value").strip(),
    }
    session["_live_draft_rec_queue_render_trace_last_lifecycle"] = dict(reg[wk])


def note_rec_queue_probe_emit(
    session: dict[str, Any],
    *,
    widget_key: str = "",
    probe_source: str = "registry_reemit",
) -> None:
    """Registry/HTML re-emit without st.button — must not set widget_rendered_this_run."""
    reg = _lifecycle_map(session)
    seq = _script_run_seq(session)
    now = time.time()
    keys = [widget_key] if widget_key else list(reg.keys())[-6:]
    for wk in keys:
        wk = str(wk or "").strip()
        if not wk:
            continue
        prev = dict(reg.get(wk) or {})
        reg[wk] = {
            **prev,
            "widget_key": wk,
            "probe_emit_run_seq": seq,
            "probe_emit_ts": now,
            "probe_source": probe_source,
            "widget_rendered_this_run": False,
            "current_script_run_seq_at_probe": seq,
            "heavy_paint_done_at_probe": _heavy_paint_done(session),
        }


def new_rec_queue_event_id() -> str:
    return uuid.uuid4().hex[:12]


def _ledger(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw = session.get(TRACE_LEDGER_KEY)
    if not isinstance(raw, list):
        raw = []
        session[TRACE_LEDGER_KEY] = raw
    return raw


def _append_ledger(session: dict[str, Any], row: dict[str, Any]) -> None:
    book = _ledger(session)
    book.append(row)
    if len(book) > MAX_LEDGER:
        del book[: len(book) - MAX_LEDGER]
    session[TRACE_LAST_KEY] = dict(row)


def register_rec_queue_render_trace(
    session: dict[str, Any],
    *,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    surface: str = "rec_card",
    already_queued: bool = False,
    render_run_seq: int | None = None,
    app_build_sha: str = "",
    help_variant: str = "",
    help_present: bool | None = None,
) -> dict[str, Any]:
    """Render-time registry — proves instrumented rec card painted before any click."""
    reg = session.get(RENDER_TRACE_REGISTRY_KEY)
    if not isinstance(reg, list):
        reg = []
        session[RENDER_TRACE_REGISTRY_KEY] = reg
    wk = str(widget_key or "").strip()
    seq = int(render_run_seq) if render_run_seq is not None else _script_run_seq(session)
    lc = _merge_lifecycle_dom_attrs(session, wk, probe_source="actual_card_render")
    row: dict[str, Any] = {
        "room_id": str(room_id or "").strip(),
        "pick_index": int(pick_index),
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip(),
        "surface": str(surface or "rec_card"),
        "expected_widget_key": wk,
        "widget_key": wk,
        "callback_id": REC_QUEUE_CALLBACK_ID,
        "callback_version": REC_QUEUE_CALLBACK_VERSION,
        "on_click_wired": True,
        "button_label": "⭐ Add to Queue",
        "already_queued": bool(already_queued),
        "render_ts": time.time(),
        "render_run_seq": seq,
        "app_build_sha": str(app_build_sha or "").strip()[:12],
        "widget_key_dupes": list(session.get("_live_draft_rec_queue_widget_key_dupes") or []),
        "help_variant": str(help_variant or "").strip() or "production_default",
        "help_present": bool(help_present) if help_present is not None else True,
        "full_app_run_seq_at_render": _script_run_seq(session),
        "recommendation_fragment_run_seq_at_render": int(session.get("_solo_stage1_recommendation_fragment_run_seq") or 0),
        **lc,
    }
    reg.append(row)
    if len(reg) > MAX_RENDER_REGISTRY:
        del reg[: len(reg) - MAX_RENDER_REGISTRY]
    session["_live_draft_rec_queue_render_trace_last"] = dict(row)
    return row


def _render_trace_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def _render_trace_build_sha() -> str:
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")[:12]
    except ImportError:
        return ""


def _queue_gate_trace_attrs(st: Any | None, session: dict[str, Any]) -> str:
    """Solo-visible gate-state attrs. Must not depend on the parent/queue gate."""
    try:
        from live_draft_queue_state_snapshot_diag import (
            format_queue_gate_dom_attrs,
            observe_queue_snapshot_gate_state,
        )

        obs = observe_queue_snapshot_gate_state(st, session, renderer_call_reached=True)
        return format_queue_gate_dom_attrs(obs)
    except Exception:
        return ""


def render_per_card_rec_queue_render_trace_marker(
    st: Any,
    session: dict[str, Any],
    trace_row: dict[str, Any],
) -> None:
    """Per-card render proof adjacent to the Add button (fragment-safe for harness)."""
    if not _render_trace_diag_enabled(st, session):
        return
    if not isinstance(trace_row, dict) or not trace_row.get("player_name"):
        return
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    sha = str(trace_row.get("app_build_sha") or _render_trace_build_sha())
    wk = str(trace_row.get("expected_widget_key") or trace_row.get("widget_key") or "")
    probe_source = str(trace_row.get("probe_source") or "actual_card_render")
    lc = _merge_lifecycle_dom_attrs(session, wk, probe_source=probe_source)
    gen = int(trace_row.get("render_run_seq") or lc.get("actual_card_render_run_seq") or 0)
    st.markdown(
        f'<div class="{PER_CARD_RENDER_TRACE_CLASS}" '
        f'data-room-id="{safe(trace_row.get("room_id"))}" '
        f'data-player-name="{safe(trace_row.get("player_name"))}" '
        f'data-player-id="{safe(trace_row.get("player_id"))}" '
        f'data-pick-index="{int(trace_row.get("pick_index") or 0)}" '
        f'data-widget-key="{safe(wk)}" '
        f'data-surface="{safe(trace_row.get("surface") or "rec_card")}" '
        f'data-callback-id="{safe(trace_row.get("callback_id") or REC_QUEUE_CALLBACK_ID)}" '
        f'data-render-generation="{gen}" '
        f'data-actual-card-render-run-seq="{int(lc.get("actual_card_render_run_seq") or 0)}" '
        f'data-actual-card-render-ts="{safe(lc.get("actual_card_render_ts"))}" '
        f'data-probe-emit-run-seq="{int(lc.get("probe_emit_run_seq") or 0)}" '
        f'data-probe-emit-ts="{safe(lc.get("probe_emit_ts"))}" '
        f'data-probe-source="{safe(probe_source)}" '
        f'data-current-script-run-seq="{int(lc.get("current_script_run_seq") or 0)}" '
        f'data-heavy-paint-done="{1 if lc.get("heavy_paint_done") else 0}" '
        f'data-heavy-paint-done-at-render="{1 if lc.get("heavy_paint_done_at_render") else 0}" '
        f'data-interactive-owner="{safe(lc.get("interactive_owner"))}" '
        f'data-paint-via="{safe(lc.get("paint_via"))}" '
        f'data-inside-fragment="{1 if lc.get("inside_fragment") else 0}" '
        f'data-fragment-run-every="{safe(lc.get("fragment_run_every"))}" '
        f'data-server-registered="{1 if lc.get("server_registered") else 0}" '
        f'data-callback-attached="{1 if lc.get("callback_attached") else 0}" '
        f'data-widget-rendered-this-run="{1 if lc.get("widget_rendered_this_run") else 0}" '
        f'data-widget-last-rendered-run-seq="{int(lc.get("widget_last_rendered_run_seq") or 0)}" '
        f'data-widget-liveness="{safe(lc.get("widget_liveness"))}" '
        f'data-app-sha="{safe(sha)}" '
        f'data-help-variant="{safe(trace_row.get("help_variant"))}" '
        f'data-help-present="{1 if trace_row.get("help_present") else 0}" '
        f'data-impl-rev="{REC_QUEUE_RENDER_TRACE_IMPL_REV}"></div>',
        unsafe_allow_html=True,
    )


def reemit_rec_queue_render_trace_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Re-paint render probes from session registry without re-rendering recommendation cards."""
    if not _render_trace_diag_enabled(st, session):
        return
    reg = list(session.get(RENDER_TRACE_REGISTRY_KEY) or [])
    if not reg and not session.get("_live_draft_rec_queue_render_trace_last"):
        return
    note_rec_queue_probe_emit(session, probe_source="registry_reemit")
    render_rec_queue_render_trace_probe(st, session, probe_source="registry_reemit")
    for row in reg[-6:]:
        if isinstance(row, dict):
            emit_row = dict(row)
            emit_row["probe_source"] = "registry_reemit"
            render_per_card_rec_queue_render_trace_marker(st, session, emit_row)


def render_rec_queue_render_trace_probe(st: Any, session: dict[str, Any], *, probe_source: str = "actual_card_render") -> None:
    """Pre-click DOM: #rec-card-queue-render-trace (solo_component_diag only)."""
    if not _render_trace_diag_enabled(st, session):
        return
    reg = list(session.get(RENDER_TRACE_REGISTRY_KEY) or [])
    last = dict(session.get("_live_draft_rec_queue_render_trace_last") or {})
    wk = str(last.get("expected_widget_key") or last.get("widget_key") or "")
    lc = _merge_lifecycle_dom_attrs(session, wk, probe_source=probe_source)
    sha = _render_trace_build_sha() or str(last.get("app_build_sha") or "")
    payload = json.dumps(
        {
            "registry_len": len(reg),
            "last": last,
            "players": [
                {
                    "player_name": r.get("player_name"),
                    "expected_widget_key": r.get("expected_widget_key"),
                    "room_id": r.get("room_id"),
                    "pick_index": r.get("pick_index"),
                    "player_id": r.get("player_id"),
                }
                for r in reg[-8:]
                if isinstance(r, dict)
            ],
            "app_build_sha": sha,
        },
        default=str,
    )[:12000]
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    gate_attrs = _queue_gate_trace_attrs(st, session)
    gate_attr_html = f"{gate_attrs} " if gate_attrs else ""
    st.markdown(
        f'<div id="{RENDER_TRACE_PROBE_ELEMENT_ID}" '
        f'class="{PER_CARD_RENDER_TRACE_CLASS} rec-card-queue-render-trace-global" '
        f'data-room-id="{safe(last.get("room_id"))}" '
        f'data-player-name="{safe(last.get("player_name"))}" '
        f'data-player-id="{safe(last.get("player_id"))}" '
        f'data-pick-index="{int(last.get("pick_index") or 0)}" '
        f'data-widget-key="{safe(last.get("expected_widget_key") or last.get("widget_key"))}" '
        f'data-surface="{safe(last.get("surface") or "rec_card")}" '
        f'data-callback-id="{safe(last.get("callback_id") or REC_QUEUE_CALLBACK_ID)}" '
        f'data-registry-len="{len(reg)}" '
        f'data-probe-source="{safe(probe_source)}" '
        f'data-actual-card-render-run-seq="{int(lc.get("actual_card_render_run_seq") or 0)}" '
        f'data-current-script-run-seq="{int(lc.get("current_script_run_seq") or 0)}" '
        f'data-heavy-paint-done="{1 if lc.get("heavy_paint_done") else 0}" '
        f'data-heavy-paint-done-at-render="{1 if lc.get("heavy_paint_done_at_render") else 0}" '
        f'data-interactive-owner="{safe(lc.get("interactive_owner"))}" '
        f'data-paint-via="{safe(lc.get("paint_via"))}" '
        f'data-inside-fragment="{1 if lc.get("inside_fragment") else 0}" '
        f'data-fragment-run-every="{safe(lc.get("fragment_run_every"))}" '
        f'data-server-registered="{1 if lc.get("server_registered") else 0}" '
        f'data-callback-attached="{1 if lc.get("callback_attached") else 0}" '
        f'data-widget-rendered-this-run="{1 if lc.get("widget_rendered_this_run") else 0}" '
        f'data-widget-last-rendered-run-seq="{int(lc.get("widget_last_rendered_run_seq") or 0)}" '
        f'data-widget-liveness="{safe(lc.get("widget_liveness"))}" '
        f'data-app-sha="{safe(sha)}" '
        f'data-help-variant="{safe(last.get("help_variant"))}" '
        f'data-help-present="{1 if last.get("help_present") else 0}" '
        f'data-impl-rev="{REC_QUEUE_RENDER_TRACE_IMPL_REV}" '
        f'{gate_attr_html}'
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )


_REC_CARD_QUEUE_GATE_EVAL_JS = f"""() => {{
  const el = document.querySelector('#{RENDER_TRACE_PROBE_ELEMENT_ID}');
  if (!el) return {{ probe_found: false, probe_absent: true, selector: '#{RENDER_TRACE_PROBE_ELEMENT_ID}' }};
  const flag = (name) => {{
    const v = (el.getAttribute(name) || '').trim().toLowerCase();
    return v === '1' || v === 'true' || v === 'yes' || v === 'on';
  }};
  return {{
    probe_found: true,
    probe_absent: false,
    selector: '#{RENDER_TRACE_PROBE_ELEMENT_ID}',
    sid: el.getAttribute('data-sid') || '',
    room_id: el.getAttribute('data-room-id') || '',
    paint_via: el.getAttribute('data-paint-via') || '',
    solo_qp: el.getAttribute('data-solo-qp') || '',
    solo_qp_present: flag('data-solo-qp-present'),
    solo_qp_flag: flag('data-solo-qp-flag'),
    solo_url_present: flag('data-solo-url-present'),
    solo_url_flag: flag('data-solo-url-flag'),
    solo_enabled: flag('data-solo-enabled'),
    parent_qp: el.getAttribute('data-parent-qp') || '',
    parent_qp_present: flag('data-parent-qp-present'),
    parent_qp_flag: flag('data-parent-qp-flag'),
    parent_url: el.getAttribute('data-parent-url') || '',
    parent_url_present: flag('data-parent-url-present'),
    parent_url_flag: flag('data-parent-url-flag'),
    parent_requested: flag('data-parent-requested'),
    parent_probe: flag('data-parent-probe'),
    queue_gate: flag('data-queue-gate'),
    renderer_call_reached: flag('data-queue-renderer-reached'),
    would_render: flag('data-queue-would-render'),
    early_return_reason: el.getAttribute('data-queue-early-return-reason') || '',
    impl_rev: el.getAttribute('data-impl-rev') || '',
    queue_gate_json: el.getAttribute('data-queue-gate-json') || '',
  }};
}}"""

_REC_CARD_QUEUE_GATE_CONTENTDOCUMENT_FALLBACK_JS = f"""() => {{
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) {{
    try {{ if (f.contentDocument) docs.push(f.contentDocument); }} catch (e) {{}}
  }}
  const flag = (name, el) => {{
    const v = (el.getAttribute(name) || '').trim().toLowerCase();
    return v === '1' || v === 'true' || v === 'yes' || v === 'on';
  }};
  for (const doc of docs) {{
    const el = doc.querySelector('#{RENDER_TRACE_PROBE_ELEMENT_ID}');
    if (!el) continue;
    return {{
      probe_found: true,
      probe_absent: false,
      selector: '#{RENDER_TRACE_PROBE_ELEMENT_ID}',
      sid: el.getAttribute('data-sid') || '',
      room_id: el.getAttribute('data-room-id') || '',
      paint_via: el.getAttribute('data-paint-via') || '',
      solo_qp: el.getAttribute('data-solo-qp') || '',
      solo_qp_present: flag('data-solo-qp-present', el),
      solo_qp_flag: flag('data-solo-qp-flag', el),
      solo_url_present: flag('data-solo-url-present', el),
      solo_url_flag: flag('data-solo-url-flag', el),
      solo_enabled: flag('data-solo-enabled', el),
      parent_qp: el.getAttribute('data-parent-qp') || '',
      parent_qp_present: flag('data-parent-qp-present', el),
      parent_qp_flag: flag('data-parent-qp-flag', el),
      parent_url: el.getAttribute('data-parent-url') || '',
      parent_url_present: flag('data-parent-url-present', el),
      parent_url_flag: flag('data-parent-url-flag', el),
      parent_requested: flag('data-parent-requested', el),
      parent_probe: flag('data-parent-probe', el),
      queue_gate: flag('data-queue-gate', el),
      renderer_call_reached: flag('data-queue-renderer-reached', el),
      would_render: flag('data-queue-would-render', el),
      early_return_reason: el.getAttribute('data-queue-early-return-reason') || '',
      impl_rev: el.getAttribute('data-impl-rev') || '',
      queue_gate_json: el.getAttribute('data-queue-gate-json') || '',
    }};
  }}
  return {{ probe_found: false, probe_absent: true, selector: '#{RENDER_TRACE_PROBE_ELEMENT_ID}' }};
}}"""


def _decode_rec_card_queue_gate_eval(
    raw: Any,
    *,
    frame_index: int | None = None,
    frame_url: str = "",
    frame_strategy: str = "",
) -> dict[str, Any]:
    out: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    out["selector"] = str(out.get("selector") or f"#{RENDER_TRACE_PROBE_ELEMENT_ID}")
    if frame_index is not None:
        out["frame_index"] = frame_index
    if frame_url:
        out["frame_url"] = frame_url
    if frame_strategy:
        out["frame_strategy"] = frame_strategy
    found = out.get("probe_found") is True
    out["probe_found"] = bool(found)
    out["probe_absent"] = not bool(found)
    out["parse_invalid"] = False
    if not found:
        return out
    # Present element missing all gate attrs is parse-invalid (distinct from absent).
    gate_keys = (
        "solo_enabled",
        "parent_requested",
        "parent_probe",
        "queue_gate",
        "renderer_call_reached",
        "would_render",
        "early_return_reason",
    )
    has_any_gate = any(k in out and out.get(k) not in (None, "") for k in gate_keys)
    raw_json = out.get("queue_gate_json")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            out["queue_gate_payload"] = json.loads(raw_json.replace("'", '"'))
            has_any_gate = True
        except Exception as exc:
            out["parse_invalid"] = True
            out["parse_error"] = str(exc)[:200]
            return out
    if not has_any_gate and not str(out.get("impl_rev") or "").strip():
        out["parse_invalid"] = True
        out["parse_error"] = "present_without_gate_fields"
    return out


def scrape_rec_card_queue_gate_state_from_page(page: Any) -> dict[str, Any]:
    """Read-only scrape of #rec-card-queue-render-trace gate-state attrs.

    Prefer Playwright page.frames (same contract as deploy / queue-snapshot scrapers),
    then contentDocument walk. Does not click, navigate, mutate query params, or
    consume a bridge.
    """
    last_absent: dict[str, Any] = {
        "probe_found": False,
        "probe_absent": True,
        "parse_invalid": False,
        "selector": f"#{RENDER_TRACE_PROBE_ELEMENT_ID}",
        "frame_strategy": "page.frames",
        "frames_searched": 0,
    }
    frames = list(getattr(page, "frames", []) or [])
    last_absent["frames_searched"] = len(frames)
    last_invalid: dict[str, Any] | None = None
    for idx, frame in enumerate(frames):
        try:
            raw = frame.evaluate(_REC_CARD_QUEUE_GATE_EVAL_JS)
        except Exception:
            continue
        parsed = _decode_rec_card_queue_gate_eval(
            raw,
            frame_index=idx,
            frame_url=str(getattr(frame, "url", "") or ""),
            frame_strategy="page.frames",
        )
        if parsed.get("probe_found") is True and parsed.get("parse_invalid") is not True:
            return parsed
        if parsed.get("probe_found") is True and parsed.get("parse_invalid") is True:
            last_invalid = parsed
            last_invalid["frames_searched"] = len(frames)
            continue
        last_absent = parsed
        last_absent["frames_searched"] = len(frames)
    try:
        raw = page.evaluate(_REC_CARD_QUEUE_GATE_CONTENTDOCUMENT_FALLBACK_JS)
    except Exception as exc:
        if last_invalid is not None:
            return last_invalid
        last_absent = dict(last_absent)
        last_absent["error"] = str(exc)[:200]
        last_absent["frame_strategy"] = last_absent.get("frame_strategy") or "contentDocument_fallback"
        return last_absent
    parsed = _decode_rec_card_queue_gate_eval(
        raw,
        frame_strategy="contentDocument_fallback" if frames else "top_page_evaluate",
    )
    if parsed.get("probe_found") is True and parsed.get("parse_invalid") is not True:
        return parsed
    if parsed.get("probe_found") is True and parsed.get("parse_invalid") is True:
        return parsed
    if last_invalid is not None:
        return last_invalid
    if frames:
        last_absent["contentDocument_fallback_absent"] = True
        return last_absent
    return parsed


def wait_and_scrape_rec_card_queue_gate_state_from_page(
    page: Any,
    *,
    timeout_s: float = 20.0,
    poll_s: float = 0.5,
) -> dict[str, Any]:
    """Bounded wait for #rec-card-queue-render-trace after auth (no navigation/click).

    Strict auth may precede rec-card paint. Poll page.frames until a current
    parse-valid probe appears or timeout. Present-but-invalid is retained but
    does not end the wait early (rerender may replace it).
    """
    deadline = time.time() + max(0.5, float(timeout_s))
    last: dict[str, Any] = {
        "probe_found": False,
        "probe_absent": True,
        "parse_invalid": False,
        "selector": f"#{RENDER_TRACE_PROBE_ELEMENT_ID}",
        "frame_strategy": "page.frames",
    }
    attempts = 0
    started = time.time()
    while time.time() < deadline:
        attempts += 1
        last = scrape_rec_card_queue_gate_state_from_page(page)
        last["attempts"] = attempts
        last["elapsed_s"] = max(0.0, time.time() - started)
        last["waited_for_probe"] = True
        last["probe_wait_timeout"] = False
        if last.get("probe_found") is True and last.get("parse_invalid") is not True:
            return last
        try:
            page.wait_for_timeout(int(max(0.05, float(poll_s)) * 1000))
        except Exception:
            time.sleep(max(0.05, float(poll_s)))
    last = scrape_rec_card_queue_gate_state_from_page(page)
    last["attempts"] = attempts + 1
    last["elapsed_s"] = max(0.0, time.time() - started)
    last["waited_for_probe"] = True
    last["probe_wait_timeout"] = True
    return last


def evaluate_context_a_live_queue_gate_reservation(gate: dict[str, Any] | None) -> dict[str, Any]:
    """Post-draft rec-card gate (Stage A / proof). Not Context-A auth-only reservation."""
    row = dict(gate or {})
    reason = str(row.get("early_return_reason") or "").strip().lower()
    enabled_reason = reason in ("", "enabled")
    checks = {
        "probe_found": row.get("probe_found") is True,
        "solo_enabled": row.get("solo_enabled") is True,
        "parent_requested": row.get("parent_requested") is True,
        "parent_probe": row.get("parent_probe") is True,
        "queue_gate": row.get("queue_gate") is True,
        "renderer_call_reached": row.get("renderer_call_reached") is True,
        "would_render": row.get("would_render") is True,
        "early_return_reason_enabled": enabled_reason and row.get("probe_found") is True,
    }
    failing = [k for k, ok in checks.items() if not ok]
    return {
        "ok": not failing,
        "checks": checks,
        "failing": failing,
        "early_return_reason": row.get("early_return_reason") or "",
        "probe_found": row.get("probe_found") is True,
        "probe_absent": row.get("probe_absent") is True,
        "classification": (
            "CONTEXT_A_LIVE_QUEUE_GATE_RESERVATION_OK"
            if not failing
            else "FRANCISCO_QUEUE_MUTATION_LIVE_AUTHENTICATED_QUEUE_GATE_NOT_READY"
        ),
    }


def register_rec_queue_widget(
    session: dict[str, Any],
    *,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    surface: str = "rec_card",
    already_queued: bool = False,
    canonical_widget_key: str | None = None,
) -> None:
    reg = session.get(WIDGET_REGISTRY_KEY)
    if not isinstance(reg, dict):
        reg = {}
        session[WIDGET_REGISTRY_KEY] = reg
    entry = {
        "room_id": str(room_id or "").strip(),
        "pick_index": int(pick_index),
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip(),
        "widget_key": str(widget_key or "").strip(),
        "canonical_widget_key": str(canonical_widget_key or "").strip() or None,
        "surface": str(surface or "rec_card"),
        "already_queued": bool(already_queued),
        "ts": time.time(),
    }
    reg[str(widget_key)] = entry
    keys = list(reg.keys())
    session["_live_draft_rec_queue_widget_key_count"] = len(keys)
    dupes = _duplicate_widget_keys(reg)
    if dupes:
        session["_live_draft_rec_queue_widget_key_dupes"] = dupes
    else:
        session.pop("_live_draft_rec_queue_widget_key_dupes", None)


def _duplicate_widget_keys(reg: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for k in reg:
        ks = str(k)
        if ks in seen:
            dupes.append(ks)
        seen.add(ks)
    return dupes


LEGACY_REC_QUEUE_KEY_TEMPLATE = "rec_card_queue_{pick_index}_{stable_key}"
COLLISION_SAFE_REC_QUEUE_KEY_TEMPLATE = "rec_card_queue_{room_id}_{pick_index}_{stable_key}_{surface}"


def build_rec_card_queue_widget_key(
    *,
    room_id: str,
    pick_index: int,
    stable_key: str,
    surface: str = "rec_card",
) -> str:
    """Collision-safe widget key (room + pick + player + surface)."""
    rid = str(room_id or "noroom").strip().upper()[:16]
    sk = str(stable_key or "unknown").strip()[:48]
    surf = str(surface or "rec_card").strip()[:24]
    return f"rec_card_queue_{rid}_{int(pick_index)}_{sk}_{surf}"


def begin_rec_queue_click_trace(
    session: dict[str, Any],
    *,
    event_id: str,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    queue_before: list[str],
) -> None:
    eid = str(event_id or "").strip() or new_rec_queue_event_id()
    row: dict[str, Any] = {
        "event_id": eid,
        "ts": time.time(),
        "room_id": str(room_id or "").strip(),
        "pick_index": int(pick_index),
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip(),
        "widget_key": str(widget_key or "").strip(),
        "surface": "rec_card",
        "button_event_observed": True,
        "callback_entered": True,
        "queue_before_mutation": list(queue_before)[:20],
        "mutation_helper_entered": False,
        "mutation_result": None,
        "queue_immediately_after_mutation": [],
        "added": False,
        "persistence_write_attempted": False,
        "persistence_write_result": None,
        "exception": None,
        "session_queue_key": "draft_queue",
    }
    _append_ledger(session, row)


def note_rec_queue_mutation_trace(
    session: dict[str, Any],
    *,
    event_id: str,
    mutation_helper_entered: bool,
    mutation_result: Any,
    queue_after: list[str],
    added: bool,
    exception: str | None = None,
) -> None:
    last = dict(session.get(TRACE_LAST_KEY) or {})
    if str(last.get("event_id") or "") != str(event_id):
        return
    last["mutation_helper_entered"] = bool(mutation_helper_entered)
    last["mutation_result"] = mutation_result
    last["queue_immediately_after_mutation"] = list(queue_after)[:20]
    last["added"] = bool(added)
    if exception:
        last["exception"] = str(exception)[:500]
    try:
        from live_draft_queue_persist import is_draft_queue_persist_dirty

        last["persistence_write_attempted"] = True
        last["persistence_write_result"] = "persist_dirty" if is_draft_queue_persist_dirty(session) else "not_dirty"
    except ImportError:
        last["persistence_write_attempted"] = False
    session[TRACE_LAST_KEY] = last
    book = _ledger(session)
    if book and str(book[-1].get("event_id") or "") == str(event_id):
        book[-1] = dict(last)
    else:
        _append_ledger(session, last)


def note_rec_queue_post_prepare(session: dict[str, Any], *, prepare_reason: str = "") -> None:
    """Run at end of prepare_draft_workflow — links rerun/hydration to last click trace."""
    last = dict(session.get(TRACE_LAST_KEY) or {})
    if not last.get("event_id"):
        return
    try:
        from draft_state import DRAFT_QUEUE_KEY, is_draft_locally_dirty

        q = [str(x).strip() for x in (session.get(DRAFT_QUEUE_KEY) or []) if str(x).strip()]
        ds_q: list[str] = []
        ds = session.get("draft_state")
        if isinstance(ds, dict):
            ds_q = [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]
    except ImportError:
        q = [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]
        ds_q = []
        is_draft_locally_dirty = lambda _s: bool(_s.get("draft_state_dirty"))  # type: ignore[assignment,misc]

    snap = {
        "event_id": last.get("event_id"),
        "ts": time.time(),
        "phase": "post_prepare_draft_workflow",
        "prepare_reason": str(prepare_reason or ""),
        "queue_after_rerun_hydration": list(q)[:20],
        "draft_state_queue": list(ds_q)[:20],
        "locally_dirty": bool(is_draft_locally_dirty(session)),
        "hydrate_skipped": session.get("_live_draft_queue_hydrate_skipped"),
        "empty_write_blocked": session.get("_live_draft_queue_empty_write_blocked"),
        "stale_hydrate_blocked": session.get("_live_draft_queue_stale_hydrate_blocked"),
    }
    last["post_prepare"] = snap
    session[TRACE_LAST_KEY] = last
    book = _ledger(session)
    if book:
        book[-1] = dict(last)


def classify_rec_queue_trace(record: dict[str, Any] | None) -> str:
    """Map app-side trace to QUEUE1C3* subcode."""
    if not isinstance(record, dict) or not record.get("event_id"):
        return "QUEUE1C3"
    if not record.get("callback_entered"):
        return "QUEUE1C3A"
    if not record.get("mutation_helper_entered"):
        return "QUEUE1C3B"
    if record.get("exception"):
        return "QUEUE1C3G"
    added = bool(record.get("added"))
    after_mut = list(record.get("queue_immediately_after_mutation") or [])
    post = record.get("post_prepare") if isinstance(record.get("post_prepare"), dict) else {}
    after_hydrate = list(post.get("queue_after_rerun_hydration") or [])
    if added and after_mut and not after_hydrate:
        return "QUEUE1C3D"
    if added and after_mut and after_hydrate and not _name_in_queue(record.get("player_name"), after_hydrate):
        return "QUEUE1C3E" if post.get("draft_state_queue") else "QUEUE1C3D"
    if not added and not after_mut:
        return "QUEUE1C3C"
    if added and after_mut and _name_in_queue(record.get("player_name"), after_hydrate):
        return "QUEUE1C3F"
    return "QUEUE1C3_8"


def _name_in_queue(name: Any, queue: list[str]) -> bool:
    target = str(name or "").strip().lower()
    if not target:
        return False
    return target in {str(x).strip().lower() for x in queue}


def trace_export_payload(session: dict[str, Any]) -> dict[str, Any]:
    last = dict(session.get(TRACE_LAST_KEY) or {})
    reg = session.get(WIDGET_REGISTRY_KEY) if isinstance(session.get(WIDGET_REGISTRY_KEY), dict) else {}
    return {
        "last": last,
        "classification": classify_rec_queue_trace(last),
        "widget_registry_size": len(reg),
        "widget_key_dupes": session.get("_live_draft_rec_queue_widget_key_dupes") or [],
        "ledger_len": len(_ledger(session)),
    }


def render_rec_queue_click_trace_probe(st: Any, session: dict[str, Any]) -> None:
    """Hidden DOM probe for production harness (solo_component_diag surfaces)."""
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        if not solo_component_diag_enabled(st, session):
            return
    except ImportError:
        if not session.get("_solo_component_diag_enabled"):
            return
    payload = json.dumps(trace_export_payload(session), default=str)[:8000]
    last = dict(session.get(TRACE_LAST_KEY) or {})
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    st.markdown(
        f'<div id="rec-card-queue-click-trace" '
        f'data-event-id="{safe(last.get("event_id"))}" '
        f'data-callback-entered="{1 if last.get("callback_entered") else 0}" '
        f'data-added="{1 if last.get("added") else 0}" '
        f'data-classification="{safe(classify_rec_queue_trace(last))}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
