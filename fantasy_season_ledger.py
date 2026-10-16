"""Season ledger: explicit scoring periods and per-period lineup snapshots.

Official league results are built period by period:

    lineup snapshot -> period player stats -> finalized period result
    -> cumulative league totals -> roto standings

This module owns the first link — the calendar and the lineup each team used for each
period. Stored under ``context["workflow"]["season_ledger"]`` (versioned):

    {
      "version": 1,
      "league_id": "...",
      "calendar": {"season": 2026, "first_day": "2026-03-26", "period_days": 7, "count": 27},
      "periods": {
        "P1": {"period_id": "P1", "number": 1, "label": "Week 1",
               "start": "2026-03-26", "end": "2026-04-01",      # inclusive MLB game dates
               "lineups": {team: snapshot}, "result": {...},      # result written at finalization
               "finalized_at": "", "finalized_by": {}, "audit": [...]},
        ...
      },
    }

Period status is derived, never stored: ``finalized`` once finalized, else ``upcoming``
before its start date, ``active`` during it, ``locked`` after its end (awaiting
finalization). Dates are compared in US Eastern time, the calendar MLB game dates use.

Lineup rule (unchanged product behavior): a team's saved lineup for a period is its
lock. New: a period's lineups also lock when the period starts; after that only the
commissioner may set a missing/late lineup, and the snapshot records that it was set
after the lock. Nothing may change a finalized period.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any

LEDGER_KEY = "season_ledger"
LEDGER_VERSION = 1
LEAGUE_TZ = "America/New_York"

PERIOD_UPCOMING = "upcoming"
PERIOD_ACTIVE = "active"
PERIOD_LOCKED = "locked"
PERIOD_FINALIZED = "finalized"

ACTING_OWNER = "owner"
ACTING_COMMISSIONER_PROXY = "commissioner_proxy"
ACTING_COMMISSIONER = "commissioner"

MAX_PERIODS = 30


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def league_today(now: datetime | None = None) -> date:
    """Today's date in the league time zone (US Eastern), or the given moment's date there."""
    moment = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(ZoneInfo(LEAGUE_TZ)).date()
    except Exception:
        return moment.date()


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


# --- ledger access -------------------------------------------------------------------


def get_season_ledger(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """The league's ledger, or None for a legacy league that has not started one."""
    if not isinstance(context, dict):
        return None
    ledger = (context.get("workflow") or {}).get(LEDGER_KEY)
    if not isinstance(ledger, dict) or not isinstance(ledger.get("periods"), dict):
        return None
    return ledger


def ledger_initialized(context: dict[str, Any] | None) -> bool:
    return bool(get_season_ledger(context) and get_season_ledger(context)["periods"])


def _ledger_for_write(context: dict[str, Any]) -> dict[str, Any]:
    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    ledger = workflow.get(LEDGER_KEY)
    if not isinstance(ledger, dict):
        ledger = {"version": LEDGER_VERSION, "periods": {}, "calendar": {}}
        workflow[LEDGER_KEY] = ledger
    ledger.setdefault("periods", {})
    ledger.setdefault("calendar", {})
    ledger["version"] = LEDGER_VERSION
    return ledger


def period_id_for(number: int) -> str:
    return f"P{int(number)}"


def list_periods(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    ledger = get_season_ledger(context)
    if not ledger:
        return []
    periods = [p for p in ledger["periods"].values() if isinstance(p, dict)]
    return sorted(periods, key=lambda p: int(p.get("number") or 0))


def get_period(context: dict[str, Any] | None, number: int) -> dict[str, Any] | None:
    ledger = get_season_ledger(context)
    if not ledger:
        return None
    period = ledger["periods"].get(period_id_for(number))
    return period if isinstance(period, dict) else None


def period_status(period: dict[str, Any] | None, *, now: datetime | None = None) -> str:
    if not isinstance(period, dict):
        return ""
    if str(period.get("finalized_at") or "").strip():
        return PERIOD_FINALIZED
    today = league_today(now)
    start = _as_date(period.get("start"))
    end = _as_date(period.get("end"))
    if start and today < start:
        return PERIOD_UPCOMING
    if end and today > end:
        return PERIOD_LOCKED
    return PERIOD_ACTIVE


def period_date_label(period: dict[str, Any] | None) -> str:
    if not isinstance(period, dict):
        return ""
    start, end = _as_date(period.get("start")), _as_date(period.get("end"))
    if not start or not end:
        return ""
    if start.year == end.year:
        return f"{start.strftime('%b')} {start.day} – {end.strftime('%b')} {end.day}, {end.year}"
    return f"{start.isoformat()} – {end.isoformat()}"


# --- calendar ------------------------------------------------------------------------


def configure_season_calendar(
    context: dict[str, Any],
    *,
    first_day: date | str,
    period_count: int,
    period_days: int = 7,
    season: int | None = None,
) -> tuple[bool, str]:
    """Create the league's scoring periods. Finalized periods are never rewritten.

    Re-running with a different calendar is allowed only while no period is finalized;
    after that the calendar is fixed (changing boundaries would rewrite history).
    """
    start = _as_date(first_day)
    if start is None:
        return False, "Choose a valid first day for Week 1."
    count = int(period_count or 0)
    days = int(period_days or 0)
    if not 1 <= count <= MAX_PERIODS:
        return False, f"Choose between 1 and {MAX_PERIODS} scoring periods."
    if not 1 <= days <= 14:
        return False, "A scoring period must be 1 to 14 days."
    existing = get_season_ledger(context)
    if existing and any(str(p.get("finalized_at") or "") for p in existing["periods"].values() if isinstance(p, dict)):
        return False, "A period is already finalized, so the season calendar can no longer change."

    ledger = _ledger_for_write(context)
    old_periods = ledger.get("periods") or {}
    periods: dict[str, Any] = {}
    for i in range(count):
        number = i + 1
        p_start = start + timedelta(days=i * days)
        p_end = p_start + timedelta(days=days - 1)
        pid = period_id_for(number)
        prior = old_periods.get(pid) if isinstance(old_periods.get(pid), dict) else {}
        periods[pid] = {
            "period_id": pid,
            "number": number,
            "label": f"Week {number}",
            "start": p_start.isoformat(),
            "end": p_end.isoformat(),
            # Keep lineups already saved for this period number when the calendar is
            # adjusted before anything is finalized.
            "lineups": copy.deepcopy(prior.get("lineups") or {}),
            "result": {},
            "finalized_at": "",
            "finalized_by": {},
            "audit": list(prior.get("audit") or []),
        }
    ledger["periods"] = periods
    ledger["calendar"] = {
        "season": int(season or start.year),
        "first_day": start.isoformat(),
        "period_days": days,
        "count": count,
        "configured_at": _utc_now_iso(),
    }
    try:
        from fantasy_league_identity import resolve_canonical_league_id

        ledger["league_id"] = str(resolve_canonical_league_id(context) or "")
    except ImportError:
        ledger["league_id"] = str(context.get("league_context_id") or "")
    return True, ""


def current_period_number(context: dict[str, Any] | None, *, now: datetime | None = None) -> int | None:
    """The first period that is not finalized (the one the league is working on)."""
    for period in list_periods(context):
        if period_status(period, now=now) != PERIOD_FINALIZED:
            return int(period["number"])
    return None


# --- lineup snapshots ----------------------------------------------------------------


def _row_name(row: Any) -> str:
    for col in ("Player", "fullName", "player_name"):
        val = row.get(col) if hasattr(row, "get") else None
        if val is not None and str(val).strip() and str(val).lower() != "nan":
            return str(val).strip()
    return ""


def _row_id(row: Any) -> str:
    for col in ("MLBAM ID", "player_id", "mlbam_id", "playerID", "ID"):
        val = row.get(col) if hasattr(row, "get") else None
        if val is not None and str(val).strip() and str(val).lower() not in ("nan", "none"):
            text = str(val).strip()
            return text[:-2] if text.endswith(".0") else text
    return ""


def _row_eligible_positions(row: Any) -> list[str]:
    try:
        from fantasy_position_eligibility import eligible_positions_from_row

        return sorted(eligible_positions_from_row(row))
    except ImportError:
        pos = str((row.get("Primary Position") if hasattr(row, "get") else "") or "").strip().upper()
        return [pos] if pos else []


def build_lineup_snapshot(
    *,
    team: str,
    slots: list[str],
    slot_assignments: dict[str, str],
    roster_df: Any,
    owner_of: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Freeze who starts, who sits, which slots are empty, and each player's eligibility.

    ``slot_assignments`` maps slot keys (e.g. ``OF``, ``OF_2``, ``UTIL``) to player names.
    ``owner_of`` maps player_key -> owning team at snapshot time (league ownership map).
    """
    from fantasy_league_context import normalize_player_key

    try:
        from fantasy_lineup_ui import build_slot_key_labels

        labels = build_slot_key_labels(list(slots))
        slot_of_key = {label.key: label.base_slot for label in labels}
        slot_keys = [label.key for label in labels]
    except ImportError:
        slot_of_key = {s: s for s in slots}
        slot_keys = list(slots)

    rows: dict[str, Any] = {}
    if roster_df is not None and not getattr(roster_df, "empty", True):
        for _, row in roster_df.iterrows():
            name = _row_name(row)
            if name:
                rows[name] = row

    def player_entry(name: str) -> dict[str, Any]:
        row = rows.get(name)
        key = normalize_player_key(name)
        return {
            "player_name": name,
            "player_key": key,
            "player_id": _row_id(row) if row is not None else "",
            "eligible_positions": _row_eligible_positions(row) if row is not None else [],
            "owner_at_snapshot": str((owner_of or {}).get(key) or team),
        }

    starters: list[dict[str, Any]] = []
    empty_slots: list[str] = []
    started: set[str] = set()
    for key in slot_keys:
        name = str(slot_assignments.get(key) or "").strip()
        base = str(slot_of_key.get(key) or key)
        if not name:
            empty_slots.append(base)
            continue
        entry = player_entry(name)
        entry["slot_key"] = key
        entry["slot"] = base
        try:
            from fantasy_lineup_fill import can_fill

            entry["eligible_for_slot"] = bool(can_fill(entry["eligible_positions"], base)) if entry["eligible_positions"] else None
        except ImportError:
            entry["eligible_for_slot"] = None
        starters.append(entry)
        started.add(name)
    bench = [player_entry(name) for name in sorted(rows) if name not in started]
    return {
        "team": str(team or "").strip(),
        "version": LEDGER_VERSION,
        "slots": list(slots),
        "starters": starters,
        "bench": bench,
        "empty_slots": empty_slots,
    }


def save_period_lineup(
    context: dict[str, Any],
    *,
    number: int,
    team: str,
    snapshot: dict[str, Any],
    actor: dict[str, Any],
    is_commissioner: bool = False,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Store a team's lineup snapshot for a period.

    Owners may set lineups before the period starts. After the start (or once the team
    already saved) only the commissioner may set a lineup, and the snapshot is marked
    ``set_after_lock``. A finalized period is never changed.
    """
    period = get_period(context, number)
    if period is None:
        return False, f"Week {int(number)} is not on the league calendar."
    status = period_status(period, now=now)
    if status == PERIOD_FINALIZED:
        return False, f"{period['label']} is finalized and can no longer change."
    team = str(team or "").strip()
    existing = (period.get("lineups") or {}).get(team)
    late = status in (PERIOD_ACTIVE, PERIOD_LOCKED)
    if (late or isinstance(existing, dict)) and not is_commissioner:
        if isinstance(existing, dict):
            return False, f"{team}'s {period['label']} lineup is already locked."
        return False, f"{period['label']} has started; lineups are locked. Ask the commissioner."
    stored = copy.deepcopy(snapshot)
    stored["saved_at"] = _utc_now_iso()
    stored["saved_by"] = dict(actor or {})
    stored["set_after_lock"] = bool(late)
    stored["replaced_previous"] = isinstance(existing, dict)
    ledger = _ledger_for_write(context)
    target = ledger["periods"][period_id_for(number)]
    target.setdefault("lineups", {})[team] = stored
    target.setdefault("audit", []).append(
        {
            "at": stored["saved_at"],
            "action": "lineup_replaced" if stored["replaced_previous"] else "lineup_set",
            "team": team,
            "actor": dict(actor or {}),
            "after_lock": bool(late),
        }
    )
    return True, ""


def get_period_lineup(context: dict[str, Any] | None, number: int, team: str) -> dict[str, Any] | None:
    period = get_period(context, number)
    if not period:
        return None
    snap = (period.get("lineups") or {}).get(str(team or "").strip())
    return copy.deepcopy(snap) if isinstance(snap, dict) else None
