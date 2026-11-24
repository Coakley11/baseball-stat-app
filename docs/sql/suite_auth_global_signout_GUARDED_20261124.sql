-- STEP 3: GUARDED one-time sign-out of every Suite user — PRODUCTION, 2026-11-24.
-- DO NOT RUN without the owner's explicit approval of this operation. One DO block = one transaction:
-- any failed check raises and NOTHING changes.
--
-- Pinned from the 2026-11-24 readiness check: 18 sessions, 4 Auth users, 4 identities, 9 public tables,
-- 0 legacy refresh tokens; refresh_tokens and mfa_amr_claims reference auth.sessions ON DELETE CASCADE.
--
-- Changes (only these):
--   auth.refresh_tokens  rows of the sessions in scope are deleted (15 of them were still usable)
--   auth.mfa_amr_claims  rows of the sessions in scope are deleted (per-session sign-in method records)
--   auth.sessions        every session created before this run is deleted
-- Never changes, and checked by content fingerprint before and after:
--   auth.users (the 4 accounts), auth.identities (the 4 identities), auth.mfa_factors (registered MFA factors),
--   every row of every public table (saved items incl. drafts/leagues/strategies/recordings/compositions,
--   users, settings, activity, app state, resume items, shared rooms/leagues, subscriptions/billing) and the
--   Step 1 evidence snapshot. Writes to the public tables wait for the few seconds this runs (5 s lock timeout).
-- No undo is needed after it commits: people simply sign in again.

do $$
declare
  expected_sessions   constant int := 18;
  allowed_new         constant int := 25;   -- sign-ins between the readiness check and this run
  expected_users      constant int := 4;
  expected_identities constant int := 4;
  expected_pub_tables constant int := 9;
  cutoff              constant timestamptz := now();
  n_scope int; n_tok int; n_tok_usable int; n_legacy int; n_amr int; n_sess int; n_amr_left int;
  fp_users text; fp_ident text; fp_mfa text; fp_public text; fp_evidence text; one text; acc text;
  t record;
begin
  -- lock the application tables against writes (reads continue), so their fingerprint cannot drift mid-run
  perform set_config('lock_timeout', '5s', true);
  for t in select tablename from pg_tables where schemaname = 'public' order by tablename loop
    execute format('lock table public.%I in share mode', t.tablename);
  end loop;

  -- checks
  if (select count(*) from auth.users) <> expected_users then
    raise exception 'refused: % Auth users, expected % (a new account? re-run the readiness check)', (select count(*) from auth.users), expected_users;
  end if;
  if (select count(*) from auth.identities) <> expected_identities then
    raise exception 'refused: % identities, expected %', (select count(*) from auth.identities), expected_identities;
  end if;
  if (select count(*) from pg_tables where schemaname = 'public') <> expected_pub_tables then
    raise exception 'refused: % public tables, expected %', (select count(*) from pg_tables where schemaname = 'public'), expected_pub_tables;
  end if;
  select count(*) into n_scope from auth.sessions where created_at <= cutoff or created_at is null;
  if n_scope < expected_sessions or n_scope > expected_sessions + allowed_new then
    raise exception 'refused: % sessions in scope, expected % (+ up to % new)', n_scope, expected_sessions, allowed_new;
  end if;

  -- fingerprints of everything that must not change
  select md5(coalesce(string_agg(id::text || ':' || coalesce(email, ''), ',' order by id), '')) into fp_users from auth.users;
  select md5(coalesce(string_agg(id::text || ':' || user_id::text || ':' || provider, ',' order by id), '')) into fp_ident from auth.identities;
  if to_regclass('auth.mfa_factors') is not null then
    execute $q$select md5(coalesce(string_agg(md5(f::text), ',' order by f.id), '')) from auth.mfa_factors f$q$ into fp_mfa;
  end if;
  acc := '';
  for t in select tablename from pg_tables where schemaname = 'public' order by tablename loop
    execute format('select %L || '':'' || count(*) || '':'' || md5(coalesce(string_agg(md5(x::text), '','' order by md5(x::text)), '''')) from public.%I x',
                   t.tablename, t.tablename) into one;
    acc := acc || one || ';';
  end loop;
  fp_public := acc;
  if to_regclass('security_audit.suite_sid_bridge_snapshot_20261124') is not null then
    execute $q$select md5(coalesce(string_agg(md5(s::text), ',' order by s.saved_item_id), ''))
               from security_audit.suite_sid_bridge_snapshot_20261124 s$q$ into fp_evidence;
  end if;

  -- the sign-out
  select count(*), count(*) filter (where not revoked) into n_tok, n_tok_usable from auth.refresh_tokens r
   where r.session_id in (select s.id from auth.sessions s where s.created_at <= cutoff or s.created_at is null);
  delete from auth.refresh_tokens r
   where r.session_id in (select s.id from auth.sessions s where s.created_at <= cutoff or s.created_at is null);
  update auth.refresh_tokens set revoked = true, updated_at = now()
   where not revoked and session_id is null and (created_at <= cutoff or created_at is null);
  get diagnostics n_legacy = row_count;
  execute 'delete from auth.mfa_amr_claims where session_id in (select id from auth.sessions where created_at <= $1 or created_at is null)'
    using cutoff;
  get diagnostics n_amr = row_count;
  delete from auth.sessions where created_at <= cutoff or created_at is null;
  get diagnostics n_sess = row_count;

  -- verification: any failure rolls everything back
  if n_sess <> n_scope then
    raise exception 'rolled back: deleted % sessions, scope was %', n_sess, n_scope;
  end if;
  if exists (select 1 from auth.sessions where created_at <= cutoff or created_at is null) then
    raise exception 'rolled back: sessions from before the cutoff remain';
  end if;
  if exists (select 1 from auth.refresh_tokens where not revoked and (created_at <= cutoff or created_at is null)) then
    raise exception 'rolled back: an old refresh token is still usable';
  end if;
  execute 'select count(*) from auth.mfa_amr_claims where session_id not in (select id from auth.sessions)' into n_amr_left;
  if n_amr_left <> 0 then
    raise exception 'rolled back: % MFA claims left without a session', n_amr_left;
  end if;
  if (select md5(coalesce(string_agg(id::text || ':' || coalesce(email, ''), ',' order by id), '')) from auth.users) <> fp_users then
    raise exception 'rolled back: Auth users changed';
  end if;
  if (select md5(coalesce(string_agg(id::text || ':' || user_id::text || ':' || provider, ',' order by id), '')) from auth.identities) <> fp_ident then
    raise exception 'rolled back: identities changed';
  end if;
  if fp_mfa is not null then
    execute $q$select md5(coalesce(string_agg(md5(f::text), ',' order by f.id), '')) from auth.mfa_factors f$q$ into one;
    if one <> fp_mfa then
      raise exception 'rolled back: MFA factors changed';
    end if;
  end if;
  acc := '';
  for t in select tablename from pg_tables where schemaname = 'public' order by tablename loop
    execute format('select %L || '':'' || count(*) || '':'' || md5(coalesce(string_agg(md5(x::text), '','' order by md5(x::text)), '''')) from public.%I x',
                   t.tablename, t.tablename) into one;
    acc := acc || one || ';';
  end loop;
  if acc <> fp_public then
    raise exception 'rolled back: application data changed';
  end if;
  if fp_evidence is not null then
    execute $q$select md5(coalesce(string_agg(md5(s::text), ',' order by s.saved_item_id), ''))
               from security_audit.suite_sid_bridge_snapshot_20261124 s$q$ into one;
    if one <> fp_evidence then
      raise exception 'rolled back: evidence snapshot changed';
    end if;
  end if;

  raise notice 'OK: signed out % sessions; deleted % refresh tokens (% were still usable), % MFA session claims; % legacy tokens revoked; 4 users, 4 identities, MFA factors, all 9 public tables and the evidence unchanged (content fingerprints identical)',
    n_sess, n_tok, n_tok_usable, n_amr, n_legacy;
end $$;

-- Verify afterwards (read-only). Expected: 0 | 0 | 4 | 4 | 0 | 1308 (sessions_now may already be > 0 if
-- someone signed in again after the run; old_sessions_left must be 0).
select (select count(*) from auth.sessions where created_at < now() - interval '1 minute') as old_sessions_left,
       (select count(*) from auth.refresh_tokens where not revoked and created_at < now() - interval '1 minute') as old_usable_refresh_tokens,
       (select count(*) from auth.users) as auth_users,
       (select count(*) from auth.identities) as identities,
       (select count(*) from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session'
          and (valid or payload ? 'refresh_token' or payload ? 'access_token')) as live_link_records,
       (select count(*) from public.suite_saved_items where not (app = '_auth_browser' and item_type = 'browser_session')) as other_saved_items,
       (select count(*) from auth.sessions) as sessions_now;
