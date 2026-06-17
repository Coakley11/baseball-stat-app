# Music Practice Coach — AMI Context Pipeline (Draft)

Goal: Music AMI receives complete practice context at send time, mirroring Baseball AMI’s draft snapshot pattern.

## Context layers

| Layer | Fields | Source |
|-------|--------|--------|
| Session | `active_song_id`, `instrument`, `skill_level`, `practice_mode` | Session state / song picker |
| Song | title, artist, sections, chord progression, key, tempo, lyrics/cues | Active song model |
| Practice | section focus, loop range, backing track (style, tempo, key), metronome | Practice UI |
| History | recent sessions, accuracy %, streaks, last practiced section | Local/cloud history |
| Question | raw user question, `question_player` equivalent (song/section if named) | AMI sidebar |

## Pipeline (proposed)

1. **Page render** — cache lightweight snapshot in `session_state["_ami_music_snapshot"]` only when song/practice inputs change (signature-based skip).
2. **Send** — `build_music_applied_math_context(page, session)` merges snapshot + question parsing.
3. **Finalize** — `attach_question_song_to_context()` binds named song/section from question text.
4. **AMI solver** — mode routing: technique, timing, chord transition, section focus, repertoire.

## Parity with Baseball

- Single source of truth for active song (like `room_your_team` / Live Draft).
- No per-page duplicate song pickers on read-only analysis pages.
- Dev-only `?dev=1` perf marks: `music_context_build`, `page_render:{page}`.

## Next steps

1. Inventory Music app session keys and page ownership.
2. Add `music_ami_context.py` with `cache_music_ami_context` + sig skip.
3. Wire `suite_analytical_question` context builder for Music app id.
4. Acceptance tests: named song in question stays primary subject.
