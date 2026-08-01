"""Human-readable summary for production callback metadata diagnostic artifacts."""

from __future__ import annotations

import json
from typing import Any


def format_metadata_diagnostic_txt(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Production callback metadata diagnostic")
    lines.append("=" * 48)
    lines.append(f"accepted_prior_application_boundary: {report.get('accepted_prior_outcome')}")
    lines.append(f"prior_metadata_run_verdict: {report.get('prior_metadata_run_verdict')}")
    lines.append(f"metadata_fix_implementation_sha: {report.get('metadata_fix_implementation_sha')}")
    lines.append(f"deploy_trigger_sha: {report.get('deploy_trigger_sha')}")
    lines.append(f"origin_dev_head: {report.get('git_head')}")
    lines.append(f"live_sha: {report.get('live_sha')}")
    lines.append(f"live_build: {report.get('live_build')}")
    lines.append(f"first_boundary: {report.get('first_boundary')}")
    lines.append(f"smallest_correction_boundary: {report.get('smallest_correction_boundary')}")
    lines.append("")

    ca = report.get("case_a_metadata_authority") or {}
    lines.append("Case A metadata authority")
    lines.append("-" * 24)
    lines.append(f"authoritative: {ca.get('authoritative')}")
    lines.append(f"reason: {ca.get('reason', '')}")
    for k, v in sorted((ca.get("checks") or {}).items()):
        lines.append(f"  {k}: {v}")
    lines.append("")

    if report.get("case_a_internal_timeline_summary"):
        lines.append("Case A internal timeline (summary)")
        lines.append(json.dumps(report["case_a_internal_timeline_summary"], indent=2, default=str))
        lines.append("")

    if report.get("production_internal_timeline_summary"):
        lines.append("Production internal timeline (summary)")
        lines.append(json.dumps(report["production_internal_timeline_summary"], indent=2, default=str))
        lines.append("")

    detail = report.get("classification_detail") or {}
    if detail:
        lines.append("CM classification detail")
        lines.append(json.dumps(detail, indent=2, default=str))
    lines.append("")
    lines.append(f"artifact_json: {report.get('artifact_path')}")
    return "\n".join(lines)


def summarize_internal_lane(rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    if not rows:
        return {"label": label, "count": 0}
    last = rows[-1]
    return {
        "label": label,
        "count": len(rows),
        "authoritative_widget_id": last.get("authoritative_widget_id") or last.get("widget_id"),
        "metadata_callback_present": last.get("metadata_callback_present"),
        "metadata_callback_identity": last.get("metadata_callback_identity"),
        "callback_registered_in_metadata": last.get("callback_registered_in_metadata"),
        "new_value_repr": last.get("new_value_repr") or last.get("deserialized_value_repr"),
        "old_value_repr": last.get("old_value_repr") or last.get("old_deserialized_value_repr"),
        "widget_changed_result": last.get("widget_changed_result"),
        "callback_selected": last.get("callback_selected"),
        "skip_reason": last.get("skip_reason"),
    }
