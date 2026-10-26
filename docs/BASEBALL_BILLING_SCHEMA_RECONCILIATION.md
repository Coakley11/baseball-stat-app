# Baseball Supabase schema reconciliation

Reconciled against the manually established live schema supplied for review on
2026-10-08. This is a local comparison only; no live Supabase connection or SQL
mutation was performed.

## Existing objects that remain authoritative and unchanged

`public.subscriptions` already supplies every application column:

- `user_id uuid` primary key referencing `auth.users(id)` with cascade delete
- `plan text not null default 'free'`
- `status text not null default 'inactive'`
- unique nullable `stripe_customer_id` and `stripe_subscription_id`
- nullable `current_period_end timestamptz`
- `created_at` and `updated_at`
- `free`/`pro` and documented status constraints

The existing RLS ownership policy and the new-user trigger are also retained.
The billing runtime migration contains no DDL for this table or trigger and no
data migration/backfill.

## Missing runtime objects added by the migration

- `private.baseball_billing_webhook_events` for signature-verified event claims,
  retry leases, duplicate detection, and collision audit.
- `private.baseball_billing_subscription_versions` for per-user event ordering.
- Four `public` RPC entry points executable only by `service_role`:
  customer attachment, event claim, subscription projection, and event finish.

The tables are kept in the non-exposed `private` schema. The RPC functions use a
pinned empty `search_path`, fully qualified object names, and revoked
anon/authenticated execution.

## Required live preconditions

Run `supabase/preflight/baseball_billing_preflight.sql` first. Do not run the
migration unless it confirms:

- all eight documented columns and expected constraints are present;
- RLS is enabled;
- authenticated has SELECT and no authenticated/public write policy exists;
- table grants are recorded (RLS may deny writes even when default grants remain);
- an authenticated SELECT policy binds `auth.uid()` to `user_id`;
- the existing `auth.users` trigger function inserts the Free/inactive row;
- baseline subscription/test-user row counts are recorded.

`20261008_baseball_billing_runtime.sql` repeats the column/RLS/grant/policy
checks and aborts before creating anything if they fail. Independently test with
real user JWTs that anon cannot read, users cannot write, and each user can read
only their own row. After applying it,
re-run the preflight: baseline subscription counts must be unchanged, while the
two private tables and four RPC functions must be present.
