"""Minimal P6 diagnostic observer — separate Streamlit session, no auth/LDR routing."""

from __future__ import annotations

import base64
import json
from typing import Any

P6_OBSERVER_QP = "solo_p6_diag_observer"
P6_RUN_ID_QP = "solo_p6_run_id"
OBSERVER_ELEMENT_ID = "solo-p6-diag-observer"


def _qp_get(st: Any, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as get_qp

        return get_qp(st, name)
    except ImportError:
        return ""


def _qp_flag(st: Any, name: str) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_flag as flag

        return flag(st, name)
    except ImportError:
        return False


def observer_page_requested(st: Any) -> bool:
    return _qp_flag(st, P6_OBSERVER_QP)


def build_observer_payload(run_id: str) -> dict[str, Any]:
    from live_draft_solo_parity_p6_persistent_diag import build_ledger_snapshot_for_run

    return build_ledger_snapshot_for_run(run_id)


def try_serve_p6_diag_observer(st: Any) -> None:
    """If observer query params are set, render ledger and stop (no workspace/auth/LDR)."""
    if not observer_page_requested(st):
        return
    run_id = _qp_get(st, P6_RUN_ID_QP).strip()
    if not run_id:
        st.error("solo_p6_run_id is required for the diagnostic observer.")
        st.stop()
        return
    payload = build_observer_payload(run_id)
    raw_json = json.dumps(payload, default=str)
    if len(raw_json) > 240000:
        raw_json = raw_json[:240000]
    b64 = base64.b64encode(raw_json.encode("utf-8")).decode("ascii")
    expected = str(payload.get("expected_token") or "")
    st.markdown(
        f'<div id="{OBSERVER_ELEMENT_ID}" '
        f'data-run-id="{run_id.replace(chr(34), chr(39))}" '
        f'data-expected-token="{expected.replace(chr(34), chr(39))[:200]}" '
        f'data-row-count="{len(payload.get("ledger_rows") or [])}" '
        f'data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )
    st.stop()
