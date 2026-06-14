"""Validate imported draft boards against the unified player pool."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from draft_player_names import (
    build_draft_player_name_index,
    classify_draft_player_import_name,
    draft_pool_display_names,
)

_REVIEW_STATUSES = frozenset({"close", "ambiguous", "invalid"})


def validate_imported_draft_df(
    import_df: pd.DataFrame,
    pool_df: pd.DataFrame,
) -> dict[str, Any]:
    """Classify every imported player row for review before board save."""
    index = build_draft_player_name_index(pool_df)
    names = draft_pool_display_names(pool_df)
    rows: list[dict[str, Any]] = []
    counts = {"exact": 0, "close": 0, "ambiguous": 0, "invalid": 0, "empty": 0}

    for idx, row in import_df.iterrows():
        raw_player = str(row.get("Player") or "").strip()
        info = classify_draft_player_import_name(raw_player, index, all_names=names)
        status = str(info.get("status") or "invalid")
        counts[status] = counts.get(status, 0) + 1
        resolved = info.get("canonical") if status == "exact" else None
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
        if row.get("status") == "exact":
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
        if row.get("skip"):
            out.at[i, "Player"] = ""
            continue
        canonical = str(row.get("resolved_canonical") or row.get("canonical") or "").strip()
        if not canonical:
            out.at[i, "Player"] = ""
            continue
        out.at[i, "Player"] = canonical
    out["Player"] = out["Player"].fillna("").astype(str).str.strip()
    return out


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
    m1.metric("Accepted players", int(summary.get("exact") or 0))
    m2.metric("Close matches", int(summary.get("close") or 0))
    m3.metric("Ambiguous matches", int(summary.get("ambiguous") or 0))
    m4.metric("Not in pool", int(summary.get("invalid") or 0))

    if int(summary.get("exact") or 0):
        accepted = [
            f"**{r.get('input')}** → {r.get('resolved_canonical') or r.get('canonical')}"
            for r in review["rows"]
            if r.get("status") == "exact"
        ]
        if accepted:
            with st.expander("Accepted players (exact match)", expanded=False):
                for line in accepted[:20]:
                    st.markdown(f"- {line}")

    needs_ui = [r for r in review["rows"] if r.get("status") in _REVIEW_STATUSES]
    if needs_ui:
        st.caption("Confirm close matches, choose among ambiguous names, or replace players not in the pool.")
        for row in needs_ui:
            pick_label = row.get("pick")
            team = row.get("team") or "—"
            raw = row.get("input") or "—"
            key_base = f"draft_import_row_{row.get('row_index')}"
            status = row.get("status")
            candidates = list(dict.fromkeys(row.get("candidates") or []))

            if status == "close":
                st.markdown(f"**Pick {pick_label}** · {team} · close match for `{raw}` — choose the correct player:")
            elif status == "ambiguous":
                st.markdown(f"**Pick {pick_label}** · {team} · `{raw}` matches several players — choose one:")
            else:
                st.warning(
                    f"**Pick {pick_label}** · {team} · `{raw}` is not in the current player pool. "
                    "Select a replacement player or leave unresolved."
                )
                search_q = st.text_input(
                    "Search pool for replacement",
                    key=f"{session_key}_{key_base}_search",
                    placeholder="Type player name",
                )
                if search_q:
                    from draft_player_names import search_draft_pool_names

                    candidates = search_draft_pool_names(search_q, pool_names, limit=15)

            options = ["— Select player —"] + candidates
            choice = st.selectbox(
                f"Official player name (pick {pick_label})",
                options,
                key=f"{session_key}_{key_base}_choice",
                label_visibility="collapsed",
            )
            skip = st.checkbox(
                "Leave unresolved (blank on board)",
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
        index = build_draft_player_name_index(pool_df)
        pool_set = set(index.values())
        bad = [
            p
            for p in validated["Player"].astype(str).tolist()
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
        st.info("Confirm every close/ambiguous match and resolve or skip every player not in the pool.")
    return applied
