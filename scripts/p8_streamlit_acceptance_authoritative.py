"""Authoritative acceptance artifacts (single Cloud pass via symmetric harness)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "p8_streamlit_acceptance_authoritative.json"
OUT_TXT = ROOT / "data" / "p8_streamlit_acceptance_authoritative.txt"


def format_txt(report: dict) -> str:
    from p8_streamlit_acceptance_symmetric import format_txt as sym_txt

    base = sym_txt(report)
    extra = [
        "",
        "=== AUTHORITATIVE ACCEPTANCE ===",
        f"deploy_marker_sha={report.get('deploy_marker_sha')}",
        f"observability_implementation_sha={report.get('observability_implementation_sha')}",
        f"active_at_send={(report.get('active_at_send_proof') or {}).get('active_at_send')}",
        f"production_identity={json.dumps(report.get('production_identity') or {}, indent=2)}",
    ]
    return base + "\n".join(extra) + "\n"


def main() -> int:
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))

    from p8_canary_build_gate import git_head_short, local_deploy_pin
    from p8_streamlit_acceptance_symmetric import _json_safe, run

    report = run(authoritative_acceptance=True)
    report["deploy_marker_sha"] = local_deploy_pin()
    report["observability_implementation_sha"] = git_head_short()
    try:
        report["origin_dev_head"] = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "origin/dev"],
                cwd=ROOT,
                text=True,
                timeout=8,
            )
            .strip()
            .lower()[:7]
        )
    except Exception:
        report["origin_dev_head"] = report.get("origin_dev_head") or ""

    safe = _json_safe(report)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(safe, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    print(format_txt(report))
    aborted = report.get("aborted") and not (report.get("control_gate") or {}).get("ok")
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
