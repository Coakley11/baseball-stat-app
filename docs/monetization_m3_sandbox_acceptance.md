# Baseball billing M3 — deterministic sandbox acceptance matrix

This runbook is for a later Stripe/Supabase **test** environment. Never paste credentials into chat or commit them. Production rollout remains `off` throughout.

Record for every check: UTC time, actor/test user, expected result, actual result, Stripe event ID where applicable, and a redacted database row identifier. Never record access tokens, full payloads, payment details, or secret values.

## A. Deterministic automated checks

1. Check out the accepted M3 SHA in an isolated worktree; confirm a clean status.
2. Run `python -m pytest -p no:cacheprovider tests/test_baseball_monetization.py tests/test_baseball_monetization_apptest.py tests/test_baseball_billing_m2.py tests/test_baseball_billing_m3_hardening.py -q`.
3. Confirm customer ownership tests reject empty, unknown, metadata-only, and conflicting mappings.
4. Confirm duplicate customer and Checkout requests reuse stable server idempotency keys.
5. Confirm two claims produce `new` then `in_progress`; expire the lease and confirm `retry` with a different token.
6. Confirm the old worker token cannot complete/fail a reclaimed event; confirm the new token can.
7. Confirm same-ID/same-fingerprint is duplicate and same-ID/different-fingerprint is collision without projection.
8. Confirm older and equal-time/lower-ID events cannot overwrite newer subscription or entitlement state.
9. Confirm test/live mismatches fail before the ledger claim.
10. Confirm declared and actual bodies over 1,000,000 bytes return 413, while a normally sized signed body succeeds.
11. Inject recognizable fake secret strings and confirm public readiness/errors contain none.
12. Confirm off/preview/test/live and URL/role-confusion matrices fail closed.

## B. Supabase migration and RLS checks

13. Create an isolated Supabase test project; create authenticated users A and B.
14. Apply M2 migration `20261006_baseball_billing_m2.sql`, then M3 migration `20261007_baseball_billing_m3_hardening.sql` in order.
15. With user A JWT, confirm A can select only A's `billing_entitlements` row and cannot see B's row.
16. With user B JWT, repeat symmetrically.
17. As anon and each authenticated user, confirm insert/update/delete fail on customers, subscriptions, entitlements, and webhook events.
18. Confirm authenticated/anon roles cannot execute claim, finish, subscription-apply, or entitlement-save functions.
19. Through the service-role test harness only, create a customer mapping and confirm uniqueness blocks a second customer for A and blocks assigning the same customer to B.
20. Claim an event through the service role and inspect only safe fields: ID/type/mode/timestamps/status/fingerprint/attempt/collision/lease metadata. Confirm no payload, email, token, or secret is stored.

## C. Stripe CLI and test-webhook checks

21. Create one Stripe test product and recurring test price; set its ID only in trusted service configuration.
22. Configure the test webhook endpoint/signing secret and start the billing service with rollout=`test`, Stripe mode=`test`.
23. Query `/billing/health`; verify Boolean readiness and mode only, with no key fragments, headers, or tokens.
24. Forward Stripe CLI test events to `/billing/webhooks/stripe`; verify valid signatures succeed and malformed signatures fail without ledger mutation.
25. Replay the identical signed event; verify `duplicate`, unchanged projection, and no second side effect.
26. Use the deterministic harness to present the same event ID with a changed verified body; verify `collision`, incremented safe collision counter, unchanged original fingerprint/projection.
27. Simulate a claimed event whose worker stops; after the five-minute lease, redeliver and verify reclaim plus successful processing.
28. Deliver a newer cancellation/payment state followed by an older active state; verify no resurrection. Repeat with equal `created` timestamps and deterministic event-ID ordering.
29. Send a live-mode-shaped event to test configuration and a test event to an isolated live-readiness configuration; both must be rejected before claim. Do not contact live Stripe.

## D. Browser and Checkout/portal checks

30. Start Baseball and the trusted billing service locally using HTTPS endpoints or explicit loopback HTTP allowed only in test mode.
31. As anonymous user, confirm pricing explains sign-in and creates no Checkout/customer.
32. Sign in as user A; confirm Free state, then initiate Checkout twice quickly. Verify one mapped Stripe customer and idempotent Checkout behavior; inspect the service request to confirm no browser price/customer/plan grant.
33. Complete Stripe test Checkout with a documented Stripe test payment method. Before webhook projection, confirm the success redirect alone leaves entitlement unchanged/unready.
34. Process the signed subscription webhook; confirm A becomes Pro, premium gates unlock, and refresh/fresh session remains Pro without a Free-paywall flash.
35. Open the customer portal as A and confirm it targets A's mapped customer. As B, confirm no access to A's portal/customer/billing rows.
36. Schedule cancellation at period end; confirm `canceled_period_end` and continued Pro through the paid period.
37. Deliver final cancellation/end state; confirm Free/expired and retained product data. Deliver payment failure/past-due and confirm documented fail-closed behavior.
38. Refresh during delayed entitlement reads; confirm the neutral membership-loading boundary preserves navigation and premium state remains uninitialized until ready.

## E. Final safety gate

39. Audit service/Streamlit logs, browser storage, URLs, readiness JSON, database audit rows, and test artifacts for secrets, bearer tokens, emails, raw webhook bodies, or payment details.
40. Run representative Live Draft regressions and confirm no billing state appears in draft room/participant/timer data.
41. Confirm `BASEBALL_BILLING_ROLLOUT` remains `test` or `off`, no live endpoints were contacted, no real charge occurred, and no credential/runtime artifact is staged.
42. Stop. Record sandbox results for review; do not enable production or merge without separate approval.

## Pass criteria

Every step must pass or have a recorded, reproducible blocker. Any ownership ambiguity, secret disclosure, RLS write path, wrong-mode projection, stale-event overwrite, false-Free flash, or real/live Stripe contact is a release blocker.
