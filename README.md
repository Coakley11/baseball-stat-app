# baseball-stat-app
# Baseball Analytics App

This project is an interactive baseball statistics application built with Python and Streamlit.

# ⚾ Daniel Cohen Baseball Explorer

Advanced Baseball Analytics, Fantasy Valuation & Draft Intelligence Platform built with Streamlit, Python, pandas, and machine learning concepts.

---

# Overview

Daniel Cohen Baseball Explorer is an interactive baseball analytics and fantasy baseball intelligence application that combines:

- Historical MLB statistical exploration
- Career analytics
- Interactive scatterplots and visualizations
- Machine learning projection concepts
- Fantasy valuation modeling
- FantasyPros and ADP integration
- Fantasy sleepers and bust analysis
- Draft assistant simulation
- Position scarcity modeling
- Team category strength analysis
- Fantasy market inefficiency analysis

The app is designed to function as both:
- a baseball analytics platform
- and a fantasy baseball draft intelligence system.

---

# Main Features

# 1. Historical Explorer

Explore player statistics by season across MLB history.

## Features
- Filter by:
  - Year
  - Team
  - League
  - Position
  - Bats
  - Statistical minimums
- Sort by any statistic
- Interactive scatterplots
- Hover tooltips with detailed player information
- Focus View and Full Outlier View
- Team color visualization
- League color visualization

## Supported Stats
- G
- AB
- R
- H
- 2B
- 3B
- HR
- RBI
- SB
- BB
- BA
- OBP
- SLG
- OPS

---

# 2. Career Totals Explorer

Analyze full career performance.

## Features
- Career totals aggregation
- Team-specific career filtering
- Franchise normalization
- Primary position detection
- Career scatterplots
- Interactive filtering
- Historical franchise mapping

## Position Order
- C
- 1B
- 2B
- 3B
- SS
- OF
- DH
- P

---

# 3. Interactive Scatterplots

Advanced visual analytics system.

## Features
- Dynamic X/Y axis selection
- Color by:
  - Team
  - League
  - Position
  - Bats
- Bubble size scaling
- Hover tooltips
- Focus View
- Full Outlier View
- Scrollable outlier visualization

## Team Color System
Uses modern MLB franchise colors:
- Dodgers → light blue
- Yankees → dark navy
- Giants → orange
- Cardinals → red
- etc.

Historical teams map to modern franchise colors:
- Florida Marlins → Miami Marlins color
- Brooklyn Dodgers → Dodgers color

Unknown franchises:
- Display as "Unknown"
- Gray color

## League Color System
- American League → blue
- National League → red
- Unknown → gray

---

# 4. Trend & Valuation Analyzer

Analyzes player trends and fantasy valuation.

## Features
- Multi-year trend analysis
- Statistical slope calculations
- Trend heat maps
- Positive/negative trend arrows
- Fantasy valuation modeling
- Breakout and decline detection

## Heat Map Logic
- Dark green → strong positive trend
- Light green → mild positive trend
- Light red → mild decline
- Dark red → strong decline

## Trend Statistics
- HR trend
- RBI trend
- SB trend
- OPS trend
- BA trend
- OBP trend
- SLG trend

---

# 5. Machine Learning Projection Engine

ML-based fantasy projection system.

## Features
- Multi-year historical input modeling
- Age-based adjustments
- Regression-to-mean concepts
- Trend continuation modeling
- Future production estimation

## Projection Inputs
- Recent seasonal statistics
- Trend metrics
- Age
- Position
- Historical production

## Projection Outputs
- Projected fantasy value
- Expected future production
- Fantasy ranking estimates

---

# 6. Fantasy Sleepers & Busts

Fantasy market inefficiency analysis page.

## Features
- FantasyPros rankings integration
- ADP integration
- Market vs model comparison
- Fantasy Edge calculations
- Sleeper detection
- Bust risk detection
- Risk disagreement analysis

## Metrics

### Current Production Score
Measures recent actual fantasy production using:
- HR
- RBI
- SB
- OPS
- Runs
- Other fantasy-relevant stats

### Expected Fantasy Value
Projects future fantasy value using:
- ML projections
- Trend analysis
- Fantasy valuation modeling

### Fantasy Edge
Measures disagreement between:
- Market Rank
- Model Rank

Formula:

Fantasy Edge = Market Rank − Model Rank

Positive Fantasy Edge:
- Model likes player MORE than market
- Possible sleeper

Negative Fantasy Edge:
- Market likes player MORE than model
- Possible bust risk

### Risk Disagreement
Measures:
- Expert disagreement
- Volatility
- Projection uncertainty

---

# 7. Fantasy Edge Map

Interactive fantasy scatterplot system.

## Axes
- X-axis → Market Rank
- Y-axis → Model Rank

## Interpretation
Above diagonal:
- Model ranks player BETTER than market
- Possible sleeper

Below diagonal:
- Market ranks player BETTER than model
- Possible bust risk

## Features
- Focus View
- Full Outlier View
- Team color visualization
- Hover tooltips
- Dynamic filtering

---

# 8. Draft Assistant Simulator

Interactive fantasy draft intelligence engine.

## Features
- Draft recommendations
- Team category analysis
- Position scarcity modeling
- Dynamic draft explanations
- Roster heat maps
- Best fit vs best value analysis
- League scoring customization
- Draft board simulation

---

# Draft Assistant Metrics

## Draft Fit Score
Measures:
- Overall draft recommendation quality

Combines:
- Expected Fantasy Value
- Fantasy Edge
- Position scarcity
- Category needs
- Team construction
- Risk adjustment

---

## Position Scarcity Model

Calculates:
- Value over replacement by position

Scarce positions receive bonus value:
- Catcher
- Shortstop
- Elite scarce positions

---

## Team Category Strength Analyzer

Analyzes roster strengths and weaknesses.

Categories:
- HR
- RBI
- SB
- BA
- OPS
- Runs

---

## Dynamic Draft Explanations

Generates explanations such as:

- Model strongly prefers player over market
- Improves stolen base category
- Fills scarce catcher position
- Strong positive OPS trend

---

## League Scoring Customization

Supports:
- Roto
- Points leagues
- Custom scoring weights

---

# Technologies Used

## Core Stack
- Python
- Streamlit
- pandas
- numpy
- scikit-learn
- Altair

## Data Sources
- Lahman Baseball Database
- FantasyPros Rankings
- FantasyPros ADP

---

# Deployment

Hosted using:

- Streamlit Community Cloud
- GitHub

---

# Future Planned Features

- Trade Analyzer
- Similar Player Engine
- Tier Dropoff Detection
- AI Draft Opponent Simulation
- Dynasty/Keeper Mode
- Injury Risk Modeling
- Championship Probability Modeling
- Draft Reach / Steal Meter
- Pick-Ahead Forecasting

---

# Author

Daniel Cohen

Built as an advanced baseball analytics and fantasy baseball intelligence platform combining:
- statistical analysis
- visualization
- machine learning concepts
- fantasy market analytics
- draft optimization systems

