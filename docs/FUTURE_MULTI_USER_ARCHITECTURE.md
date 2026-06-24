# Future Multi-User Architecture (Roadmap Only)

**Status:** Directional — **not implemented**  
**Last captured:** 2026-06-17  
**Applies to:** Baseball App, Music Practice Coach, Investment App, Command Center, Applied Mathematical Intelligence, and future suite apps.

This document records the long-term multi-user vision so current work stays compatible with eventual account-based workspaces and multiplayer live drafts. **No implementation is required now.**

---

## Core concept

Every person eventually has their own account.

Example: Daniel logs in; Brother logs in. They use the same application platform but **completely separate workspaces**.

| Daniel changes | Brother changes |
|----------------|-----------------|
| Only affects Daniel | Only affects Brother |

Neither user should see or overwrite the other user's information.

### Hierarchy (target model)

```
Account
  → Apps (Baseball, Music, Investment, …)
    → Workspaces
      → Settings
      → AMI (insights, history, controls)
      → Saved state (filters, boards, rooms, progress)
```

**Everything eventually becomes account-scoped.**

---

## Per-app scope (private by default)

### Baseball App

Account-specific examples:

- Drafts, teams, watchlists, queues
- Sleepers, recommendations, saved rooms
- AMI history and insight dismissals
- Page filters, fantasy team/format preferences

### Music Practice Coach

Account-specific examples:

- Active songs, practice history
- Instrument, skill level, progress tracking
- Practice plans, favorites, saved progressions
- Music Coach / AMI history

### Investment App

Account-specific examples:

- Watchlists, portfolios
- Saved analysis, preferences, notes
- AMI history

### Command Center

Command Center becomes **user-aware**:

| Daniel | Brother |
|--------|---------|
| Daniel insights | Brother insights |
| Daniel AMIs | Brother AMIs |
| Daniel history | Brother history |
| Daniel projects | Brother projects |

Completely separate experiences per logged-in user.

### Applied Mathematical Intelligence (AMI)

AMI answers and stored context are tied to the **requesting user** (and, in shared rooms, to that user's private strategy layer — see below).

---

## Future multiplayer live draft

Long-term vision: a **host** creates a draft room; other users **join** with a room code.

Example:

- Room code: `ABC123`
- Daniel → Team A
- Brother → Team B
- Friend 1 → Team C
- Friend 2 → Team D

### Shared room state (visible to all participants)

Everyone in the room sees the same:

- Draft board, picks, clock
- Team rosters (as revealed by the room)
- Room settings, draft history

### Private user state (never leaked across users)

Each participant keeps a **private strategy layer** the room does not expose:

| Daniel (private) | Brother (private) |
|------------------|-------------------|
| Daniel queue | Brother queue |
| Daniel watchlist | Brother watchlist |
| Daniel notes | Brother notes |
| Daniel recommendations | Brother recommendations |
| Daniel AMI answers | Brother AMI answers |

Daniel cannot see Brother's queue/watchlist/notes/recommendations/AMI answers, and vice versa.

### AMI in a shared room

AMI must be **user-aware inside the room**.

Same question, different users, different answers:

> "Who should I draft next?"

**Daniel's AMI** uses: Daniel roster, categories, queue, draft position, strategy, **plus** shared room state.

**Brother's AMI** uses: Brother roster, categories, queue, draft position, strategy, **plus** the same shared room state.

Identical wording can yield different recommendations because private context differs.

---

## Long-term goals (checklist)

1. Single-user practice drafts  
2. Single-user live draft tracking  
3. Multi-user live draft rooms  
4. Account-based workspaces across all suite apps  
5. User-specific AMI recommendations  
6. User-specific Command Centers  
7. User-specific Music workspaces  
8. User-specific Investment workspaces  
9. Shared draft rooms with **shared board state** + **private strategy layers**

---

## Design principles for current work (compatibility)

Use these when building features today so migration to accounts/multiplayer is easier later.

1. **Namespace by principal** — Persist and load state with a stable user/account id (even if today that id is a single device or anonymous session). Avoid global singletons that assume one human.

2. **Separate shared vs private** — For draft-related code, distinguish:
   - **Room state** (board, picks, clock, public rosters)
   - **User state** (queue, watchlist, notes, personal recommendations, AMI context)

3. **AMI context is per-user** — `source_state`, `return_context`, instant insight payloads, and Command Center blobs should remain attachable to `(account_id, app_id, …)` not only `(device_id, …)`.

4. **Command Center is per-user** — Activity, question history, insight storage, and resume keys should not bleed across accounts.

5. **Cloud sync keys** — Full-session blobs (`suite_cloud_state`, workspace envelopes) should eventually key off account, not only device/file id.

6. **No cross-user reads in APIs** — Queries and caches should require an explicit room membership or account scope; never infer "the" user from app globals alone.

7. **Multiplayer is additive** — Single-user flows remain valid; room join adds a shared layer without replacing private workspace sync.

---

## Related docs (current, pre-account)

- Baseball: `docs/BASEBALL_PAGE_STATE_PROTOCOL.md`, `docs/PHONE_DELL_SYNC_AUDIT.md`
- Music: `ai-music-practice-coach/docs/MUSIC_PHASE_B_PROTOCOL.md`, `cursor-prompts/music_app_roadmap.md`
- Music AMI context plan: `docs/music_ami_context_plan.md`

When account auth ships, update those protocols to reference this document for scope and isolation rules.

---

## Explicit non-goals (for now)

- No auth provider choice, schema migration, or Supabase RLS design in this doc  
- No live draft room protocol or WebSocket design  
- No breaking changes to current device-based persistence until an account milestone is scheduled
