# AMI A2: the selected Draft Strategy inside AMI's research answers (read-only)

Branch `feature/ami-a2-research-bridge`, from Dev `fbcccb9` (which already contains A1). Not deployed.

## What it does

| Question / page | What AMI adds |
|---|---|
| Any player research answer (Compare Players, Trend Value, Valuation, Historical Explorer, Career Totals, player profiles) | One line: where those players sit in the selected strategy — "In your **Sluggers** strategy: Aaron Judge #1 (pinned, your note saved); Juan Soto #2." A player not in it is reported as not in it. |
| "Compare my top two shortstops" (optionally "… in my Speed strategy") | The players are taken from the strategy by the user's own ranking ("From your **Sluggers** strategy, your top two shortstops: Corey Seager (#3), Mookie Betts (#4)."), then the existing stat tools answer the comparison. Too few at the position is said plainly. |
| "How deep is shortstop in my strategy?" | The strategy's players at that position, plus the draft page's positional depth table (available, best available, drop-off) when a draft board exists. Without a board AMI says it needs one. |
| Panel context line on research pages | Names the selected strategy, from this session's editor state only (no storage call). |

"Selected strategy" = the one open in Draft Strategy · PRO in this session, or the only saved one. With several saved
strategies and none selected, research answers add nothing (they never ask "which strategy?").

## Safety (unchanged from A1)

- Two new **read-only** registry tools, `strategy_membership` and `strategy_top_at_position`, declared with
  `plan_capability="draft_strategy_library"` (the Draft Strategy page's capability). The registry still refuses any
  tool that writes. They reuse A1's account-scoped reads (`_live`: the store's own access check first).
- Signed-out visitors and (when enforcement is on) non-Pro users: research answers are unchanged and carry no
  strategy line; strategy questions get the same "Sign in" / "part of Pro" answer as A1. No storage read happens
  before the access check.
- Membership needs an **exact full-name match**: "Geovany Soto" never counts as "Juan Soto".
- Saved data is used; unsaved editor changes are labelled. Deleted strategies are never opened.
- Positional depth only takes questions that name the strategy, so "Do I have enough catchers?" keeps its draft
  team-needs route.
- Nothing is enforced today and no billing setting changes.

## Files

- `ami_assistant/tools/strategy_research.py` — the two tools, position words and matching.
- `ami_assistant/strategy_research.py` — question resolution ("my top N <position>", depth) and the membership line.
- `ami_assistant/engine.py` — pre-routing resolution and the post-answer membership line (registry calls only).
- `ami_assistant/context.py` — research pages name the selected strategy.

## Tests

`tests/test_ami_a2_research_bridge.py` (26): membership on compare/trend/valuation/historical answers; not-in-strategy;
no selection; only-one counts as selected; unsaved labelled; deleted never read; leaderboards unchanged; no writes
and session unchanged apart from AMI memory; signed-out (no line, no read); enforced gate (free vs Pro); two-account
isolation; top-N resolution (named strategy, multi-position entries, too few, single player → profile); depth with
and without a board; depth routing guard. `tests/test_ami_assistant_safety.py` lists the two new gated tools.

## Next (A3)

Confirmed findings and preferences: AMI offers to save a finding, note or preference with the exact text; only the
user's **Save** writes (revision-checked, `ami_confirmed`).
