# Music Practice Coach — AMI Context Pipeline (Draft)

Goal: Music AMI receives complete practice context at send time, mirroring Baseball AMI’s draft snapshot pattern.

## Context layers

| Layer | Fields | Source |
|-------|--------|--------|
| Session | `active_song_id`, `instrument`, `skill_level`, `practice_mode` | Session state / song picker |
| Song | title, artist, sections, chord progression, key, tempo, lyrics/cues | Active song model |
| Practice | section focus, loop range, backing track (style, tempo, key), metronome | Practice UI |
| History | recent sessions, accuracy %, streaks, last practiced section | Local/cloud history |
| Question | raw user question, named song/section/chord from text | AMI sidebar |

## Question-type → context payload

Music AMI should receive **only the fields relevant to the question**, plus shared session anchors (active song, instrument, skill level).

| Question type | Example | Required context | Optional context |
|---------------|---------|------------------|------------------|
| Active song | “What should I focus on in this song?” | `active_song`, sections, `practice_mode` | history, skill level |
| Practice plan | “How should I practice this week?” | history, skill level, weak sections, `practice_mode` | instrument, tempo goals |
| Backing track | “Match the backing track tempo to my level” | backing track settings, tempo, key, skill level | active song, section focus |
| Chord progression | “Why is the G→Am transition hard?” | chord progression, fingering chart, section | instrument, skill level |
| Section focus | “Drill the chorus slowly” | `section_focus`, loop range, tempo, active song | lyrics/cues, history |
| Tempo / key | “Should I transpose down a step?” | key, tempo, skill level, section difficulty | backing track, instrument |
| Lyrics / cues | “When do I come in after the bridge?” | lyrics/cues, section markers, active song | practice mode |
| Skill / instrument | “Barre chords on acoustic — where to start?” | instrument, skill level, chord progression | history, section focus |
| Practice history | “What did I improve last session?” | recent practice history, accuracy, streaks | active song, section focus |

## Pipeline (proposed)

1. **Page render** — cache lightweight snapshot in `session_state["_ami_music_snapshot"]` when song/practice inputs change (signature-based skip).
2. **Send** — `build_music_applied_math_context(page, session)` merges snapshot + `detect_music_send_intent(question)`.
3. **Finalize** — `finalize_music_context_for_send()` binds named song/section/chord from question text; clears stale focus when question names a different target.
4. **AMI solver** — mode routing per question type (technique, timing, chord transition, section focus, repertoire, practice plan).

## Parity with Baseball

- Single source of truth for active song (like `room_your_team` / Live Draft).
- Read-only analysis pages inherit active song — no duplicate pickers.
- Team-fit / named-player anchoring: named song or section stays primary subject (no top-candidate substitution).
- Dev-only `?dev=1` perf marks: `music_context_build`, `page_render:{page}`.

## Next steps

1. Inventory Music app session keys and page ownership.
2. Add `music_ami_context.py` with `cache_music_ami_context`, `detect_music_send_intent`, sig skip.
3. Wire `suite_analytical_question` context builder for Music app id.
4. Acceptance tests: named song in question stays primary subject; question-type routing selects correct context slice.
