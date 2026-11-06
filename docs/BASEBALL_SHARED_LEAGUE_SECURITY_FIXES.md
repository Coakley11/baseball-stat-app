# Shared League security fixes R-1..R-7 (2026-11-05)

Branch `fix/shared-league-commissioner-authority`, from the combined candidate `2398f5c` (which is
unchanged). Local only: not pushed, merged or deployed. No production record, migration or
permission was changed. Findings: `docs/BASEBALL_SHARED_LEAGUE_SECURITY_REVIEW.md` (on
`plan/free-pro-entitlements`).

## Owner policy implemented

1. **Commissioner authority comes from the stored league only.** It never comes from an account's
   own saved copy.
2. **Only the authenticated host of a Shared Draft room may create that room's Shared League,** and
   the host becomes its first commissioner. Other participants keep drafting and managing their
   own teams.
3. **Sign-in is required for every Shared League action.** That covers creating, joining, claiming,
   inviting, accepting, shared reads and writes, and commissioner actions. With sign-in off, solo
   drafts and public features are unchanged, but no Shared League action is possible.
4. **Revoked, declined and expired invites confer nothing.** Invite answers and cancellations are
   safe against concurrent writes.
5. **Every privileged change is enforced on the server.** It is checked in
   `authorize_league_write` against the stored league, not just by hiding buttons.
6. **Existing league ids, teams, rosters, draft results and saved data are unchanged.**

## What changed

| Step | Change | Where |
|---|---|---|
| R-1 | `is_league_commissioner` uses the stored league whenever one exists (the old local rules remain only for a private league that was never shared). `repair_commissioner_identity` and `merge_shared_into_context` copy the stored commissioner into the local copy instead of the account's own id. | `fantasy_league_invites.py`, `fantasy_shared_league_store.py` |
| R-2 | `authorize_league_write` is **default deny** for non-commissioners. A member may change only: their own pending invite (to accepted or declined; who it was for cannot change); ownership records naming themselves, for a team nobody else holds (one team); trade proposals they are party to, plus new proposals from their own team; their own team's roster, plus both rosters of a trade they accept in that write; their own lineup in periods still upcoming; and new activity entries. Everything else keeps its stored value, including the commissioner, name, draft, settings, lineup format, calendar, finalizations, metadata and identity fields. A new league's commissioner must be its creator. | `fantasy_shared_league_authz.py` |
| R-3 | Membership counts only pending or accepted invites. Accept, decline and cancel read the stored league fresh and save with an **atomic compare-and-swap**: one PATCH on `league_id` and `revision`, and an empty result means another write came first. Cancel retries once and re-validates; accept rolls back and says so. | `fantasy_shared_league_supabase_store.py`, `fantasy_shared_league_store.py`, `fantasy_league_invites.py` |
| R-4 | Creating a room's league requires the verified account to be the **stored** room's host (`commissioner_participant_id` / `host_participant_id` / `host_user_id`). This is checked before anything is saved, and again on the server. The commissioner is set to the creating host. The button is disabled for others, with the reason shown. | `live_draft_shared_league.py`, `draft_archive_ui.py`, authz |
| R-5 | `load_shared_league` returns a league in a user request only to a verified member or invitee: one rule for all 33 readers. A record that carries an account id must match that id (usernames and workspaces count only for records without one). | `fantasy_shared_league_store.py`, authz |
| R-6 | `commit_shared_room_pick` writes only for a seated participant or the host. A participant may move the draft only from in progress to complete (the final pick); pause, resume and other status changes are the host's. A refused write changes nothing and returns the stored room. | `draft_room_shared_state.py`, authz |
| R-7 | `scripts/sql/baseball_shared_*.sql` now enable RLS and revoke anon/authenticated (service role only). Re-running them can no longer reopen the tables. | `scripts/sql/` |
| Also | Imported leagues always record the uploader as commissioner, even without a team claim (they used to be stored with none). The Shared Draft room store is isolated per test (tests had used the repository's `data/draft_rooms`). | `fantasy_league_context.py`, tests |

**Sign-in definition.** Sign-in enabled, plus the session's sign-in flag, plus an Auth user id
(`verified_account_ids`). Code outside a user request (scripts, tests) is not checked, as before.

## Existing leagues (including Danny–Barry)

- **No stored data changes.** The rules decide who may act; they never rewrite leagues.
- **A league made from a room that has no stored `commissioner_user_id`** (as the production
  Danny–Barry league may be stored) has the **stored room's host** as commissioner. This is the
  approved policy for every room league. It is read from the room each time and never written. So
  Danny keeps his commissioner tools, including cancelling the incorrect invite
  `inv_ef4d2624aa75` (still unchanged), and Barry keeps every member action.
- **A league with neither a stored commissioner nor a room host** has no commissioner until the
  recovery below. Members keep full member access.
- Pending invites stay valid. Revoked, declined and expired invites stop conferring access (R2
  check 10 counts any affected account before deployment).

## Recovery design (review only; nothing automatic)

For a room with no recorded host, or a league with no commissioner and no room host:

1. **Detect** (read-only): R2 checks 2–4 and 6, plus a room count with no host
   (`host_user_id = '' and host_participant_id is null`, counts only).
2. **Evidence report** (read-only, labels only): who sent the league's invites
   (`invited_by_user_id`), who owns teams, the room's participants and seats, and activity authors.
3. **Owner decision**: the owner names the commissioner for each case, or decides there is none.
4. **One audited write per league**, separately approved: a single-row update with a revision
   guard (`where league_id = … and revision = …`). It sets `commissioner_user_id` and
   `commissioner_assigned = {"by": "owner_recovery", "at": …, "evidence": …}`, with before and
   after checks. Nothing else changes.
5. **Until then**, commissioner-only actions explain that the league has no commissioner yet and
   the app owner can assign one. Members are unaffected.

## Counting leagues for the one-free-league allowance (design for Stage 6)

- **Unit:** a row of `baseball_shared_leagues`. `league_id` is its primary key, so a league is one
  row. Library entries, archived drafts and workspace copies are not rows, so they are **never
  counted**.
- **Owner:** the effective commissioner (`commissioner_ids`): the stored commissioner, or the
  stored room host for a legacy room league. Both of the account's ids match.
- **Duplicates:** rows that share a `source_room_code` count once. Rooms map to one league
  (`league_for_room`), but legacy fingerprint ids are deduplicated defensively.
- **Grandfathered leagues count** toward the allowance (owner decision). They are never deleted or
  disabled, never lose members, and their commissioner keeps managing them without Pro.
- **Query:** server-side with the service role, filtered (not the 200-row list):
  `shared_league_json->>commissioner_user_id = any(ids)`, plus legacy room leagues joined to
  rooms the account hosts. Counted on each create attempt inside the existing creation check.

## Tests

- **New:** `tests/test_shared_league_commissioner_authority.py`, 32 tests, all run as user
  requests with sign-in on. They cover: the finding-1 reproduction; forged local metadata; every
  privileged mutation (refused); legitimate member writes (allowed); invitation races
  (compare-and-swap, cancel racing an acceptance); room-host authority, including reconnect and a
  room with no host; existing-league compatibility; sign-in off; room writes; the Supabase CAS
  request; and the install scripts.
  **28 of them fail on the candidate's code**, so they detect the vulnerabilities. The 4 that pass
  on both are the "members can still act" checks.
- **Updated to intended behavior:** fixtures that called an id without a sign-in "signed in"; a
  member write that used to replace the whole roster map; forged-local-metadata expectations; the
  12 s soft cache in cross-account tests; developer-only diagnostics; and explicit team claims.
- **Legacy 14:** 6 fixed. `test_guest_cannot_start_shared_draft` passes again: its timer tail, an
  open product question, moved to `test_first_pick_clock_rearms_once_after_a_slow_first_paint`.
  Still open, all non-security:
  - 2 Live Draft confirmation-message tests (the success flash is not rendered in the AppTest
    fixture);
  - 2 origin-visibility tests (incomplete fixture draft);
  - 3 Shared Draft pool tests and the timer question;
  - the post-reboot step of the trade-reboot test, which fails identically on the candidate.

## Two-account QA plan (baseball-qa-staging)

Run the app from this branch on the QA configuration, with two QA accounts in two browsers:

1. Host creates a room; the guest joins; they draft to completion. The guest's Create Shared League
   is disabled with the reason; the host creates it.
2. The host reconnects in a new browser and still holds commissioner tools.
3. The guest (member) has no invite or settings controls. Forged attempts are refused on the server,
   and the stored league is unchanged (verified by read-only REST).
4. The host invites a third account. Cancel and accept are tried at the same moment, and exactly one
   wins.
5. A revoked invitee loses access. A member trades, sets a lineup and makes a waiver move, and all
   work.
6. With sign-in off in a local run, no Shared League action is possible, and solo drafts still work.

## Update 2026-11-06: production R2, two-account QA, QA-found fixes, first-pick clock

### Production R2 (owner ran it read-only in daniel-ai-suite)

5 leagues. All 5 store `commissioner_user_id` (0 missing; checks 13 and 14 are both 0), so no
league relies on the derived room-host commissioner and no recovery step is needed. In all 5, the
commissioner owns a team. 4 leagues have a team owned by someone other than the commissioner;
for those owners nothing changes except that league-wide actions are now refused for them.
Invites: accepted 2, declined 1, pending 1.

- **1 declined invite whose invitee owns a team.** Membership comes from the team-ownership record,
  not the invite, so that member keeps their team, roster, lineups and trades, and reading the
  league. The declined invite itself confers nothing and cannot be revived (test
  `test_a_team_owner_whose_invite_was_declined_keeps_their_team_and_nothing_more`).
- **0 invalidated invites whose invitee owns no team.** Nobody loses access.
- **1 invite without `invitee_user_id`.** It is matched only to the account named by its stored
  username, workspace or full email (never another account). It grants no commissioner power and
  the commissioner can still cancel it (test
  `test_an_invite_without_an_account_id_matches_only_the_named_account`). If it is the known wrong
  pending invite `inv_ef4d2624aa75`, only `coakley11` could answer it until Danny cancels it.
- Optional read-only follow-up **R3** (counts only) narrows these two rows down and checks the data
  shapes the QA fixes below depend on: `docs/sql/baseball_shared_security_recheck_readonly.sql`
  on `plan/free-pro-entitlements`.

### Two-account QA on baseball-qa-staging (qa_danny commissioner, qa_barry member, qa_other)

The run used the isolated QA configuration (both keys and the URL decode to the QA project; the
guard refuses anything else), a local app on 127.0.0.1:8611 and the app's own code paths.

| Check | Result |
|---|---|
| Existing QA league `league:room-oyn4nc`: Danny has the invite panel, Barry does not | pass |
| New Shared Draft: Danny hosts room 50RJB0, Barry joins and claims Barry | pass |
| First pick: no clock during the 90 s first load (30 s timer, no autopick); clock started at board-ready; expiry then autopicked; `timer_live_ready_at` stored | pass |
| Barry refreshes mid-draft: room state and stored deadline intact | pass |
| Barry's Create Shared League is disabled: "Only this room's host can create its Shared League…" | pass |
| Danny closes the browser, signs in from a new one, the completed room restores, Danny creates the league (`commissioner_user_id` = Danny) | pass |
| Danny invites qa_barry; Barry accepts and claims Barry; Barry has no invite panel | pass |
| Server tamper run as Barry with his real identity (25 checks): forged local commissioner metadata, send or cancel invites, rename or change settings, make himself commissioner, manage Danny's team, change the season; QA Other cannot read or write | 25 pass (after the fixes below) |
| Barry's own-team write; stale write refused; 4 concurrent writers, exactly 1 wins | pass |
| Danny invites qa_other and cancels it; Other loses the league; Other cannot accept or answer the revoked invite | pass |
| Cancel and decline at the same moment: exactly one wins, storage matches, the loser is told "This invite is no longer pending. Nothing was changed." | pass |
| Trade: Danny proposes, Barry accepts, both rosters swap; Barry cannot reopen it; an over-reaching accept changes neither roster | pass (after the fixes below) |
| App restarted twice: both stay signed in; leagues, claims and commissioner tools intact | pass |
| Pre-existing QA data: 2 leagues and 5 rooms byte-identical (rooms compared without presence timestamps; revisions unchanged) | pass |

### Found by QA and fixed (commits 697e409 and the follow-up)

1. **A member could add a team.** An accepted invitee (a member without a team) could store an
   ownership record and a roster for a team the league does not have (team ""). Members now claim
   only an existing, unowned team of the stored league, one team in total, and never add rosters.
2. **Trades could be rewritten.** A party could move an accepted trade back to pending; the
   accepting member's write could set the other team's roster to anything. Now a settled trade
   never changes; from pending the recipient accepts, declines or counters and the proposer
   cancels (any member may mark stale or expired); a proposal's teams and players never change;
   an accepted trade must move the other roster by exactly its terms, or it stays pending and
   neither roster changes; a member never adds a player who is on another team's roster.
3. **Malformed trade data broke every member's Library page.** An accepted trade whose players
   were plain strings (QA test data) raised `AttributeError` in `fantasy_trade_roster_sync`. Members
   can no longer store or execute proposals whose players are not player records. (The app itself
   always writes records; R3 check 7 counts any such trade in production.)

QA data written by the run stayed in baseball-qa-staging: room 50RJB0 and `league:room-50rjb0`
(teams Danny and Barry, trades and invites used by the checks). The stray "" team from finding 1 and
the trade from finding 2 were put back by Danny as commissioner.

### First-pick clock (owner decision 2026-11-06)

`first_pick_expired_before_actionable`: a pick-1 clock that ran out before pick 1 was ever actionable
is never autopicked; the first live-board paint initializes it once and stores
`timer_live_ready_at`. After that the deadline survives reruns, refreshes, reconnects and restarts,
and an expiry follows the timeout and autopick policy. `tests/test_first_pick_timer_policy.py` (10).

### Legacy test status

All 14 of the original legacy failures now pass except one, and none was fixed by weakening a
product rule. Each change brings a test to the app's current intended behavior: copy, fixture
completeness, same-server pool cache isolation, the rebuilt context id, and Solo timer ownership.

The one still open is `test_second_account_sees_library_after_create_from_room_participants`. It
fails identically on the candidate. A seated room participant's team is **reserved** for them, not
claimed, so their Library shows the league only after they accept the host's invite (QA confirmed
that flow). Open product question: should a reservation alone list the league?

## Update 2026-11-06 (later): reservations, atomic accept, third QA run

**Owner decision: a team reservation alone is not Shared League membership.** A Live Draft
participant keeps their Live Draft Room. They see a pending invite once the commissioner sends one,
and the league appears in their Saved Draft Library only after they accept it and claim the team.
Nobody is enrolled automatically.

- `401f9a9`: a reserved team record (`claim_status` "reserved…", no account id) used to match the
  participant by email. It made them a member who could read the league and change that team's
  roster without an invite. A reservation is no longer ownership or membership, and only the
  account a team is reserved for may claim it.
- `3a15648`: accepting an invite and claiming its team are one action. QA found an invitee whose
  claim of another person's reserved team was refused, yet the invite stayed "accepted" with no
  team (the app's rollback cannot undo an acceptance). Such an acceptance now stays pending. The
  Accept form offers a reserved team only to the participant it is reserved for.

Third QA run (baseball-qa-staging, room L9EBUJ, `league:room-l9ebuj`):

| Step | Result |
|---|---|
| Existing memberships: Danny and Barry still see both existing leagues, Danny keeps the invite panel, QA Other sees neither | pass |
| Reserved only: Barry keeps the Live Draft Room; the league is not in his Library; the server refuses reads, claims and roster writes (8 checks) | pass |
| QA Other invited: the form offers no team ("No unclaimed teams remain"); a forced claim of Barry's team is refused and the invite stays pending (9 checks) | pass |
| Barry invited: the pending invite offers Barry; he accepts and claims it; the league appears in his Library | pass |
| QA Other declines; Library unchanged | pass |
| Pre-existing QA leagues byte-identical; rooms unchanged apart from presence timestamps | pass |

## Update 2026-11-06 (evening): trades match players as the app does; Accept form uses the server rule

- **Trade player matching.** The app checks and executes a trade by normalized player key
  (`normalize_player_key`: accents, case, punctuation and Jr./Sr./II-V folded; a roster entry's
  stored `player_key` first). The server's exact-swap and no-duplicate checks compared exact names,
  so a trade whose terms and roster spelled a player differently ("Jose Ramirez" and "José
  Ramírez") executed in the app, but the server silently kept the stored rosters and the pending
  trade. The server now matches players the same way the app does. Production R3 check 11 (1
  pending trade) uses exact names; R4 tells a spelling variant apart from a player who really moved.
- **Accept form.** With a verified sign-in, a reserved team is offered only when the server's
  `_reservation_is_session` would allow the claim (an account id must match; an email prefix that
  equals a username is never enough). Before, the `coakley11` account was offered a team reserved
  for `coakley11@…` and then refused; nothing changed, but the offer was wrong.
- Verified separately: accepting an invite and claiming its team stay atomic when persistence fails
  (a conflict, a refused write, OSError, ValueError, a lost write, a failed re-read). The invite
  stays pending, the account's Library and league contexts are restored, no team is owned, and a
  retry succeeds.
