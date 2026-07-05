#!/usr/bin/env python3
"""Read-only probe of production cloud baseball full_session workflow keys."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflow_persist_guard import probe_cloud_workflow_for_workspace  # noqa: E402


def main() -> int:
    workspaces = ["daniel", "coakley11", "ariel", "guest", "test_user"]
    if len(sys.argv) > 1:
        workspaces = [w.strip() for w in sys.argv[1:] if w.strip()]

    results = [probe_cloud_workflow_for_workspace(ws) for ws in workspaces]
    print(json.dumps(results, indent=2, default=str))

    any_drafts = any(int(r.get("draft_archive_count") or 0) > 0 for r in results)
    any_contexts = any(int(r.get("league_context_count") or 0) > 0 for r in results)
    if not results[0].get("cloud_enabled"):
        print("\nCloud storage is not configured in this environment.", file=sys.stderr)
        return 2
    if any_drafts or any_contexts:
        print("\nFound workflow data in at least one cloud workspace.", file=sys.stderr)
        return 0
    print("\nNo draft_archive_teams or league contexts found in probed cloud workspaces.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
