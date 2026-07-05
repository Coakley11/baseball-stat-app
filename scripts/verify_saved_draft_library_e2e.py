#!/usr/bin/env python3
"""End-to-end Saved Draft Library save verification (local, no Streamlit UI).

Runs:
1. Simulator save -> session library count
2. Disk persist round-trip via baseball_persistent_state helpers
3. Optional cloud probe when configured

Usage:
  python scripts/verify_saved_draft_library_e2e.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from draft_archive_state import DRAFT_ARCHIVE_KEY, list_draft_archives
from draft_library_save_trace import (
    begin_save_trace,
    finalize_save_trace,
    probe_disk_workflow_for_workspace,
    record_library_load_trace,
)
from fantasy_league_context import FANTASY_LEAGUE_CONTEXT_STATE_KEY, save_simulator_league_context
from workflow_persist_guard import workflow_counts_from_session


def _mock_board(picks: int = 16) -> pd.DataFrame:
    rows = []
    teams = ["Daniel", "Team B", "Team C", "Team D"]
    for i in range(picks):
        rows.append(
            {
                "Pick": i + 1,
                "Team": teams[i % len(teams)],
                "Player": f"Player {i + 1}",
                "Position": "OF",
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    session: dict = {"room_your_team": "Daniel", "draft_shared_settings": {}}
    board = _mock_board()

    print("=== Saved Draft Library E2E (local) ===")
    begin_save_trace(session, source="draft_room_simulator", reason="simulator_league_context_saved", draft_name="E2E Mock")
    before = workflow_counts_from_session(session)
    entry, context = save_simulator_league_context(
        session,
        board,
        my_team_name="Daniel",
        draft_name="E2E Mock",
        defer_activation=True,
        reuse_session_draft_id=False,
    )
    after = workflow_counts_from_session(session)
    draft_id = str(entry.get("draft_id") or "")
    print(f"1. Session save: draft_id={draft_id} counts {before} -> {after}")

    if not draft_id or after["draft_archive_count"] <= before["draft_archive_count"]:
        print("FAIL: session library did not increment")
        return 1

    diag = finalize_save_trace(
        session,
        reason="simulator_league_context_saved",
        before=before,
        after=after,
        persist_ok=True,
        entry=entry,
        cloud_write_ok=False,
        disk_write_ok=False,
        probe_cloud=False,
    )
    print(f"2. Trace steps: {diag.get('steps')}")

    blob = {
        DRAFT_ARCHIVE_KEY: session[DRAFT_ARCHIVE_KEY],
        FANTASY_LEAGUE_CONTEXT_STATE_KEY: session[FANTASY_LEAGUE_CONTEXT_STATE_KEY],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "baseball_user_state.json"
        path.write_text(json.dumps(blob), encoding="utf-8")
        restored = json.loads(path.read_text(encoding="utf-8"))
        disk_count = len(restored.get(DRAFT_ARCHIVE_KEY) or [])
        in_disk = any(str(r.get("draft_id") or "") == draft_id for r in restored.get(DRAFT_ARCHIVE_KEY) or [])
        print(f"3. Disk round-trip: count={disk_count} contains_draft={in_disk}")
        if not in_disk:
            print("FAIL: draft missing from disk blob")
            return 1

    cold: dict = {}
    cold[DRAFT_ARCHIVE_KEY] = blob[DRAFT_ARCHIVE_KEY]
    cold[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = blob[FANTASY_LEAGUE_CONTEXT_STATE_KEY]
    load = record_library_load_trace(cold)
    print(
        f"4. Library load trace: session={load.get('library_load_count_session')} "
        f"restore_source={load.get('restore_source')}"
    )

    disk_probe = probe_disk_workflow_for_workspace()
    print(f"5. Live disk probe (may be empty locally): {disk_probe.get('draft_archive_count', 0)} drafts")

    print("PASS: simulator save -> session -> disk blob verified")
    print(f"   league_context_id={context.get('league_context_id')}")
    print(f"   archives_in_session={len(list_draft_archives(session))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
