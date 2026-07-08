# Shared League Invite + Trade — Two-Account Manual Smoke Test

**Last updated:** 2026-07-08  
**Deploy target:** `baseball-stat-app` · branch `dev`  
**Prerequisite:** Two distinct workspaces/accounts (e.g. `daniel` + `ariel`, or `daniel` + `coakley11`)

## Automated headless check (run first)

```bash
cd baseball-stat-app
python scripts/smoke_shared_league_invite_trade_manual.py
python -m pytest tests/test_fantasy_league_invites.py tests/test_fantasy_league_invite_trade_e2e.py -q
```

Expected: all `PASS` lines and pytest green.

---

## Manual UI smoke — Account A (Commissioner / Daniel)

Use workspace **`daniel`** (or your commissioner workspace).

### A1. Import and save uploaded league

1. Open **Draft Room** → **Import existing draft**.
2. Upload a completed league CSV (≥2 teams, all players validated).
3. **Save to Saved Drafts** — name it e.g. `Daniel 2026 Home League`.
4. Confirm flash shows **League ID** `league:…`.

**Pass:** Saved Draft Library lists the import as **Uploaded League**.

### A2. Claim commissioner team (if prompted)

1. Open **Saved Draft Library**.
2. If **Claim your team** appears, claim your team (e.g. `Donny`).

**Pass:** Team shows **Claimed by [your account]**.

### A3. Invite second account

1. In Saved Draft Library, expand **Invite managers to this shared league**.
2. Enter invitee workspace slug (e.g. `ariel`).
3. Click **Send invite**.

**Pass:** Success toast; no duplicate-pending error.

### A4. Set Active (required for trades)

1. Click **Set Active** on the saved uploaded league.

**Pass:** Active Draft section shows the league.

---

## Manual UI smoke — Account B (Invitee / Ariel)

Sign in as second account. Use workspace **`ariel`** (or invited workspace).

### B1. See invite banner

1. Open **Saved Draft Library** (no re-upload needed).

**Pass:** Banner: *"You've been invited to join Daniel 2026 Home League…"*

### B2. Accept invite and claim team

1. Choose an **unclaimed** team from dropdown.
2. Click **Accept invite**.

**Pass:**
- League appears in **Saved Drafts** as Uploaded League
- Your claimed team is shown on the card
- **Not** a duplicate import (same league name/content; `league_id` matches commissioner if shown in diagnostics)

### B3. Set Active

1. **Set Active** on the joined league.

**Pass:** Active Draft shows your team context.

---

## Trade smoke — both accounts

### C1. Trades unlock

On **Fantasy Lineup Assistant** (or trade section), each account should **not** see:

> Trades are unavailable for solo mock drafts…  
> Trades unlock after at least two teams are claimed by different accounts.

**Pass:** Trade proposal UI is enabled for both accounts.

### C2. Propose (Account A)

1. Daniel proposes: give **Player A**, receive **Player B** from Team 2.

**Pass:** Outgoing trade shows as pending for Daniel.

### C3. Receive after reload (Account B)

1. **Refresh browser** on Ariel's session (or re-open app).
2. Ensure joined league is still **Set Active**.
3. Open trade / Lineup trade section.

**Pass:** Incoming pending trade visible for Team 2.

### C4. Accept (Account B)

1. Accept the trade.

**Pass:**
- Rosters swap in UI (Daniel has Player B; Ariel has Player A)
- Trade history shows **Accepted**

### C5. Commissioner reload

1. Refresh Daniel's browser with league still **Set Active**.

**Pass:**
- Updated rosters match accepted trade
- Trade history shows same accepted trade
- League activity line present in Trade History

---

## Failure triage

| Symptom | Likely cause |
|---------|----------------|
| No invite banner on B | Wrong workspace; inbox not written; registry slug mismatch |
| Accept fails "team already claimed" | Team taken; pick another unclaimed team |
| Trades still locked | Both teams not claimed by different accounts; league not **Set Active**; not `real_league` |
| B doesn't see pending trade after reload | Active league not set; shared store not synced — run headless smoke |
| Rosters don't swap after accept | Shared store/local context drift — check `data/shared_leagues/league_*.json` |

---

## Developer diagnostics

With **Developer Mode** on, inspect:

- `data/shared_leagues/league_{fingerprint}.json` — `team_ownership`, `trade_proposals`, `league_activity`, `league_invites`
- `data/workspaces/{workspace}/league_invite_inbox.json` — pending invite refs for invitee

Copy shared league JSON when reporting issues.
