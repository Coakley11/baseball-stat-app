"""Plain-language copy for ordinary users — no storage or implementation jargon."""

from __future__ import annotations

from typing import Any

# Terms that must not appear in ordinary user-facing strings (see tests/test_ui_user_copy.py).
USER_COPY_BANNED_TERMS: tuple[str, ...] = (
    "cloud save",
    "saved to cloud",
    "remote state",
    "persistence",
    "payload",
    "database row",
    "supabase",
    "session state",
    "workspace id",
    "revision",
    "serialized",
    "parsed",
    "cache",
    "migration",
    "traceback",
    "developer mode",
    "manage app",
)

SIGN_IN_PROMPT = (
    "Sign in to create or join shared drafts and leagues, and to keep your drafts, "
    "filters, and settings available between sessions."
)

SESSION_RESTORED_BANNER = "Welcome back — we restored your last settings."

SETTINGS_SAVED_TOAST = "Settings saved"

SAVE_STATUS_HEADING = "Save status"

SAVE_TEMP_SESSION = (
    "Saves here are temporary — they will disappear when the app restarts."
)
SAVE_SIGN_IN_FOR_ACCOUNT = "Sign in to save drafts and settings to your account."
SAVE_SIGN_IN_CROSS_DEVICE = (
    "Sign in so your saved drafts appear on every device after you come back."
)
SAVE_DEMO_SIGN_IN = (
    "You are browsing as a guest. Sign in to keep saved drafts tied to your account."
)
SAVE_VERIFIED = "Your saved drafts are backed up to your account."
SAVE_VERIFIED_COUNT = "Your account has {count} saved draft(s) available after restart."
SAVE_NOT_CONFIRMED = (
    "We could not confirm your online backup yet. Try saving again after signing in."
)

DRAFT_SAVED_LIBRARY = "Draft saved to your Draft Library."
DRAFT_SAVED_LIBRARY_NAMED = "Saved **{name}** to your Draft Library."
DRAFT_SAVED_WITH_PLAYERS = "Saved **{name}** ({count} players) to your Draft Library."

SHARED_DRAFT_CREATED = (
    "Shared draft created successfully. You can find it in the Draft Library."
)
SHARED_LEAGUE_SAVED = (
    "**{league}** saved. Your team: **{team}**. "
    "You can invite managers from the league panel."
)
SHARED_LEAGUE_LOCAL_ONLY = (
    "League saved on this device. Online sync did not confirm — "
    "other devices may not see it yet."
)
SHARED_LEAGUE_BACKUP_UNCONFIRMED = (
    "League saved on this device, but we could not confirm your online backup yet. "
    "Try again later or sign out and back in."
)

LIBRARY_NOT_RESTORED = (
    "Your saved drafts did not load in this session. Sign in with the same account, "
    "or try again in a moment."
)
LIBRARY_EMPTY_SLOT = (
    "Your account loaded an empty save slot. Try signing out and back in, "
    "or save a draft again."
)

TRADE_PROPOSED = "Trade offer sent."
TRADE_ACCEPTED = "Trade accepted. Both rosters have been updated."
TRADE_DECLINED = "Trade declined."

UPLOADED_DRAFT_READY = "Your uploaded draft is ready to review."

LINEUP_SAVED = "Your lineup has been saved."

DRAFT_BOARD_SAVED = "Saved {count} pick(s) to your Draft Library."
DRAFT_BOARD_SAVED_ACCOUNT = "Saved {count} pick(s) to your account."
DRAFT_BOARD_DEVICE_ONLY = (
    "Saved {count} pick(s) on this device only. Sign in to keep them after the app restarts."
)
DRAFT_BOARD_BACKUP_FAILED = (
    "Saved {count} pick(s) on this device, but your online backup did not confirm. "
    "Stay on this page and try **Save Draft Board Now** again in a moment."
)
DRAFT_BOARD_SAVE_FAILED = "Could not save your draft board right now. Try again in a moment."

DRAFT_LAB_LOAD_FAILED = (
    "Could not open this draft in Draft Lab. Try **Set Active** again or choose "
    "a different saved draft."
)

CREATION_STILL_WORKING = (
    "Still setting up your draft… This can take a moment on first load."
)

IMPORT_TEAM_MISMATCH = (
    "Your league team list does not match the uploaded file. Re-import or edit team names."
)
IMPORT_BOARD_MISMATCH = (
    "Draft board team names do not match your uploaded file. Import again to sync them."
)
IMPORT_ROOM_MISMATCH = (
    "Draft room team names do not match your uploaded file. Import again to sync them."
)
IMPORT_TEAMS_MATCH = "Team names from your file match the draft board and league list."

WORKSPACE_OWNERSHIP_WARNING = (
    "This account cannot use that profile. We switched you to your own workspace."
)

SAVED_SESSION_CAPTION = "We remember your last page and filter choices."

SAVE_DRAFT_CAPTION = (
    "Saved to your Draft Library. Saving does not change your Active Draft unless you choose Set Active."
)


def contains_banned_user_term(text: str) -> bool:
    low = str(text or "").lower()
    return any(term in low for term in USER_COPY_BANNED_TERMS)


def format_user_error(exc: BaseException | str, *, developer_mode: bool = False) -> str:
    """Hide tracebacks and infrastructure errors from ordinary users."""
    if developer_mode:
        return str(exc)
    msg = str(exc or "").strip()
    if not msg:
        return "Something went wrong. Try again in a moment."
    low = msg.lower()
    if any(
        token in low
        for token in (
            "traceback",
            'file "',
            "line ",
            "pgrst",
            "postgrest",
            "supabase",
            "runtimeerror:",
            "keyerror:",
            "typeerror:",
        )
    ):
        return "Something went wrong. Try again in a moment."
    if len(msg) > 180:
        return "Something went wrong. Try again in a moment."
    return msg


def format_save_status_banner(status: dict[str, Any]) -> tuple[str, str, bool]:
    """Map durability status dict to plain heading + optional warning. Returns (heading, warning, ok)."""
    if not isinstance(status, dict):
        return SAVE_VERIFIED, "", True
    if status.get("durable_persistence"):
        count = int(status.get("cloud_saved_draft_count") or 0)
        if count > 0:
            label = SAVE_VERIFIED_COUNT.format(count=count)
        else:
            label = SAVE_VERIFIED
        return label, "", True
    if not status.get("cloud_enabled"):
        return SAVE_TEMP_SESSION, SAVE_TEMP_SESSION, False
    # Guest / demo without durable verification
    if status.get("cloud_saved_draft_count", 0) and not status.get("durable_persistence"):
        return SAVE_DEMO_SIGN_IN, SAVE_SIGN_IN_CROSS_DEVICE, False
    label = SAVE_SIGN_IN_FOR_ACCOUNT
    warning = str(status.get("durability_warning") or SAVE_NOT_CONFIRMED)
    if contains_banned_user_term(warning):
        warning = SAVE_NOT_CONFIRMED
    return label, warning, False


def format_shared_league_success(*, league_label: str, my_team: str) -> str:
    league = str(league_label or "League").strip() or "League"
    team = str(my_team or "—").strip() or "—"
    return SHARED_LEAGUE_SAVED.format(league=league, team=team)


def all_user_copy_constants() -> dict[str, str]:
    """Exported user-facing strings for copy regression tests."""
    out: dict[str, str] = {}
    for name, val in globals().items():
        if not name.isupper():
            continue
        if isinstance(val, str):
            out[name] = val
    return out
