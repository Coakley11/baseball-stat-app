"""Quick Guide copy for each page — "What it does / When to use it / Main outputs" cards.

Moved verbatim out of ``streamlit_app.py`` so the AMI assistant's help registry reuses the
exact text users see (``streamlit_app.render_page_guide`` imports it from here).
"""

PAGE_GUIDES = {
    "Historical Explorer": {
        "purpose": "Search Lahman seasons by year, position, and team.",
        "when": "When you want season-by-season stats for many players at once.",
        "outputs": "Sortable table, top-10 bar chart, and optional scatterplots for the filtered set.",
    },
    "Career Totals": {
        "purpose": "Roll up career counting and rate stats across a year range.",
        "when": "When you care about full-career production, not one season.",
        "outputs": "The leader's career in numbers and a top-10 chart first; filters, Hall of Fame Case Mode and the full career table under Explore more.",
    },
    "Leaderboards": {
        "purpose": "Rank players on a single stat with quick filters.",
        "when": "When you want a simple who-leads-in-HR/OPS view.",
        "outputs": "Leaderboard table and top-10 chart for the chosen stat.",
    },
    "Comparison Tool": {
        "purpose": "Compare up to three players side by side using stats, trends, and optional significance tests.",
        "when": "When you are choosing between a few names and want the same view for each.",
        "outputs": "Who leads in HR, RBI, SB, OBP and OPS over the same seasons, with head-to-head bars; tables, trend charts and significance tests under Explore more.",
    },
    "Trend Value": {
        "purpose": "See who is improving or fading over recent seasons.",
        "when": "During draft prep or when judging breakout vs decline risk.",
        "outputs": "The fastest riser and biggest drop in your stat with a season-by-season chart; the trend table, breakout/decline lists and player dashboards under Explore more.",
    },
    "Valuation": {
        "purpose": "Ranks hitters by mixing how good they have been lately with whether their stats are rising or falling.",
        "when": "During draft prep or trade talks when you want one short list of names worth a closer look.",
        "outputs": "The top hitter with production and trend ranks and the weights, plus a top-10 chart; the full table (Valuation Score, Current Score, Trend Score, stats) under Explore more.",
        "extra": [
            "<strong>Valuation Score (0–100):</strong> Higher is better. 100.00 = top of your filtered list; 0.00 = bottom.",
            "<strong>Current Score:</strong> How strong recent counting and rate stats are in the year window you chose.",
            "<strong>Trend Score:</strong> Whether production is trending up or down (larger = more improvement).",
            "<strong>Reading the table:</strong> Sort by Valuation Score, then check HR, RBI, OPS, and the two component scores.",
            "<strong>For fantasy:</strong> Shortlist adds, draft targets, and trade candidates here, then confirm on Trend Value or Comparison.",
        ],
    },
    "ML Predictions": {
        "purpose": "Machine-learning next-season stat projections for each hitter.",
        "when": "When you want model-based forecasts beyond simple trends.",
        "outputs": "The top projected hitters for your sort, with the model's confidence label and its held-out accuracy; the full table, tuning and feature importance under Explore more.",
    },
    "Fantasy Sleepers & Busts": {
        "purpose": "Find where our model and the draft market (FantasyPros rankings, ADP) disagree.",
        "when": "During draft prep or on draft day when you want buy-low and avoid-overpay lists.",
        "outputs": "Top sleeper and bust-risk cards (model rank, market rank, Fantasy Edge); the edge map, full tables and filters under Explore more.",
    },
    "Draft Room Simulator": {
        "purpose": "Set up a league and log every pick yourself, then view rosters and grade the draft.",
        "when": "For a practice draft, or to mirror a draft running on another site. Draft Assistant reads this board.",
        "outputs": "Draft board, roster views, and post-draft grades.",
    },
    "Draft Assistant Simulator": {
        "purpose": "Recommend your next pick from needs, scarcity, and projections.",
        "when": "While drafting, after picks are entered in Draft Room Simulator or Live Draft Room.",
        "outputs": "Ranked available players with plain-language reasons.",
    },
    "Draft Lab / Simulation": {
        "purpose": "The computer runs a four-team mock draft with Draft Assistant-style pick logic, then analyzes it.",
        "when": "When you want to test a draft strategy or compare how different approaches build rosters.",
        "outputs": "Draft board, team rosters, team rankings, best/questionable picks, position gaps, and exports.",
    },
    "Live Draft Room": {
        "purpose": "Draft with your league in real time: a shared snake draft with pick timers, manual picks and auto-pick rules.",
        "when": "On draft day with your league, or a solo practice run with the same room.",
        "outputs": "Live draft board, team rosters, recommendations, exports, and the saved draft for your league.",
    },
    "Saved Draft Library": {
        "purpose": "Browse, rename, duplicate, share and activate saved drafts from Live Draft Room and Draft Room Simulator.",
        "when": "After finishing a draft or when switching between your real league, mock drafts and practice rosters.",
        "outputs": "The active league for League Standings, Lineup Assistant and Waiver Wire; every saved draft is kept.",
    },
    "Fantasy Standings Tracker": {
        "purpose": "Score every fantasy team with current-season stats.",
        "when": "In-season to see category standings and roster totals.",
        "outputs": "Team ranks and category breakdowns (loads stats for Lineup Assistant too).",
    },
    "Fantasy Lineup Assistant": {
        "purpose": "Set your weekly starting lineup (Lineup Management), or build, check and propose trades (Trade Center).",
        "when": "Each scoring period, and whenever you are weighing a trade.",
        "outputs": "Whether this week's lineup is complete and saved, the lineup board (starters, open spots, bench), and a trade verdict card; start/sit recommendations and lineup diagnosis under Explore more.",
    },
    "Waiver Wire / Add-Drop Center": {
        "purpose": "Waiver pool, team needs, add/drop recommendations, and weekly transaction planner.",
        "when": "In-season with an Active Draft from Saved Drafts.",
        "outputs": "Waiver-eligible players, recommended adds/drops, pending moves, and league activity log.",
    },
}
