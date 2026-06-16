"""Prove which save reasons are blocked by _cloud_autosave_blocked_reason.

The post-restore cooldown is bypassed by `bypass_block`, but a SECOND gate
(_cloud_autosave_blocked_reason) blocks the cloud write when the reason is not
in _FORCE_SAVE_CLOUD_REASONS and workspace sync was skipped. This is the gate
that lets historical/career chart saves through (historical_edit/career_edit)
while silently dropping draft-settings and format saves.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suite_user_persistence import _cloud_autosave_blocked_reason

REASONS = [
    "historical_edit",            # charts (works)
    "career_edit",                # charts (works)
    "draft_room_settings_changed",
    "live_draft_setting_changed",
    "draft_sim_settings_changed",
    "draft_assistant_settings_changed",
    "global_settings_changed",
]


def check(reason: str, sync_skipped: bool) -> str:
    st = MagicMock()
    st.session_state = {}
    if sync_skipped:
        st.session_state["_suite_workspace_sync_skipped_no_apply"] = True
    # Empty draft board / no comparison players (the no-picks settings scenario).
    state: dict = {"active_page": "Draft Room Simulator"}
    blocked = _cloud_autosave_blocked_reason(st, "baseball", state, save_reason=reason)
    return blocked or "ALLOWED"


def main() -> None:
    print(f"{'reason':<36} {'sync_ok':<14} {'sync_skipped':<14}")
    print("-" * 64)
    for reason in REASONS:
        ok = check(reason, sync_skipped=False)
        skipped = check(reason, sync_skipped=True)
        print(f"{reason:<36} {ok:<14} {skipped:<14}")


if __name__ == "__main__":
    main()
