# Baseball settings ownership: current behaviour, defects and target design

Status: **investigation and design only, 2026-11-02. Nothing implemented.** Code read is the deployed `dev` (`bc74759`) and this branch (Stage B, `fix/cloud-restore-hydration`). "Verified" means read in code; "Inferred" means not executed.

## Headline

There is effectively **one draft-settings scope per workspace**. A handful of global session keys hold projection style, projection window, scoring format, your team and team count:

- `draft_shared_settings`, `room_format`, `room_window`, `fantasy_draft_projection_style`, `room_your_team`, `room_team_count`, `room_rounds`.

They are written by:

- the Draft Room Simulator, Live Draft, Draft Assistant and Draft Lab;
- Saved Draft Library activation;
- account-preference activation.

Every page alias is then mirrored from them. Nothing is keyed by draft id, room code or source id, except the shared-room document and the participant queue slots. Editing a setting in one draft therefore changes every other draft and page.

## Persistence layers (deployed)

| Layer | Scope | Notes |
|---|---|---|
| Streamlit `session_state` | browser session | `SessionStateProxy`, **not a `dict` subclass** (verified). Code that checks `isinstance(session, dict)` silently gets `{}` |
| Workspace pointer `data/suite_active_workspace.json` | global on the server | `SUITE_WORKSPACE_ID` overrides it per process |
| Workspace blob `data/workspaces/<ws>/baseball_user_state.json` | workspace | `_GLOBAL_KEYS`, `_WORKSPACE_KEYS` and `_WORKFLOW_KEYS` in `baseball_persistent_state.py`; refused for anonymous guests |
| `page_filter_state[<page>]` | workspace + page | `restore_page_state` re-mirrors the global canonical settings over each page snapshot |
| Live Draft "sticky prefs" (`user_page_preferences`) | intended per user and workspace | **Non-functional with the real session (D1)** |
| Cloud `suite_app_current_state` | row `app` = `baseball[__ws]`, PK `app` only | Blob mirror (see `SUITE_APP_CURRENT_STATE_ISOLATION_PLAN.md`) |
| Cloud `suite_user_settings` | `(user_id, app)` | Account prefs (active draft, league, overrides, research). **No scoring, style or window** |
| Saved drafts `draft_archive_teams[]` | per `draft_id` | Hold `fantasy_format`, `roster_slots` and `projection_settings`, but see D3 |
| Shared room document `baseball_shared_draft_rooms` | per `room_code` | Commissioner-authoritative room config, contained by Step B |
| Participant slots `draft_room_participant_state[ROOM].by_participant[pid]` | room + participant, stored inside the workspace blob | queue, watchlist, notes |

**Hydration on cold start, sign-in and refresh.** The steps run in this order:

1. auth;
2. clamp to the owned workspace;
3. `apply_baseball_disk_state`;
4. workflow hydrate;
5. `prepare_global_fantasy_settings(force_mirror)`;
6. restore auth and enforce ownership;
7. startup workflow;
8. repair live-draft configs;
9. **account prefs reassert, which has final authority**;
10. Simulator scrub.

## Ownership matrix (current)

| Setting | Owner today | Persisted / key scope | Risk |
|---|---|---|---|
| Projection style | workspace-global (`draft_shared_settings.projection_style`, `fantasy_draft_projection_style`) | blob, ws | Shared by Live Draft, Simulator, Draft Assistant, Draft Lab, ML and Valuation; editing it anywhere changes all of them. Saved drafts store it, but activating a draft doesn't restore it |
| Projection window | global `lookback_window` / `room_window` | blob, ws | Same, plus the saved-draft key mismatch (D3) |
| Scoring format | global `room_format` (Live mirror `live_draft_scoring`) | blob, ws | Overwritten by Library / league activation and Live→Simulator sync. Live page restore forces the global over its snapshot |
| Roster slots | Live page snapshot `live_slot_*` / saved `roster_slots` / league `roster_settings` | ws / draft / league | Simulator saves record `{}` (D3). `lineup_format` means H2H/Roto, not roster |
| Team count, picks per team | global `room_team_count` / `room_rounds` + Live page keys | blob, ws | Rewritten by Live sync and saved-mock resume |
| Timer, auto-pick rule, draft type | room `config` is authoritative in a room; setup widgets are ws-scoped | room doc / blob | Low |
| League name | `live_draft_league_name` | blob, ws | Not per draft |
| Your team | global `room_your_team` + aliases (`lineup_team`, …) | blob, ws | Many writers (D4); Team Management and Live Draft share one team |
| Free-pool drafting | session `allow_free_pool_drafting` beats the room config | blob, ws | A participant's value overrides the commissioner's (D8) |
| Recommendation sort | page-prefixed keys | page snapshot | OK per section, not per draft |
| Team Management (team, format, window, style) | mirrors of the draft globals | blob, ws | Follows whichever draft last wrote the globals; not league-scoped |
| Draft Room Simulator config | the same `room_*` globals + `draft_room_state` | blob, ws, single board | Overwritten by Live Draft and Library activation |
| Draft queue / watchlist | `draft_queue` (ws) + participant room slot | blob | See the queue-ownership decision (Draft Strategy audit) |
| Research filters | `page_filter_state` | blob, ws + page | Inherited across sign-out/in on deployed (fixed by Stage B) |
| Account prefs | account | `suite_user_settings` | Activation clobbers the globals (D5); deployed sync imports a missing `suite_storage` (fixed by Stage B) |

## Defects

- **D1 (verified):** Live Draft sticky preferences don't persist with the real session. `user_page_preferences.py:20-21` and `86-89` replace a non-`dict` session with `{}`, and `SessionStateProxy` is not a `dict`. Reads return None and writes go to a throwaway dict.
- **D2 (verified):** one global draft-settings scope. Any Live Draft setup change rewrites the shared canonical settings and every alias (`streamlit_app.py:25098-25116` → `shared_draft_context.write_canonical_draft_settings`). Page restore re-mirrors them, and the Draft Lab handoff rewrites them.
- **D3 (verified):** saved drafts lose settings. Saves pass `config=draft_shared_settings`, whose window key is `lookback_window`, but the archive reads `projection_window` (`draft_archive_state.py:168`). Window, ML blend and slots save as None or `{}`. Resume writes the entry shape back into the shared settings, overwriting the account-wide ones. Activation restores only team and format.
- **D4 (verified):** `room_your_team` has about ten writers, including archive activation, league activation, Live→Simulator sync, the multiplayer override and a self-heal on read.
- **D5 (verified):** the account default overrides the draft. The final account-pref reassert re-activates the "active draft" and rewrites `room_your_team` / `room_format`.
- **D6 (verified):** `read_canonical_draft_settings` always returns concrete defaults, so `kw.get(x) or cfg.get(x)` never reaches a room or draft config.
- **D7 (verified code, inferred runtime):** a Shared participant's pool uses that participant's own session settings, not the commissioner's (`live_draft_canonical_pool.py:65, 92-119`). The guest local pool does the opposite and is correct, so the result depends on which loader runs.
- **D8 (verified):** free-pool drafting — the session value beats the room config (`draft_source_validation.py:53-60`).
- **D9 (verified, local only today):** the room config's `your_team` is overwritten in the session with the viewer's team. It must never be published.
- **D10 (verified deployed, fixed by Stage B):** logout and account switch keep the previous account's filters, globals and participant slots in the session.
- **D11 (fixed by Stage B):** `isinstance(dict)` ownership checks, and `daniel` fallbacks for an empty workspace id.
- **D12 (verified on Stage B):** guest → account carries the guest's settings into the account, because the clear runs only on a known-id change. This contradicts the guest-isolation requirement.
- **Related (diagnostics):** `nav_page_trace.is_nav_page_trace_enabled` has the same `isinstance(dict)` problem, so `?nav_trace=1` never logs on hosted.

## Target architecture

**Scopes**

| Scope | Holds | Stored in |
|---|---|---|
| `account:<user_id>` | cross-section preferences, defaults for new drafts | `suite_user_settings`, never workspace-normalized to `daniel` |
| `section:<user_id>:<page>` | research filters | blob |
| `entity:draft:<id>`, `sim:<board>`, `live:<draft_room_id>`, `league:<id>`, `source:<id>` | that entity's settings | blob `settings_v2.entities` |
| `room:<room_code>` | commissioner-authoritative config | the room document only |
| `participant:<room_code>:<user_id>` | personal queue, watchlist, rec sort | blob `settings_v2.participants` |
| `guest:<ws>` | session only | never merged into an account; offer an explicit "copy into my account" |

**Single chokepoint (`settings_store.py`)**

- `effective(session, surface)` resolves the active entity, and `set(session, scope, field, value)` is the only write path.
- Widgets use surface-local keys, seeded from `effective()`.
- Only fields declared `shared` are mirrored.
- Account defaults are copied into an entity once, at creation, and never re-applied.
- Non-commissioners can't write `room:`.
- Every session check uses `Mapping`, not `dict`.

**Hydration**

The steps run in this order:

1. auth;
2. owned workspace;
3. **clear on any account change, guest included**;
4. account doc;
5. blob;
6. resolve the active entity per surface;
7. seed the widgets;
8. shared mirror.

Nothing after step 7 writes entity fields. The account reassert may change *which* entity is active, but never its fields.

**Migration** is idempotent, behind a `settings_v2_migrated` flag:

- **Backup:** keep a pre-migration copy in the blob.
- **Account defaults:** `account_defaults` ← current `draft_shared_settings`.
- **Simulator:** `sim:` ← `room_*` + the shared settings.
- **Saved drafts:** `draft:<id>` ← the entry's settings, mapping `projection_window` ↔ `lookback_window`. Gaps are filled from the legacy globals and marked `migrated_from=legacy_global`.
- **Leagues:** `league:` ← league context.
- **Shared rooms:** `room:` ← the room config.
- **Participants:** `participant:` ← the existing slots.
- **Transition:** dual-write the legacy keys for one release, and delete nothing.

## Regression tests

1. Per-account isolation with a real `SessionStateProxy`: two accounts in one browser and on one server, and a guest never reaching an account.
2. Draft independence: editing a setting in Live Draft leaves the Simulator, Draft Lab, saved drafts and Team Management unchanged, and vice versa.
3. Declared shared fields are the same everywhere.
4. Saved-draft round-trip (save → resume → save) keeps window, ML, slots, team count and picks, and leaves the shared settings unchanged.
5. The account-pref reassert leaves the Simulator and Live configs untouched.
6. Shared room:
   - a participant's pool uses the commissioner's settings;
   - a participant can't change the room config or the commissioner's team;
   - personal queue and sort survive rejoin.
7. No reset on refresh, resume, rejoin, rerun, or sign-out/in.
8. `user_page_preferences` and `live_draft_canonical_pool` work with a non-dict mapping.
9. Migration is idempotent and loses no field.

## Dependencies and order

1. **Stage B first.** This builds on Stage B (proxy-aware ownership, clear on account change, storage fallback). Stage B must be integrated first, or the two will conflict, and its D12 behaviour needs reversing for guests.
2. **The queue model is a decision.** Global per account (owner-reviewed commit `bfd84f9` on `feature/baseball-completion`) or participant-private per room (the new request) has to be decided before the `participant:` scope is final.
3. **Database order.** The `suite_app_current_state` PK change (isolation plan) comes before any cloud-scoped `settings_v2`.
