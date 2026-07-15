# Portfolio Screenshot Guide — Baseball Stat App

> Master shot list and portfolio rationale live in the root [`README.md`](../README.md) → **Screenshots Needed (final plan)**. This guide is the operational shoot checklist for the curated **9 primary** shots.

## Enable Screenshot Mode

1. Open the app locally or on Streamlit Cloud (`dev`)
2. Sidebar → toggle **Portfolio Screenshot Mode**
3. Hide Developer Mode expanders; wait for “Running…” to clear
4. Capture into `docs/screenshots/` using the exact filenames below

---

## Pre-capture setup (do this once)

1. Sign in with Real Accounts (needed for shared-league invite/claim shots).
2. Import or complete a draft with recognizable player names (4+ rounds).
3. **Save to Saved Drafts** and **Activate** that draft.
4. Create a Shared League, send an invite, and claim a team.
5. On Fantasy Standings Tracker, load current-season stats (MLB API or CSV) so Lineup / Trade have data.
6. Enable Screenshot Mode before each capture.

---

## Hero detail: Live Draft Room (`02-live-draft-room.png`)

**Goal:** Board + On Clock / timer + recommendation cards (headshots) + Roster Needs Checklist + queue — no developer clutter.

### Pre-flight (clean UI)

1. Sidebar → **Developer Mode = OFF**
2. Sidebar → **Portfolio Screenshot Mode = ON** (visible by default; set `PORTFOLIO_CAPTURE_UI=0` to hide the toggle)
3. Hard-refresh once after pulling these LDR cleanup changes (clears leftover debug session flags)
4. Confirm the main area does **not** show banners like “Live Draft render trace”, LDR step captions, or sidebar workflow/nav traces

### Best state to create

1. Open **📡 Live Draft Room**
2. Prefer **Solo Draft** (simplest portfolio story) — e.g. 8–12 teams, standard roster slots
3. **Start** the draft and make **3–6 picks** so the board looks populated
4. Pause when **you are On Clock** (or any team) with **timer visible and counting**
5. Scroll so the viewport includes, top-to-bottom if possible:
   - League / On Clock header + timer
   - **Draft Control Center** / queue (if compact)
   - **Draft Board** with named picks
   - **Recommendation cards** with Decision Score + headshots
   - **Roster Needs Checklist** (and scarcity if it fits without crowding)

### Filename

`docs/screenshots/02-live-draft-room.png`

### Avoid in frame

- Empty “No picks yet” board
- Setup/lobby-only screen
- Expanded Advanced / Shared Draft diagnostic panels
- Any yellow debug banners or `⏱ LDR` captions

---

## Final 9-shot checklist

| # | Filename | Page / location | Visible content checklist |
|---|----------|-----------------|---------------------------|
| 1 | `01-draft-assistant-recommendations.png` | Draft Assistant Simulator | Top rows, Decision Score, survival %, Why this pick, needs |
| 2 | `02-live-draft-room.png` | Live Draft Room | Board + timer + recommendation cards + Roster Needs Checklist |
| 3 | `03-uploaded-draft-import.png` | Draft Room Simulator → Import | Validated preview, remap UI, Apply / Save actions |
| 4 | `04-shared-league-claims.png` | Library invite/claim panel | Active Draft + claimed vs unclaimed teams + invite controls |
| 5 | `05-lineup-management.png` | Lineup Assistant → Lineup Management | Weekly board, headshots, start/sit / recommended lineup |
| 6 | `06-trade-center.png` | Lineup Assistant → Trade Center | Give/get players + category impact or Offers list |
| 7 | `07-research-mode-comparison.png` | Comparison Tool (+ Research Mode ON) | 2–3 players with MLB headshots + metrics |
| 8 | `08-hof-case-mode.png` | Career Totals → HOF Case Mode | Target + cohort / HOF prevalence |
| 9 | `09-baseball-insight-ami.png` | Rich page + sidebar | Insight question + returned AMI answer |

**Omitted on purpose:** Waiver, Standings, Draft Lab, Historical Explorer, Sleepers-only, Saved Library-only (redundant with the nine above).

---

## Hero page detail: Draft Assistant Simulator

**Why this page:** Strongest single-frame story — next-pick rankings, needs, scarcity, and plain-language explanations.

### Desktop (1920×1080 or 1280×800)

| Step | Action |
|------|--------|
| 1 | Ensure FantasyPros CSVs are present |
| 2 | Open Draft Room Simulator — log 3–5+ picks (or activate an imported draft) |
| 3 | Go to **Draft Assistant Simulator** |
| 4 | Enable Screenshot Mode |
| 5 | Expand recommendations (top 10 visible) |
| 6 | Capture full viewport: rankings + top recommendation explanation |

**Filename:** `01-draft-assistant-recommendations.png`

---

## Screenshot Mode behavior

- Hides Quick guide blocks (replaced by executive summary cards where applicable)
- Collapses advanced expanders by default
- Hides debug panels and sidebar instructional captions
- Tighter vertical spacing
- Hero banner on Draft Assistant page

---

## Final checklist

- [ ] All 9 primary PNGs present under `docs/screenshots/`
- [ ] Filenames match README gallery links exactly
- [ ] No empty-state or error banners in final assets
- [ ] Screenshot Mode was on for each capture
- [ ] README **Screenshots** section verified after copy
