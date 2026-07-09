#!/usr/bin/env python3
"""Locate saved draft archives across cloud user_ids, app keys, and disk paths."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflow_persist_guard import discover_workflow_migration_sources  # noqa: E402


def main() -> int:
    session: dict = {}
    if len(sys.argv) > 1:
        session["_suite_auth_user_id"] = sys.argv[1].strip()
    if len(sys.argv) > 2:
        session["_suite_auth_external_id"] = sys.argv[2].strip()
        session["_suite_auth_session"] = True
        session["_suite_auth_user_email"] = sys.argv[2].strip()

    report = discover_workflow_migration_sources(session, app_id="baseball")
    print(json.dumps(report, indent=2, default=str))

    recoverable = int(report.get("recoverable_draft_count") or 0)
    if not report.get("cloud_enabled"):
        print("\nCloud storage is not configured in this environment.", file=sys.stderr)
        if recoverable > 0:
            print(f"Disk-only: found {recoverable} recoverable draft(s).", file=sys.stderr)
            return 0
        return 2

    sources = list(report.get("sources") or [])
    rich = [s for s in sources if int(s.get("draft_count") or 0) > 0]
    if rich:
        print(f"\nFound {recoverable} recoverable draft(s) in {len(rich)} source(s).", file=sys.stderr)
        best = report.get("best_source") or {}
        print(
            f"Best: {best.get('source_type')} · "
            f"{best.get('cloud_app_key') or best.get('path')} · "
            f"user_id={best.get('user_id')} · "
            f"names={best.get('draft_names')}",
            file=sys.stderr,
        )
        return 0

    print("\nNo recoverable drafts found in migration scan.", file=sys.stderr)
    users = report.get("historical_suite_users") or []
    if users:
        print("Historical suite_users rows:", file=sys.stderr)
        for row in users:
            print(f"  external_id={row.get('external_id')} id={row.get('id')} email={row.get('email')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
