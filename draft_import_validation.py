"""Validate imported draft boards against the unified player pool."""

from __future__ import annotations

import re
from typing import Any, Callable

import pandas as pd

from draft_player_names import (
    build_draft_player_name_index,
    classify_draft_player_import_name,
    draft_pool_display_names,
)


def validate_imported_draft_df(
    import_df: pd.DataFrame,
    pool_df: pd.DataFrame,
) -> dict[str, Any]:
    """Classify every imported player row for review before board save."""
    index = build_draft_player_name_index(pool_df)
    names = draft_pool_display_names(pool_df)
    rows: list[dict[str, Any]] = []
    counts = {"exact": 0, "corrected": 0, "ambiguous": 0, "unresolved": 0, "empty": 0}

    for idx, row in import_df.iterrows():
        raw_player = str(row.get("Player") or "").strip()
        info = classify_draft_player_import_name(raw_player, index, all_names=names)
        status = str(info.get("status") or "unresolved")
        counts[status] = counts.get(status, 0) + 1
        resolved = info.get("canonical") if status in ("exact", "corrected") else None
        rows.append(
            {
                "row_index": int(idx),
                "round": row.get("Round"),
                "pick": row.get("Pick"),
                "team": str(row.get("Team") or "").strip(),
                "input": raw_player,
                "status": status,
                "canonical": info.get("canonical"),
                "candidates": list(info.get("candidates") or []),
                "resolved_canonical": resolved,
                "skip": False,
            }
        )

    return {
        "rows": rows,
        "summary": counts,
        "import_df": import_df.copy(),
        "pool_size": len(names),
    }


def import_review_ready(review: dict[str, Any]) -> bool:
    """True when every non-empty import row has a resolution or explicit skip."""
    for row in review.get("rows") or []:
        if row.get("status") == "empty":
            continue
        if row.get("skip"):
            continue
        if str(row.get("resolved_canonical") or "").strip():
            continue
        return False
    return True


def build_validated_import_dataframe(review: dict[str, Any]) -> pd.DataFrame:
    """Apply resolutions — unresolved/skipped rows get blank Player cells."""
    base = review.get("import_df")
    if not isinstance(base, pd.DataFrame):
        return pd.DataFrame(columns=["Round", "Pick", "Team", "Player"])
    out = base.copy()
    for row in review.get("rows") or []:
        i = int(row.get("row_index", -1))
        if i < 0 or i >= len(out):
            continue
        if row.get("skip") or row.get("status") == "unresolved" and not row.get("resolved_canonical"):
            out.at[i, "Player"] = ""
            continue
        canonical = str(row.get("resolved_canonical") or row.get("canonical") or "").strip()
        out.at[i, "Player"] = canonical
    out["Player"] = out["Player"].fillna("").astype(str).str.strip()
    return out


def summarize_import_validation(review: dict[str, Any]) -> dict[str, int]:
    """Human-facing summary counts after user resolutions."""
    accepted = auto_corrected = needs_review = unresolved = skipped = 0
    for row in review.get("rows") or []:
        if row.get("status") == "empty":
            continue
        if row.get("skip"):
            skipped += 1
            continue
        canonical = str(row.get("resolved_canonical") or "").strip()
        if not canonical:
            unresolved += 1
            continue
        if row.get("status") in ("ambiguous", "unresolved"):
            needs_review += 1
        if row.get("status") == "corrected" or (
            row.get("status") in ("ambiguous", "unresolved")
            and canonical != str(row.get("input") or "").strip()
        ):
            auto_corrected += 1
        if row.get("status") == "exact" or (
            canonical and canonical == str(row.get("input") or "").strip()
        ):
            accepted += 1
        elif row.get("status") in ("exact", "corrected"):
            accepted += 1
    return {
        "accepted": accepted,
        "auto_corrected": auto_corrected,
        "needs_review": needs_review,
        "unresolved": unresolved,
        "skipped": skipped,
    }


def render_draft_import_validation_ui(
    st: Any,
    *,
    review: dict[str, Any],
    pool_df: pd.DataFrame,
    session_key: str = "_draft_import_review",
    apply_label: str = "Apply validated import to draft board",
    on_apply: Callable[[pd.DataFrame], None] | None = None,
) -> bool:
    """Show validation summary and row-level fixes. Returns True if import applied."""
    if not review or not review.get("rows"):
        return False

    pool_names = draft_pool_display_names(pool_df)
    summary = review.get("summary") or {}
    st.markdown("**Import validation summary**")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Exact matches", int(summary.get("exact") or 0))
    m2.metric("Auto-corrected", int(summary.get("corrected") or 0))
    m3.metric("Needs review", int(summary.get("ambiguous") or 0))
    m4.metric("Unresolved", int(summary.get("unresolved") or 0))

    needs_ui = [r for r in review["rows"] if r.get("status") in ("ambiguous", "unresolved")]
    if needs_ui:
        st.caption("Choose the correct pool name for ambiguous or unresolved rows, or skip a pick.")
        for row in needs_ui:
            pick_label = row.get("pick")
            team = row.get("team") or "—"
            raw = row.get("input") or "—"
            key_base = f"draft_import_row_{row.get('row_index')}"
            candidates = list(dict.fromkeys(row.get("candidates") or []))
            if row.get("status") == "unresolved":
                search_q = st.text_input(
                    f"Search pool for pick **{pick_label}** (`{raw}`)",
                    key=f"{session_key}_{key_base}_search",
                    placeholder="Type last name, e.g. Lindor or Judge",
                )
                if search_q:
                    from draft_player_names import search_draft_pool_names

                    candidates = search_draft_pool_names(search_q, pool_names, limit=15)
            options = ["— Select player —"] + candidates
            choice = st.selectbox(
                f"Pick **{pick_label}** · {team} · imported `{raw}`",
                options,
                key=f"{session_key}_{key_base}_choice",
            )
            skip = st.checkbox(
                "Skip this pick (leave blank on board)",
                key=f"{session_key}_{key_base}_skip",
            )
            if skip:
                row["skip"] = True
                row["resolved_canonical"] = None
            elif choice and choice != "— Select player —":
                row["skip"] = False
                row["resolved_canonical"] = choice

    ready = import_review_ready(review)
    applied = False
    if st.button(apply_label, disabled=not ready, key=f"{session_key}_apply"):
        validated = build_validated_import_dataframe(review)
        invalid_left = validated[
            validated["Player"].astype(str).str.strip().ne("")
        ].copy()
        # Final guard: every non-empty player must be in pool
        index = build_draft_player_name_index(pool_df)
        pool_set = set(index.values())
        bad = [
            p
            for p in invalid_left["Player"].astype(str).tolist()
            if str(p).strip() and str(p).strip() not in pool_set
        ]
        if bad:
            st.error(f"Cannot apply — non-pool names remain: {', '.join(bad[:5])}")
        else:
            if on_apply:
                on_apply(validated)
            applied = True
            st.session_state.pop(session_key, None)

    if not ready:
        st.info("Resolve or skip every ambiguous/unresolved player before applying the import.")
    return applied
