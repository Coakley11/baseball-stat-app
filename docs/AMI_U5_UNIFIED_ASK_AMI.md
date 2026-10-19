# U5 — one Ask AMI

Branch `u5/unified-ask-ami`, from `integration/ami-readers-u4 @ 674055b`. Local only: not pushed,
not merged, not deployed.

## 1. What changed for the user

| Before | After |
|---|---|
| Two boxes in the sidebar: **💬 Ask AMI** (quick answers) and **⚾ Baseball Insight** (sends a question to Command Center) | One **Ask AMI** |
| On a phone: open the sidebar (») to find either box | An **💬 Ask AMI** bar at the top of every page, right under the page switcher |
| A typed example in the placeholder | Up to three one-tap suggested questions for the page (its help metadata; each one is tested to route) |
| A deeper analysis meant a second box and retyping the question | **Get full analysis** under an answer sends the same question and page context to Command Center |
| Home: "use the Baseball Insight box" | Home: use Ask AMI; press Get full analysis for a deeper write-up |

The answer, its source line ("App data · League Standings (official) · Your league (QA),
read-only", or "Lahman Baseball Database …"), follow-ups, "Earlier in this conversation" and
"Clear conversation" are unchanged.

## 2. Design

**One assistant, one conversation, one visible surface per device.**
- `ami_assistant/ui.py` renders the same fragment twice: in the sidebar
  (`.st-key-ami_sidebar_panel`) and in a phone bar at the top of the page
  (`.st-key-ami_phone_entry`, an expander).
- CSS with the app's own breakpoint (`mobile_foundation.PHONE_MAX_PX`, 640 px) shows exactly
  one of them: the sidebar panel above 640 px, the phone bar at or below it.
- Both stay mounted, so widget identity is stable across reruns.
- Both read and write the one session conversation (`_ami_assistant_conversation`,
  `_ami_assistant_last`). The phone widgets use an `m_` key prefix.

**Quick answers** come from the unchanged read-only engine. Each surface is a fragment, so asking
reruns only the panel, never the page's analytics.

**Deep analysis on an explicit press only.**
- The ⚾ Baseball Insight button's submit was extracted, unchanged, into
  `baseball_ami_sidebar.submit_baseball_insight`. That covers the page context
  (`build_baseball_applied_math_context`), the source state (`build_source_state`),
  `submit_analytical_question` (activity, resume item, context blob), the send counter and the
  `on_after_send` save deferral.
- `streamlit_app.py` passes it to the panel as `full_analysis`, through `_ami_full_analysis`.
  The panel calls it only inside the click handler of **Get full analysis**.
- The `ami_assistant` package still imports nothing that writes. The handoff comes in from the
  host, so the package's static import ban (storage, auth, billing, network, model SDKs,
  `applied_math_context`) still holds.

**When Get full analysis is offered:** under an answer grounded in data (the app's, the user's
league, or a question outside AMI's data). It is not offered under app help, refused instructions
("Draft Bobby Witt for me") or a clarifying question back to the user.
- After a press: "Full analysis requested. Open Command Center when you're ready to review it."
- A repeat within the duplicate window gets the pipeline's own duplicate notice.
- A failure gets a short error. Nothing is retried automatically.

**Kept, unchanged:**
- `submit_analytical_question` and the Command Center / Applied Mathematical Intelligence
  pipeline.
- Hall of Fame Case Mode's on-page send (Career Totals).
- The page-level "send to AMI" flows (Comparison, Sleepers, Valuation history).
- `render_baseball_insight_sidebar` itself, which now calls `submit_baseball_insight`. It is
  still reachable through `suite_analytical_question.render_applied_math_sidebar_entry` for
  `source_app="baseball"`, but nothing in this app calls that for Baseball (Music Coach uses the
  shared entry with `source_app="music"`). The Baseball app just no longer renders the box.

**Help:** "Where did Baseball Insight go?", "What is Command Center?" and "How do I get a full
analysis?" answer from a new glossary term, `full_analysis`.

## 3. Component ownership

| Piece | Owner | Change |
|---|---|---|
| `ami_assistant/ui.py`, `glossary.py`, `router.py` | AMI | the unified panel, phone bar, suggestions, Get full analysis, help |
| `baseball_ami_sidebar.py` | AMI / Command Center bridge | `submit_baseball_insight` extracted; the box renders as before |
| `streamlit_app.py` | shared | the one AMI wiring block only: the Insight call replaced by `_ami_full_analysis` + `full_analysis=` (and the import) |
| `home_page.py` | U1 (regular) | the Ask card's sentence |
| `suite_analytical_question.py`, `applied_math_context.py`, persistence | Command Center / regular | none |

## 4. Safety

- **Read-only:** no new tool, no tool with `mutates`; the no-write-tool test is unchanged.
- **No cloud persistence for quick answers:**
  - suggested, typed, follow-up and phone questions run with `submit_analytical_question`,
    `record_activity`, `submit_baseball_insight` and `requests` patched to fail, and nothing
    calls them;
  - AMI's session keys are in none of the workspace persistence allowlists;
  - `build_baseball_disk_state` on a session holding a quick conversation contains none of it.
- **Handoff only on press:** asking never calls the handoff. One press calls it once with the
  question and the page; a repeat is reported as a duplicate.
- **Authorization, team isolation and calculation parity:** unchanged. The readers, access rules
  and tools are the same.
- **Plans:** the page gate's snapshot still reaches the tools. No new Pro restriction; Get full
  analysis is not gated, the same as the Insight button it replaces.
- **No model API calls, no credentials.**

## 5. Regression risk

- **Concurrent lines.** `integration/baseball-auth-dev` (`edeb8b3`) and
  `integration/baseball-billing-auth-current-dev` (`df6f9b6`) also touch `streamlit_app.py`
  (account-sidebar rerun guard, developer-mode toggle, plan gate).
  - `git merge-tree` gives the **same** conflict set with and without U5. Auth:
    `baseball_account_workspace.py`. Billing/auth: that file plus billing config, monetization
    and docs.
  - Those conflicts already exist between those lines and `674055b`.
  - `streamlit_app.py` merges cleanly with both.
- **Sidebar rerun guard.** The auth line's `claim_sidebar_render` guards the account chrome, not
  the AMI fragment. AMI renders once per run in the sidebar plus once in the main area.
- **Tests that pinned the old box.** `test_baseball_ami_button_label`,
  `test_ami_submit_button_audit` and the AMI wiring test now pin the new wiring:
  `submit_baseball_insight` is used, and the box isn't rendered by the app.
- **What a phone user sees.** Above 640 px the phone bar is `display: none`. At or below, the
  sidebar copy is hidden, and on a phone the sidebar is collapsed anyway.

## 6. Verification

**New tests (`tests/test_ami_assistant_u5.py`, 13):**
- one-tap suggestions;
- Get full analysis offered only under data answers, and calling the handoff only on a press
  (once, with the question and page), with the duplicate notice;
- no button without a host handoff;
- the phone bar and sidebar share one conversation;
- exactly one surface is visible per device (CSS);
- `submit_baseball_insight` equals the Insight button's submit (context, source state, the
  `Career_Totals` send counter, the save deferral once and not for a duplicate), and the old
  button calls it;
- quick answers write nothing;
- quick conversations are never persisted (allowlists + `build_baseball_disk_state`);
- the app's wiring and the Hall of Fame on-page send;
- Home copy;
- help for Baseball Insight / Command Center / full analysis.

**Focused suites:**
- AMI, the Insight/handoff/Hall of Fame/page-send, U1–U4, monetization and mobile suites:
  355 passed, 11 failed.
- 10 of the 11 also fail on `674055b`.
- The 11th, `test_ami_submit_button_audit::test_deploy_marker_resolves_commit_dynamically`,
  passes alone. It only reads `suite_deploy_marker`, so it is order-dependent.

**Full suite** (`pytest tests --continue-on-collection-errors`):

| Run | Passed | Failed | Collection errors |
|---|---|---|---|
| U5 branch | 5,123 | 258 | 13 |

| Category | Count | Detail |
|---|---|---|
| Introduced by U5 | **0** | Every failure also fails in the `06acd43` baseline |
| Pre-existing (also failed on `674055b`) | 254 + 13 | as in `docs/AMI_READERS_U4_INTEGRATION.md` |
| Environment-dependent | 3 | `test_workflow_persist_guard` (it reads this checkout's local `data/`): 9 of its tests fail alone too. They passed in the `674055b` run and failed in the `ff46ff6` and `06acd43` runs. U5 changes none of the modules involved |
| Load flake | 1 | `test_live_draft_full_page_rendered` passes alone (it also failed in the `ff46ff6` run) |

**Browser** (Playwright; 1280 / 430 / 390 / 360; zero horizontal overflow):

| Check | 1280 | 430 | 390 | 360 |
|---|---|---|---|---|
| Visible surface (real app) | sidebar panel | phone bar | phone bar | phone bar |
| Baseball Insight box present (real app) | no | no | no | no |
| Home card points to Ask AMI | yes | yes | yes | yes |
| Answer, "Compare Judge and Soto." (real app) | 1.4 s | 2.1 s | 1.9 s | 1.4 s |
| Get full analysis offered (real app; **not pressed**: the real handoff writes to Command Center) | yes | yes | yes | yes |
| Suggested question → answer (harness) | 1.3 s | 0.8 s | 0.8 s | 0.9 s |
| Follow-up "Who had more power?" uses the conversation (harness) | yes | yes | yes | yes |
| Get full analysis → confirmation (harness, stub handoff that only records) | yes | yes | yes | yes |

- **Measurement race:** the harness's first visibility reading at 390/360 sampled the sidebar
  panel before the phone container's CSS arrived. Re-measured once settled, it is
  `display: none` and the phone bar is the only visible surface.
- **Page context:** the "Looking at" line follows the page ("Compare Players · …").
