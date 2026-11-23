# Membership cache review (E0) — before any Pro restriction is switched on

**Question (owner, 2026-11-23):** can E0's 60-second membership cache keep Pro access alive after a
cancellation, expiration or other entitlement change?

## How the cache works (E0, Dev `3da29bd`)

- `run_entitlement` resolves membership server-side (billing database) and caches the answer **in
  the user's own Streamlit session**, keyed by the signed-in user id, for 60 seconds.
- A different account, sign-in or sign-out re-resolves at once (verified in QA: Pro → sign out →
  Free; Pro account → other account on the same browser → Free).
- An answer that is not ready (billing unreachable, still loading) is never cached; enforced features
  then wait ("Checking your membership…") — they are never granted by default.
- A return from Stripe (`?billing=…`) re-resolves; any new page load starts a new session with an
  empty cache.
- Nothing the browser sends can set or extend the cache.

## The window

| Change on the billing side | What an already-open session sees |
|---|---|
| Subscription **canceled at period end** | Pro until the paid period ends — by design, not the cache |
| Period ends / **expired** / `subscription.deleted` | Pro for **at most 60 s** more, then Free |
| Renewal **fails → past due** | Pro for **at most 60 s** more, then paused |
| Refund / admin revoke | at most 60 s |
| **Upgrade** | Free for at most 60 s, but the Checkout return (`?billing=`) refreshes at once |

So the only exposure is: a user whose Pro just ended keeps Pro for up to one minute, in a tab they
already had open. Their data is theirs, no other account is affected, and new tabs see the change
immediately.

## Recommendation before enforcement is switched on

1. **Keep the 60 s cache for labels and reads** (page renders, Pro notes, AMI answers): it avoids a
   billing query on every rerun, and the exposure is a minute of read access.
2. **Use a fresh check for operations that create or change Pro data or start expensive Pro work** —
   saving a strategy, saving back from a draft, running a Draft Lab simulation, grading a Live draft,
   Simulate Draft Pick. Add `require(..., fresh=True)` (bypasses the cache, one billing read, then
   updates the cache). This closes the window where it matters most.
3. **Add "Refresh subscription status"** on the account panel (calls `refresh_entitlement`) for
   support cases.
4. Optional later: shorten the TTL to 30 s, or store a `membership_version` that the billing webhook
   bumps so a cached answer is discarded as soon as the subscription row changes.

None of this changes current behaviour: enforcement is off, so the cache only drives labels today.
Item 2 is planned for the first activation step and is included in the E2 branch design.
