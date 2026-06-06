"""Deploy marker for Baseball app — compare to GitHub dev HEAD after reboot."""

from __future__ import annotations

SUITE_BUILD_LABEL = "2026-06-06-trend-compare-log-v1"
GIT_COMMIT_SHORT = "08094d7"
GIT_BRANCH = "dev"
TREND_ACTIVITY_DIAGNOSTICS_LIVE = True

# Commits that must be present for player_trend_viewed logging.
DEPLOY_COMMITS_INCLUDED = ("ec818df", "643641a", "0b787f5", "eb45c03", "cc9190b", "08094d7")
