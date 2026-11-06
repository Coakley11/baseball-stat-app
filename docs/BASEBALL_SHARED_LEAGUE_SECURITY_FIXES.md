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
