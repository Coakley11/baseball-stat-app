# AMI Coach × Pro Draft Strategies: plan (2026-11-08)

Branch `feature/ami-strategy-coach`, based on the Dev release `255db97` (Slice 2). Nothing here is deployed
without the owner's approval.

## Starting point (what exists today)

- AMI is **deterministic and read-only**: router → read-only tool registry → grounded template composer.
  It makes no model calls. `ToolRegistry.register` refuses any tool with `mutates=True`.
  `capabilities.FUTURE_ACTIONS` already declares `queue_player` as "declared, never callable". Any write
  must reuse the UI's canonical function, after an explicit confirmation.
- AMI context comes from an allowlist (`context.PAGE_KEYS`), never from iterating session state.
  `safety.scrub` / `clean_text` drop secret-looking text.
- Slice 2 already expects AMI:
  - `draft_strategy_v2.NOTE_SOURCES = ("user", "ami_confirmed")`;
  - research entries carry `kind`, `player_key` and `source`;
  - every edit records an `actor` in the strategy's history;
  - saves check `base_revision`, so a stale write is refused instead of overwriting.
- The selected strategy is the editor's open one: `draft_strategy_work.OPEN_KEY`
  (`_draft_strategy_open_id`). Its working copy (`WORK_KEY`) may have unsaved edits.
- Pro gate: `baseball_monetization` capability `draft_strategy_library` → feature `DRAFT_STRATEGIES`.
  AMI tools declare it as `plan_capability`, so they follow the same gate as the page. Nothing is
  enforced today, and this work changes no billing or enforcement setting.

## Rules every slice keeps

1. **AMI never writes by itself.** Tools stay read-only. A change is a *proposal* (data) shown with its
   exact before/after. Only the user's click on **Save to <strategy>** writes, through the same
   `draft_strategy_work` / `draft_strategy_v2` functions the Pro editor uses, with `source`/`actor` =
   `ami_confirmed` and the usual revision check.
2. **The Global Queue is never touched by AMI.** Transfers stay in the Pro editor's Transfer tab, with its
   own confirmations.
3. **Strategies stay independent.** A proposal names one strategy id. It never touches another strategy,
   the trash, or the Fixed / Adaptive working copies.
4. **Account isolation.** Strategy reads go through `draft_strategy_store._require_access` for the
   signed-in account. Guests get "Sign in to use saved strategies". Nothing about strategies goes into
   any shared or room document.
5. **No invented baseball facts.** Numbers come from the existing stat and draft tools (Lahman, page
   snapshots, projections). Strategy answers quote only the user's own records. When data is missing,
   AMI says so.

## Slices

### A1: the selected strategy as AMI context (read-only), the first slice

**Status (2026-11-08):** implemented on this branch; see `docs/AMI_A1_MY_STRATEGY.md`. It builds on the KI-1 correction (`fix/s2-stale-loaded-strategy`), so AMI never reads a deleted strategy.

- `ami_assistant/tools/strategy.py`, read-only tools with `plan_capability="draft_strategy_library"`:
  - `get_selected_strategy`: name, approach, preferences, queue size, top of the queue with pins,
    note and research counts, saved/unsaved state. It reads the open working copy, so unsaved edits
    are labelled as unsaved.
  - `get_strategy_player`: is <player> in it, at what rank, pinned or not, the user's note.
  - `list_my_strategies`: names and sizes only, so AMI can say which one is selected.
  - `compare_strategy_to_global`: players only in one or the other, read-only.
- Context: AMI knows "Draft Strategy" as a page (selected strategy name and size only; small by design).
  On the research and draft pages, the context line names the selected strategy.
- Router intents: "what's in my strategy", "is Judge in my Power strategy", "where is Soto ranked",
  "what did I note about Witt", "how does my strategy differ from my Global Queue", "how many catchers
  does it have" (positions as stored on the entries).
- Tests:
  - tool and router units;
  - guest refusal;
  - two isolated accounts never see each other's strategies;
  - unsaved working copy vs saved copy;
  - deleted strategies are invisible;
  - a store spy proves no write call happens;
  - a simulated enforced gate refuses non-Pro users the same way the page does;
  - no secrets in the payload (`safety.find_secrets`).

### A2: research bridge

- Answers on Compare Players, Historical Explorer, Trend Value, Career Totals, Sleepers & Busts and the
  projection/valuation pages add strategy membership ("Judge is #3 in **Power**, pinned").
- Answers also handle "compare my top two first basemen" by resolving players from the strategy, then
  using the existing stat tools.
- Positional scarcity comes from the existing draft context ("Positional depth") when a board exists.
  Otherwise AMI says it needs a board.

### A3: confirmed findings and preferences

- AMI offers to save a research finding (`append_research`, kind `finding`), a player note (`set_note`)
  or a preference such as preferred rounds or targets (`set_preferences`). It shows the exact text and
  any note it would replace.
- **Save** writes to the working copy and saves it with the revision check. If the strategy changed
  elsewhere, the save is refused with a plain message and nothing is overwritten.
- **Dismiss** writes nothing.
- The edit appears in the strategy's history as `ami_confirmed`.

### A4: confirmed queue changes

- Add, remove, move and replace-order proposals, shown as a numbered before/after list with the counts
  (respecting the 300-player limit).
- Confirm applies the same `draft_strategy_v2.insert/remove/move/replace_queue` functions as the editor;
  Dismiss leaves everything unchanged.
- No transfer to or from the Global Queue.

### A5: conversational plan builder

A guided multi-turn flow that builds on A1–A4: rankings, positional scarcity, comparisons, sleeper
targets and preferred draft rounds. Each step ends in a proposal the user confirms or skips.

## Release order

Each slice runs focused tests, CI against the then-current Dev, and browser QA on the QA project with QA
accounts. A deployment happens only with the owner's separate approval.
