"""Boot the REAL streamlit_app.py on an active Live Draft (Solo or Shared) and read the page order.

Offline and isolated:
- shared rooms live in a temporary local-file store, never Supabase;
- ``SUITE_STORAGE_ISOLATED=1`` keeps suite storage on this checkout, never a sibling repo;
- the pick clock is an hour, so nothing expires during the ~2 minute boot.

``landmarks(at)`` returns the drafting-screen sections in render order (first occurrence), using
the phone-layout hook keys, the section markup classes and the section headings.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ["Team A", "Team B", "Team C", "Team D"]
PICKS_PER_TEAM = 8
HOST_ID = "user:paritytesthost"
GUEST_ID = "user:paritytestguest"

# (landmark, needle) — needle is matched in an element's protobuf text with quotes unescaped.
# Class needles include ``class="`` so CSS rules in <style> blocks (which name every class) never
# match; headings match the exact heading body; Control Center by its Pause button key.
_MARKERS: tuple[tuple[str, str], ...] = (
    ("clock", 'class="live-draft-on-clock'),
    ("team_needs", 'class="ld-team-needs-panel'),
    ("rec_cards", 'class="ld-rec-card-header'),
    ("manual_pick", 'body: "Manual Draft"'),
    ("queue", 'body: "Draft Queue"'),
    ("board", 'body: "Draft Board"'),
    ("control_center", '-live_draft_pause"'),
    ("chat", 'class="ld-aim-root'),
    ("room_code", 'class="ld-room-code-panel'),
    ("status_summary", 'body: "#### Draft Status Summary"'),
    ("rosters", 'body: "Team Rosters"'),
)


def isolate_environment() -> Path:
    """Process-wide isolation for an in-process AppTest. Returns the temporary room-store root."""
    import sys

    # The app prints diagnostics with emoji. On a Windows console code page those prints raise
    # mid-script and the page stops after the clock; the hosted (Linux) app is UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    os.environ["SUITE_STORAGE_ISOLATED"] = "1"
    os.environ["BASEBALL_SHARED_DRAFT_ROOM_BACKEND"] = "local"
    # A throwaway workspace per process: the default workspace keeps saved page state between
    # runs, and restoring it replaced the seeded draft with Draft Setup on a fresh process.
    if not os.environ.get("SUITE_WORKSPACE_ID", "").startswith("ldrparity"):
        import atexit
        import shutil
        import time

        workspace_id = f"ldrparity{os.getpid()}t{int(time.time())}"
        os.environ["SUITE_WORKSPACE_ID"] = workspace_id
        from suite_workspace import workspace_dir

        atexit.register(shutil.rmtree, str(workspace_dir(workspace_id)), ignore_errors=True)
    import draft_room_shared_state as shared_state

    root = Path(tempfile.mkdtemp(prefix="ldr_parity_rooms_"))
    store = shared_state.LocalFileSharedRoomStore(root=root)
    shared_state._DEFAULT_STORE = store
    shared_state._LOCAL_STORE = store
    return root


def active_room(mode: str) -> dict[str, Any]:
    from live_draft_timer_logic import live_draft_reset_timer

    order, n = [], 1
    for rnd in range(1, PICKS_PER_TEAM + 1):
        for team in TEAMS if rnd % 2 else list(reversed(TEAMS)):
            order.append({"Pick": n, "Round": rnd, "Team": team})
            n += 1
    pool = pd.DataFrame(
        [
            {
                "playerID": f"p{i:03d}",
                "fullName": f"Player {i:03d}",
                "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF", "DH", "UTIL"][i % 8],
                "Expected Fantasy Value": float(400 - i),
                "Decision Score": float(100 - (i % 40)),
            }
            for i in range(1, 120)
        ]
    )
    room = {
        "draft_room_id": f"PARITY-{mode.upper()}",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": list(TEAMS),
        "pick_order": order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in TEAMS},
        "config": {
            "num_teams": len(TEAMS),
            "picks_per_team": PICKS_PER_TEAM,
            "rounds": PICKS_PER_TEAM,
            "timer_seconds": 3600,
            "teams": list(TEAMS),
            "your_team": "Team A",
            "user_team": "Team A",
            "league_name": "Parity League",
            "draft_setup_mode": mode,
            "auto_pick_rule": "balanced recommendation",
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 0, "P": 0, "BN": 0},
        },
        "pool": pool,
    }
    live_draft_reset_timer(room)
    return room


def _base_seed(user_id: str, mode: str) -> dict[str, Any]:
    return {
        "_suite_auth_user_id": user_id,
        "draft_room_participant_id": user_id,
        "auth_user_id": user_id,
        "main_sidebar_page": "Live Draft Room",
        "active_page": "Live Draft Room",
        "live_draft_setup_mode": mode,
    }


def solo_seed() -> dict[str, Any]:
    seed = _base_seed(HOST_ID, "solo")
    seed["live_draft_room"] = active_room("solo")
    return seed


def shared_seeds() -> tuple[str, dict[str, Any], dict[str, Any]]:
    """(room code, commissioner seed, guest seed) for one active shared room."""
    from draft_room_context import create_and_host_shared_room, join_shared_draft_room

    host = _base_seed(HOST_ID, "shared")
    code, _doc = create_and_host_shared_room(host, active_room("shared"), host_team="Team A")
    guest = _base_seed(GUEST_ID, "shared")
    ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B")
    if not ok:
        raise RuntimeError(f"guest join failed: {msg}")
    return code, host, guest


def run_page(seed: dict[str, Any], *, timeout: int = 900):
    from streamlit.testing.v1 import AppTest

    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=timeout)
        for key, value in seed.items():
            at.session_state[key] = value
        at.run()
        return at
    finally:
        os.chdir(cwd)


def _walk(node: Any):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for child in children.values():
            yield from _walk(child)


def landmarks(at: Any) -> list[str]:
    """Drafting-screen sections in render order, each listed once (first occurrence)."""
    seen: list[str] = []
    for node in _walk(at.main):
        if type(node).__name__ in ("Block", "SpecialBlock", "ElementTree"):
            continue
        text = str(getattr(node, "proto", "") or "").replace('\\"', '"')
        # Solo's clock is the keyed solo_live_clock component (skip its hidden pre-warm mount);
        # Shared's is a components.html iframe carrying the live-draft-on-clock markup.
        if "-solo_live_clock_" in text and "solo_live_clock_prewarm_" not in text and "clock" not in seen:
            seen.append("clock")
        for name, needle in _MARKERS:
            if needle in text and name not in seen:
                seen.append(name)
    return seen


def count(at: Any, needle: str) -> int:
    """How many rendered elements contain ``needle`` (protobuf text, quotes unescaped)."""
    total = 0
    for node in _walk(at.main):
        if type(node).__name__ in ("Block", "SpecialBlock", "ElementTree"):
            continue
        if needle in str(getattr(node, "proto", "") or "").replace('\\"', '"'):
            total += 1
    return total


def expander_texts(at: Any, label: str) -> list[str]:
    """Protobuf text of every element inside the expander(s) labelled ``label``."""
    out: list[str] = []
    for exp in at.expander:
        if exp.label == label:
            for node in _walk(exp):
                if type(node).__name__ not in ("Block", "SpecialBlock", "ElementTree", "Expander"):
                    out.append(str(getattr(node, "proto", "") or "").replace('\\"', '"'))
    return out


def hook_keys(at: Any) -> list[str]:
    """Phone-layout hook containers (``ldr-m-*``) in render order."""
    keys: list[str] = []
    for node in _walk(at.main):
        if type(node).__name__ != "Block":
            continue
        block_id = str(getattr(getattr(node, "proto", None), "id", "") or "")
        if "-ldr-m-" in block_id:
            key = "ldr-m-" + block_id.split("-ldr-m-", 1)[1]
            if key not in keys:
                keys.append(key)
    return keys
