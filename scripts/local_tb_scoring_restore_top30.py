"""Offline Pick-1 normal-roster recommendation table using restored scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from draft_score_display import fmt_pick_score, fmt_player_grade, fmt_roster_fit_score
from live_draft_pick_scoring import apply_draft_pick_scoring

OUT = ROOT / "data" / "tb_probe" / "scoring_restore_top30.json"


def _find_player(scored: pd.DataFrame, needle: str) -> pd.Series | None:
    names = scored["fullName"].astype(str)
    exact = scored[names.str.lower() == needle.lower()]
    if not exact.empty:
        return exact.iloc[0]
    contains = scored[names.str.contains(needle, case=False, na=False, regex=False)]
    if not contains.empty:
        return contains.iloc[0]
    return None


def _row_dict(r: pd.Series) -> dict:
    adp = pd.to_numeric(r.get("ADP"), errors="coerce")
    if pd.isna(adp):
        adp = pd.to_numeric(r.get("ADP Rank"), errors="coerce")
    return {
        "rank": int(r["rec_rank"]),
        "player": str(r.get("fullName", "")),
        "pos": str(r.get("Primary Position", "")),
        "player_grade": fmt_player_grade(r.get("Expected Fantasy Value")),
        "decision_score": fmt_pick_score(r.get("Decision Score")),
        "roster_fit": fmt_roster_fit_score(r.get("Draft Fit Score")),
        "pos_scarcity": round(
            float(pd.to_numeric(r.get("Position Scarcity Score"), errors="coerce") or 0), 4
        ),
        "market_rank": float(pd.to_numeric(r.get("Market Rank"), errors="coerce") or 0),
        "adp": float(adp or 0),
        "fantasy_edge": float(pd.to_numeric(r.get("Fantasy Edge"), errors="coerce") or 0),
        "sleeper": float(pd.to_numeric(r.get("Sleeper Score"), errors="coerce") or 0),
        "efv_raw": float(pd.to_numeric(r.get("Expected Fantasy Value"), errors="coerce") or 0),
        "ds_raw": float(pd.to_numeric(r.get("Decision Score"), errors="coerce") or 0),
    }


def main() -> None:
    import streamlit_app as app

    pool = app.get_cached_unified_projection_pool_live()
    efv = pd.to_numeric(pool["Expected Fantasy Value"], errors="coerce")
    slots = {
        "C": 1,
        "1B": 1,
        "2B": 1,
        "3B": 1,
        "SS": 1,
        "OF": 3,
        "DH": 1,
        "P": 0,
        "BN": 5,
    }
    config = {
        "slots": slots,
        "num_teams": 10,
        "picks_per_team": 15,
        "draft_mode": "solo",
    }
    room = {"status": "in_progress", "config": config, "rosters": {}, "current_pick": 1}
    scored, _gaps = apply_draft_pick_scoring(
        pool.copy(),
        pd.DataFrame(),
        target_counts=slots,
        current_pick=1,
        recommendation_mode="decision",
        room=room,
    )
    scored = scored.sort_values("Decision Score", ascending=False).reset_index(drop=True)
    scored["rec_rank"] = scored.index + 1
    top30 = [_row_dict(scored.iloc[i]) for i in range(min(30, len(scored)))]
    named_keys = [
        ("Aaron Judge", "Aaron Judge"),
        ("Juan Soto", "Juan Soto"),
        ("Bobby Witt Jr.", "Bobby Witt"),
        ("Shohei Ohtani", "Shohei Ohtani"),
        ("Francisco Lindor", "Francisco Lindor"),
        ("Gunnar Henderson", "Gunnar Henderson"),
        ("Ben Williamson", "Ben Williamson"),
    ]
    named = {}
    for label, needle in named_keys:
        hit = _find_player(scored, needle)
        if hit is None and label != needle:
            hit = _find_player(scored, label)
        named[label] = _row_dict(hit) if hit is not None else None
    out = {
        "pool_rows": int(len(pool)),
        "efv_max": float(efv.max()),
        "efv_median": float(efv.median()),
        "efv_gt_1_5_frac": float((efv > 1.5).mean()),
        "top30": top30,
        "named": named,
        "top1": top30[0] if top30 else None,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"top5": top30[:5], "named": named}, indent=2))


if __name__ == "__main__":
    main()
