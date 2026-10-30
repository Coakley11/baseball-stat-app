# Plaintext sign-in tokens in `suite_saved_items`: incident-response recommendation

Status: recommendation only. Nothing here has been run. Every action that changes Auth state needs the owner's separate approval: revoking sessions, changing Auth settings, rotating keys. **Sessions are never deleted and users never invalidated without that approval.**

## What is exposed

- Every suite app stores each signed-in browser's Supabase `access_token` and `refresh_token` **in plain text**, in `suite_saved_items.payload`, on rows with `app = '_auth_browser'` and `item_type = 'browser_session'`.
  - Written by `save_browser_auth_session(_versioned)` and `enrich_bridge_payload`.
  - Read back by `load_browser_auth_session` to restore a sign-in after a refresh. Streamlit has no server cookie; the URL carries only an opaque session id.
- While the table had RLS off with anon SELECT, anyone holding the anon key could read them.
- **Refresh token.** Renews a session indefinitely until revoked, so this is the real risk.
- **Access token.** Valid until it expires (the project's JWT expiry, 1 hour by default). While valid it can call Supabase Auth as that user, including **changing the user's password or email**, unless the project requires reauthentication for those changes.

## Order of operations

### 1. Contain first

Run Step 1 of `SUITE_RLS_CONTAINMENT.md`. Revoking sessions before containment would be pointless: the next sign-in would write fresh tokens into the same readable table.

### 2. Read-only assessment, immediately after

Run `docs/sql/suite_auth_token_exposure_readonly.sql`. It returns aggregates only: no token, email, user id or individual IP.

| Query | What it shows | What to look for |
|---|---|---|
| T1 | How many stored browser sessions hold tokens, how many accounts, how old | — |
| T2 | How many live sessions and unrevoked refresh tokens exist | The size of the revocation |
| T3 | Sessions grouped by user agent and by /16 network | Every suite app refreshes server-side, so normal sessions show the server's client library and cloud networks. Anything else needs a closer look. |
| T4 | Auth actions over 90 days | `user_updated_password`, `user_modified` or `token_revoked` spikes (a burst of `token_revoked` points to refresh-token reuse) |

- Also run the Logs Explorer query in `SUITE_RLS_CONTAINMENT.md` for anon requests to `/rest/v1/suite_saved_items`.
- Neither check is needed before containment or before revocation. They decide whether more than revocation is needed.

### 3. Revoke refresh tokens (separate approval, Dev first)

**Rehearse on Dev first.** Use one isolated test account: sign it in on a suite app, revoke its sessions with the chosen option below, then check:
- the app shows the sign-in screen cleanly;
- no restore loop and no lost local work;
- signing in again works.

The current restore path should behave this way: a failed `set_session` is caught, recorded and leaves the session signed out. The rehearsal is what proves it.

**Revocation goes through Supabase's supported Auth interfaces only.** Per the owner's 2026-10-30 instruction, nothing writes directly to the managed `auth` schema. The earlier "mark refresh tokens revoked with SQL" option is withdrawn.

- **Global sign-out** is Supabase's supported mechanism: `POST /auth/v1/logout?scope=global`, which is `auth.sign_out(scope="global")` in the client libraries.
  - It ends every session of that user, so every refresh token stops working.
  - Endpoints that check the session (`/auth/v1/user`, and with it password and email changes) refuse that user's access tokens at once.
  - JWT-only checks (PostgREST) accept them until expiry.
  - Supabase Auth removes the user's session records itself. That is the supported behaviour, and it's why this needs separate approval.
- **The procedure** is prepared separately and verified against Supabase's current documentation before use, with a Dev rehearsal on a test account. It needs a way to call it for each affected account. Options to evaluate:
  - each user signs out of all devices;
  - an admin call, if the current Admin API offers one per user id;
  - a coordinated rotation of the signing key, which alone ends access tokens but **not** refresh tokens.
- **Scope.** All accounts with a stored browser session (T1). Users sign in again once.
- **Leave the stored rows alone.** Don't change or delete the `suite_saved_items` token rows: once revoked they're useless, and the apps overwrite them on the next sign-in. Clearing them is part of the long-term change below.

### 4. Access tokens already issued

- **They expire on their own.** Containment stops new theft, so any token taken earlier is dead within the project's **JWT expiry** of containment (check Dashboard → Authentication → JWT expiry; 1 hour by default).
- **Close the password and email route.** Turn on reauthentication for password changes and keep secure email change on (Dashboard → Authentication → Providers / Security). A stolen access token then can't take over an account permanently. Settings change, so separate approval.
- **Signing-key rotation** kills access tokens immediately. Recommended only if T4 or the logs show misuse, and only after checking which key system the project uses (Dashboard → Settings → JWT Keys).
  - **New asymmetric signing keys:** rotating, then revoking the old key, invalidates outstanding access tokens without changing the API keys.
  - **Legacy JWT secret:** rotating it also invalidates the legacy anon and service-role keys every suite app uses. **All apps stop working until every app's secrets are updated.** Plan it as a coordinated change, never as a quick fix.

### 5. The owner's account

- The owner's own tokens were in the table, so check T4 for the owner's account first.
- Changing the password doesn't by itself revoke existing refresh tokens; step 3 does.

## Long term: stop keeping raw tokens in general saved-item storage

**Where it happens today** (the same shared module in every suite app):
- `suite_storage_supabase.save_browser_auth_session`, `save_browser_auth_session_versioned`, `load_browser_auth_session(_record)` and `invalidate_browser_auth_session`;
- `suite_auth_bridge_token_meta.enrich_bridge_payload`;
- the callers in `suite_auth_browser.py` and `suite_auth_bridge_restore.py`.

**Recommended design:**
1. **A dedicated table, `suite_auth_browser_sessions`, out of general saved items.**
   - Created with RLS on and anon / authenticated revoked in the same migration. That matters because Supabase grants new `public` tables to anon by default.
   - Generic saved-item reads can then never return a token.
2. **Store no access token.** It's short-lived, and a restore can get a fresh one from the refresh token (`refresh_session`).
3. **Encrypt the refresh token** with an authenticated cipher (AES-GCM / Fernet).
   - Use a server-only key in Streamlit secrets (for example `[suite_auth] token_encryption_key`), distinct from every Supabase key and shared by the suite apps that share sign-ins.
   - Store a key id so the key can be rotated.
   - A database reader, even one with the service role, then gets only ciphertext.
4. **Look rows up by a hash of the URL session id,** never the id itself, so the database alone can't map a URL to a session.
5. **Expiry and sign-out.** Set `expires_at` (for example 30 days). Sign-out marks the row revoked and clears the ciphertext. Restore refuses expired or revoked rows and fails closed if decryption fails.
6. **Migration.**
   - The new code stops reading the old plaintext rows. Users sign in once.
   - After every app is on the new code, a separately approved one-time cleanup removes the token fields from the old `browser_session` rows.
   - Nothing else in `suite_saved_items` is touched.
7. **Tests.**
   - Encrypt and decrypt round-trip, and a wrong key fails closed.
   - No stored payload contains a raw token: a scan test over everything the save path writes.
   - Restore after refresh, and on a second tab.
   - Sign-out revokes.
   - A revoked or expired row means signed out, not an error loop.
   - On Dev: the two-browser sign-in flows the auth bridge already covers.

**This is a change in all seven suite apps.** It needs its own branch and review, and isn't part of the Baseball Stage B branch.
