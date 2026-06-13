"""Deploy marker for Baseball app — compare to GitHub dev HEAD after reboot."""

from __future__ import annotations

SUITE_BUILD_LABEL = "2026-06-11-live-draft-cloud-restore-v1"
GIT_COMMIT_SHORT = "pending"
GIT_BRANCH = "dev"
TREND_ACTIVITY_DIAGNOSTICS_LIVE = True

# Commits that must be present for live draft cloud persistence + restore.
DEPLOY_COMMITS_INCLUDED = (
    "7feb3de",
    "live-draft-cloud-save-fix",
)
