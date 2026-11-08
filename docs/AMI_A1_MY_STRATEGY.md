# AMI A1: the existing AMI Coach reads your selected Draft Strategy (read-only)

Branch `feature/ami-strategy-coach`. It is built on `fix/s2-stale-loaded-strategy` (KI-1), which is built
on the Dev release `255db97`. Not deployed.

## What it does

The existing AMI Coach gets a `my_strategy` intent for questions about the user's **own saved Draft
Strategies** and Global Queue. It is part of the existing AMI, not a separate assistant.

| Question | What AMI uses |
|---|---|
| What players are in my Power-Hitting Strategy? | that strategy (name matched case/punctuation-insensitively) |
| Where did I rank Aaron Judge? | the selected strategy (or the one named earlier in the conversation) |
| Is Juan Soto in this queue? | the selected strategy on Draft Strategy · PRO (the Global Queue when none is selected) |
| What notes did I save about Bobby Witt Jr.? | the user's note, quoted; if that player is in another strategy, that strategy is named |
| How many catchers do I have in this strategy? | positions stored on the strategy's entries; players with no position recorded are reported, not guessed |
| What are my main positional priorities? | the saved approach, category priorities, ranking note, pins and the position mix of the top 10 |
| How does this strategy differ from my Global Queue? | players only in each, players in both with both ranks |
| Which saved strategies do I have? | names, sizes, which one is selected, unsaved changes |

Follow-ups keep the strategy and the question ("What about Pete Alonso?"). Change requests ("Add Judge to my
Speed strategy") get a plain answer: AMI only reads strategies for now. It points to the control that makes
the change (no waiver or roster wording). The change itself comes in A3/A4, as confirmed proposals.

`draft_strategy` is unchanged: general advice such as "Should I draft for need or best available?" still
routes there. `my_strategy` needs a personal cue:
- "my / saved / selected … strategy" or "strategies";
- "did I rank / save / note", "my notes";
- "Global Queue";
- "this strategy" when one is selected;
- "this queue" and "my priorities" on the Draft Strategy page;
- a follow-up to a `my_strategy` answer.

How-to questions ("How do I save my strategy?") stay with page help.

## Safety

- **Read-only.**
  - The four tools (`list_my_strategies`, `get_my_strategy`, `get_global_list`,
    `compare_strategy_to_global`) are registered in AMI's read-only registry, which refuses tools that write.
  - They read session values with `.get` only, and never call helpers that create session keys, purge the
    trash or drop the Global Queue's "loaded from" record.
  - Tests snapshot the session before and after every question and tool call, and record every storage
    write: there are none.
- **Account-scoped.**
  - Strategies are read through `draft_strategy_v2.list_strategies_v2` / `research_log`, behind the store's
    own access check: signed in, plus the same Pro entitlement as the page.
  - Storage is per account (Supabase rows per user / the local workspace folder).
  - AMI's conversation memory stays in the user's browser session and is never saved to the cloud.
- **Deleted strategies are never read.**
  - Recently deleted lives in a separate item type that these tools never open.
  - A selected strategy deleted elsewhere is reported as "no longer saved" and not used.
  - The Global Queue's "loaded from" is reported only while that strategy is live. This coordinates
    with KI-1.
- **Saved vs unsaved.**
  - Answers use the saved strategy.
  - Unsaved editor edits are shown separately under "Unsaved changes in the editor (not saved yet)".
  - A never-saved strategy is labelled as such.
- **Nothing invented.**
  - Ranks, notes, pins, positions and research are quoted from the user's own records.
  - A player not in the strategy is reported as not there.
  - Player matching never guesses between two candidates.
  - No statistics are added.
- **Free and Pro.**
  - The strategy tools declare `plan_capability="draft_strategy_library"`, the page's capability. The registry
    gate uses the host's entitlement snapshot, so when enforcement is on, non-Pro users get the same "part of
    Pro" answer as the page, before any storage read.
  - The store's own check then applies as on the page; with billing rollout off or in preview it makes no
    network call.
  - The Global Queue tool declares no capability: it stays free.
  - Signed-out visitors get a sign-in answer and no storage read.
  - Nothing is enforced today, and this work changes no billing or enforcement setting.
- **Context.**
  - The panel's context line names the open strategy on Draft Strategy · PRO, read from this session's
    editor state only, with no storage call.
  - The tools stay authoritative on what is saved and live.

## Files

- `ami_assistant/tools/strategy.py`: the read-only tools, strategy and player matching.
- `ami_assistant/strategy_router.py`: the `my_strategy` intent, focus, player and strategy-name extraction,
  and change-request answers.
- `ami_assistant/strategy_compose.py`: the answers.
- Small hooks in `router.py`, `compose.py`, `engine.py`, `conversation.py`, `context.py`,
  `capabilities.py` and `tools/__init__.py`.

## Tests

- `tests/test_ami_my_strategy.py` (29 tests):
  - routing of the owner's questions;
  - general advice unchanged;
  - answers for every question;
  - unsaved vs saved;
  - a never-saved strategy;
  - deleted strategies never read;
  - "loaded from" for a deleted strategy;
  - no writes;
  - registry read-only;
  - two-account isolation;
  - signed-out visitors;
  - the enforced Pro gate (simulated);
  - context from session only;
  - matching that never guesses.
- The existing AMI suites must stay green (routing audit, acceptance, answer quality, help, panel, safety,
  tools, readers, U5).
