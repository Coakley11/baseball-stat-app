# Baseball hosted staging — package and execution plan

Prepared 2026-10-23. Nothing here has been pushed, deployed or configured. Every step below waits for the owner's
authorization. Production resources are never needed: staging uses a QA Supabase project, Stripe test mode and
new Streamlit Cloud apps only.

## 1. What gets staged

| Repo | Branch (local only) | Code | Contents |
|---|---|---|---|
| Baseball | `staging/baseball-release-<tip>` (this branch) | code = `804b3b5` | R4 `0410fc8` + R5 Live Draft fix `dab9bef` + local Full Analysis store fix `c048901` + `800b1c7` + `804b3b5` + this document |
| Command Center | `staging-prep/suite-app-url-overrides` | `392ab9d` | `dev` `3e80fca` + canonical shared links `0e2d1e7` `ee4c921` `f6b21d6` + sync guard `fac586f` + `392ab9d` |

The two commits added on top of `c048901`:

- `800b1c7` **Full analysis: load the local store only when Supabase is not configured.** `c048901` loaded the local
  Command Center store on every send. On a machine with both Supabase configured and an importable local store,
  the context blob then went to SQLite while the Continue card went to Supabase. Every configured-Supabase send is
  now write-for-write what it was before `c048901`: six scenarios were checked, including Supabase configured,
  unconfigured and failing, each with and without a local store. Hosted has no local store, so hosted was never
  affected.
- `804b3b5` **Staging URL support.** Production links are hard-coded. A staging deployment can now point an app's
  base URL at itself with `SUITE_APP_URL_<APP>`, and point Baseball's "← Command Center" link at its own Command
  Center with `SUITE_COMMAND_CENTER_URL`. Both are unset in production, so every production URL stays the same.
  `suite_deep_links.py` stays byte-identical to Command Center's canonical copy (`392ab9d`).

Command Center and Baseball must move together. `suite_deep_links.py` is synced from Command Center. A sync from
`fac586f` (without `392ab9d`) would remove the staging override from Baseball. A sync from `392ab9d` changes no
Baseball file (sandboxed dry run).

## 2. Staging architecture

```
 QA tester ──► Baseball Staging (Streamlit Cloud, branch staging/baseball-release-<tip>)
                 │  ▲         │ Upgrade / Manage subscription
                 │  │         ▼
                 │  │      Billing Service Staging (HTTPS ASGI host: baseball_billing_service:app)
                 │  │         ▲                      │
                 │  │         │ test webhooks        │ service-role writes
                 │  │      Stripe (TEST MODE)        ▼
                 ▼  │                        QA Supabase project (auth + suite tables + subscriptions)
 Command Center Staging (Streamlit Cloud, branch staging/command-center-392ab9d) ──────────▲
```

- **One QA Supabase project** serves auth, the suite tables and `public.subscriptions`. Streamlit reads the
  entitlement with the signed-in user's JWT, so auth and subscriptions must live in the same project.
- **Command Center Staging** is a second new Streamlit app, from the same Command Center code, using the QA
  project. The existing Command Center Dev app keeps its own secrets and is not repointed.
- **The billing service cannot run inside Streamlit Cloud.** It needs its own HTTPS host (owner's choice), with
  the Stripe test webhook endpoint at `/billing/webhooks/stripe`.
- **AMI (Applied Intelligence) has no staging app.** A Full Analysis card opens the production AMI app. Testers
  must not open AMI cards, or any non-Baseball card, from staging. See section 7.

## 3. Secrets and configuration matrix (categories only, never commit values)

### Baseball Staging — Streamlit Cloud Secrets

| Where | Key | Value |
|---|---|---|
| root | `SUITE_APP_URL_BASEBALL` | the Baseball Staging URL |
| root | `SUITE_COMMAND_CENTER_URL` | the Command Center Staging URL |
| `[suite_activity]` | `supabase_url` | QA project URL |
| `[suite_activity]` | `supabase_key` | QA service-role key (server side, as in production) |
| `[suite_activity]` | `supabase_anon_key` | QA anon/publishable key |
| `[suite_activity]` | `suite_auth_enabled` | `true` |
| `[suite_activity]` | `suite_auth_redirect_url` | the Baseball Staging URL (unset, it falls back to the Command Center Dev URL) |
| `[suite_activity]` | `suite_user_id` | an obviously-QA id such as `qa_staging_signed_out` (identity used when signed out) |
| `[baseball_billing]` | `rollout` / `stripe_mode` | `"test"` / `"test"` |
| `[baseball_billing]` | `service_url` | Billing Service Staging URL |
| `[baseball_billing]` | `public_base_url` | the Baseball Staging URL (Checkout/Portal returns) |

Do not set `SUITE_APP_URL_APPLIED_INTELLIGENCE` unless an AMI staging app exists. Root-level secrets reach the code
as environment variables: Streamlit 1.59 loads secrets at server start, before the first script run.

### Billing Service Staging — host environment (server only)

`BASEBALL_BILLING_ROLLOUT=test`, `BASEBALL_STRIPE_MODE=test`, `STRIPE_SECRET_KEY` (`sk_test_…` only),
`STRIPE_WEBHOOK_SECRET` (the staging endpoint's test signing secret), `STRIPE_BASEBALL_PRO_TEST_PRICE_ID` (the
sandbox price in `docs/BASEBALL_BILLING_SETUP.md`), `BASEBALL_PUBLIC_BASE_URL` (Baseball Staging URL),
`BASEBALL_BILLING_SUPABASE_URL`, `BASEBALL_BILLING_SUPABASE_ANON_KEY` and `BASEBALL_BILLING_SUPABASE_SECRET_KEY`
(all QA). Never set `STRIPE_BASEBALL_PRO_LIVE_PRICE_ID`, an `sk_live_` key, or `rollout`/`stripe_mode` = `live`.

### Command Center Staging — Streamlit Cloud Secrets

| Where | Key | Value |
|---|---|---|
| root | `SUITE_APP_URL_BASEBALL` | the Baseball Staging URL |
| `[suite_activity]` | `supabase_url`, `supabase_key`, `supabase_anon_key` | the same QA project |
| `[suite_activity]` | `suite_auth_enabled`, `suite_auth_redirect_url` | `true`, the Command Center Staging URL |

### QA Supabase project — one-time setup

1. Create a new project. Never reuse or copy the production project's data or customer workspaces.
2. Apply Command Center's `supabase/migrations/001_suite_activity.sql`, `002_suite_account_memory.sql` and
   `003_suite_account_memory_resume.sql`.
3. Apply Baseball's `scripts/sql/baseball_shared_draft_rooms.sql` and `scripts/sql/baseball_shared_leagues.sql`.
4. Create `public.subscriptions`, its RLS ownership policy and the signup trigger as a **schema-only** copy of the
   existing project. Neither repo contains their DDL; the billing migration assumes they exist and fails closed
   without them.
5. Run `supabase/preflight/baseball_billing_preflight.sql`, apply `supabase/migrations/20261008_baseball_billing_runtime.sql`,
   then re-run the preflight. Row counts must be unchanged and the six runtime objects present.
6. Auth → URL configuration: set the Site URL to Baseball Staging. Add the Redirect URLs Baseball Staging and
   Command Center Staging, including their `?suite_auth_landing=recovery` forms. Use the recovery template from
   Command Center's `docs/SUPABASE_RECOVERY_EMAIL_TEMPLATE.md`.
7. Create QA accounts A and B, with test mailboxes you control.

### Stripe — test mode only

Use the existing test Product/Price, enable the test Billing Portal, and create a test webhook endpoint at
`https://<billing service>/billing/webhooks/stripe`. Subscribe it to `checkout.session.completed`,
`customer.subscription.created|updated|deleted`, `invoice.paid` and `invoice.payment_failed`.

## 4. Execution sequence (each step needs authorization)

1. **Command Center integration.** From the clean review worktree, never Daniel's working tree, which has `dev`
   checked out with 41 uncommitted changes:
   ```powershell
   cd C:\Users\danie\Documents\GitHub\cc-staging-prep
   git fetch origin
   git merge-base --is-ancestor origin/dev 392ab9d; $LASTEXITCODE   # 0 = still a fast-forward
   python -m pytest -q -p no:cacheprovider --continue-on-collection-errors tests
   #   expect 43 failed / 354 passed / 3 errors — the same failures as 3e80fca (pre-existing)
   git push origin 392ab9d:refs/heads/dev                              # fast-forward only; deploys the CC Dev app
   git push origin 392ab9d:refs/heads/staging/command-center-392ab9d   # frozen branch for CC Staging
   ```
   Then smoke the Command Center Dev app: Continue cards open, and Baseball links unchanged with no override set.
   Daniel's local `dev` later catches up with `git pull --ff-only`. None of his uncommitted files are among the 8
   incoming ones. `main` (Command Center production, `16dbb18`) is not touched.
2. **Baseball staging branch.**
   ```powershell
   cd C:\Users\danie\Documents\GitHub\baseball-staging-prep
   git fetch origin
   git push origin staging/baseball-release-<tip>:refs/heads/staging/baseball-release-<tip>
   git rev-parse --short origin/dev    # must still be 763001b — dev is production and is not moved
   ```
3. **Hosted resources.** Create the QA Supabase project (section 3). Deploy Billing Service Staging. Create the
   Stripe test webhook. Create the two Streamlit apps: Baseball Staging (`Coakley11/baseball-stat-app`, branch
   `staging/baseball-release-<tip>`, `streamlit_app.py`) and Command Center Staging (`Coakley11/daniel-ai-command-center`,
   branch `staging/command-center-392ab9d`, `ai_command_center.py`). Use the same Python version as each
   production app. Paste the secrets once the URLs are known, then reboot both apps.
4. Supabase acceptance (section 5.1).
5. Command Center ↔ Baseball round trip (section 5.3).
6. Hosted Live Draft (section 5.4).
7. Stripe sandbox (section 5.2).
8. Evaluate results against the stop conditions (section 6).
9. Decide Free/Pro enforcement. `ENFORCED_PAGE_FEATURES` and `ENFORCED_FEATURES` stay empty until then.
10. Only then consider moving Baseball `dev`: fast-forward `origin/dev` `763001b` to the accepted SHA. That deploys
    production.

## 5. Acceptance checklists

Record for every row: pass/fail, account, browser/device, time, and a screenshot of any failure. Run phone rows at
390 px (or a real phone) and desktop rows at 1280 px.

### 5.1 Supabase hosted acceptance (accounts A and B)

**Authentication**
- [ ] Sign up A (and B) if sign-up is enabled; confirm the email arrives and the link lands on Baseball Staging, not production.
- [ ] A signs in; the account panel shows A; `public.subscriptions` has one Free/inactive row for A, created by the trigger.
- [ ] A signs out → signed-out state; protected account data is not shown.
- [ ] A signs in again → same workspaces as before.
- [ ] Session refresh: leave A idle past the access-token lifetime (or force a refresh), then act → still A, with no silent sign-out mid-action.
- [ ] Browser refresh (F5) on Home, a league page and Live Draft → still A, same page and state.
- [ ] Password reset email → link lands on Baseball Staging with `suite_auth_landing=recovery`, and the reset works.

**Isolation**
- [ ] A creates workspace/league "QA-A"; B creates "QA-B".
- [ ] A sees only QA-A; B sees only QA-B (workspace picker, Home cards, Command Center Staging cards).
- [ ] Copy a deep link from A (`?suite_workspace=…&suite_resume=…`) and open it signed in as B → B does not see A's data or workspace (expect B's own workspace or a refusal, never A's).
- [ ] Open the same link signed out → no A data.
- [ ] Command Center Staging signed in as B shows no A cards.

**Persistence**
- [ ] A creates and saves a QA league → refresh → reopen → identical.
- [ ] A opens the same league in a second browser (or a private window signed in as A) → identical.
- [ ] Lineup save → refresh and second browser show the saved lineup.
- [ ] Trade proposal / waiver claim, where the league supports it → survives refresh and second browser.
- [ ] Finalize a week → finalized state persists after refresh, a second browser and sign-out/in.

**Failure safety** (with a controlled outage: temporarily revoke the QA key in staging secrets, or block the QA
project's REST host in the test browser's network tools; restore afterwards)
- [ ] Failed cloud read on open → the app says it could not load and does **not** offer to save over the cloud state.
- [ ] Failed cloud write (Save during the outage) → a clear failure plus Retry; nothing claims success.
- [ ] Restore → Retry saves exactly once (no duplicate rows or cards).
- [ ] Stale browser: open the league in browser 1, change and save it in browser 2, then save from browser 1 → browser 1 does not silently overwrite the newer state (newer wins or a conflict is shown).
- [ ] Second session: two sessions of A edit different things → neither destroys the other's saved state.
- [ ] Full Analysis during the outage → "could not save" with Retry; after restore, Retry saves once and the card appears once in Command Center Staging.

### 5.2 Stripe sandbox (test mode, enforcement off)

- [ ] A starts Free: the account shows Free, and every page is still usable (nothing is enforced).
- [ ] Upgrade → a Stripe Checkout page in **test mode** (test banner) with the expected test price and amount.
- [ ] Pay with `4242 4242 4242 4242` → return to Baseball Staging `public_base_url` → Pro appears only after the webhook (refresh if needed).
- [ ] Cancel from Checkout → return to Baseball Staging; still Free.
- [ ] Return-URL forgery: open the success URL by hand (no payment) as B → B stays Free.
- [ ] The billing service log shows `checkout.session.completed` and `customer.subscription.created`; the Stripe dashboard shows 2xx deliveries.
- [ ] Duplicate: resend the same event from the Stripe dashboard → 2xx, with no duplicate state change or second subscription row.
- [ ] Retry: stop the billing service briefly (or return 5xx), let Stripe retry, restore → the event is applied once.
- [ ] Out of order: replay an older `customer.subscription.updated` after a newer one → it does not resurrect or downgrade access (`test_out_of_order_event_cannot_resurrect_or_downgrade_access`).
- [ ] Manage Subscription → the test Billing Portal opens for A only. B without a customer gets no portal.
- [ ] Cancel at period end in the Portal → still Pro until Stripe reports the end; then (test clock or immediate cancel) Free.
- [ ] Payment failure (`4000 0000 0000 0341`, or a test-clock renewal) → past_due does not grant Pro.
- [ ] Sign out and in after each entitlement change → the state shown matches `public.subscriptions`.
- [ ] Nothing anywhere shows a live key, live price or live-mode banner.

### 5.3 Command Center ↔ Baseball staging round trip

Before starting, open Command Center Staging and hover every Baseball card. Each must point at the **Baseball
Staging** host. If one points at `baseball-stat-app-d4jlymjc4iptaadc3kquwx`, stop: the override is not set.

- [ ] Historical: pick a stat and year range in Historical Explorer → Get full analysis → Command Center Staging shows "Continue historical analysis" (stat · years) → Continue → Baseball Staging opens Historical Explorer with the same stat and years.
- [ ] Hall of Fame: open a player's case → Full analysis → card → Continue → Career Totals with the same target player (not a different player).
- [ ] Draft Lab: run a Draft Lab analysis → card → Continue → Draft Lab / Simulation with the same room/mode. A refresh after that loses the room analysis (known, section 7).
- [ ] Generic Ask AMI on a Baseball page → the Continue card back to Baseball keeps the question and page context. Do **not** open the Applied Intelligence card: it goes to the production AMI app.
- [ ] Baseball Staging's "← Command Center" link → Command Center Staging, not the Dev or production Command Center.
- [ ] Repeat Historical and Hall of Fame on a phone.

### 5.4 Hosted Live Draft (Solo)

- [ ] Cold start: reboot Baseball Staging, then open Live Draft directly → the page renders with no error.
- [ ] Start a new Solo Live Draft → Ready → **Start Draft enables** (locally 14–22 s on a cold server; allow up to a minute on Cloud) → the room goes live.
- [ ] Make several picks (at least 3 user picks, with the CPU picks between them).
- [ ] **Phone (390) refresh mid-draft** → the same room returns with the picks preserved. This is the outstanding check.
  Locally (no Supabase), a refresh after a pick does **not** resume the room at 390 or 1280. The accepted baseline
  `56820e6` behaves the same, so this isn't new. The pick is kept in the saved workspace state, but the page offers
  a fresh setup instead. If hosted behaves the same, record it as a release decision for the `dev` move: a Solo
  draft can't be resumed after a refresh.
- [ ] Navigate away (Home) and back → the same room and picks.
- [ ] Close the tab, reopen Live Draft as the same account → the room can be recovered or resumed.
- [ ] Desktop 1280: the same flow once.
- [ ] Optional, with Cloud logs: no `StreamlitDuplicateElementKey` or `main_sidebar_page` errors in the app logs.

## 6. Stop conditions

Stop staging and report if any of these happen:

- data loss or corruption;
- a cross-account read or write;
- a destructive overwrite after a failed read;
- Pro granted without a webhook-backed entitlement;
- any production URL, key or database used by staging;
- a broken primary workflow or a first-load exception;
- a Live Draft room lost without a refresh (start, picks, away and back).

A room that isn't resumed after a browser refresh is pre-existing. Record it and continue (see 5.4).

## 7. Known non-blockers and limits

- Draft Lab: refresh after a Continue loses the room analysis.
- Phone: Back after a Home-card jump can stay on Draft Lab.
- Solo refresh does not resume the room (before or after picks), locally and on the accepted baseline. Hosted
  confirmation is in 5.4. This is the one item that may matter for the `dev` move.
- Diagnostic query flags are developer probes and not on any normal path. A hand-typed `?solo_p8_focused_binding=1`
  still imports `streamlit_app` (`live_draft_solo_p8_focused_binding.py:66`) and shows an error box on Live Draft.
  `?solo_rv_ladder=…` shows no error. A two-line fix (use `running_app_module()`) is available if wanted.
- The real local Command Center DB holds old test-fixture rows (test identities only). Left untouched; it is not used by hosted staging.
- No AMI staging app: AMI cards from staging open production AMI. Don't open them during staging.
