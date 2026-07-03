# Daniel Cohen Baseball Explorer

**A full-stack fantasy baseball decision-support platform** built with Python and Streamlit. It combines historical MLB analytics, projection modeling, draft intelligence, live multiplayer drafts, and natural-language insight handoff to a companion Applied Mathematical Intelligence (AMI) workspace.

**Live demo:** [baseball-stat-app.streamlit.app](https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app)  
**Deploy branch:** `dev` · **Entry point:** `streamlit_app.py`

Built as part of the **Daniel Cohen AI Suite** (shared workspace auth, cloud persistence, and Command Center / AMI handoffs). Daily development happens on branch `dev`.

---

## At a glance (portfolio overview)

| | |
|---|---|
| **Role** | Full-stack Python application — analytics pipelines, draft intelligence, multiplayer state, and test-driven persistence |
| **Stack** | Python 3.11+ · Streamlit · pandas · Lahman CSVs · FantasyPros merge · optional Supabase · AMI Command Center handoff |
| **Scale** | 14 connected pages · **151 automated test modules** · unified projection pool · live multiplayer draft rooms |
| **Differentiators** | **Decision Score** as the canonical pick-ranking metric across draft surfaces; host-configured roster slots as source of truth; revisioned Supabase draft sync; structured AMI context handoff |

---

## For employers and reviewers

This project demonstrates end-to-end ownership of a data-heavy decision-support product: Lahman-scale analytics, a **pure draft scoring engine** decoupled from Streamlit, multiplayer draft rooms with revisioned Supabase sync, and **AMI integration** that ships structured page context to a companion solver workspace. The targeted draft regression suite (~120 tests) covers scoring, host-slot configuration, poll sync, persistence, and AMI payloads — inspectable without running the full UI.

---

## 1. Executive Summary

Most fantasy baseball tools show you numbers. This app helps you **decide what to do with them**.

Daniel Cohen Baseball Explorer is an interactive analytics platform for:

- Exploring decades of MLB batting data (Lahman database)
- Comparing players with statistical rigor
- Identifying trend breakouts, volatility, and valuation signals
- Running snake drafts — manually, simulated, or live with timers and multiplayer room codes
- Ranking next picks with **Decision Score** — a unified metric blending player value, roster fit, scarcity, category needs, and availability
- Tracking in-season standings and building start/sit lineups
- Asking follow-up questions in plain English via **Baseball Insight**, with structured page context routed to **AMI / Command Center** for solver-backed answers

The app is designed as a portfolio piece demonstrating **data engineering, statistical modeling, real-time collaborative state, test-driven development, and product-minded UX** — not a static dashboard.

---

## 2. Why This Project Is Different

| Typical fantasy tool | This platform |
|---------------------|---------------|
| Static rankings table | **Decision Score** — one canonical pick-ranking metric shared across Draft Assistant, Live Draft Room, auto-pick, and Draft Lab |
| One page, one purpose | **14 connected pages** with cross-page player transfers, shared projection pool, and persistent filters |
| Generic ADP lists | **Fantasy Edge** (model rank vs. market rank) plus survival probability at your next pick |
| Draft board OR analytics | **Canonical draft board** syncs simulator ↔ live draft ↔ assistant ↔ standings |
| Chatbot bolted on | **AMI / Baseball Insight** packages structured page context (recommendations, roster gaps, sleepers, trends) and routes questions to Command Center |
| Refresh loses your work | **Per-page state persistence**, workspace profiles, optional Supabase cloud sync, and multiplayer draft rooms |

Engineering highlights an employer can inspect in code:

- Pure scoring module (`live_draft_pick_scoring.py`) computes **Decision Score** decoupled from Streamlit for testability
- Host-configured roster slots as single source of truth (`live_draft_roster_slots.py`)
- Session-level UI caching for live draft performance (`live_draft_ui_cache.py`)
- Revisioned multiplayer draft documents in Supabase with JSON sanitization and poll-based sync

---

## 3. User Journey

A typical season-long workflow:

1. **Explore & compare** — Filter Historical Explorer or Career Totals; send interesting players to Comparison or Trend Value.
2. **Build a draft board** — Log picks in Draft Room Simulator, or run a full mock in Draft Simulation Test Mode.
3. **Draft live** — Promote to Live Draft Room (solo or shared multiplayer with room code), use timer + recommendations + roster checklist.
4. **Get next-pick advice** — Open Draft Assistant; needs auto-detect from your board and host slot configuration.
5. **Find value** — Sleepers & Busts surfaces market inefficiencies; Valuation and Trend Value add complementary lenses.
6. **Season management** — Load current stats into Fantasy Standings Tracker; use Fantasy Lineup Assistant for start/sit and trade ideas.
7. **Ask why** — Use Baseball Insight in the sidebar to send context-rich questions to Command Center and resume answers on return.

Cross-cutting tools follow you everywhere: **draft queue**, **watchlist**, **recent comparisons**, and **Player Actions** (queue, compare, trend, simulate pick).

---

## 4. Major Pages

| Page | What you do |
|------|-------------|
| **Historical Explorer** | Season-level batting filters, scatter plots, optional Hall of Fame coloring |
| **Career Totals** | Aggregated career lines with advanced filters and HOF Case Mode |
| **Leaderboards** | Sortable career/season leader tables |
| **Comparison Tool** | Side-by-side player comparison with significance testing |
| **Trend Value** | Slope, volatility, consistency, and multi-player trend charts |
| **Valuation** | Weighted performance + trend valuation scores |
| **ML Predictions** | ML-style next-season projections with tunable model inputs |
| **Fantasy Sleepers & Busts** | Market edge analysis with optional draft-board sync |
| **Draft Room Simulator** | Manual snake draft board and roster tracking |
| **Draft Assistant Simulator** | Next-pick recommendations from your live board |
| **Draft Simulation Test Mode** | Automated 4-team mock draft + post-draft analytics |
| **Live Draft Room** | Timed live snake draft, solo or multiplayer |
| **Fantasy Standings Tracker** | Roto/points standings from MLB API or CSV |
| **Fantasy Lineup Assistant** | Start/sit scores, lineup builder, trade analyzer |

---

## 5. Draft Assistant

**Problem it solves:** “Given my board, roster, and league settings, who should I take next — and why?”

**How it works:**

- Reads your **canonical Draft Room board** (synced from Simulator or Live Draft)
- Builds a **unified projection pool** (Lahman stabilized projections + FantasyPros market ranks)
- Auto-detects **position and category needs** from host-configured roster slots and your current roster
- Ranks every undrafted player by **Decision Score** (canonical recommendation metric); **Draft Fit Score** captures roster-construction fit as a component
- Surfaces **survival probability** — likelihood a player is still available at your next pick
- Generates plain-language **“Why this pick”** explanations (additive to badges, not repetitive)

**Key settings:** projection window (3/4/5 years), format (5×5 Roto or Points), projection style (Conservative / Balanced / Aggressive), optional ML blend weight.

**AMI:** Compact recommendation rows and roster context are packaged for Baseball Insight questions like “Should I take this player?”

---

## 6. Live Draft Room

**Problem it solves:** Run a real-time fantasy draft with structure, recommendations, and persistence.

**Modes:**

- **Solo draft** — You control all teams; no room code
- **Shared multiplayer** — 6-character room code; guests join via Supabase-backed shared state

**Features:**

- Configurable **roster slots** (C, 1B, 2B, 3B, SS, OF, DH, P, bench) — host slots drive all need/scarcity logic
- **Snake draft** with draft board, team rosters, and pick timer (pause/resume supported)
- **Recommendation cards** ranked by **Decision Score**, with Fantasy Edge, roster fit, scarcity, and draft insight text
- **Roster Needs Checklist** and **Position Scarcity Map** above recommendations
- **Manual draft panel**, **auto-pick rules**, queue integration, and leave/return navigation without losing draft state
- Completed or in-progress boards **sync back** to Draft Room Simulator for Assistant and Standings

---

## 7. Sleepers & Busts

**Problem it solves:** Find players the market may be mispricing before your league does.

**Scoring:**

- **Fantasy Edge** = Model Rank − Market Rank (positive → model likes player more than ADP)
- **Sleeper Score** blends capped positive edge with Expected Fantasy Value
- **Bust risks** = players with the most negative edge in the bust table

**Workflow:**

- Filter by position, age, projected HR, rank caps, and minimum player grade
- Optional **draft-room sync**: exclude drafted players and focus on open positional needs
- Scatterplot compares market rank vs. model rank with diagonal reference
- Send top sleepers to Comparison, Trend, Valuation, or AMI via Player Actions

---

## 8. Valuation Engine

**Problem it solves:** Rank players by a blend of current production and directional trend — not just one season snapshot.

**Formula (user-tunable weights):**

- **Perf_Score** — normalized current counting and rate stats
- **Trend_Score** — per-stat linear trends from the trend engine
- **Valuation_Score** — min–max scaled composite (0–1 display)

**Features:**

- Lag-year filters, minimum games, position filters, stat floors
- Merges canonical projection columns for draft-context cards
- Optional draft-board sync to hide already-drafted players
- State persists across navigation (`valuation_state.py`)

---

## 9. Trend Analysis

**Problem it solves:** Separate real improvement from noise — and visualize it.

**Per-stat metrics:**

| Metric | Meaning |
|--------|---------|
| Slope | Full-career linear trend |
| Recent Slope | Last 3 seasons emphasis |
| Volatility | Standard deviation of year-over-year change |
| Consistency Rating | CV-based stability band |
| R² | Trend fit quality |
| Trend Direction | Improving / Declining / Stable / Accelerating |
| Fantasy Signal | Plain-language fantasy interpretation |

**UI:** Single-player dashboard and multi-player charts (up to 6) with smoothed moving averages. Supports draft-room sync and cross-page transfers.

---

## 10. Projection System

**Problem it solves:** One consistent projection basis across every fantasy page.

**Pipeline:**

1. **Lahman lookback** — configurable 3/4/5-year windows per player
2. **Stabilized counting stats** — regression-to-mean and calibration (`projection_calibration.py`)
3. **Rate projection** — BA/OBP/SLG/OPS trend extrapolation
4. **Projection styles** — Conservative / Balanced / Aggressive adjust regression strength and breakout weights
5. **FantasyPros merge** — market rank, expert std dev, ADP
6. **Derived metrics** — Expected Fantasy Value, Model Rank, Fantasy Edge, Sleeper Score
7. **Optional ML blend** — global toggle reweights projections via trained Random Forest signal (`ml_training_build.py`)

**ML Predictions page** adds a separate interactive layer: aging curves, similar-player comps, and slider-tunable inference — with its own persisted state (`projections_state.py`).

---

## 11. Fantasy Standings Tracker

**Problem it solves:** See how your drafted roster is performing in-season.

**Data sources:**

- **MLB Stats API** auto-fetch (seasons 2020–2035), or
- Uploaded current-season CSV

**Scoring formats:**

- **5×5 Roto** — category ranks summed to total roto points
- **Points league** — HR×4 + RBI + R + SB×2 + OPS×25

Rosters join Draft Room picks to live stats by normalized player name. Outputs per-team totals, league rank, and category-need summary for Lineup Assistant handoff.

---

## 12. Fantasy Lineup Assistant

**Problem it solves:** Weekly start/sit decisions and basic trade evaluation.

**Requires:** roster stats loaded from Standings Tracker.

**Scoring:** Current Fantasy Score, Momentum, Consistency, Volatility Meter → **Lineup Confidence**

**Recommendations:** Start / Lean Start / Matchup Dependent / Sit / Bench-Risk with reasons.

**Lineup builder:** Position-aware slots (C, 1B, 2B, 3B, SS, OF×3, UTIL, bench) for 5×5 Roto, Points, or H2H Categories.

**Trade analyzer:** Evaluate give/get player packages within the lineup page.

---

## 13. Draft Lab / Draft Simulator

Two complementary tools:

### Draft Room Simulator
- Manual pick entry for 2–16 teams
- Board + rosters + league setup tabs
- Source of truth for the **canonical draft board**
- Per-pick player grades on the board
- Can convert to Live Draft Room with settings handoff

### Draft Simulation Test Mode (Draft Lab)
- Automated **4-team snake simulation** (15 picks/team default)
- Post-draft analytics: team strengths, roster gaps, best/questionable picks, trade ideas
- **At-pick score snapshots** preserved for post-mortem (not recomputed from end state)
- Accepts handoff from Live Draft Room; resumable from Command Center deep links

---

## 14. AMI Integration

**Baseball Insight** appears in the sidebar on every page.

**What it does:**

- Submit natural-language questions about players, drafts, sleepers, trends, trades, and strategy
- Packages **structured page context** via `applied_math_context.py` (recommendations, roster gaps, sleeper tables, trend summaries, HOF case state)
- Routes to **Daniel AI Command Center** for solver-backed answers
- Supports **return insight** — resume AMI answers on the originating page with dismiss persistence
- Optional local instant solver when AMI sibling repo is configured (`AMI_REPO_PATH`)

**Hall of Fame Case Mode** (Career Totals) sends rich cohort context for Cooperstown-style reasoning questions.

---

## 15. Persistence / Cloud Sync

| Layer | Implementation |
|-------|----------------|
| **Local disk** | `data/baseball_user_state.json` + per-workspace copies under `data/workspaces/{id}/` |
| **Workspaces** | Profiles (e.g. daniel, guest) with Command Center inheritance |
| **Page state** | Per-page widget registry — filters survive sidebar navigation (`page_state.py`) |
| **Draft state** | Canonical board (`draft_room_state.py`) + live draft JSON blob (`live_draft_state.py`) |
| **Multiplayer** | Supabase `baseball_shared_draft_rooms` — revisioned documents, poll sync |
| **Auth (optional)** | Supabase Real Accounts for shared draft rooms (`suite_auth.py`) |
| **Device continuity** | Anonymous device ID for guest sessions |

Cloud sync is optional; the app runs fully local with CSV data files.

---

## 16. Notable Engineering Challenges

1. **Single canonical draft board** — Live Draft, Simulator, Assistant, and Standings must agree on picks, teams, and roster slots without drift.
2. **Unified projection pool** — One cached pool powers draft scoring, sleepers, valuation cards, and AMI context with session-aware invalidation.
3. **Pure scoring decoupling** — `live_draft_pick_scoring.py` computes **Decision Score** without Streamlit so 120+ draft tests can validate the canonical ranking logic directly.
4. **Multiplayer live draft** — Host/guest team assignment, revision conflicts, JSON sanitization for Supabase, timer recovery across Streamlit reruns.
5. **Host slot source of truth** — Roster needs, scarcity maps, and Assistant auto-detect all read host-created slot config — not hardcoded position templates.
6. **Streamlit state protocol** — Dirty flags, cloud restore guards, widget key migration, and navigation ownership to prevent page bounce and stale overwrites.
7. **AMI context hardening** — Position-representative player pools, intent routing (sleeper vs. bust vs. draft pick), blob persistence for resume.
8. **Performance under rerun** — Session caches for recommendations, undrafted pool, and decision panels; cache invalidation on pick/poll/timer events.

---

## 17. Architecture

```
streamlit_app.py          # UI entry — 14 pages, shared helpers, Player Actions
├── Analytics layer
│   ├── historical_state / career_totals_state / leaderboards_state
│   ├── comparison_state / trend_state / valuation_state
│   └── projections_state / fantasy_state
├── Projection layer
│   ├── canonical_projections.py    # Shared proj_* columns
│   ├── projection_calibration.py   # Stabilized counting stats
│   ├── projection_style.py         # Conservative / Balanced / Aggressive
│   └── ml_training_build.py        # ML training cache + inference
├── Draft layer
│   ├── draft_room_state.py         # Canonical board + live↔sim sync
│   ├── live_draft_state.py         # Live room persistence
│   ├── live_draft_pick_scoring.py  # Pure scoring engine
│   ├── live_draft_roster_slots.py  # Host slot config
│   ├── live_draft_ui_cache.py      # Session performance caches
│   ├── draft_ami_helpers.py        # AMI payload + needs inference
│   └── draft_lab_analysis.py       # Post-draft analytics
├── Multiplayer layer
│   ├── draft_room_supabase_store.py
│   ├── draft_room_context.py
│   └── draft_room_membership.py
├── AMI layer
│   ├── baseball_ami_sidebar.py
│   ├── applied_math_context.py
│   └── suite_analytical_question.py
└── Persistence layer
    ├── baseball_persistent_state.py
    ├── page_state.py
    ├── suite_workspace.py
    └── suite_storage_supabase.py
```

**Cross-cutting:** `workflow_sidebar.py` (queue/watchlist), `page_transfers.py` (filter/player handoffs), `global_fantasy_settings_state.py` (shared scoring settings), `player_photos.py` (profile cards).

---

## 18. Setup & Install

### Requirements

- **Python 3.11+** (see `.devcontainer/devcontainer.json`)
- Dependencies: `pip install -r requirements.txt`

### Data files (place in repo root)

| File | Required | Purpose |
|------|----------|---------|
| `People.csv` | Yes | Lahman player biographical data |
| `Batting.csv` | Yes | Lahman batting statistics |
| `Fielding.csv` | Yes | Position data |
| `HallOfFame.csv` | Optional | HOF badges, filters, Case Mode |
| `FantasyPros_2026_Draft_H_Rankings.csv` | For draft/sleepers | Expert rankings |
| `FantasyPros_2026_Hitter_MLB_ADP_Rankings.csv` | For draft/sleepers | ADP / market ranks |

Lahman files: [SABR Lahman Database](https://sabr.org/lahman-database/)

### Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Open `http://localhost:8501`

### Optional environment variables

| Variable | Purpose |
|----------|---------|
| `SUITE_SUPABASE_URL` | Cloud persistence |
| `SUITE_SUPABASE_KEY` / `SUITE_SUPABASE_ANON_KEY` | Supabase client |
| `SUITE_AUTH_ENABLED` | Real Account sign-in |
| `AMI_REPO_PATH` | Local AMI instant solver |

Configure secrets in `.streamlit/secrets.toml` for Streamlit Cloud (see `.streamlit/secrets.toml.example`).

### Streamlit Cloud deployment

- **Repository:** `Coakley11/baseball-stat-app`
- **Branch:** `dev`
- **Main file:** `streamlit_app.py` (lowercase — required on Linux)
- Build marker: `deploy_commit.txt` + `suite_deploy_marker.py`

---

## 19. Roadmap

**Near term**
- [ ] Full pytest suite green (draft regression suite is green; broader suite cleanup in progress)
- [ ] AMI solver routing polish for bust-risk and multi-team roster-needs questions
- [ ] Draft Room immediate force-save on widget change (documented partial in acceptance matrix)
- [ ] Richer AMI context for Career Totals, Leaderboards, Valuation standalone pages

**Medium term**
- [ ] Pitcher scoring and two-way player support in draft engine
- [ ] In-season waiver wire recommendations tied to Standings category gaps
- [ ] Mobile-optimized Live Draft Room layout
- [ ] CI matrix with targeted draft regression on every PR

**Explored / deferred**
- Keeper/dynasty draft modes
- Auction draft support
- External league import (ESPN/Yahoo API)

---

## 20. Screenshots

> Enable **Portfolio Screenshot Mode** in the sidebar before capturing. See `docs/PORTFOLIO_SCREENSHOT_GUIDE.md`.

| # | Page | Filename (placeholder) | What to show |
|---|------|------------------------|--------------|
| 1 | Draft Assistant | `screenshots/01-draft-assistant-recommendations.png` | Top recommendations, needs, survival %, Why this pick |
| 2 | Live Draft Room | `screenshots/02-live-draft-room.png` | Board, roster checklist, recommendation cards, timer |
| 3 | Sleepers & Busts | `screenshots/03-sleepers-busts.png` | Sleeper table + market vs. model scatter |
| 4 | Trend Value | `screenshots/04-trend-value.png` | Multi-player trend chart with slope/volatility |
| 5 | Comparison Tool | `screenshots/05-comparison-tool.png` | Side-by-side comparison with significance |
| 6 | Valuation | `screenshots/06-valuation.png` | Valuation score table with trend weight slider |
| 7 | ML Predictions | `screenshots/07-ml-predictions.png` | Projection table with ML adjustment columns |
| 8 | Draft Lab results | `screenshots/08-draft-lab-analysis.png` | Post-draft team analysis and pick verdicts |
| 9 | Fantasy Standings | `screenshots/09-standings-tracker.png` | Roto standings with category breakdown |
| 10 | Baseball Insight | `screenshots/10-baseball-insight-ami.png` | Sidebar insight + returned AMI answer |

---

## Testing

The project includes **150+ automated test modules** covering draft scoring, persistence, multiplayer sync, AMI context, page state, and analytics engines.

### Run all tests

```bash
python -m pytest
```

### Targeted draft regression suite

Core draft system tests (scoring, live draft, multiplayer, handoff, AMI helpers):

```bash
python -m pytest ^
  tests/test_live_draft_roster_slots.py ^
  tests/test_live_draft_decision_panels.py ^
  tests/test_live_draft_polish.py ^
  tests/test_draft_score_display.py ^
  tests/test_draft_actions.py ^
  tests/test_draft_ami_helpers.py ^
  tests/test_suite_storage_supabase.py ^
  tests/test_draft_lab_analyze_handoff_smoke.py ^
  tests/test_draft_pick_commit.py ^
  tests/test_draft_state.py ^
  tests/test_multiplayer_draft_acceptance.py ^
  -q
```

### Broader draft + live draft coverage

```bash
python -m pytest tests/test_draft_*.py tests/test_live_draft_*.py -q
```

### Persistence / page-state smoke

```bash
python -m pytest tests/test_*state*.py tests/test_baseball_persistence.py tests/test_page_state.py -q
```

See `docs/BASEBALL_ACCEPTANCE_MATRIX.md` for the full 14-page acceptance checklist.

---

## License & Attribution

- **Lahman Baseball Database** — historical statistics (see SABR)
- **FantasyPros** — market ranking CSVs (user-provided)
- Built by **Daniel Cohen** as a portfolio and research project

---

## Related Projects

This app integrates with the **Daniel AI Command Center** and **Applied Mathematical Intelligence** workspace suite. Baseball Insight questions route to AMI for solver-backed answers; workspace and auth are shared across apps when Supabase is configured.
