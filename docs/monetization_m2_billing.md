# Baseball Monetization M2 — trusted billing architecture

M2 is an architecture checkpoint. Billing defaults to `off`; no credentials, prices, external projects, or real charges are included.

## Trust and identity

The only billing identity is a Supabase-authenticated `auth.users.id`, verified again by the billing service from the bearer token. Email, workspace IDs, browser customer IDs, query parameters, success redirects, and Streamlit session plan values are not billing authority. Anonymous checkout is rejected.

The M1 Free/Pro selector remains available only when the server opts into local/test controls. Production ignores it.

## Data flow

1. Streamlit reads the user's RLS-protected normalized entitlement using their Supabase JWT.
2. An upgrade click sends only `upgrade to Pro` intent and the bearer token to the separate billing service.
3. The service verifies the token, resolves the configured price, finds or creates the server-owned customer mapping, and asks Stripe for Checkout.
4. A successful browser return grants nothing.
5. Stripe sends the exact raw webhook body. The service verifies its signature before JSON parsing or mutation.
6. The event ledger durably claims a PII-minimized fingerprint. Duplicate, active-lease, failed-retry, collision, and out-of-order cases are handled explicitly.
7. The service verifies customer ownership, stores newer subscription state, and projects a provider-independent entitlement.
8. Product pages continue calling the central feature entitlement API and never query Stripe.

## Subscription semantics

- `active` and `trialing`: Pro.
- active with `cancel_at_period_end`: Pro until the trusted provider reports access ended.
- `past_due`: Free, payment problem recorded (fail closed).
- canceled, unpaid, expired, or paused: Free/expired.
- missing, malformed, unavailable, or still-loading trusted state: `ready=False`; premium navigation is preserved behind a neutral loading view, not flashed as a Free paywall.

## Service boundary

Run `baseball_billing_service:app` separately with Uvicorn. It exposes:

- `GET /billing/health` — Boolean/non-secret readiness only.
- `POST /billing/checkout` — verified user and trusted Pro price.
- `POST /billing/portal` — verified owner of an existing customer mapping.
- `POST /billing/webhooks/stripe` — signed raw-body webhook processing.

The Streamlit process needs only the billing service URL and user JWT. Stripe and service-role secrets belong only in the billing service environment.

## Rollout modes

- `off` (default): no purchase action.
- `preview`: pricing visible, Checkout disabled.
- `test`: requires explicit Stripe test mode, `sk_test_` credentials, configured test price, webhook secret, URLs, and Supabase settings.
- `live`: requires an explicit `live` rollout, explicit Stripe live mode, matching live credential, and complete Checkout/webhook configuration. Credentials alone never activate it.

Environment variable names:

- `BASEBALL_BILLING_ROLLOUT`
- `BASEBALL_STRIPE_MODE`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_BASEBALL_PRO_PRICE_ID`
- `BASEBALL_PUBLIC_BASE_URL`
- `BASEBALL_BILLING_SERVICE_URL`
- `BASEBALL_BILLING_SUPABASE_URL`
- `BASEBALL_BILLING_SUPABASE_SERVICE_ROLE_KEY`
- `BASEBALL_BILLING_SUPABASE_ANON_KEY`
- existing fallbacks: `SUITE_SUPABASE_URL`, `SUITE_SUPABASE_ANON_KEY`

Never place secret/service-role values in Streamlit session state, logs, URLs, committed files, or browser configuration.

## Supabase and RLS

Apply `supabase/migrations/20261006_baseball_billing_m2.sql` forward-only. It creates one-to-one customer ownership, subscriptions, derived entitlements, and the webhook ledger. Ordinary authenticated users may select only their own entitlement row. They cannot read customer/subscription/event tables, write projections, alter customer ownership, or invoke trusted mutation functions. Service-role use is confined to the billing service.

## External Stripe/Supabase test acceptance (later)

1. Create a separate Supabase test project or isolated test schema; enable Baseball real-account auth.
2. Apply the M2 migration and verify RLS with two test users: own entitlement readable, other user's row invisible, all client writes rejected.
3. Create a Stripe test product and recurring test price; configure its ID server-side.
4. Configure only test keys and set rollout=`test`, Stripe mode=`test`; start the billing service separately.
5. Register/forward the Stripe test webhook to `/billing/webhooks/stripe` using the endpoint's test signing secret.
6. Sign in as test user A, start Checkout, use a Stripe test payment method, and verify the success redirect alone does not grant Pro before webhook projection.
7. Verify customer mapping uniqueness and active Pro projection; refresh/new session must not flash a Free paywall.
8. Repeat webhook delivery and confirm duplicate success; force a processing failure then retry; send older subscription state and confirm it cannot overwrite newer state.
9. Schedule cancellation and confirm Pro remains through the paid period; deliver cancellation/end state and confirm Free/expired.
10. Exercise payment failure/past-due behavior and the customer portal.
11. Confirm test events are rejected in live mode and live events are rejected in test mode.
12. Review logs and browser/session data for secret leakage. Keep live rollout disabled.

## Production work intentionally deferred

Approve price/currency/tax/refund/trial/past-due policies, provision production Stripe and Supabase resources, deploy the trusted service, configure webhook monitoring/reconciliation, complete security review, perform test acceptance, and require an explicit live-launch approval. M2 does not perform these steps.

## Music concepts reused

The design reuses Music's provider-independent projection, authenticated UUID authority, server-selected price/customer, raw-body signature verification, event claim/lease/retry rules, ordering tuple, restrictive RLS, safe public config status, and disabled-by-default rollout. No code or runtime import points at the Music repository.
