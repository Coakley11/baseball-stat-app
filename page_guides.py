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
        "outputs": "Career table plus charts for the filtered group.",
    },
    "Leaderboards": {
        "purpose": "Rank players on a single stat with quick filters.",
        "when": "When you want a simple who-leads-in-HR/OPS view.",
        "outputs": "Leaderboard table and top-10 chart for the chosen stat.",
    },
    "Comparison Tool": {
        "purpose": "Compare up to three players side by side using stats, trends, and optional significance tests.",
        "when": "When you are choosing between a few names and want the same view for each.",
        "outputs": "Year-by-year table, career totals, trend charts, and category-style comparisons.",
    },
    "Trend Value": {
        "purpose": "See who is improving or fading over recent seasons.",
        "when": "During draft prep or when judging breakout vs decline risk.",
        "outputs": "Trend table (change columns), breakout/decline lists, and single-player dashboards.",
    },
    "Valuation": {
        "purpose": "Ranks hitters by mixing how good they have been lately with whether their stats are rising or falling.",
        "when": "During draft prep or trade talks when you want one short list of names worth a closer look.",
        "outputs": "A sortable table (Valuation Score, Current Score, Trend Score, stats) plus best/worst callouts at the bottom.",
        "extra": [
            "<strong>Valuation Score (0–100):</strong> Higher is better. 100.00 = top of your filtered list; 0.00 = bottom.",
            "<strong>Current Score:</strong> How strong recent counting and rate stats are in the year window you chose.",
            "<strong>Trend Score:</strong> Whether production is trending up or down (larger = more improvement).",
            "<strong>Reading the table:</strong> Sort by Valuation Score, then check HR, RBI, OPS, and the two component scores.",
            "<strong>For fantasy:</strong> Shortlist adds, draft targets, and trade candidates here, then confirm on Trend Value or Comparison.",
        ],
    },
    "ML Predictions": {
        "purpose": "Machine-learning style next-season stat projections.",
        "when": "When you want model-based forecasts beyond simple trends.",
        "outputs": "Ranked projection table; tune advanced blending in the expander.",
    },
    "Fantasy Sleepers & Busts": {
        "purpose": "Find undervalued players, risky market picks, and names where your projections differ from ADP.",
        "when": "During draft prep or on draft day when you want buy-low and avoid-overpay lists.",
        "outputs": "Sleeper and bust tables, market-vs-model chart, and plain-language reasons.",
    },
    "Draft Room Simulator": {
        "purpose": "Log picks, view rosters, and grade drafts.",
        "when": "During a live or mock draft — this feeds the Draft Assistant.",
        "outputs": "Pick board, roster views, and post-draft grades.",
    },
    "Draft Assistant Simulator": {
        "purpose": "Recommend your next pick from needs, scarcity, and projections.",
        "when": "While drafting, after picks are entered in Draft Room.",
        "outputs": "Ranked available players with plain-language reasons.",
    },
    "Draft Lab / Simulation": {
        "purpose": "Run a four-team mock draft with Draft Assistant-style pick logic and post-draft analysis.",
        "when": "When you want to practice draft strategy or compare how different approaches build rosters.",
        "outputs": "Draft board, team rosters, team rankings, best/questionable picks, position gaps, and exports.",
    },
    "Live Draft Room": {
        "purpose": "Run a configurable live snake draft in your browser with timers, manual picks, and auto-pick rules.",
        "when": "Mock drafts or testing draft-room flow before multi-user sync is added.",
        "outputs": "Live draft board, team rosters, recommendations, exports, and optional handoff to Draft Simulation analysis.",
    },
    "Saved Draft Library": {
        "purpose": "Browse, rename, duplicate, and activate saved draft teams from Live Draft and Simulator.",
        "when": "After finishing a draft or when switching between real team, mock drafts, and practice rosters.",
        "outputs": "Active saved draft for Standings Tracker and Lineup Assistant; multiple archives preserved.",
    },
    "Fantasy Standings Tracker": {
        "purpose": "Score every fantasy team with current-season stats.",
        "when": "In-season to see category standings and roster totals.",
        "outputs": "Team ranks and category breakdowns (loads stats for Lineup Assistant too).",
    },
    "Fantasy Lineup Assistant": {
        "purpose": "Start/sit guidance and position-valid recommended lineups.",
        "when": "Each scoring period with current stats loaded from Standings Tracker.",
        "outputs": "Starters by slot, bench list, and lineup diagnosis.",
    },
    "Waiver Wire / Add-Drop Center": {
        "purpose": "Waiver pool, team needs, add/drop recommendations, and weekly transaction planner.",
        "when": "In-season with an Active Draft from Saved Drafts.",
        "outputs": "Waiver-eligible players, recommended adds/drops, pending moves, and league activity log.",
    },
}
