# Daniel Cohen Baseball Explorer & Fantasy Intelligence Platform

This Streamlit app is a baseball analytics and fantasy baseball decision-support platform. It combines historical MLB statistics, player comparisons, trend analysis, valuation models, ML-style projections, fantasy draft tools, live fantasy standings, lineup assistance, and trade analysis into one interactive app.

The app is designed for users who want to explore baseball data, compare players across seasons or ages, analyze statistical trends, identify fantasy sleepers and bust risks, simulate drafts, manage fantasy rosters, and make smarter draft, lineup, and trade decisions.

## Main Features

- Historical MLB player explorer

- Career totals and leaderboards

- Player comparison tool

- Statistical significance testing

- Age-based player comparison

- Advanced trend analysis

- Multi-player trend charts

- Smoothed moving-average trends

- Trend slope, volatility, consistency, and breakout/decline indicators

- Valuation score system

- ML-style player projections

- Fantasy sleepers and bust-risk analysis

- Draft Assistant Simulator

- Draft Room Simulator

- Fantasy Standings Tracker

- Fantasy Lineup Assistant / Start-Sit AI

- Trade Analyzer / Roster Move Assistant

- Draft-room syncing across fantasy pages

- Player action menus for draft, queue, comparison, trend review, trade targets, and draft simulation

## Fantasy Baseball Tools

The fantasy tools are built to help users make better decisions during and after a draft. The Draft Room tracks picks and rosters, while the Draft Assistant recommends players based on roster needs, position scarcity, fantasy edge, market rank, model rank, category fit, and projected value.

The Fantasy Sleepers page identifies players who may be undervalued by the market, while the Lineup Assistant helps evaluate who to start, sit, bench, queue, or consider in trades.

## Trend Intelligence

The Trend Value and Comparison Tool pages go beyond raw statistics. They calculate trend slope, recent slope, volatility, consistency ratings, R², and fantasy-style interpretation. This helps identify players who are improving, declining, stable, accelerating upward, or showing risky volatility.

## Current Status

This app is an evolving AI-assisted baseball analytics project. It is designed as a portfolio project showing data analysis, fantasy baseball strategy, Streamlit development, statistical reasoning, and interactive decision-support design.

## Deployment

Streamlit Cloud: branch **`dev`**, main file **`streamlit_app.py`** (lowercase — see `.streamlit/config.toml`).

**Analyze with Applied Math** appears in the sidebar right after page navigation (under Command Center). If your Cloud app tracks **`main`**, merge `dev` → `main` to ship cross-app features.

### Lahman data files

Place these CSVs in the **same directory as `streamlit_app.py`** (repo / deploy root):

| File | Required |
|------|----------|
| `People.csv` | Yes |
| `Batting.csv` | Yes |
| `Fielding.csv` | Yes |
| `HallOfFame.csv` | Optional — **required for Hall of Fame badges, filters, and Case Mode** |

`HallOfFame.csv` comes from the [Lahman database](https://sabr.org/lahman-database/). The app uses rows where `inducted == Y`. If this file is missing, Career Totals and Historical Explorer still run, but no ⭐ badges or HOF cohort statistics are available until you add it.