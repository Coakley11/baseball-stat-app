"""Bidirectional Solo countdown — Streamlit v2 component wake at deadline zero."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import streamlit as st

_FRONTEND_DIR = (Path(__file__).resolve().parent / "frontend").resolve()

_SOLO_COUNTDOWN_JS = """
export default function(component) {
  const { data, setTriggerValue, parentElement } = component;
  const args = data || {};
  const deadline = Number(args.deadline || 0);
  const expireToken = String(args.expire_token || "");
  let activeToken = expireToken;
  let tickTimer = null;
  let sentTokens = {};

  function noteClient(stage) {
    try {
      let node = parentElement.querySelector("#solo-expire-client");
      if (!node) {
        node = document.createElement("div");
        node.id = "solo-expire-client";
        node.setAttribute("data-last", "");
        node.setAttribute("data-chain", "");
        node.style.display = "none";
        parentElement.appendChild(node);
      }
      const chain = String(node.getAttribute("data-chain") || "");
      node.setAttribute("data-last", stage);
      node.setAttribute(
        "data-chain",
        chain ? chain + "|" + stage : stage
      );
    } catch (e) {}
  }

  function clearTick() {
    if (tickTimer) {
      clearTimeout(tickTimer);
      tickTimer = null;
    }
  }

  function sendExpireToken(token) {
    if (!token || activeToken !== token || sentTokens[token]) return;
    sentTokens[token] = true;
    noteClient("component_value_sent");
    setTriggerValue("expire", token);
  }

  function tick() {
    if (activeToken !== expireToken) return;
    const rem = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
    if (rem <= 0) {
      noteClient("browser_deadline_crossed");
      window.setTimeout(function () {
        sendExpireToken(expireToken);
      }, 0);
      return;
    }
    tickTimer = window.setTimeout(tick, 250);
  }

  if (!expireToken || !Number.isFinite(deadline) || deadline <= 0) {
    return () => clearTick();
  }

  clearTick();
  tick();
  return () => clearTick();
}
"""

_COMPONENT = st.components.v2.component(
    "solo_countdown_wake",
    js=_SOLO_COUNTDOWN_JS,
    isolate_styles=False,
)


def get_component_frontend_dir() -> Path:
    return _FRONTEND_DIR


def component_frontend_ready() -> bool:
    return bool(_SOLO_COUNTDOWN_JS.strip())


def build_solo_expire_token(room: dict[str, Any]) -> str:
    """Unique expiration token: draft_id|pick_index|deadline."""
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()
    pick_index = int(room.get("current_pick_index") or 0)
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        deadline = live_draft_timer_deadline(room)
        if deadline is None:
            deadline = float(room.get("timer_deadline") or 0.0)
        else:
            deadline = float(deadline)
    except ImportError:
        deadline = float(room.get("timer_deadline") or 0.0)
    return f"{draft_id}|{pick_index}|{deadline:.3f}"


def parse_solo_expire_token(token: str) -> dict[str, Any] | None:
    parts = str(token or "").strip().split("|")
    if len(parts) != 3:
        return None
    try:
        return {
            "draft_id": parts[0].strip(),
            "pick_index": int(parts[1]),
            "deadline": float(parts[2]),
        }
    except (TypeError, ValueError):
        return None


def _coerce_component_token(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("token", "expire_token", "value"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value).strip()


def render_solo_countdown_wake(
    st: Any,
    room: dict[str, Any],
    *,
    key: str,
    session: dict[str, Any] | None = None,
    on_expire: Any | None = None,
) -> str | None:
    """Mount zero-height countdown component; returns expire token when deadline crosses zero."""
    if str(room.get("status") or "") != "in_progress":
        return None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline
    except ImportError:
        return None

    deadline = live_draft_timer_deadline(room)
    if deadline is None:
        raw_deadline = room.get("timer_deadline")
        if raw_deadline is not None:
            deadline = float(raw_deadline)
    if deadline is None:
        if isinstance(session, dict):
            session["_solo_component_diag"] = {
                "mounted": False,
                "reason": "no_deadline",
                "key": key,
            }
        return None

    expire_token = build_solo_expire_token(room)
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()
    pick_index = int(room.get("current_pick_index") or 0)
    deadline_arg = int(math.ceil(float(deadline)))
    expire_cb = on_expire if callable(on_expire) else (lambda: None)
    result = _COMPONENT(
        data={
            "draft_id": draft_id,
            "pick_index": pick_index,
            "deadline": deadline_arg,
            "expire_token": expire_token,
        },
        key=key,
        on_expire_change=expire_cb,
    )
    token = _coerce_component_token(getattr(result, "expire", None))
    if isinstance(session, dict):
        session["_solo_component_diag"] = {
            "mounted": True,
            "key": key,
            "expire_token": expire_token,
            "deadline": deadline_arg,
            "returned_token": token,
            "raw_type": type(getattr(result, "expire", None)).__name__,
            "component_api": "v2",
            "result_keys": sorted(str(k) for k in result.keys()) if hasattr(result, "keys") else [],
        }
    return token or None
