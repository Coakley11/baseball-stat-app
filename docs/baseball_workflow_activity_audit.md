# Baseball workflow activity audit

**Last updated:** 2026-06-06  
**Scope:** What Baseball logs to Command Center vs what is session-only. **Continue ranking unchanged** — this documents logging coverage only.

---

## Trend Value

| Workflow | Logged? | event_type | resume_key | Continue (when wired) | Notes |
|----------|---------|------------|------------|-------------------------|-------|
| Single-player dashboard chart | ✅ | `player_trend_viewed` | `trend:{player}` | Yes | Fires after chart render |
| Multi-player trend visualization (2+) | ✅ **new** | `trend_comparison_viewed` | `trendcompare:{A}:{B}` | Pending CC ranking | Was session-only (`record_workflow_comparison_group`) |
| Trend filter / lag change | ✅ | `trend_filter_changed` | — | **Excluded** | Activity feed only; not a named workflow |
| Breakout / decline lists | ✅ | `breakout_analysis` | `baseball:breakouts` | Yes | Fires on filter sig change |
| Trend insight row select (leaderboard) | ❌ | — | — | **Excluded** | UI selection only; no chart hook |

---

## Comparison Tool

| Workflow | Logged? | event_type | resume_key |
|----------|---------|------------|------------|
| Two players compared | ✅ | `player_comparison` | `compare:{A}:{B}` |

Note: `player_comparison` is **Comparison Tool** (stat sig tests), not Trends multi-chart.

---

## Other pages (currently logged)

| Workflow | event_type | resume_key |
|----------|------------|------------|
| Draft prep | `draft_prep` | `baseball:draft` |
| Trade analysis | `trade_analysis` | `baseball:trade` |
| Projection report | `projection_report` | `baseball:projections` |
| Sleeper research | `sleeper_research` | `baseball:sleepers` |
| Roster build | `roster_build` | `roster:{team}` or `baseball:roster` |

---

## Session-only (explicitly not logged)

| Workflow | Reason |
|----------|--------|
| Watchlist add/remove | Sidebar MRU; low signal; would spam Continue |
| Draft queue add/reorder | Same — use `draft_prep` / `roster_build` for meaningful completion |
| Player insight row pick (trend/market/draft/ML) | Selection widget only; no completed analysis |
| Feature-importance / ML insight drill-down | Not wired to activity hooks yet |
| Page navigation / filter debug keys | Developer `render_page_filters_debug` only |

---

## Developer diagnostics (Trend Value)

**Developer: Latest Trend Activity Event** shows:

- `event_type`, `resume_key`, `players`, `timestamp`, `recorded`, `supabase_write_ok`, `write_path`, `error`

---

## Deep link resume (Baseball)

| resume_key | Opens | Restores |
|------------|-------|----------|
| `trend:{player}` | Trend Value | Single-player dashboard |
| `trendcompare:{A}:{B}` | Trend Value | Multi-player trend chart (2 players) |
| `compare:{A}:{B}` | Comparison Tool | Comparison widgets |

---

## Next (after logging verified)

1. Wire `trend_comparison_viewed` into Command Center Continue (ranking only — not in this pass)
2. Optional: `watchlist_updated` / `draft_queue_updated` if product wants those as Continue cards
