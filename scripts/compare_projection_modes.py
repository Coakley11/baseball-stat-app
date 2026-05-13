"""
Offline comparison of draft projection styles (no Streamlit).

Splices selected helpers from streamlit_app.py so behavior matches the app.
Run from repo root: python scripts/compare_projection_modes.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
SA = BASE / "streamlit_app.py"

# Import projection factors from the real module (no Streamlit).
sys.path.insert(0, str(BASE))
from projection_style import PROJECTION_STYLE_OPTIONS, get_draft_projection_factors  # noqa: E402


def _snip(start: int, end: int) -> str:
    lines = SA.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start - 1 : end])


def _load_helpers_and_build() -> dict:
    g: dict = {"np": np, "pd": pd, "Path": Path}

    def read_required_csv(filename: str) -> pd.DataFrame:
        p = BASE / filename
        if not p.exists():
            raise FileNotFoundError(p)
        return pd.read_csv(p, low_memory=False)

    g["read_required_csv"] = read_required_csv
    g["get_draft_projection_factors"] = get_draft_projection_factors

    blocks = [
        _snip(47, 91),
        _snip(95, 142),
        _snip(144, 210),
        _snip(715, 745),
        _snip(2149, 2166),
        _snip(2168, 2218),
        _snip(281, 296),
        "def load_data():\n" + _snip(2728, 2825),
        _snip(2829, 3057),
    ]
    src = "\n\n".join(blocks)
    exec(compile(src, str(SA), "exec"), g, g)
    return g


def _resolve_name(df: pd.DataFrame, want: str) -> str | None:
    want_n = want.strip().lower()
    names = df["fullName"].astype(str)
    for n in names.unique():
        if str(n).strip().lower() == want_n:
            return str(n)
    # accents / Jr.
    for n in names.unique():
        base = re.sub(r"\s+", " ", str(n).lower().replace(".", ""))
        if base == re.sub(r"\s+", " ", want_n.replace(".", "")):
            return str(n)
    return None


def main() -> None:
    g = _load_helpers_and_build()
    load_data = g["load_data"]
    build_realistic_draft_ml_adjustments = g["build_realistic_draft_ml_adjustments"]
    add_latest_and_projection_columns = g["add_latest_and_projection_columns"]
    add_rate_stats = g["add_rate_stats"]
    compute_trend_slope = g["compute_trend_slope"]
    baseball_age_for_season = g["baseball_age_for_season"]

    _batting_df, yearly_df, _people = load_data()
    max_year = int(yearly_df["yearID"].max())
    room_window = 3
    room_years = list(range(max_year - room_window + 1, max_year + 1))
    recent = yearly_df[yearly_df["yearID"].isin(room_years)].copy().sort_values(["playerID", "yearID"])

    agg = recent.groupby(["playerID", "fullName", "bats"], as_index=False)[
        ["G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]
    ].sum()
    agg = add_rate_stats(agg)
    agg = agg[(agg["G"] >= 30) & (agg["AB"] >= 75)].copy()

    trends = recent.groupby("playerID").apply(
        lambda grp: pd.Series(
            {
                "R_trend": compute_trend_slope(grp, "R"),
                "HR_trend": compute_trend_slope(grp, "HR"),
                "RBI_trend": compute_trend_slope(grp, "RBI"),
                "SB_trend": compute_trend_slope(grp, "SB"),
                "BA_trend": compute_trend_slope(grp, "BA"),
                "OPS_trend": compute_trend_slope(grp, "OPS"),
                "BB_trend": compute_trend_slope(grp, "BB"),
            }
        ),
        include_groups=False,
    ).reset_index()

    room_df = agg.merge(trends, on="playerID", how="left")
    room_df = add_latest_and_projection_columns(room_df, recent)

    latest_cols = [
        "playerID",
        "primaryHistoricalTeamName",
        "primaryTeamName",
        "primaryLeague",
        "careerPrimaryPos",
        "primaryPos",
        "yearID",
        "birthYear",
        "birthMonth",
        "birthDay",
    ]
    avail = [c for c in latest_cols if c in recent.columns]
    latest_ctx = recent.sort_values(["playerID", "yearID"]).groupby("playerID").tail(1)[avail].copy()
    latest_ctx["Age"] = latest_ctx.apply(
        lambda r: baseball_age_for_season(
            r.get("yearID"), r.get("birthYear"), r.get("birthMonth", np.nan), r.get("birthDay", np.nan)
        ),
        axis=1,
    )
    room_df = room_df.merge(latest_ctx, on="playerID", how="left", suffixes=("", "_ctx"))
    room_df["Primary Position"] = (
        room_df.get("careerPrimaryPos", room_df.get("primaryPos", "DH"))
        .fillna(room_df.get("primaryPos", "DH"))
        .fillna("DH")
    )
    room_df["Primary Position"] = room_df["Primary Position"].replace({"": "DH", "PH": "DH", "PR": "DH"}).fillna("DH")

    # Targets: str resolves by fullName match, or (display_label, "pid:playerID" | lookup_name)
    targets: list = [
        "Juan Soto",
        "Aaron Judge",
        ("Bobby Witt Jr.", "pid:wittbo02"),
        ("Julio Rodríguez", "Julio Rodriguez"),
        "Corbin Carroll",
        "Gunnar Henderson",
        "Shohei Ohtani",
    ]

    want_players: list[tuple[str, str]] = []
    seen_fn: set[str] = set()
    for t in targets:
        if isinstance(t, tuple):
            label, ref = t[0], t[1]
            if ref.startswith("pid:"):
                pid = ref[4:]
                sub = room_df[room_df["playerID"] == pid]
                if sub.empty:
                    continue
                fn = str(sub.iloc[0]["fullName"])
            else:
                r = _resolve_name(room_df, ref)
                if not r:
                    continue
                fn = r
        else:
            label = t
            r = _resolve_name(room_df, label)
            if not r:
                continue
            fn = r
        if fn in seen_fn:
            continue
        seen_fn.add(fn)
        want_players.append((label, fn))

    modes = list(PROJECTION_STYLE_OPTIONS)
    rows_out: list[dict] = []

    for mode in modes:
        out = build_realistic_draft_ml_adjustments(room_df.copy(), "5x5 Roto", projection_mode=mode)
        out["Model Rank"] = out["Expected Fantasy Value"].rank(ascending=False, method="min")
        for display, fullname in want_players:
            sub = out[out["fullName"] == fullname]
            if sub.empty:
                continue
            r = sub.iloc[0]
            rows_out.append(
                {
                    "Player": display,
                    "Mode": mode,
                    "EFV": float(r["Expected Fantasy Value"]),
                    "ML_Adj": float(r["ML Adjustment"]),
                    "proj_HR": float(r["proj_HR"]),
                    "proj_SB": float(r["proj_SB"]),
                    "proj_OPS": float(r["proj_OPS"]),
                    "proj_BA": float(r["proj_BA"]),
                    "Rank": int(r["Model Rank"]),
                }
            )

    if not rows_out:
        print("No target players found in yearly pool (check Batting.csv coverage).")
        print("Resolved sample names:", room_df["fullName"].dropna().head(20).tolist())
        return

    wide = {}
    for row in rows_out:
        key = row["Player"]
        wide.setdefault(key, {})[row["Mode"]] = row

    print(f"Window: last {room_window} seasons ending {max_year}, 5x5 Roto, pool N={len(room_df)}")
    print()
    for p in sorted(wide.keys()):
        print("===", p, "===")
        for mode in modes:
            r = wide[p].get(mode)
            if not r:
                print(f"  {mode}: (missing)")
                continue
            print(
                f"  {mode:22s} EFV={r['EFV']:.4f}  MLAdj={r['ML_Adj']:+.4f}  "
                f"HR={r['proj_HR']:.1f} SB={r['proj_SB']:.1f} OPS={r['proj_OPS']:.3f} BA={r['proj_BA']:.3f}  Rank={r['Rank']}"
            )
        b = wide[p].get("Balanced")
        if b:
            for mode in modes:
                if mode == "Balanced":
                    continue
                r = wide[p].get(mode)
                if r:
                    print(f"    Rank delta vs Balanced ({mode}): {r['Rank'] - b['Rank']:+d}")
        print()


if __name__ == "__main__":
    main()
