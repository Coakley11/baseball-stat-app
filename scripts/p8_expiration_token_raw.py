"""Exact expiration token fields for artifacts (no markdown truncation)."""

from __future__ import annotations

import ast
import re
from typing import Any


def _unwrap_repr(repr_str: Any) -> str:
    s = str(repr_str or "").strip()
    if not s or s == "missing":
        return ""
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        try:
            return str(ast.literal_eval(s))
        except (SyntaxError, ValueError):
            return s[1:-1]
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        try:
            return str(ast.literal_eval(s))
        except (SyntaxError, ValueError):
            return s[1:-1]
    return s


def _rows(rows: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == event]


def _last_token_row(rows: list[dict[str, Any]], token: str) -> dict[str, Any]:
    if not token:
        return rows[-1] if rows else {}
    for r in reversed(rows):
        rep = str(r.get("deserialized_value_repr") or r.get("new_value_repr") or "")
        if token in rep or token.replace("|", "") in rep.replace("|", ""):
            return r
    return rows[-1] if rows else {}


def build_expiration_token_raw_report(
    *,
    expected_token: str,
    filtered_rows: list[dict[str, Any]],
    expiration: dict[str, Any] | None = None,
    return_value_chain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exp = expiration or {}
    rv = return_value_chain or {}
    browser = rv.get("browser") if isinstance(rv.get("browser"), dict) else {}
    entered = _rows(filtered_rows, "production_stage1_prod_on_change_entered")
    exited = _rows(filtered_rows, "production_stage1_prod_on_change_exited")
    dispatch = _rows(filtered_rows, "production_stage1_callback_dispatch_evaluated")
    backend = _rows(filtered_rows, "production_stage1_backend_widget_state_after_backmsg")

    last_dispatch = _last_token_row(dispatch, expected_raw)
    last_backend = _last_token_row(backend, expected_raw)
    entry = entered[-1] if entered else {}
    exit_row = exited[-1] if exited else {}

    expected_raw = str(expected_token or exp.get("token_sent") or browser.get("exact_expiration_token") or "").strip()
    browser_raw = str(exp.get("token_sent") or browser.get("exact_expiration_token") or "").strip()
    backend_raw = _unwrap_repr(
        last_dispatch.get("new_value_repr")
        or last_backend.get("deserialized_value_repr")
        or last_backend.get("new_value_repr")
    )
    callback_entry_raw = _unwrap_repr(entry.get("session_state_value_repr"))
    callback_exit_raw = _unwrap_repr(exit_row.get("session_state_value_at_exit_repr"))
    post_callback_raw = _unwrap_repr(
        (rv.get("session_state") or {}).get("same_key_value_repr")
        if isinstance(rv.get("session_state"), dict)
        else ""
    )
    wrapper_raw = _unwrap_repr(
        (rv.get("wrapper") or {}).get("coalesced_token")
        if isinstance(rv.get("wrapper"), dict)
        else (rv.get("declaration") or {}).get("return_value_repr")
        if isinstance(rv.get("declaration"), dict)
        else ""
    )

    def _eq(a: str, b: str) -> bool:
        if not a or not b:
            return False
        return a == b or a.replace("|", "") == b.replace("|", "")

    return {
        "expected_token_raw": expected_raw,
        "browser_token_raw": browser_raw,
        "backend_new_value_raw": backend_raw,
        "callback_entry_value_raw": callback_entry_raw,
        "callback_exit_value_raw": callback_exit_raw,
        "post_callback_session_value_raw": post_callback_raw,
        "wrapper_read_value_raw": wrapper_raw,
        "browser_equals_expected": _eq(browser_raw, expected_raw),
        "backend_equals_expected": _eq(backend_raw, expected_raw),
        "callback_entry_equals_expected": _eq(callback_entry_raw, expected_raw),
        "callback_exit_equals_expected": _eq(callback_exit_raw, expected_raw),
        "wrapper_read_equals_expected": _eq(wrapper_raw, expected_raw),
    }
