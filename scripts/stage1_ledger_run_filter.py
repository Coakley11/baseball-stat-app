"""Filter merged Stage 1 ledger rows to a single diagnostic run identity."""

from __future__ import annotations

from typing import Any


def _token_room_id(token: str) -> str:
    parts = str(token or "").strip().split("|")
    if not parts:
        return ""
    return parts[0].strip().upper()


def filter_ledger_rows_for_diagnostic_run(
    rows: list[dict[str, Any]],
    *,
    run_id: str = "",
    room_id: str = "",
    deployment_sha: str = "",
    exact_token: str = "",
) -> dict[str, Any]:
    rid = str(run_id or "").strip()
    room = str(room_id or "").strip().upper()
    sha = str(deployment_sha or "").strip().lower()[:7]
    tok = str(exact_token or "").strip()
    tok_room = _token_room_id(tok)

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        reasons: list[str] = []
        row_run = str(row.get("run_id") or "").strip()
        row_room = str(row.get("room_id") or "").strip().upper()
        row_sha = str(row.get("deployment_sha") or row.get("cloud_sha") or "").strip().lower()[:7]
        row_tok = str(row.get("expected_token") or row.get("token") or row.get("bound_token") or "")
        row_tok_room = _token_room_id(row_tok)

        if rid and row_run and row_run != rid:
            reasons.append("run_id_mismatch")
        if room and row_room and row_room != room:
            reasons.append("room_id_mismatch")
        if sha and row_sha and row_sha != sha:
            reasons.append("deployment_sha_mismatch")
        if tok_room and row_tok_room and row_tok_room != tok_room:
            reasons.append("token_room_mismatch")
        if tok and row_tok and row_tok.strip() != tok and row.get("event") in (
            "production_stage1_delivery_only_observation_completed",
            "production_stage1_post_bind_actionable_flush",
            "production_stage1_bound_token_gate",
            "production_stage1_process_production_expire_token_entry",
        ):
            reasons.append("exact_token_mismatch")

        if reasons:
            rejected.append({"row": row, "reasons": reasons})
        else:
            kept.append(row)

    return {
        "rows_before": len(rows),
        "rows_after": len(kept),
        "rejected_count": len(rejected),
        "rejected": rejected[:80],
        "filtered_rows": kept,
        "filter_run_id": rid,
        "filter_room_id": room,
        "filter_deployment_sha": sha,
        "filter_exact_token": tok,
        "rejection_reasons": _rejection_reason_counts(rejected),
    }


def _rejection_reason_counts(rejected: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in rejected:
        if not isinstance(item, dict):
            continue
        for reason in item.get("reasons") or []:
            key = str(reason)
            counts[key] = counts.get(key, 0) + 1
    return counts
