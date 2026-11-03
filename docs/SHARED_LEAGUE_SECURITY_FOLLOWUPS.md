# Shared League security: open follow-ups (2026-11-02)

These are left over from the Shared League security release (`fix/shared-league-authz`). None of them weakens that release's checks; each one needs its own decision.

## 1. Invite matcher inconsistency
`fantasy_league_invites._invite_matches_user` is looser than the strict league matcher (`fantasy_shared_league_startup_sync._record_matches_account`):
- it accepts the fallback workspace `daniel`;
- it compares against ids from `suite_user` / `suite_workspace` helpers, which can fall back to the deployment's configured account.

**Contained by this release:** with sign-in on, the inbox, accept and decline also require the strict member/invitee check against the stored league (`_strict_invitee_of`), and every league write requires it on the server.

**Follow-up:** align `_invite_matches_user` itself with the strict rules. Invites addressed only to the `daniel` workspace would then need a real account id or name.

## 2. Roster edits by members are not limited to their own team
Members change rosters only through the app's trade and claim flows. The server checks membership and protects the commissioner fields, but not per-team roster ownership.

## 3. Lower-risk items from the review
- **Live-room saves:** these don't re-check the commissioner on the server. Resume and Auto Pick are checked.
- **Replace saved draft:** this can delete a Library entry. It is reachable only together with the logout leftovers.
- **Trade accept:** this goes ahead when its check fails. It is not reachable through the app, and the local-league case needs review first.
- **Logout leftovers:** session data remains after logout. Fixed by Stage B, which ships separately.

## 4. Behaviour kept as deployed, for the clean-up decision
- **Unauthorized copies stay stored:** existing copies of a Shared League that an account may not see are hidden and no longer refreshed, but stored as they are. Whether to remove them is the owner's decision after the read-only exposure audit.
- **Copies of a league that no longer exists:** these still follow the existing Library clean-up rules, unchanged.
- **Migration scan time:** the account-wide legacy-migration "last scanned" time is re-stamped on Library visits. It is not part of any league copy.
- **Sign-in off:** with sign-in off, the app has one configured account and nothing is hidden. The hosted app has sign-in on.
