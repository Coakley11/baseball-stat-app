# Baseball workflow activity audit

**Last updated:** 2026-06-06  
Master suite audit: `daniel-ai-command-center/cursor-prompts/plans/suite-workflow-coverage-audit.md`

| Workflow | Logged? | Continue card? | App Directory? | Priority | Restore? | Notes |
|----------|---------|----------------|----------------|----------|----------|-------|
| Single-player trend chart | ✅ | ✅ | Partial | 58 | ✅ `trend:{player}` | `player_trend_viewed` after dashboard chart |
| Multi-player trend comparison | ✅ | ✅ | Partial | 59 | ✅ `trendcompare:A:B` | `trend_comparison_viewed` after comparison chart |
| Player comparison (Comparison Tool) | ✅ | ✅ | Partial | 59 | ✅ `compare:A:B` | Not the Trends multi-chart |
| Trade analysis | ✅ | ✅ | Partial | 54 | ✅ `bb:trade` | Fantasy Lineup Assistant |
| Draft simulation prep | ✅ | ✅ | Partial | 56 | ✅ `bb:draft` | Draft Simulation Test Mode |
| Live draft / roster build | ✅ | Partial | Partial | ~35 | Partial | `roster_build` when lab completes |
| Draft queue edits | ❌ | ❌ | ❌ | — | Session | **Excluded:** sidebar queue MRU |
| Watchlist additions | ❌ | ❌ | ❌ | — | Session | **Excluded:** would spam Continue |
| Breakout / decline lists | ✅ | Weak | Partial | 35 | Partial | `breakout_analysis` on filter sig |
| Sleeper / bust research | ✅ | Partial | Partial | ~35 | Partial | `sleeper_research` |
| ML projection report | ✅ | Partial | Partial | ~48 | Partial | `projection_report` on ML run |
| Trend filter change only | ✅ | ❌ | ❌ | — | — | **Excluded:** `trend_filter_changed` |
| Player insight row picks | ❌ | ❌ | ❌ | — | — | **Excluded:** selection widget only |
| Feature / ML insight drill-down | ❌ | ❌ | ❌ | — | — | **P1 backlog** |
| Valuation analysis | ❌ | ❌ | ❌ | — | Disk | **P1 backlog** |
| Live Draft Room picks | ❌ | ❌ | ❌ | — | Disk | **P1 backlog** |
| Custom rankings | ❌ | ❌ | ❌ | — | — | No dedicated page |
| Team builder | ❌ | ❌ | ❌ | — | — | Draft room covers roster building |

## Developer diagnostics (Trend Value)

**Developer: Latest Trend Activity Event** — `event_type`, `resume_key`, `players`, `recorded`, `supabase_write_ok`, `write_path`, `error`

## Deep link resume

| resume_key | Opens | Restores |
|------------|-------|----------|
| `trend:{player}` | Trend Value | Single-player dashboard |
| `trendcompare:{A}:{B}` | Trend Value | Multi-player trend chart |
| `compare:{A}:{B}` | Comparison Tool | Comparison widgets |
