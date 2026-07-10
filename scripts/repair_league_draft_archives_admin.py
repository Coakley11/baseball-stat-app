#!/usr/bin/env python3
"""One-shot admin repair for wiped draft_archive_teams after trade proposal regression.

Rebuilds saved draft library cards from canonical shared league context for
Daniel and coakley11, writes cloud rows, and verifies fresh readback.

Usage:
  python scripts/repair_league_draft_archives_admin.py
  python scripts/repair_league_draft_archives_admin.py --dry-run
  python scripts/repair_league_draft_archives_admin.py --league-id league:abc --workspace daniel
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fantasy_admin_draft_archive_repair import (  # noqa: E402
    DEFAULT_REPAIR_LEAGUE_ID,
    DEFAULT_REPAIR_WORKSPACES,
    run_league_draft_archive_repair,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Admin repair for shared-league draft archive wipe.")
    parser.add_argument(
        "--league-id",
        default=DEFAULT_REPAIR_LEAGUE_ID,
        help=f"Canonical shared league id (default: {DEFAULT_REPAIR_LEAGUE_ID})",
    )
    parser.add_argument(
        "--workspace",
        action="append",
        dest="workspaces",
        help="Workspace slug to repair (repeatable). Defaults to daniel + coakley11.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Repair in memory only; do not write cloud or disk.",
    )
    parser.add_argument(
        "--no-disk",
        action="store_true",
        help="Skip local disk writeback (cloud write still runs unless --dry-run).",
    )
    args = parser.parse_args()

    workspaces = tuple(args.workspaces) if args.workspaces else DEFAULT_REPAIR_WORKSPACES
    trace = run_league_draft_archive_repair(
        league_id=args.league_id,
        workspaces=workspaces,
        dry_run=bool(args.dry_run),
        write_disk=not args.no_disk,
    )
    print(json.dumps(trace, indent=2, default=str))

    if not trace.get("shared_doc_found"):
        print("\nFAIL: shared league document not found.", file=sys.stderr)
        return 2
    if not trace.get("ok"):
        print("\nFAIL: repair completed with errors.", file=sys.stderr)
        for ws in trace.get("workspace_results") or []:
            errs = ws.get("errors") or []
            if errs:
                print(f"  {ws.get('workspace_id')}: {errs}", file=sys.stderr)
        return 1

    mode = "dry-run" if args.dry_run else "write"
    print(f"\nOK: admin draft archive repair ({mode}) succeeded for {', '.join(workspaces)}.", file=sys.stderr)
    for ws in trace.get("workspace_results") or []:
        before = (ws.get("repair_trace") or {}).get("before") or {}
        after = (ws.get("repair_trace") or {}).get("after") or {}
        rb = ws.get("readback") or {}
        print(
            f"  {ws.get('workspace_id')}: archives {before.get('raw_archive_count')} -> "
            f"{after.get('raw_archive_count')}; readback={rb.get('draft_archive_count')}; "
            f"active={after.get('active_draft_archive_id')}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
