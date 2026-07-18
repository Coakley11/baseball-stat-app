"""Shared draft room — explicit team ownership and claim helpers."""

from __future__ import annotations

from typing import Any


def list_room_teams(room: dict[str, Any] | None) -> list[str]:
    if not isinstance(room, dict):
        return []
    teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    if teams:
        return teams
    cfg = dict(room.get("config") or {})
    named = [str(t).strip() for t in (cfg.get("teams") or []) if str(t).strip()]
    if named:
        return named
    # Derive from pick order when persist stripped top-level teams.
    order_teams: list[str] = []
    seen: set[str] = set()
    for slot in room.get("pick_order") or []:
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("Team") or "").strip()
        if name and name not in seen:
            seen.add(name)
            order_teams.append(name)
    if order_teams:
        return order_teams
    n = int(cfg.get("num_teams") or 0)
    return [f"Team {i + 1}" for i in range(n)] if n else []


def list_required_human_teams(
    room: dict[str, Any] | None = None,
    document: dict[str, Any] | None = None,
) -> list[str]:
    """Configured human seats — denominator for Participants joined X of Y.

    Never derived from how many participants are currently visible.
    """
    teams = list_document_teams(document, session_room=room if isinstance(room, dict) else None)
    if not teams and isinstance(room, dict):
        teams = list_room_teams(room)
    return [t for t in teams if not _is_cpu_or_placeholder_team(t)]


def list_document_teams(document: dict[str, Any] | None, *, session_room: dict[str, Any] | None = None) -> list[str]:
    """Canonical team list for host lobby and guest join — same source of truth.

    Prefer shared ``document.room``; union session runtime teams so a thin/stale
    document cannot hide Team B while the host lobby still shows it.
    """
    doc_teams: list[str] = []
    if isinstance(document, dict):
        room_blob = document.get("room")
        if isinstance(room_blob, dict):
            doc_teams = list_room_teams(room_blob)
    session_teams = list_room_teams(session_room) if isinstance(session_room, dict) else []
    if not doc_teams:
        return session_teams
    if not session_teams:
        return doc_teams
    # Preserve document order; append any session-only teams.
    seen = {t.lower() for t in doc_teams}
    merged = list(doc_teams)
    for team in session_teams:
        if team.lower() not in seen:
            merged.append(team)
            seen.add(team.lower())
    return merged


def load_shared_room_document(session: dict[str, Any], *, room_code: str | None = None) -> dict[str, Any] | None:
    """Load shared room with the same global lookup + fallback guests use."""
    code = str(room_code or session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code:
        return None
    try:
        from draft_room_create_verify import load_shared_room_with_diagnostics
        from draft_room_shared_state import get_shared_room_store

        result = load_shared_room_with_diagnostics(get_shared_room_store(), code)
        doc = result.get("document")
        return doc if isinstance(doc, dict) else None
    except ImportError:
        pass
    try:
        from draft_room_shared_state import load_shared_room

        doc = load_shared_room(code)
        return doc if isinstance(doc, dict) else None
    except ImportError:
        return None


def load_shared_participants(session: dict[str, Any], *, room_code: str | None = None) -> dict[str, dict[str, Any]]:
    doc = load_shared_room_document(session, room_code=room_code)
    if not isinstance(doc, dict):
        return {}
    raw = doc.get("participants") or {}
    if isinstance(raw, dict):
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    return {}


def _host_id_aliases(session: dict[str, Any], document: dict[str, Any] | None = None) -> set[str]:
    doc = document
    if doc is None:
        doc = load_shared_room_document(session)
    try:
        from draft_room_membership import document_host_ids

        return document_host_ids(doc)
    except ImportError:
        pass
    if isinstance(doc, dict):
        return {
            str(x).strip()
            for x in (doc.get("host_participant_id"), doc.get("host_user_id"))
            if str(x or "").strip()
        }
    return set()


def _host_participant_id(session: dict[str, Any], document: dict[str, Any] | None = None) -> str:
    aliases = _host_id_aliases(session, document)
    if not aliases:
        return ""
    if isinstance(document, dict):
        primary = str(document.get("host_participant_id") or "").strip()
        if primary:
            return primary
    return next(iter(aliases))


def _participant_is_host(pid: str, host_aliases: set[str], meta: dict[str, Any] | None = None) -> bool:
    meaningful = {a for a in host_aliases if not _is_generic_local_identity(a)}
    key = str(pid or "").strip()
    if key and key in meaningful:
        return True
    if isinstance(meta, dict):
        for field in ("user_id", "account_user_id", "participant_id", "external_id"):
            alias = str(meta.get(field) or "").strip()
            if alias and not _is_generic_local_identity(alias) and alias in meaningful:
                return True
    return False


def _identity_tokens(pid: str, meta: dict[str, Any] | None) -> set[str]:
    tokens = {str(pid or "").strip()}
    if isinstance(meta, dict):
        for field in ("user_id", "account_user_id", "participant_id", "external_id"):
            tokens.add(str(meta.get(field) or "").strip())
    return {t for t in tokens if t}


def _is_generic_local_identity(value: str) -> bool:
    raw = str(value or "").strip().lower()
    return (not raw) or raw.startswith(("local:", "anonymous:", "demo:"))


def _canonical_identity_key(
    pid: str,
    meta: dict[str, Any] | None,
    *,
    host_aliases: set[str],
) -> str:
    """One stable key per human — host aliases collapse to host_participant_id.

    Generic local/anonymous ids must not collapse distinct participants (Daniel vs
    Coakley11 both getting ``local:default``) into one seat.
    """
    tokens = _identity_tokens(pid, meta)
    # Ignore generic local tokens when matching host aliases so Coakley11 cannot
    # inherit the host seat via a shared ``local:default`` user_id stamp.
    meaningful_host_aliases = {a for a in host_aliases if not _is_generic_local_identity(a)}
    host_match = tokens & meaningful_host_aliases
    if host_match:
        return sorted(host_match, key=lambda x: (len(x), x))[0]
    if isinstance(meta, dict):
        for field in ("user_id", "account_user_id", "external_id"):
            val = str(meta.get(field) or "").strip()
            if val and not _is_generic_local_identity(val):
                return val
    pid_s = str(pid or "").strip()
    if pid_s and not _is_generic_local_identity(pid_s):
        return pid_s
    return pid_s


def canonicalize_shared_room_claims(
    document: dict[str, Any] | None,
    *,
    host_aliases: set[str] | None = None,
) -> dict[str, Any]:
    """Collapse alias participant rows so one identity owns at most one team.

    Returns diagnostics + occupancy used by available-team calculation.
    """
    doc = document if isinstance(document, dict) else {}
    hosts = set(host_aliases or ())
    if not hosts:
        try:
            from draft_room_membership import document_host_ids

            hosts = document_host_ids(doc)
        except ImportError:
            hosts = {
                str(x).strip()
                for x in (doc.get("host_participant_id"), doc.get("host_user_id"))
                if str(x or "").strip()
            }

    teams = list_document_teams(doc)
    raw_participants = dict(doc.get("participants") or {})
    # identity -> chosen (pid, meta, team)
    by_identity: dict[str, tuple[str, dict[str, Any], str]] = {}
    raw_by_team: dict[str, list[str]] = {t: [] for t in teams}

    # Prefer host_participant_id records first so create-time claim wins.
    ordered_items = sorted(
        raw_participants.items(),
        key=lambda kv: (
            0 if str(kv[0]) == str(doc.get("host_participant_id") or "") else 1,
            str((kv[1] or {}).get("joined_at") or "") if isinstance(kv[1], dict) else "z",
            str(kv[0]),
        ),
    )

    for pid, meta in ordered_items:
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        if team in raw_by_team:
            raw_by_team[team].append(str(pid))
        else:
            raw_by_team.setdefault(team, []).append(str(pid))
        ident = _canonical_identity_key(str(pid), meta, host_aliases=hosts)
        if not ident:
            continue
        if ident in by_identity:
            # Same person already claimed — ignore extra seats (e.g. alias → Team B).
            continue
        by_identity[ident] = (str(pid), meta, team)

    occupancy: dict[str, dict[str, Any]] = {}
    for team in teams:
        occupancy[team] = {
            "team": team,
            "claimant_raw_ids": list(raw_by_team.get(team) or []),
            "canonical_claimant": None,
            "canonical_participant_id": "",
            "is_host": False,
            "available": True,
            "reason": "open",
        }

    for ident, (pid, meta, team) in by_identity.items():
        if team not in occupancy:
            occupancy[team] = {
                "team": team,
                "claimant_raw_ids": list(raw_by_team.get(team) or []),
                "canonical_claimant": None,
                "canonical_participant_id": "",
                "is_host": False,
                "available": True,
                "reason": "open",
            }
        is_host = _participant_is_host(pid, hosts, meta)
        display = str(meta.get("display_name") or "").strip() or ("Commissioner" if is_host else "Guest")
        slot = occupancy[team]
        if slot.get("canonical_participant_id"):
            # Two distinct identities on one team — keep first, mark conflict.
            slot["reason"] = f"claimed by {slot.get('canonical_claimant')}; conflict with {pid}"
            continue
        slot["canonical_claimant"] = display
        slot["canonical_participant_id"] = pid
        slot["canonical_identity"] = ident
        slot["is_host"] = is_host
        slot["available"] = False
        slot["reason"] = "claimed by commissioner" if is_host else f"claimed by {display}"

    # Repair document participants to canonical map (drop alias-only extra seats).
    repaired: dict[str, dict[str, Any]] = {}
    for ident, (pid, meta, team) in by_identity.items():
        entry = dict(meta)
        entry["assigned_team"] = team
        entry.setdefault("user_id", str(meta.get("user_id") or pid))
        repaired[pid] = entry

    return {
        "teams": teams,
        "host_aliases": sorted(hosts),
        "occupancy": occupancy,
        "repaired_participants": repaired,
        "identity_count": len(by_identity),
        "raw_participant_count": len(raw_participants),
    }


def session_identity_aliases(session: dict[str, Any] | None) -> set[str]:
    """Identity tokens for the *current* browser user only.

    Never pull other participants' ids from the membership map — that caused guests
    to inherit the commissioner's Team A / host role via already_joined matching.
    """
    if not isinstance(session, dict):
        return set()
    tokens: set[str] = set()
    try:
        from draft_room_participant_state import resolve_participant_id

        tokens.add(str(resolve_participant_id(session) or "").strip())
    except ImportError:
        pass
    for key in (
        "draft_room_participant_id",
        "_suite_cloud_user_id",
        "_suite_auth_user_id",
        "auth_user_id",
        "account_user_id",
        "ACTIVE_PARTICIPANT_ID_KEY",
    ):
        tokens.add(str(session.get(key) or "").strip())
    try:
        from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY

        tokens.add(str(session.get(ACTIVE_PARTICIPANT_ID_KEY) or "").strip())
    except ImportError:
        pass
    try:
        from suite_auth import AUTH_USER_ID_KEY

        tokens.add(str(session.get(AUTH_USER_ID_KEY) or "").strip())
    except ImportError:
        pass
    # Only this session's own membership row (never sibling participant keys).
    try:
        from draft_room_participant_state import MEMBERSHIP_KEY, resolve_participant_id

        membership = session.get(MEMBERSHIP_KEY)
        my_pid = str(resolve_participant_id(session) or "").strip()
        if isinstance(membership, dict) and my_pid:
            for room_mem in membership.values():
                if not isinstance(room_mem, dict):
                    continue
                meta = room_mem.get(my_pid)
                if isinstance(meta, dict):
                    tokens.add(str(meta.get("participant_id") or my_pid).strip())
                # Legacy flat shape: room_mem["participant_id"] == me
                flat_pid = str(room_mem.get("participant_id") or "").strip()
                if flat_pid and flat_pid == my_pid:
                    tokens.add(flat_pid)
    except ImportError:
        pass
    return {t for t in tokens if t}


def list_available_shared_room_teams(
    authoritative_room: dict[str, Any] | None,
    current_participant_id: str = "",
    *,
    session_room: dict[str, Any] | None = None,
    current_identity_aliases: set[str] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Authoritative open teams for join UI and claim gates.

    Uses the shared room document only for occupancy. ``session_room`` may fill
    missing team names but never invents claimants.
    """
    doc = dict(authoritative_room or {})
    if session_room and isinstance(session_room, dict):
        # Ensure team list completeness without merging session claims.
        teams = list_document_teams(doc, session_room=session_room)
        room_blob = dict(doc.get("room") or {})
        if teams and not list_room_teams(room_blob):
            room_blob["teams"] = list(teams)
            cfg = dict(room_blob.get("config") or {})
            cfg["teams"] = list(teams)
            room_blob["config"] = cfg
            doc["room"] = room_blob

    canon = canonicalize_shared_room_claims(doc)
    pid = str(current_participant_id or "").strip()
    aliases = {str(a).strip() for a in (current_identity_aliases or set()) if str(a).strip()}
    if pid:
        aliases.add(pid)
    host_aliases = set(canon.get("host_aliases") or [])
    current_idents = {
        _canonical_identity_key(a, {"user_id": a}, host_aliases=host_aliases) for a in aliases if a
    }

    def _owned_by_current(slot: dict[str, Any]) -> bool:
        owner_pid = str(slot.get("canonical_participant_id") or "").strip()
        owner_ident = str(slot.get("canonical_identity") or "").strip()
        if owner_pid and owner_pid in aliases:
            return True
        if owner_ident and owner_ident in current_idents:
            return True
        if owner_ident and owner_ident in aliases:
            return True
        raw_ids = [str(x).strip() for x in (slot.get("claimant_raw_ids") or []) if str(x).strip()]
        return bool(aliases.intersection(raw_ids))

    already_team = ""
    for team, slot in (canon.get("occupancy") or {}).items():
        if _owned_by_current(slot):
            already_team = team
            break

    available: list[str] = []
    for team in canon.get("teams") or []:
        if _is_cpu_or_placeholder_team(team):
            slot = (canon.get("occupancy") or {}).get(team) or {}
            slot["available"] = False
            slot["reason"] = "cpu_or_placeholder"
            continue
        slot = (canon.get("occupancy") or {}).setdefault(
            team,
            {
                "team": team,
                "claimant_raw_ids": [],
                "canonical_claimant": None,
                "canonical_participant_id": "",
                "available": True,
                "reason": "open",
            },
        )
        owner_pid = str(slot.get("canonical_participant_id") or "").strip()
        if not owner_pid:
            # Alias-only raw ids that were collapsed away still appear in claimant_raw_ids.
            slot["available"] = True
            slot["reason"] = "open"
            available.append(team)
            continue
        if _owned_by_current(slot):
            slot["available"] = False
            slot["reason"] = "already_claimed_by_you"
            continue
        slot["available"] = False
        available_note = slot.get("reason") or "claimed"
        slot["reason"] = available_note

    diag = {
        **canon,
        "current_participant_id": pid,
        "current_identity_aliases": sorted(aliases),
        "already_joined_team": already_team or None,
        "available_teams": list(available),
        "document_teams": list(canon.get("teams") or []),
        "session_teams": list_room_teams(session_room) if session_room else [],
        "room_code": str(doc.get("room_code") or ""),
        "draft_room_id": str(doc.get("draft_room_id") or ""),
        "room_revision": int(doc.get("revision") or 0),
        "room_status": str(doc.get("status") or ""),
        "joined_participants": dict(doc.get("joined_participants") or {}),
        "pick_order_teams": [
            str(s.get("Team") or "").strip()
            for s in (dict(doc.get("room") or {}).get("pick_order") or [])
            if isinstance(s, dict) and str(s.get("Team") or "").strip()
        ],
    }
    return available, diag


def repair_shared_document_claims(document: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with alias duplicate seats removed (one identity → one team)."""
    import copy

    out = copy.deepcopy(document) if isinstance(document, dict) else {}
    canon = canonicalize_shared_room_claims(out)
    repaired = dict(canon.get("repaired_participants") or {})
    if repaired != dict(out.get("participants") or {}):
        out["participants"] = repaired
        out["_claims_repaired"] = True
    return out


def _is_cpu_or_placeholder_team(name: str) -> bool:
    raw = str(name or "").strip().lower()
    if not raw:
        return True
    # Whole-token / prefix checks — avoid matching ordinary names containing "bot".
    if raw.startswith("cpu ") or raw.startswith("cpu-") or raw == "cpu":
        return True
    tokens = raw.replace("-", " ").replace("_", " ").split()
    blocked = {"cpu", "bot", "placeholder", "computer"}
    if any(tok in blocked for tok in tokens):
        return True
    if "ai team" in raw or "auto-draft" in raw or "auto draft" in raw:
        return True
    return False


def open_teams_for_join(
    document: dict[str, Any],
    *,
    current_participant_id: str = "",
) -> list[str]:
    """Human teams not yet claimed — wrapper over authoritative calculator."""
    available, _diag = list_available_shared_room_teams(
        document,
        current_participant_id=current_participant_id,
    )
    return available


def team_claim_rows(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One row per fantasy team: team name, claim status, owner label, host flag."""
    doc = document
    if doc is None:
        doc = load_shared_room_document(session)
    if not isinstance(doc, dict):
        doc = {"room": room if isinstance(room, dict) else {}, "participants": load_shared_participants(session)}
    # Ensure team list includes session teams for lobby display.
    teams = list_document_teams(doc, session_room=room if isinstance(room, dict) else None)
    room_blob = dict(doc.get("room") or {})
    if teams:
        room_blob["teams"] = list(teams)
        doc = dict(doc)
        doc["room"] = room_blob

    available, diag = list_available_shared_room_teams(doc, current_participant_id="")
    _ = available
    session["_draft_room_claim_diag"] = diag
    occupancy = dict(diag.get("occupancy") or {})
    rows: list[dict[str, Any]] = []
    for team in teams:
        slot = occupancy.get(team) or {}
        claimed = bool(slot.get("canonical_participant_id"))
        rows.append(
            {
                "team": team,
                "claimed": claimed,
                "owner_label": "Host" if slot.get("is_host") else str(slot.get("canonical_claimant") or ""),
                "is_host": bool(slot.get("is_host")),
                "participant_id": str(slot.get("canonical_participant_id") or ""),
                "claim_reason": str(slot.get("reason") or ""),
                "claimant_raw_ids": list(slot.get("claimant_raw_ids") or []),
            }
        )
    return rows


def count_joined_teams(session: dict[str, Any], room: dict[str, Any]) -> tuple[int, int]:
    """Return (claimed_human_seats, required_human_seats).

    Denominator is always configured required human teams (e.g. 2), never the
    size of a stale/partial participant list.
    """
    doc = load_shared_room_document(session)
    required = list_required_human_teams(room, document=doc if isinstance(doc, dict) else None)
    rows = team_claim_rows(session, room, document=doc if isinstance(doc, dict) else None)
    claimed_teams = {
        str(r.get("team") or "").strip()
        for r in rows
        if r.get("claimed") and str(r.get("team") or "").strip()
    }
    if required:
        joined = sum(1 for team in required if team in claimed_teams)
        return joined, len(required)
    total = len(rows)
    joined = sum(1 for r in rows if r.get("claimed"))
    return joined, total


def claimed_team_count(session: dict[str, Any], room: dict[str, Any]) -> int:
    joined, _total = count_joined_teams(session, room)
    return joined


def distinct_claimed_owner_count(session: dict[str, Any], room: dict[str, Any] | None = None) -> int:
    """Distinct canonical participant IDs with a claimed team."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return 0
    owners: set[str] = set()
    for row in team_claim_rows(session, live):
        if not row.get("claimed"):
            continue
        pid = str(row.get("participant_id") or "").strip()
        if pid:
            owners.add(pid)
    return len(owners)


def waiting_participant_count(session: dict[str, Any], room: dict[str, Any]) -> int:
    joined, total = count_joined_teams(session, room)
    return max(0, int(total) - int(joined))


def format_team_claim_status(session: dict[str, Any], row: dict[str, Any]) -> str:
    """User-facing team line using canonical participant identity."""
    team = str(row.get("team") or "").strip()
    if not row.get("claimed"):
        return f"{team} — open"
    try:
        from live_draft_ux import format_participant_identity
    except ImportError:
        format_participant_identity = None  # type: ignore[assignment,misc]
    try:
        from draft_room_participant_state import resolve_participant_id

        my_pid = str(resolve_participant_id(session) or "").strip()
        owner_pid = str(row.get("participant_id") or "").strip()
        if my_pid and owner_pid and my_pid == owner_pid:
            if format_participant_identity:
                return format_participant_identity(
                    "You",
                    role="Guest" if not row.get("is_host") else "Commissioner",
                    team=team,
                )
            return f"{team} — claimed by you"
    except ImportError:
        pass
    owner = str(row.get("owner_label") or "Guest").strip()
    role = "Commissioner" if row.get("is_host") else "Guest"
    if format_participant_identity:
        return format_participant_identity(owner, role=role, team=team)
    if row.get("is_host"):
        return f"{team} — claimed by {owner} (commissioner)"
    return f"{team} — claimed by {owner}"


ROOM_NOT_FOUND_MSG = "Room code not found"


def format_team_ownership_line(row: dict[str, Any]) -> str:
    team = str(row.get("team") or "")
    if row.get("claimed"):
        owner = str(row.get("owner_label") or "Guest")
        if row.get("is_host"):
            return f"**{team}** (Host) · ✓ Claimed"
        return f"**{team}** · ✓ Claimed by {owner}"
    return f"**{team}** · Available"


def format_team_ownership_html(row: dict[str, Any]) -> str:
    team = str(row.get("team") or "")
    try:
        from live_draft_ux import format_participant_identity
    except ImportError:
        format_participant_identity = None  # type: ignore[assignment,misc]
    if row.get("claimed"):
        owner = str(row.get("owner_label") or "Guest")
        role = "Commissioner" if row.get("is_host") else "Guest"
        if format_participant_identity:
            return format_participant_identity(owner, role=role, team=team) + " · ✓ Claimed"
        if row.get("is_host"):
            return f"<strong>{team}</strong> (Host) · ✓ Claimed"
        return f"<strong>{team}</strong> · ✓ Claimed by {owner}"
    return f"<strong>{team}</strong> · Available"


def lookup_open_teams_for_code(
    room_code: str,
    *,
    store: Any = None,
    current_participant_id: str = "",
    session: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """Read-only lookup of open teams for join UI. Returns (teams, error)."""
    code = str(room_code or "").strip().upper()
    if not code:
        return [], ""
    try:
        from draft_room_create_verify import is_plausible_share_code

        if not is_plausible_share_code(code):
            return [], "Enter a valid 6-character room code."
    except ImportError:
        pass
    try:
        from draft_room_context import get_shared_room_store
        from draft_room_create_verify import load_shared_room_with_diagnostics

        backend = store or get_shared_room_store()
        load_result = load_shared_room_with_diagnostics(backend, code)
        document = load_result.get("document")
        if not isinstance(document, dict):
            reason = str(load_result.get("reason") or "not_found")
            if reason == "query_error":
                return [], str(load_result.get("query_error") or "Could not look up room.")
            return [], "Room code not found"
        # Repair alias duplicate seats before availability calculation.
        document = repair_shared_document_claims(document)
        status = str(document.get("status") or "").lower()
        if status in (
            "closed",
            "complete",
            "completed",
            "cancelled",
            "canceled",
            "expired",
            "ended",
            "deleted",
        ):
            return [], "Room is no longer joinable"

        pid = str(current_participant_id or "").strip()
        aliases: set[str] = set()
        if isinstance(session, dict):
            aliases = session_identity_aliases(session)
            if not pid:
                try:
                    from draft_room_participant_state import resolve_participant_id

                    pid = str(resolve_participant_id(session) or "").strip()
                except ImportError:
                    pass

        session_room = None
        if isinstance(session, dict):
            live = session.get("live_draft_room")
            if isinstance(live, dict):
                session_room = live

        open_teams, diag = list_available_shared_room_teams(
            document,
            pid,
            session_room=session_room,
            current_identity_aliases=aliases,
        )
        if isinstance(session, dict):
            session["_draft_room_claim_diag"] = {
                **diag,
                "lookup_backend": load_result.get("backend"),
                "lookup_fallback_used": bool(load_result.get("lookup_fallback_used")),
                "participants": dict(document.get("participants") or {}),
            }

        already = str(diag.get("already_joined_team") or "").strip()
        if already:
            return [], f"You are already joined as {already}"

        if not diag.get("document_teams"):
            return [], "Room data could not be loaded — team list missing from shared room."
        if not open_teams:
            # Surface which identity blocked each seat for Developer Mode.
            occupied = {
                team: slot
                for team, slot in (diag.get("occupancy") or {}).items()
                if slot.get("canonical_participant_id") or slot.get("claimant_raw_ids")
            }
            if isinstance(session, dict):
                session["_draft_room_claim_diag"]["exclusion_detail"] = occupied
                # Last-chance reattach: local membership still owns a seat in this room.
                try:
                    from draft_room_participant_state import membership_team_for_participant, resolve_participant_id

                    mem_team = membership_team_for_participant(
                        session, code, participant_id=resolve_participant_id(session)
                    )
                    if mem_team:
                        session["_draft_room_claim_diag"]["already_joined_team"] = mem_team
                        return [], f"You are already joined as {mem_team}"
                except ImportError:
                    pass
            return [], "No teams are available"
        return open_teams, ""
    except ImportError:
        return [], "Join lookup is unavailable."
