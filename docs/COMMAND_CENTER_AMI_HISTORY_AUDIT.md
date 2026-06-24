# Command Center AMI History — Current Behavior & Roadmap

**Status:** Audit / roadmap (2026-06-17)  
**Applies to:** Command Center, Baseball, Music, Investment, Applied Mathematical Intelligence

---

## User-reported symptom

Multiple Baseball AMI questions were asked (Eric Wagaman tests and others). Command Center appears to show **only the newest question**; older questions seem to disappear.

---

## What is actually stored today

The suite **does not** use a single global “latest insight” slot for all history. Several layers exist:

| Layer | Table / key | Write behavior | Read behavior |
|-------|-------------|----------------|---------------|
| **Resume / Continue cards** | `suite_resume_items` | `upsert_resume_item` per `item_key` (`ai:question:{question_id}`) | `load_active_resume_items(limit=8)` — newest first |
| **Insight payloads** | `suite_saved_items` (`item_type=applied_math_insight`) | `remember_saved_item` per unique `insight_id` | `load_saved_items` / `load_latest_applied_math_insight_for_app` returns **one** newest match |
| **Question context blobs** | `suite_saved_items` (`item_type=analytical_question_context`) | Per `question_id` | `load_analytical_question_payload(qid)` |
| **Activity events** | `suite_events` | `append_event` — **append-only** | `load_events(limit=MAX_EVENTS)` |

### Per-question identity

- `question_id` = fingerprint of question + source app + page + context (`suite_analytical_question.question_id`)
- `resume_key` = `ai:question:{question_id}`
- `insight_id` = hash of question_id + conclusion snippet

Different questions → different IDs → **separate rows** in cloud storage (not overwritten), unless the same question is re-sent within the duplicate window.

### What *is* single-slot (by design today)

| Location | Key | Effect |
|----------|-----|--------|
| Source app session | `_ami_pending_insight` | Latest staged insight for on-page card |
| Source app hydration | `load_latest_applied_math_insight_for_app` | Picks **one** newest insight when hydrating |
| Command Center UI (observed) | — | Surfaces **one** prominent Continue / latest AMI card |

So: **history is largely stored; the gap is surfacing it in Command Center UI**, not necessarily losing data on write.

---

## Likely causes of “only latest visible”

1. **Command Center UI** may render a single resume/continue card (or one per app) rather than a “Recent Insights” list.
2. **`load_active_resume_items(limit=8)`** exists but CC may not list all eight in the homepage layout.
3. **Events are deferred** for `analytical_question` sends (`append_event` in background thread) — history may lag slightly but should still accumulate.
4. **User expectation** matches insight card on source app (`_ami_pending_insight`), which intentionally shows only the current pending insight.

---

## Desired behavior (roadmap — not implemented)

### Recent Insights list (5–10 items)

Example:

1. Would Eric Wagaman help my fantasy team as a sleeper?
2. Which sleeper has the best combination of upside and safety?
3. Should I trade for more stolen bases?
4. What should I practice next?
5. How should I practice this chorus?

Clicking an item should:

- Reopen that AMI result (frozen answer + metadata)
- Load context blob by `question_id` / `insight_id`
- **Not** roll back the source app’s live page state

### Return to source app from an old insight

| Show (frozen) | Do **not** restore |
|---------------|---------------------|
| Original AMI answer, method, assumptions | Old draft board, filters, roster |
| Question text, source page label | Page navigation to “as-was” workspace |
| Timestamp / confidence | Old widget values |

User returns to Baseball/Music/Investment with **today’s** workspace; insight is read-only history.

### Future Command Center

- Recent insights, favorites, search
- Filter by Baseball / Music / Investment / Applied Math
- Open original source app/page (deep link) without time-traveling workspace state

---

## Implementation notes (when scheduled)

1. **CC homepage:** `load_active_resume_items` + `load_saved_items(item_type=applied_math_insight)` merged, deduped by `question_id`, sorted by `updated_at`.
2. **Reopen path:** AMI / Applied Intelligence hydrates from `insight_id` or `question_id` blob only; `consume_ami_return_resume` must not force full `source_state` workspace restore for history views.
3. **Source apps:** Keep `_ami_pending_insight` as “current” card; optional “View in Command Center history” link.
4. **Account scope:** See `docs/FUTURE_MULTI_USER_ARCHITECTURE.md` — history keys must include `user_id`.

---

## Verification checklist (manual)

- [ ] Send 3 different Baseball questions (different text)
- [ ] Supabase `suite_resume_items`: 3 rows with distinct `item_key` (`ai:question:…`)
- [ ] Supabase `suite_saved_items`: multiple `applied_math_insight` rows
- [ ] Supabase `suite_events`: multiple `analytical_question` events
- [ ] Command Center UI: count how many Continue cards / history rows appear
- [ ] Reopen oldest via AMI URL with `suite_ai_question_id` — answer still loads from blob
