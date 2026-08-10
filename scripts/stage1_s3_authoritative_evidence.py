"""Build authoritative server evidence union from scraped S3 DOM payload."""

from __future__ import annotations

from typing import Any

from live_draft_stage1_server_evidence import merge_authoritative_server_rows


def build_authoritative_server_rows_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(payload or {})
    ledger = dict(payload.get("ledger") or {})
    ingress = dict(payload.get("appsession_ingress") or {})
    module_rows = list(ledger.get("module_rows") or [])
    if not module_rows:
        module_rows = list(ledger.get("rows") or [])
    local_rows = list(ledger.get("local_rows") or [])
    critical_rows = list(ledger.get("critical_server_rows") or [])
    ingress_rows = list(ingress.get("rows") or [])
    merge = merge_authoritative_server_rows(
        module_rows=module_rows,
        local_rows=local_rows,
        critical_rows=critical_rows,
        ingress_rows=ingress_rows,
    )
    merged = list(merge.get("merged_rows") or [])
    return {
        "authoritative_server_rows": merged,
        "row_count": len(merged),
        "phase_counts": dict(merge.get("phase_counts") or {}),
        "source_counts": {
            "module": merge.get("module_row_count"),
            "local": merge.get("local_row_count"),
            "critical": merge.get("critical_row_count"),
            "ingress": merge.get("ingress_row_count"),
        },
        "duplicate_event_id_count": merge.get("duplicate_event_id_count"),
        "event_ids": list(merge.get("event_ids") or []),
        "oldest_ts": merge.get("oldest_ts"),
        "newest_ts": merge.get("newest_ts"),
    }
