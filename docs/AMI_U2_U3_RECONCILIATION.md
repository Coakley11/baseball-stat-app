# AMI ↔ U2/U3 reconciliation (first slice)

Branch `feature/ami-foundation`, starting at `4705b51`. It reconciles with the accepted
`ui/u2-u3-simplification @ 4bc3d30`. AMI stays **read-only**: no tool saves, drafts, trades,
adds/drops, finalizes or acts as commissioner.

## 1. Merge

`c0e8cf5` is a normal `--no-ff` merge of `4bc3d30`. History was not rewritten.

There was one conflict, in `streamlit_app.py`. AMI keeps `PAGE_GUIDES` in `page_guides.py`, while
U2/U3 edited the old inline dict.

- **Resolution:** keep AMI's `from page_guides import PAGE_GUIDES` and carry U2/U3's guide text
  into `page_guides.py`. The inline dict was not restored.
- **Proof the text matches:** `page_guides.PAGE_GUIDES` equals U2/U3's inline dict exactly
  (`ast.literal_eval` comparison).
- **Proof nothing was lost:** the merged `streamlit_app.py` differs from `4bc3d30` only by AMI's
  own pre-existing changes. Its added lines equal AMI's diff on top of U1. Its only extra removals
  are U2/U3's guide-dict lines, which now live in `page_guides.py`.

## 2. Labels and page names

- **Labels come from one place.** AMI shows the labels from `nav_groups.NAV_LABELS` via
  `context.display_label`: Compare Players, Sleepers & Busts, Lineup & Trades, League Standings,
  Waiver Wire. Page keys remain authoritative.
- **Renames are understood automatically.** `find_page` matches a page's key and its *current
  label*, so a future rename is understood without an alias. Old names stay as aliases:
  "Comparison Tool", "Fantasy Sleepers & Busts", "Lineup Assistant", "Trade Center",
  "Fantasy Standings Tracker", "Live Fantasy Standings". "Where is the Comparison Tool?" routes to
  Compare Players.
- **Prose can't drift.** AMI's prose names pages as `[[<page key>]]`, rendered by
  `context.render_page_names`. The test `test_help_prose_names_pages_by_their_current_labels`
  checks every help output (page help, how-tos, glossary, draft tools) and fails if any spells an
  old label. It also checks that every `[[…]]` reference names a real page.
- **Out of scope for that test:** the Quick Guide copy (`page_guides`) is the app's own text and
  is quoted as is.

## 3. Home and the draft tools

- **Home buttons.** Home's buttons come from `home_page.TASKS` (minus the draft card),
  `draft_tools.HOME_DRAFT_CHOICES` (Run a Live Draft, Simulate a Draft, Analyze Draft Strategy,
  Open Saved Drafts) and the "My league" block.
- **Tightened test.** It renders Home with Streamlit's AppTest, with and without a league, and
  compares the buttons actually drawn with AMI's list in both directions. The stale "Start a mock
  draft" string still sitting in `TASKS` can no longer pass.
- **Purposes come from `draft_tools.DRAFT_TOOLS`.** Draft-tool purposes come from there and from
  nowhere else: each draft page's help purpose, the new `explain_draft_tools` tool ("What's the
  difference between the draft tools?", "Should I use Draft Lab or Draft Assistant?"), and the
  "How do I start a draft?" / "Where do I open an old draft?" how-tos.
- **Overlapping names.** Tool names are matched without overlap, so "Live Draft Room" isn't also
  read as "Draft Room".

## 4. U2/U3 page help

- **Headings.** Career Totals, Compare Players, Trend Value, Valuation, ML Predictions,
  Sleepers & Busts and Lineup & Trades now lead with their U2/U3 page heading. Each heading is
  pinned to its `page_head` call in the source.
- **"How to read it" lines**, each pinned to the page's own rule in the source:

| Page | Rule | Pinned to |
|---|---|---|
| Compare Players | who leads in HR/RBI/SB/OBP/OPS; **no overall winner** | `u2_answers.COMPARE_METRICS`, "No overall winner" |
| Valuation | production + trend components and weights; a flat trend is **never a decline**; hitters only | `u2_answers` "never called a decline", `valuation_scores.VALUATION_MIN_AB` |
| Trend Value | rate-stat trends weighted by plate appearances | glossary term built from `trend_slopes.RATE_SHRINK_PA` |
| ML Predictions | confidence is the model's label, not a range; no interval | `u2_answers.ml_answer` text |
| Sleepers & Busts | ranking gaps, not predictions | `u2_answers.sleeper_bust_answer` text |
| Lineup & Trades | completeness/status first; Use Suggested Lineup doesn't save or lock; trades live here | `u3_answers.lineup_answer`, `trade_verdict` |

- **Explore more is page-specific.** For U2/U3 pages it comes from each page's own guide line
  ("… under Explore more"); for U1 pages it is written per page. "Where are the advanced filters?"
  answers with *that page's* Explore more contents. Pages that haven't been reorganized say they
  have no Explore more section.

## 5. Commissioner Tools, lineup status, trade verdict

- **Commissioner Tools.** The glossary term `commissioner_tools`:
  - uses the panel label from `ui_hierarchy.COMMISSIONER_PANEL_LABEL` and quotes the panel's
    caption verbatim (test-pinned);
  - says the commissioner can act only for an unclaimed team, under the banner "Commissioner
    acting for <team>" (pinned to `fantasy_team_control`);
  - says acting for a team doesn't make it yours, and owner actions stay outside the panel.
- **Lineup status.** `lineup_status` explains Not saved / Draft / Saved and locked (and plain
  Locked). A test produces each status from `u3_answers.lineup_answer` itself. AMI **does not**
  infer your current status; that needs `fantasy_read_api.week_lineup_status` (§7).
- **Trade verdict.**
  - The `trade_verdict` term is built from `u3_answers.TRADE_VALUE_LABELS`,
    `TRADE_VALUE_THRESHOLD` and `ROSTER_ISSUE_LABEL`. A test produces all four labels from
    `trade_verdict` itself.
  - AMI's named-player trade answer now names the engine's verdict with the card's wording (the
    same mapping, not a new judgment).
  - When there are roster warnings, it says the card may read "Creates roster issue" instead.
    AMI can't tell which warnings are your own roster's until `roster_issues` is exposed (§7).

## 6. Plan (Pro) gate hook

- **Declaring a feature.** `ToolSpec.feature` names a `baseball_monetization.FeatureId`. The three
  "Advanced draft intelligence" tools carry it: `get_draft_recommendations`,
  `explain_draft_recommendation` and `get_team_needs`.
- **When it applies.** The check runs only while the app enforces that feature
  (`ENFORCED_PAGE_FEATURES`, or a future feature-level `ENFORCED_FEATURES`). It then uses the same
  `can_use_feature` the UI uses.
- **Where the snapshot comes from.** The snapshot is the page gate's own `_monetization_snapshot`
  for this run, passed `streamlit_app → render_ami_assistant_panel → ask → REGISTRY.call`.
- **No resolving in AMI.** AMI never calls `resolve_trusted_entitlement`, which can reach the
  billing provider, and fails closed when the snapshot is missing or not ready.
- **Today's behaviour.** Nothing is enforced, so behaviour is unchanged (tested). With the feature
  enforced in a test: Free gets "part of Pro", Pro passes, and a loading or missing snapshot is
  refused.
- **Product decision needed.** Advanced draft intelligence isn't page-mapped. If the product
  enforces it, the regular branch should add it to a feature-level enforced set that the UI also
  applies. AMI already reads that set.

## 7. Shared readers (now consumed)

All seven exist since `quality/ami-shared-readers @ 633538f` and AMI uses them; see
`docs/AMI_READERS_U4_INTEGRATION.md`. The list below is what this slice asked for.

AMI does not import internal fantasy modules to fill these gaps.

| Reader | Unblocks |
|---|---|
| `fantasy_read_api.week_lineup_status(session, team, week)` = `u3_answers.lineup_answer` over the saved record | "Is my lineup saved?" with the page's exact status |
| `roster_issues` (from `fantasy_trade_legality.trade_roster_issues`) + the analysis package on `TradeEvaluation` | the exact Trade Center label via `u3_answers.trade_verdict` |
| `pending_trade_draft(session, team)` | "Would *this* trade…" without naming players |
| `waiver_recommendations_view(session, team, position)` + `loaded_player_pool(session)` | waiver recommendations and their reasons |
| `player_owner(session, player)` | "who owns X now", without AMI reading roster internals |
| `week_view(session, number, team)` | weeks, without depending on the shape of `period_result` |

## 8. Unchanged

- The official League Standings vs current-roster what-if distinction; the fantasy read tools.
- Side-effect guarantees: fantasy reads, and now the U2/U3 help questions, leave the session
  byte-identical.
- No write tool; the `mutates=True` refusal.
