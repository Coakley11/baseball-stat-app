# Command Center handoff: the `music_resume_payload` import boundary

**Branch:** `fix/command-center-deeplink-boundary`, from `integration/baseball-final-candidate
@ c5281b0`. Local only.

## Root cause

`suite_deep_links.py` is a **shared suite module**: the same file builds Continue / resume links for
every suite app (Music, Investment, Baseball, NBA, Applied Intelligence). The Command Center repo
owns it, and it is copied into each app.

`57009b3` ("Sync suite modules", 2026-07-16) replaced Baseball's copy with the shared one. That
copy imports `music_resume_payload` at the top of the file. Only the Music-facing apps ship that
module (Command Center, Investment, Music); **Baseball never had it**.

| Effect in a Baseball checkout (hosted, or anywhere without the sibling Command Center repo) | How it showed |
|---|---|
| Get full analysis, the Baseball Insight box, Hall of Fame case sends, per-page Send to AMI: `suite_analytical_question.build_applied_math_resume_url` imports `suite_deep_links` and raised | "Couldn't send this to Command Center" (U5) / failed send |
| `suite_activity_client.record_activity`: Continue links for Baseball activity | silently missing (exception swallowed) |
| `baseball_hof_activity`: HOF `continue_url`; `applied_math_return_insight`: return links | silently empty |
| 5 test files (`test_baseball_command_center_integration`, `test_baseball_draft_activity`, `test_draft_lab_resume`, `test_hof_case_resume`, `test_suite_workspace`) | collection errors in every full run |

It worked on the developer machine only by accident: loading the Command Center's
`suite_storage` puts the sibling repo on `sys.path`.

## What the module is used for

`suite_deep_links` uses three of the four names it imported: `normalize_resume_kind`,
`legacy_resume_key_for_payload` and `encode_payload_b64`. All three are used only in
`_music_scalar_params_from_payload` and `build_music_continue_url`, which build a Music Continue
link from a typed Music payload. `decode_payload_b64` was imported but unused. No Baseball link
needs any of them.

## Fix: correct the import boundary (no copied module)

- `music_resume_payload` is imported inside the two Music-only functions, not at the top of
  the file.
- The four names stay reachable as attributes of `suite_deep_links` (PEP 562 `__getattr__`), so
  any app that used them through this module keeps working.
- Nothing is copied from the Music or Command Center repos. Music behaviour is unchanged wherever
  the module exists. The handoff payload, page context and metadata are unchanged.

**Ownership and dependency boundary:**
- `suite_deep_links` (shared; Command Center owns it) may use `music_resume_payload` only for
  Music links.
- Apps that never build Music links don't ship that module.
- The Command Center should take the same change upstream, so the next "Sync suite modules"
  doesn't bring the top-level import back.

## Evidence

- **Parity:**
  - With `music_resume_payload` present, 16 links are byte-identical before and after
    (Applied Intelligence history/fantasy/HOF, Baseball, Investment, NBA, Music including a typed
    Continue payload).
  - Without it, all 15 non-Music-payload links are identical, and only the typed Music link
    needs the module.
- **Boundary test:** `tests/test_suite_deep_links_boundary.py` uses a fresh interpreter (`-E -s`)
  with the module blocked. 4/4 pass; 3 of them fail on the unfixed file.
- **Isolated end-to-end** (a clean checkout plus only the Command Center's `suite_storage` as an
  isolated SQLite destination; `music_resume_payload` absent and blocked; cloud off; network
  blocked):

  | Check | Result |
  |---|---|
  | History, fantasy-league, Hall of Fame and per-page (Trend Value, Sleepers & Busts) handoffs | reach the store with question, page context, a resume card with a working link, and the context blob |
  | Hall of Fame | records `hof_case_analysis_submitted`; blob type `baseball_hof_case`; the packet round-trips |
  | Quick conversations | persist nothing |
  | Write requests | refused, with no handoff offered |
  | Plan features | none enforced; the handoff isn't a plan capability |

- **Browser:** the real app from that checkout, with `music_resume_payload` blocked in the server
  process, at 1280 and 390:
  - exactly one Ask AMI (sidebar on desktop, top expander on phones) and no Insight box;
  - suggestions and a follow-up work;
  - Get full analysis shows "Full analysis requested…" and writes the records;
  - pressing again shows "You already asked…";
  - no exceptions or overflow.
- **Focused A/B** (150 files; same worktree, only `suite_deep_links.py` toggled):
  - passed 1,118 → 1,180, failed 83 → 82, files crashing on import 13 → 8;
  - three handoff tests that failed now pass (`test_hof_ami_handoff`, two in
    `test_instant_insight_submit`).
  - The "new" failures are 10 tests in the 5 newly importable files. They fail identically on the
    original code once the module is supplied, so they are not caused by this change (see below).
- **U5 (`ami/u5-unified-entry @ 0c00c76`):** merges with this fix without conflicts.
  - On the merge: U5's suite + the boundary tests pass, 22/22.
  - U5's three real-handoff tests pass **without** the Command Center path and with the module
    blocked.

## Not fixed here (pre-existing, separate owners)

1. **Lost Baseball deep-link features.** `57009b3` also removed Baseball-specific branches that
   the 10 newly visible tests expect:
   - `bb:hof_case` / `bb:draft_lab` routing;
   - `suite_hof_target` / `suite_hof_case`;
   - `suite_historical_stat` / Draft Lab resume.

   Continue links from Command Center back into Baseball therefore open less precisely than in
   June and July. The fix is to restore those branches in the shared module, upstream at the
   Command Center. Owners: Command Center + Baseball.
2. **A failed save reports success.** `submit_analytical_question` swallows storage errors, so a
   failed write still shows "Full analysis requested". An immediate retry is then treated as a
   duplicate: it writes a resume card without the context blob. Owners: Command Center + AMI.
3. **AMI read "Is Team B's lineup saved?" as your own team** and answered with Team A's status
   (no private data was shown). Owner: AMI.
