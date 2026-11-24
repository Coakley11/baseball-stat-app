-- GUARDED one-time sign-out of every Suite user (all apps on this Supabase project). DRAFT, 2026-11-24.
-- DO NOT RUN without the owner's explicit approval of this specific operation.
--
-- What it changes, in one transaction:
--   * auth.refresh_tokens: every refresh token issued before this run is deleted (session tokens) or marked
--     revoked (legacy tokens without a session), so no existing sign-in can be renewed.
--   * auth.sessions (and auth.mfa_amr_claims for those sessions): every session created before this run is
--     deleted, so access tokens that name one of them are no longer accepted by the Auth server.
-- What it never changes: auth.users, auth.identities, and every table in the public schema (songs, recordings,
-- leagues, drafts, strategies, subscriptions, billing). It fingerprints all of them before and after and rolls
-- everything back if any differs, if any old session or usable old refresh token remains, or if the number
-- of sessions does not match the readiness query.
-- Run suite_auth_signout_readiness_READONLY.sql first and copy its 'Auth sessions to sign out' value below.
-- There is no undo after it commits: users simply sign in again. Nothing else needs restoring.

do $$
declare
  expected_sessions constant int := -1;   -- SET from the readiness query before running
  allowed_new       constant int := 25;   -- sign-ins that may happen between the readiness query and this run
  cutoff            constant timestamptz := now();
  n_scope int; n_tok_deleted int; n_tok_revoked int; n_amr int := 0; n_sessions int;
  users_before bigint; ident_before bigint; public_before text; public_after text;
  t record;
begin
  if expected_sessions < 0 then
    raise exception 'refusing: set expected_sessions from suite_auth_signout_readiness_READONLY.sql';
  end if;
  if not (has_table_privilege(current_user, 'auth.sessions', 'DELETE')
          and has_table_privilege(current_user, 'auth.refresh_tokens', 'DELETE')
          and has_table_privilege(current_user, 'auth.refresh_tokens', 'UPDATE')) then
    raise exception 'refusing: % may not delete Auth sessions or refresh tokens here', current_user;
  end if;

  select count(*) into n_scope from auth.sessions where created_at <= cutoff or created_at is null;
  if n_scope < expected_sessions or n_scope > expected_sessions + allowed_new then
    raise exception 'refusing: % sessions in scope, expected % (+ up to % new)', n_scope, expected_sessions, allowed_new;
  end if;

  -- fingerprints of everything that must not change
  select count(*) into users_before from auth.users;
  select count(*) into ident_before from auth.identities;
  public_before := '';
  for t in select tablename from pg_tables where schemaname = 'public' order by tablename loop
    execute format('select %L || '':'' || count(*) || '':'' || md5(coalesce(string_agg(md5(x::text), '','' order by md5(x::text)), '''')) from public.%I x',
                   t.tablename, t.tablename) into public_after;
    public_before := public_before || public_after || ';';
  end loop;

  -- 1. refresh tokens: delete those that belong to a session in scope, revoke legacy ones without a session
  delete from auth.refresh_tokens r
   where r.session_id in (select s.id from auth.sessions s where s.created_at <= cutoff or s.created_at is null);
  get diagnostics n_tok_deleted = row_count;
  update auth.refresh_tokens set revoked = true, updated_at = now()
   where not revoked and session_id is null and (created_at <= cutoff or created_at is null);
  get diagnostics n_tok_revoked = row_count;
  -- 2. MFA claims of those sessions (normally removed by cascade; explicit so a non-cascading key cannot block)
  if to_regclass('auth.mfa_amr_claims') is not null then
    execute 'delete from auth.mfa_amr_claims where session_id in (select id from auth.sessions where created_at <= $1 or created_at is null)'
      using cutoff;
    get diagnostics n_amr = row_count;
  end if;
  -- 3. the sessions
  delete from auth.sessions where created_at <= cutoff or created_at is null;
  get diagnostics n_sessions = row_count;

  -- verification: any failure raises, which rolls back every statement above
  if exists (select 1 from auth.sessions where created_at <= cutoff or created_at is null) then
    raise exception 'rolled back: sessions from before the cutoff remain';
  end if;
  if exists (select 1 from auth.refresh_tokens where not revoked and (created_at <= cutoff or created_at is null)) then
    raise exception 'rolled back: an old refresh token is still usable';
  end if;
  if (select count(*) from auth.users) <> users_before or (select count(*) from auth.identities) <> ident_before then
    raise exception 'rolled back: Auth users or identities changed';
  end if;
  public_after := '';
  for t in select tablename from pg_tables where schemaname = 'public' order by tablename loop
    declare one text;
    begin
      execute format('select %L || '':'' || count(*) || '':'' || md5(coalesce(string_agg(md5(x::text), '','' order by md5(x::text)), '''')) from public.%I x',
                     t.tablename, t.tablename) into one;
      public_after := public_after || one || ';';
    end;
  end loop;
  if public_after <> public_before then
    raise exception 'rolled back: application data changed';
  end if;

  raise notice 'signed out: % sessions deleted, % session refresh tokens deleted, % legacy tokens revoked, % MFA claims removed; users, identities and all public tables unchanged',
    n_sessions, n_tok_deleted, n_tok_revoked, n_amr;
end $$;

-- After it commits, run this (read-only) and keep the result:
select (select count(*) from auth.sessions where created_at < now() - interval '1 minute') as old_sessions_left,
       (select count(*) from auth.refresh_tokens where not revoked and created_at < now() - interval '1 minute') as old_usable_refresh_tokens,
       (select count(*) from auth.users) as auth_users;
