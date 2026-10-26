# Baseball monetization M1 inventory

This is an archived candidate classification, not the current billing contract.
No page-level gate is enforced while Stripe/Supabase billing is in test
acceptance; the final Free-vs-Pro split will be approved separately.

| Surface | Initial tier | Reasoning |
| --- | --- | --- |
| Historical/player/stat search and analysis | Free | Primary discovery path and clearest way to understand product value. |
| Career totals and rankings/leaderboards | Free | Foundational baseball reference and analysis. |
| Standard charts and visualizations | Free | Essential to demonstrating the core analytics experience. |
| Comparison Tool | Free | A core analysis workflow; future expanded comparison depth may be limited. |
| Trend Value and Valuation | Free | Useful differentiated analytics without withholding the basic product. |
| ML Predictions | Pro | Compute-heavy, differentiated forecasting and tuning. Representative M1 gate. |
| Fantasy Sleepers & Busts | Free | Gives Free users a meaningful fantasy insight workflow. |
| Draft Room Simulator | Free | Core draft workflow and product demonstration. |
| Draft Assistant Simulator | Free | Standard recommendations, queue, boards, roster construction, and team needs remain useful. Advanced intelligence is reserved but not separately gated in M1. |
| Draft Lab / Simulation | Pro | Advanced scenario analysis. Representative M1 gate before page initialization. |
| Live Draft | Free | No M1 lifecycle gate; monetization must never interrupt an active draft. |
| Draft boards and queues | Free | Core workflow and supporting context for drafting. |
| Saved Draft Library | Free with limits | M1 applies no limit; later tiers may expand saved drafts/workspaces after usage and storage policy review. |
| Fantasy standings/team management | Free | Core league context and management. |
| Fantasy Lineup Assistant | Free | Useful standard roster recommendation workflow. |
| Waiver/add-drop workflows | Free | Core in-season fantasy workflow. Advanced automation may become Pro later. |
| Trade workflows | Undecided | The capability is contextual rather than a primary navigation page; audit completeness and usage before gating. |
| Recommendations and team needs | Free with limits | Existing recommendations stay Free. Richer optimization and advanced draft intelligence are a future Pro candidate. |
| Persistent leagues/workspaces | Free with limits | Current persistence stays available; expanded counts are reserved for future policy. |
| Exports/downloads | Free with limits | Existing exports stay available. Premium formatting or expanded export sets may become Pro. |
| Applied-math/assistant insights | Undecided | Cross-cutting assistant value and compute cost need a separate usage audit. |

Billing now supplies an authenticated, server-authoritative entitlement snapshot
from `public.subscriptions`; neither client session state nor the development
selector is a billing authority. See `BASEBALL_BILLING_SETUP.md`.

The Free/Pro development selector requires all three conditions: an eligible in-app Developer Mode session, `BASEBALL_ENTITLEMENT_DEV_CONTROLS=1`, and `BASEBALL_ENTITLEMENT_RUNTIME=local` (or `test`). Production ignores the session selection even if it is present.
