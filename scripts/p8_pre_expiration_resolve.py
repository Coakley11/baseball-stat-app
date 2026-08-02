"""Authoritative pre-expiration field resolution (harness only)."""

from __future__ import annotations

import time
from typing import Any

PREEXP_LEDGER_EVENTS = (
    "production_stage1_start_handler_exited",
    "production_stage1_handler_exit_session_state_proof",
    "production_stage1_room_state_read",
    "production_stage1_room_state_write",
    "production_countdown_declaration_pre",
    "production_countdown_declaration_post",
    "production_live_draft_branch_canary",
)


def _norm_room(v: Any) -> str:
    return str(v or "").strip().upper()


def _deadline_from_row(row: dict[str, Any]) -> float | None:
    for key in ("deadline", "timer_deadline", "session_deadline_token"):
        raw = row.get(key)
        if raw is None or str(raw).strip() in ("", "None"):
            continue
        try:
            val = float(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            continue
    auth = row.get("authoritative_session_state")
    if isinstance(auth, dict) and auth is not row:
        for key in ("deadline", "timer_deadline", "session_deadline_token"):
            raw = auth.get(key)
            if raw is None or str(raw).strip() in ("", "None"):
                continue
            try:
                val = float(raw)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                continue
    return None


def _pick_from_row(row: dict[str, Any]) -> int | None:
    for key in ("pick_index", "session_pick_index", "current_pick_index"):
        if row.get(key) is not None:
            try:
                return int(row.get(key))
            except (TypeError, ValueError):
                pass
    auth = row.get("authoritative_session_state")
    if isinstance(auth, dict) and auth is not row:
        for key in ("session_pick_index", "pick_index", "current_pick_index"):
            if auth.get(key) is not None:
                try:
                    return int(auth.get(key))
                except (TypeError, ValueError):
                    pass
    return None


def _token_from_row(row: dict[str, Any]) -> str:
    for key in ("expected_token", "deadline_token", "session_deadline_token", "token"):
        t = str(row.get(key) or "").strip()
        if t and "|" in t:
            return t
    return ""


def _rows_for_room(
    rows: list[dict[str, Any]], *, room_id: str, run_id: str = ""
) -> list[dict[str, Any]]:
    rid = _norm_room(room_id)
    run = str(run_id or "").strip()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ev = str(r.get("event") or "")
        if ev not in PREEXP_LEDGER_EVENTS and not ev.startswith("production_countdown_declaration"):
            continue
        row_room = _norm_room(
            r.get("room_id")
            or r.get("created_room_id")
            or r.get("session_room_id")
            or (r.get("authoritative_session_state") or {}).get("session_room_id")
        )
        row_run = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
        if rid and row_room and row_room != rid:
            continue
        if run and row_run and row_run != run and row_room != rid:
            continue
        out.append(r)
    out.sort(key=lambda x: (float(x.get("ts") or 0), int(x.get("script_run_seq") or 0)))
    return out


def _build_token_from_app(room_id: str, pick_index: int, deadline: float) -> str:
    try:
        from solo_countdown_component import build_solo_expire_token

        room = {
            "draft_room_id": room_id,
            "draft_id": room_id,
            "current_pick_index": pick_index,
            "timer_deadline": deadline,
        }
        return str(build_solo_expire_token(room) or "").strip()
    except Exception:
        return ""


def _parse_token(token: str) -> dict[str, Any] | None:
    try:
        from solo_countdown_component import parse_solo_expire_token

        return parse_solo_expire_token(token)
    except Exception:
        parts = str(token or "").strip().split("|")
        if len(parts) != 3:
            return None
        try:
            return {
                "draft_id": parts[0].strip().upper(),
                "pick_index": int(parts[1]),
                "deadline": float(parts[2]),
            }
        except (TypeError, ValueError):
            return None


def _countdown_mounted_scrape(scrape: dict[str, Any]) -> bool:
    if scrape.get("countdown_mounted"):
        return True
    mount = scrape.get("mount") or {}
    if str(mount.get("mounted") or "") in ("1", "true"):
        return True
    if scrape.get("timer_seconds") not in (None, ""):
        return True
    ui = scrape.get("ui") or {}
    if ui.get("ccTimer") is not None:
        return True
    text = str(scrape.get("text_excerpt") or "")
    return bool(scrape.get("in_progress")) and "Time remaining:" in text


def resolve_authoritative_pre_expiration_state(
    *,
    ledger_rows: list[dict[str, Any]],
    ui_scrape: dict[str, Any],
    room_id: str,
    diagnostic_run_id: str = "",
    click_count: int = 1,
    room_latch_pass: bool = False,
    now_ts: float | None = None,
) -> dict[str, Any]:
    """Merge server ledger + render corroboration into authoritative pre-expiration fields."""
    now = float(now_ts if now_ts is not None else time.time())
    rid = _norm_room(room_id) or _norm_room(ui_scrape.get("room_id"))
    run_id = str(diagnostic_run_id or "").strip()
    scoped = _rows_for_room(ledger_rows, room_id=rid, run_id=run_id)

    candidates: dict[str, list[dict[str, Any]]] = {
        "room_id": [],
        "status": [],
        "pick_index": [],
        "deadline": [],
        "expected_token": [],
    }

    def _add(field: str, value: Any, source: str, row: dict[str, Any] | None = None) -> None:
        if value is None or value == "":
            return
        candidates[field].append({"value": value, "source": source, "event": (row or {}).get("event"), "ts": (row or {}).get("ts")})

    # Server reads (ultra_early preferred)
    reads = [r for r in scoped if r.get("event") == "production_stage1_room_state_read"]
    ultra = [r for r in reads if "ultra_early" in str(r.get("read_label") or "")]
    for r in reversed(ultra or reads):
        _add("room_id", _norm_room(r.get("session_room_id") or r.get("room_id")), "room_state_read", r)
        if str(r.get("session_draft_status") or r.get("room_status") or "").lower() == "in_progress":
            _add("status", "in_progress", "room_state_read", r)
        _add("pick_index", _pick_from_row(r), "room_state_read", r)
        dl = _deadline_from_row(r)
        if dl is not None:
            _add("deadline", dl, "room_state_read", r)
        _add("expected_token", _token_from_row(r), "room_state_read", r)

    proofs = [r for r in scoped if r.get("event") == "production_stage1_handler_exit_session_state_proof"]
    for r in reversed(proofs):
        auth = r.get("authoritative_session_state") or {}
        _add("room_id", _norm_room(auth.get("session_room_id") or r.get("room_id")), "handler_session_proof", r)
        if str(auth.get("session_draft_status") or r.get("room_status") or "").lower() == "in_progress":
            _add("status", "in_progress", "handler_session_proof", r)
        _add("pick_index", _pick_from_row(r), "handler_session_proof", r)
        dl = _deadline_from_row(r)
        if dl is not None:
            _add("deadline", dl, "handler_session_proof", r)
        _add("expected_token", _token_from_row(r), "handler_session_proof", r)

    handlers = [r for r in scoped if r.get("event") == "production_stage1_start_handler_exited"]
    for r in reversed(handlers):
        _add("room_id", _norm_room(r.get("created_room_id") or r.get("room_id")), "start_handler_exited", r)
        if str(r.get("draft_status") or r.get("room_status") or "").lower() == "in_progress":
            _add("status", "in_progress", "start_handler_exited", r)
        _add("pick_index", _pick_from_row(r), "start_handler_exited", r)
        dl = _deadline_from_row(r)
        if dl is not None:
            _add("deadline", dl, "start_handler_exited", r)
        _add("expected_token", _token_from_row(r), "start_handler_exited", r)

    decl = [
        r
        for r in scoped
        if str(r.get("event") or "").startswith("production_countdown_declaration")
    ]
    for r in reversed(decl):
        _add("expected_token", _token_from_row(r), str(r.get("event") or "declaration"), r)
        _add("pick_index", _pick_from_row(r), str(r.get("event") or "declaration"), r)
        dl = _deadline_from_row(r)
        if dl is not None:
            _add("deadline", dl, str(r.get("event") or "declaration"), r)

    scrape_rid = _norm_room(ui_scrape.get("room_id"))
    if scrape_rid:
        _add("room_id", scrape_rid, "ui_scrape", None)
    if ui_scrape.get("in_progress"):
        _add("status", "in_progress", "ui_scrape", None)
    if ui_scrape.get("pick_index") is not None:
        _add("pick_index", int(ui_scrape.get("pick_index")), "ui_mount", None)
    mount = ui_scrape.get("mount") or {}
    for key in ("pick_index", "pick-index"):
        if mount.get(key) not in (None, ""):
            try:
                _add("pick_index", int(mount.get(key)), "ui_mount", None)
            except (TypeError, ValueError):
                pass
    dl_mount = mount.get("diag_deadline") or mount.get("deadline") or ui_scrape.get("deadline")
    if dl_mount not in (None, ""):
        try:
            _add("deadline", float(dl_mount), "ui_mount", None)
        except (TypeError, ValueError):
            pass
    dom_token = str(ui_scrape.get("production_token") or ui_scrape.get("expire_token") or mount.get("token") or "")
    if dom_token.strip():
        _add("expected_token", dom_token.strip(), "ui_mount", None)

    def _select(field: str, priority: list[str]) -> tuple[Any, str]:
        for src in priority:
            for c in candidates[field]:
                if c["source"] == src or src in str(c["source"]):
                    return c["value"], c["source"]
        if candidates[field]:
            c = candidates[field][-1]
            return c["value"], c["source"]
        return None, ""

    room_val, room_src = _select("room_id", ["room_state_read", "handler_session_proof", "start_handler_exited", "ui_scrape"])
    status_val, status_src = _select("status", ["room_state_read", "handler_session_proof", "start_handler_exited", "ui_scrape"])
    pick_val, pick_src = _select(
        "pick_index",
        [
            "production_countdown_declaration_post",
            "production_countdown_declaration_pre",
            "room_state_read",
            "handler_session_proof",
            "start_handler_exited",
            "ui_mount",
        ],
    )
    deadline_val, deadline_src = _select(
        "deadline",
        [
            "production_countdown_declaration_post",
            "production_countdown_declaration_pre",
            "room_state_read",
            "handler_session_proof",
            "start_handler_exited",
            "ui_mount",
        ],
    )
    token_val, token_src = _select(
        "expected_token",
        [
            "production_countdown_declaration_post",
            "production_countdown_declaration_pre",
            "room_state_read",
            "handler_session_proof",
            "start_handler_exited",
            "ui_mount",
        ],
    )

    token_constructed = False
    if not token_val and room_val and pick_val is not None and deadline_val is not None:
        built = _build_token_from_app(str(room_val), int(pick_val), float(deadline_val))
        if built:
            token_val = built
            token_src = "build_solo_expire_token"
            token_constructed = True

    parsed = _parse_token(str(token_val or "")) if token_val else None
    mount_ok = _countdown_mounted_scrape(ui_scrape)
    dom_pick_missing = ui_scrape.get("pick_index") is None and not (mount.get("pick_index") or mount.get("token"))
    dom_deadline_missing = not ui_scrape.get("deadline") and not mount.get("deadline")
    dom_token_missing = not dom_token.strip()

    room_creation_count = sum(
        1
        for r in ledger_rows
        if r.get("event") == "production_stage1_start_handler_exited" and _norm_room(r.get("created_room_id")) == rid
    )

    consistency: dict[str, Any] = {
        "room_id_matches_ui": bool(room_val and scrape_rid and _norm_room(room_val) == scrape_rid),
        "token_parses": parsed is not None,
        "token_matches_room": bool(parsed and _norm_room(parsed.get("draft_id")) == _norm_room(room_val)),
        "token_pick_matches": bool(parsed and pick_val is not None and int(parsed.get("pick_index")) == int(pick_val)),
        "token_deadline_matches": bool(
            parsed and deadline_val is not None and abs(float(parsed.get("deadline")) - float(deadline_val)) < 0.01
        ),
        "countdown_mounted": mount_ok,
        "deadline_not_expired": bool(deadline_val and float(deadline_val) > now),
    }

    ready = bool(
        room_latch_pass
        and click_count == 1
        and room_creation_count <= 1
        and room_val
        and status_val == "in_progress"
        and pick_val is not None
        and int(pick_val) == 0
        and deadline_val is not None
        and float(deadline_val) > 0
        and token_val
        and consistency["token_parses"]
        and consistency["room_id_matches_ui"]
        and consistency["token_matches_room"]
        and consistency["token_pick_matches"]
        and consistency["token_deadline_matches"]
        and mount_ok
        and consistency["deadline_not_expired"]
    )

    return {
        "room_id": _norm_room(room_val),
        "room_id_source": room_src,
        "status": status_val,
        "status_source": status_src,
        "pick_index": pick_val,
        "pick_index_source": pick_src,
        "deadline": deadline_val,
        "deadline_source": deadline_src,
        "expected_token": str(token_val or ""),
        "expected_token_source": token_src,
        "expected_token_constructed": token_constructed,
        "candidates": candidates,
        "consistency": consistency,
        "countdown_mounted": mount_ok,
        "dom_diagnostics_missing": {
            "pick_index": dom_pick_missing,
            "deadline": dom_deadline_missing,
            "token": dom_token_missing,
        },
        "click_count": click_count,
        "room_creation_events": room_creation_count,
        "pre_expiration_ready": ready,
        "parsed_token": parsed,
    }
