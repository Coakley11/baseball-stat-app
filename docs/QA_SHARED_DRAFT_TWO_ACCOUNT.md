# QA: two-account Shared Draft, invitations and team claims

Prepared 2026-11-05 for branch `fix/shared-draft-invites-dev` (`bbbb0aa`). Nothing here touches production.
The app runs **locally** (no new Streamlit Cloud app, no billing service, no Stripe) against a separate
**QA Supabase project**. Two QA accounts play Danny and Barry in two independent browser sessions.

## 1. The QA project (owner)

A free-plan Supabase project is enough; the free plan is not billed. Never copy production users, drafts,
invitations or keys into it.

1. Create a new project named clearly, for example `baseball-qa`. Note its URL, the **service_role** key and
   the **anon** key (Project Settings → API). Keep them out of chat and out of git.
2. SQL editor, run in this order (all are in the repos; no production data is involved):
   1. Command Center `supabase/migrations/001_suite_activity.sql`
   2. Command Center `supabase/migrations/002_suite_account_memory.sql`
      (if it stops at `suite_user_settings`, run `003_suite_account_memory_resume.sql`)
   3. Baseball `scripts/sql/baseball_shared_draft_rooms.sql`
   4. Baseball `scripts/sql/baseball_shared_leagues.sql`

   Billing tables are not needed for these scenarios (the app reads no entitlement for them; Free is fine).
3. Authentication → Providers → Email: enabled. Authentication → URL Configuration → Site URL
   `http://localhost:8611` (the local QA app).
4. Authentication → Users → **Add user** twice, with **Auto Confirm User** ticked (no email needed):
   - `qa.danny@<a domain you control>` — plays Danny (commissioner)
   - `qa.barry@<a domain you control>` — plays Barry (invitee)

   A third account `qa.other@…` is needed for scenario 12 (wrong recipient).

## 2. The local QA app (owner places the secrets; nobody prints them)

In `C:\tmp\bb-invites-dev\.streamlit\secrets.toml` (git-ignored; it does not exist yet):

```toml
[qa]
is_qa_project = true          # the launcher refuses to start without this

[suite_activity]
supabase_url = "<QA project URL>"
supabase_key = "<QA service_role key>"
supabase_anon_key = "<QA anon key>"
suite_auth_enabled = true
suite_auth_redirect_url = "http://localhost:8611"
suite_user_id = "qa_signed_out"
```

Start it with `powershell -File scripts\qa\run_qa_local.ps1` (port 8611). It checks only the `[qa]` marker and
prints no key.

Two independent sessions: one normal browser window (Danny) and one private/incognito window, or a second
browser (Barry). Each signs in with its own QA account.

## 3. Scenarios (record pass/fail, account, time; screenshot any failure)

| # | Who | Do | Expect |
|---|---|---|---|
| 1 | Danny | Live Draft → Shared Draft: create a 2-team room (Danny, Barry), share the room code. Barry joins with the code (scenario 10), both draft to completion. Danny: **Create Shared League** | Green "**League** saved" only; no "on this device only" warning. Read-only check Q2: league stored, origin `live_draft`, Danny's team claimed, Barry's reserved |
| 2 | Danny | Refresh; Saved Draft Library → open the league | The league is there, same rosters |
| 3 | Danny | Library → Invite managers → username shown on Barry's Library page → **Find account** | "Username **…** belongs to an existing Baseball account" and "played team **Barry** in this league's Shared Draft" |
| 4 | Danny | Tick the confirmation → **Send invite** | Invite sent; Q3 shows the invite with an account hash that equals Barry's account hash (Q1) |
| 5 | Barry | Saved Draft Library (already open is fine: wait up to 15 s and interact) | "Shared league invites" with the league; his username caption is shown |
| 6 | Barry | Accept → claim team **Barry** | Success; Q3 shows status accepted, claimed Barry; team Barry owned by Barry's hash; Danny's team unchanged |
| 7 | both | Open the league's Live Draft / room | Both see the same board |
| 8 | both | In a new Shared Draft room (both seated), Danny picks, then Barry | Each pick appears in the other browser; the on-clock team and snake order are right; drafted players leave the pool |
| 9 | both | Refresh; sign out; sign in again | Same leagues, teams, picks; nothing missing or duplicated |
| 10 | Barry | Join a room by typing its code (no invite) | Joins the right room and seat |
| 11 | both | Before 1 and 6, note each account's Active League. After creating / accepting | Active League unchanged for both (Danny may use **Set Active League**) |
| 12 | Other | As `qa.other`: Library, and try the invite id via any path | No invite shown, no league shown; accept refused. Also: Danny sends to an unknown username → refused, nothing stored |

Stop and report on any cross-account read or write, lost pick, lost team claim or a success message for a
save that Q2/Q3 do not show.

## 4. Read-only checks in the QA project

`scripts/qa/qa_shared_draft_checks.sql` (SELECT only): Q1 accounts, Q2 leagues, Q3 invites and team owners,
Q4 rooms. Account ids appear only as 6-character hashes.

## 5. Teardown (owner, after sign-off)

Delete the QA project, or keep it for the next release. Nothing in production is created or changed by
these steps.
