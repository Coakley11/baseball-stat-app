# Baseball workflow activity audit

**Last updated:** 2026-07-03  
Master suite audit: `daniel-ai-command-center/cursor-prompts/plans/suite-workflow-coverage-audit.md`

## Command Center card kinds

| Kind | Purpose | Click behavior | Examples |
|------|---------|----------------|----------|
| **Continue** (`cc_card_kind: continue`) | Active/resumable task with specific state | Deep link restores the referenced item even if the page was cleared | Live Draft pick, saved draft team, HOF case, comparison, historical run |
| **App Directory** (`cc_card_kind: app_entry`) | Long-term workstream entry | Opens the app’s last general page — does not force the card’s specific item | Baseball Analytics session, general draft prep |

Continue cards carry `resume_key`, `resume_title`, and `action_url`. App Directory cards update `suite_app_current_state` without a task-specific resume key.

| Workflow | Logged? | Continue card? | App Directory? | Priority | Restore? | Notes |
|----------|---------|----------------|----------------|----------|----------|-------|
| Single-player trend chart | ✅ | ✅ | Partial | 58 | ✅ `trend:{player}` | `player_trend_viewed` after dashboard chart |
| Multi-player trend comparison | ✅ | ✅ | Partial | 59 | ✅ `trendcompare:A:B` | `trend_comparison_viewed` after comparison chart |
| Player comparison (Comparison Tool) | ✅ | ✅ | Partial | 59 | ✅ `compare:A:B` | Not the Trends multi-chart |
| Trade analysis | ✅ | ✅ | Partial | 54 | ✅ `bb:trade` | Fantasy Lineup Assistant |
| Draft Room Simulator | ✅ | ✅ | Partial | 56 | ✅ `bb:simulator_draft` | `simulator_draft_session` on board picks |
| Draft Assistant | ✅ | ✅ | Partial | 56 | ✅ `bb:draft_assistant` | Recommendations updated (deduped per pick) |
| Saved Draft Library save/load | ✅ | ✅ | Partial | 55 | ✅ `bb:saved_draft:{id}` | Save + activate + standings load |
| Historical Explorer analysis | ✅ | ✅ | Partial | 57 | ✅ `historical:{stat}:{years}` | Table render (deduped on filter sig) |
| Fantasy Standings update | ✅ | ✅ | Partial | 54 | ✅ `bb:standings:{season}:{fmt}` | After standings calculated |
| Live Draft Room | ✅ | ✅ | Partial | 55 | ✅ `bb:live_draft:{room}` | Created, pick (with player name), complete |
| Hall of Fame case | ✅ | ✅ | Partial | 58 | ✅ `bb:hof_case:{slug}` | `hof_case_analysis_submitted` |
| Draft simulation prep / lab | ✅ | ✅ | Partial | 56 | ✅ `bb:draft_lab:{room}` | Draft Simulation Test Mode |
| Live draft / roster build | ✅ | Partial | Partial | ~35 | Partial | `roster_build` when lab completes |
| Draft queue edits | ❌ | ❌ | ❌ | — | Session | **Excluded:** sidebar queue MRU |
| Watchlist additions | ❌ | ❌ | ❌ | — | Session | **Excluded:** would spam Continue |
| Breakout / decline lists | ✅ | Weak | Partial | 35 | Partial | `breakout_analysis` on filter sig |
| Sleeper / bust research | ✅ | Partial | Partial | ~35 | Partial | `sleeper_research` |
| ML projection report | ✅ | Partial | Partial | ~48 | Partial | `projection_report` on ML run |
| Trend filter change only | ✅ | ❌ | ❌ | — | — | **Excluded:** `trend_filter_changed` (activity feed only) |
| Developer diagnostics panels | ❌ | ❌ | ❌ | — | — | **Excluded:** gated behind developer mode |
| Player insight row picks | ❌ | ❌ | ❌ | — | — | **Excluded:** selection widget only |
| Feature / ML insight drill-down | ❌ | ❌ | ❌ | — | — | **P1 backlog** |
| Valuation analysis | ❌ | ❌ | ❌ | — | Disk | **P1 backlog** |
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
| `bb:live_draft:{room}` | Live Draft Room | Draft room id |
| `bb:saved_draft:{id}` | Saved Draft Library | Activates saved draft archive |
| `bb:standings:{season}:{fmt}` | Fantasy Standings Tracker | Standings context |
| `historical:{stat}:{start}-{end}` | Historical Explorer | Sort stat + year range |
| `bb:draft_assistant` | Draft Assistant Simulator | Assistant board state |
| `bb:simulator_draft` | Draft Room Simulator | Mock draft board |
| `bb:hof_case:{slug}` | Career Totals (HOF mode) | Target player + AMI context |
