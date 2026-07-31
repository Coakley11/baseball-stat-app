"""Static symmetric comparison: Case A vs production component return binding."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "data" / "p8_component_return_binding_trace.json"
OUT_TXT = ROOT / "data" / "p8_component_return_binding_trace.txt"

CASE_A = {
    "component_name": "minimal_wake_repro",
    "module": "minimal_component_wake_repro_core",
    "declare_fn": "render_one_cycle",
    "streamlit_api": "_COMPONENT(expire_token, key, default=None, on_change=_on_change)",
    "on_change_at_mount": True,
    "reads_raw_return_after_mount": True,
    "delivery_sources": ["on_change", "return_value"],
    "wrappers": [],
    "declarations_per_cycle": 1,
    "user_key_pattern": "minimal_wake_repro_{cycle}",
}

PRODUCTION = {
    "component_name": "solo_countdown_wake",
    "module": "solo_countdown_wake_micro_core",
    "declare_fn": "render_micro_isolation_once",
    "streamlit_api": "mount_solo_countdown_wake_with_token(..., default=None, on_change=...)",
    "wrappers": [
        "live_draft_solo_persistent_wake._mount_persistent_wake_micro_controlled",
        "live_draft_stage1_post_bind_flush.evaluate_bound_token_gate",
        "live_draft_stage1_post_bind_flush.complete_delivery_only_observation_and_actionable_flush",
    ],
    "user_key": "solo_countdown_wake_solo_persistent",
    "delivery_mode_default": "return_value",
    "prior_bug": "production_use_return_value_delivery set on_change=None at mount",
    "correction_6b21b58_followup": "register _prod_on_change; single mount per script run; raw capture",
}


def classify_bind(report: dict) -> dict:
    diffs = report.get("signature_diffs") or []
    first = diffs[0] if diffs else {}
    code = "BIND9"
    rationale = "See first_difference."
    if first.get("field") == "on_change_at_mount":
        code = "BIND5"
        rationale = (
            "Production return_value path disabled on_change at mount; Case A always registers on_change "
            "and reads both Session State and raw return."
        )
    elif first.get("field") == "declarations_per_script_run":
        code = "BIND1"
        rationale = "Multiple production declarations per script run for the same persistent key."
    return {
        "code": code,
        "rationale": rationale,
        "first_failure_boundary": "PYTHON_COMPONENT_RETURN_BINDING",
        "smallest_correction_boundary": "Component return / on_change parity with Case A",
    }


def build_report() -> dict:
    diffs = [
        {
            "field": "on_change_at_mount",
            "case_a": True,
            "production_before_fix": False,
            "production_after_fix": True,
            "first_exact_difference": "return_value delivery cleared mount on_change",
        },
        {
            "field": "delivery_sources",
            "case_a": ["on_change", "return_value"],
            "production_before_fix": ["return_value_only"],
            "production_after_fix": ["on_change", "return_value", "gate_coalesce"],
        },
        {
            "field": "wrappers",
            "case_a": [],
            "production": PRODUCTION["wrappers"],
        },
        {
            "field": "declarations_per_script_run",
            "case_a": 1,
            "production_risk": "multiple pre/post canaries per run if mount invoked more than once",
            "guard_added": "per_run_key _solo_prod_mount_run_{key}",
        },
    ]
    report = {
        "accepted_cloud": "6b21b58",
        "accepted_classification": "S9C",
        "case_a": CASE_A,
        "production": PRODUCTION,
        "signature_diffs": diffs,
        "first_difference": diffs[0],
        "withdrawn_hypotheses": [
            "S1 stale widget ID",
            "LIFECYCLE4 backend did not run",
            "wrong iframe/parent",
            "invalid BackMsg",
            "wrong session/socket",
            "missing Live Draft routing",
        ],
    }
    report["bind_classification"] = classify_bind(report)
    return report


def format_txt(report: dict) -> str:
    cls = report.get("bind_classification") or {}
    lines = [
        "P8 component return binding comparison (Case A vs production)",
        f"BIND={cls.get('code')}",
        cls.get("rationale") or "",
        f"boundary={cls.get('smallest_correction_boundary')}",
        "",
        f"first_difference={json.dumps(report.get('first_difference'), indent=2)}",
        "",
        f"artifact={OUT_JSON}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    report = build_report()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    print(format_txt(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
