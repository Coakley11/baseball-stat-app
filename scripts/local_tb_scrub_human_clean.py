"""Clear stale Live Draft session so human testing starts clean."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scrub(ws: Path) -> list[str]:
    if not ws.is_file():
        return [f"missing:{ws}"]
    raw = json.loads(ws.read_text(encoding="utf-8"))
    state = raw.get("state") if isinstance(raw.get("state"), dict) else raw
    cleared: list[str] = []
    for k in list(state.keys()):
        kl = k.lower()
        if (
            "live_draft" in kl
            or "draft_room" in kl
            or k in ("active_shared_draft_room_code", "draft_room_shared_meta")
        ):
            if k == "page_filter_state":
                continue
            state.pop(k, None)
            cleared.append(k)
    pfs = state.get("page_filter_state")
    if isinstance(pfs, dict):
        ldr = pfs.get("Live Draft Room")
        if isinstance(ldr, dict):
            for rk in (
                "live_draft_room",
                "live_draft_state",
                "active_shared_draft_room_code",
                "draft_room_shared_meta",
            ):
                if rk in ldr:
                    ldr.pop(rk, None)
                    cleared.append(f"pfs.{rk}")
            ldr["live_draft_setup_mode"] = "solo"
    # Archive any active room JSON files so they are not auto-restored.
    rooms = ROOT / "data" / "draft_rooms"
    if rooms.is_dir():
        for p in rooms.glob("*.json"):
            if p.name.startswith("_archive_"):
                continue
            dest = rooms / f"_archive_human_clean_{p.stem}.json"
            try:
                p.replace(dest)
                cleared.append(f"archived:{p.name}")
            except OSError as exc:
                cleared.append(f"archive_fail:{p.name}:{exc}")
    ws.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return cleared


def main() -> None:
    for name in ("daniel", "guest"):
        cleared = scrub(ROOT / "data" / "workspaces" / name / "baseball_user_state.json")
        print(name, cleared)


if __name__ == "__main__":
    main()
