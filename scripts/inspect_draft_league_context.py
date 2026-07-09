"""Inspect a saved draft's league_rosters on disk and cloud."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def inspect_blob(blob: dict[str, Any] | None, label: str, draft_id: str) -> None:
    if not isinstance(blob, dict):
        print(f"=== {label} ===")
        print("missing or not a dict")
        return

    archives = blob.get("draft_archive_teams") or []
    entry = next(
        (a for a in archives if str(a.get("draft_id") or "") == draft_id),
        None,
    )
    print(f"=== {label} ===")
    if not entry:
        ids = [str(a.get("draft_id")) for a in archives if isinstance(a, dict)]
        print(f"draft not in draft_archive_teams; archive ids: {ids}")
    else:
        rosters = entry.get("league_rosters") or {}
        snap = entry.get("snapshot") or {}
        teams = list(rosters.keys()) if isinstance(rosters, dict) else []
        print("draft_name:", entry.get("draft_name"))
        print("draft_type:", entry.get("draft_type"))
        print("team_name:", entry.get("team_name"))
        print("league_context_id:", entry.get("league_context_id"))
        print("snapshot:", json.dumps(snap, default=str)[:800])
        print("league_rosters team count:", len(teams))
        print("league_rosters teams:", teams)
        for team in teams:
            players = (rosters.get(team) or {}).get("players") or []
            n = len([p for p in players if isinstance(p, dict)])
            print(f"  {team}: {n} players")
        print("entry players (direct):", len(entry.get("players") or []))

    store = blob.get("fantasy_league_context_state") or {}
    contexts = store.get("contexts") or {}
    ctx: dict[str, Any] | None = None
    for c in contexts.values():
        if not isinstance(c, dict):
            continue
        meta = c.get("metadata") or {}
        if str(meta.get("source_draft_id") or "") == draft_id:
            ctx = c
            break
        if str(c.get("league_context_id") or "").endswith(draft_id):
            ctx = c
            break
    if not ctx and entry:
        lcid = str(entry.get("league_context_id") or "")
        ctx = contexts.get(lcid) if lcid else None
    if not ctx:
        print("no league context linked to draft")
        print("context ids:", list(contexts.keys())[:10])
    else:
        rosters = ctx.get("league_rosters") or {}
        teams = list(rosters.keys()) if isinstance(rosters, dict) else []
        print("context league_context_id:", ctx.get("league_context_id"))
        print("context_type:", ctx.get("context_type"))
        print("my_team_name:", ctx.get("my_team_name"))
        print("context league_rosters team count:", len(teams))
        print("context teams:", teams)
        for team in teams:
            players = (rosters.get(team) or {}).get("players") or []
            n = len([p for p in players if isinstance(p, dict)])
            print(f"  {team}: {n} players")
    print()


def main() -> None:
    draft_id = sys.argv[1] if len(sys.argv) > 1 else "f768a17fef32"

    try:
        from suite_user_persistence import _load_raw

        for ws in ["daniel", None]:
            state, path, _ = _load_raw("baseball", ws)
            label = f"disk ws={ws or 'active'} path={path}"
            inspect_blob(state, label, draft_id)
    except Exception as exc:
        print("disk error:", type(exc).__name__, exc)
        print()

    try:
        from suite_storage_supabase import load_current_state_for_app
        from suite_workspace import scoped_cloud_app_id

        for ws in ["daniel"]:
            key = scoped_cloud_app_id("baseball", ws)
            row = load_current_state_for_app(key)
            metrics = (row or {}).get("metrics") or {}
            blob = metrics.get("full_session") if isinstance(metrics, dict) else {}
            inspect_blob(blob, f"cloud key={key}", draft_id)

        row = load_current_state_for_app("baseball")
        metrics = (row or {}).get("metrics") or {}
        blob = metrics.get("full_session") if isinstance(metrics, dict) else {}
        inspect_blob(blob, "cloud key=baseball", draft_id)
    except Exception as exc:
        print("cloud error:", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
