"""Immutable resolved fantasy context — one coherent archive/context pair per render."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


RESOLVED_CACHE_KEY = "_resolved_fantasy_context_cache"
RESOLVED_CACHE_FP_KEY = "_resolved_fantasy_context_fp"
RESOLVED_DIAG_KEY = "_resolved_fantasy_context_diag"


@dataclass(frozen=True)
class ResolvedFantasyContext:
    source_kind: str
    active_draft_id: str
    active_league_context_id: str
    canonical_league_id: str
    active_team_name: str
    team_names: tuple[str, ...]
    league_rosters: dict[str, Any]
    lineup_config: dict[str, Any]
    creation_origin: str
    source_revision: str
    context_fingerprint: str
    coherent: bool = True
    coherence_error: str = ""
    cache_hit: bool = False

    def to_diag(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "active_draft_id": self.active_draft_id,
            "active_league_context_id": self.active_league_context_id,
            "canonical_league_id": self.canonical_league_id,
            "active_team_name": self.active_team_name,
            "roster_team_names": list(self.team_names),
            "roster_source_draft_id": self.active_draft_id,
            "roster_source_context_id": self.active_league_context_id,
            "context_fingerprint": self.context_fingerprint,
            "cache_hit": self.cache_hit,
            "cache_fingerprint": self.context_fingerprint,
            "context_coherent": self.coherent,
            "coherence_error": self.coherence_error,
            "source_revision": self.source_revision,
            "creation_origin": self.creation_origin,
        }


def _roster_team_names(league_rosters: dict[str, Any] | None) -> list[str]:
    if not isinstance(league_rosters, dict):
        return []
    return sorted(str(k).strip() for k in league_rosters.keys() if str(k).strip())


def _source_draft_id(context: dict[str, Any], archive: dict[str, Any] | None) -> str:
    meta = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    draft_id = str(
        meta.get("source_draft_id")
        or meta.get("draft_id")
        or context.get("draft_id")
        or (archive or {}).get("draft_id")
        or ""
    ).strip()
    return draft_id


def _fingerprint(
    *,
    draft_id: str,
    context_id: str,
    league_id: str,
    team: str,
    team_names: list[str],
    source_revision: str,
) -> str:
    raw = "|".join(
        [
            draft_id,
            context_id,
            league_id,
            team,
            ",".join(team_names),
            source_revision,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _content_revision(context: dict[str, Any], archive: dict[str, Any] | None) -> str:
    for src in (archive, context):
        if not isinstance(src, dict):
            continue
        for key in ("content_revision", "content_updated_at", "updated_at", "revision"):
            val = src.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    try:
        rosters = context.get("league_rosters") or {}
        blob = json.dumps(rosters, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
    except Exception:
        return "0"


def validate_resolved_fantasy_context(
    *,
    active_team_name: str,
    team_names: list[str],
    league_rosters: dict[str, Any],
    active_draft_id: str,
    context: dict[str, Any],
) -> tuple[bool, str]:
    roster_keys = set(_roster_team_names(league_rosters))
    named = {str(t).strip() for t in team_names if str(t).strip()}
    team = str(active_team_name or "").strip()
    if roster_keys and team and team not in roster_keys:
        return False, f"active_team_not_in_rosters:{team}|available={sorted(roster_keys)}"
    if named and roster_keys and named != roster_keys:
        # Allow named ⊂ roster_keys when names come from matchup caption subsets, but
        # never allow disjoint sets (Upload names vs Robins keys).
        if not named.issubset(roster_keys) and not roster_keys.issubset(named):
            return False, f"team_names_mismatch:named={sorted(named)}|rosters={sorted(roster_keys)}"
    meta = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    source_draft = str(meta.get("source_draft_id") or meta.get("draft_id") or context.get("draft_id") or "").strip()
    if active_draft_id and source_draft and active_draft_id != source_draft:
        return False, f"draft_id_mismatch:active={active_draft_id}|context={source_draft}"
    return True, ""


def _empty_resolved(*, error: str = "", cache_hit: bool = False) -> ResolvedFantasyContext:
    return ResolvedFantasyContext(
        source_kind="none",
        active_draft_id="",
        active_league_context_id="",
        canonical_league_id="",
        active_team_name="",
        team_names=tuple(),
        league_rosters={},
        lineup_config={},
        creation_origin="",
        source_revision="",
        context_fingerprint="",
        coherent=not bool(error),
        coherence_error=error,
        cache_hit=cache_hit,
    )


def resolve_fantasy_context_for_page(
    session: dict[str, Any],
    *,
    force: bool = False,
) -> ResolvedFantasyContext:
    """Build one immutable context object from the coherent active archive/context pair."""
    try:
        from fantasy_context_source import resolve_fantasy_workflow_source_descriptor

        desc = resolve_fantasy_workflow_source_descriptor(session)
    except ImportError:
        desc = {}
    if not isinstance(desc, dict):
        desc = {}

    context = desc.get("context") if isinstance(desc.get("context"), dict) else None
    archive = desc.get("archive") if isinstance(desc.get("archive"), dict) else None
    if not isinstance(context, dict):
        try:
            from fantasy_league_context import get_active_league_context

            context = get_active_league_context(session, respect_source_priority=False)
        except ImportError:
            context = None
    if not isinstance(context, dict):
        resolved = _empty_resolved(error="no_active_context")
        session[RESOLVED_DIAG_KEY] = resolved.to_diag()
        return resolved

    # Always deep-copy rosters from the selected context — never a session-global shortcut.
    league_rosters = copy.deepcopy(context.get("league_rosters") or {})
    if not isinstance(league_rosters, dict):
        league_rosters = {}
    # Prefer archive league_rosters when context map empty but archive is the same draft.
    if not league_rosters and isinstance(archive, dict):
        arch_rosters = archive.get("league_rosters")
        if isinstance(arch_rosters, dict) and arch_rosters:
            league_rosters = copy.deepcopy(arch_rosters)

    draft_id = _source_draft_id(context, archive)
    context_id = str(context.get("league_context_id") or desc.get("league_context_id") or "").strip()
    try:
        from fantasy_league_identity import resolve_canonical_league_id

        league_id = str(resolve_canonical_league_id(context) or desc.get("canonical_league_id") or "").strip()
    except ImportError:
        league_id = str(desc.get("canonical_league_id") or context.get("league_id") or "").strip()

    team = str(desc.get("my_team_name") or context.get("my_team_name") or "").strip()
    if not team and isinstance(archive, dict):
        team = str(archive.get("team_name") or "").strip()
    team_names = [str(t).strip() for t in (desc.get("team_names") or []) if str(t).strip()]
    if not team_names:
        team_names = _roster_team_names(league_rosters)

    lineup_config: dict[str, Any] = {}
    for key in ("lineup_settings", "roster_settings", "scoring_settings"):
        block = context.get(key)
        if isinstance(block, dict) and block:
            lineup_config[key] = copy.deepcopy(block)
    if isinstance(archive, dict):
        for key in ("roster_slots", "slot_instances", "fantasy_format"):
            if archive.get(key) is not None and key not in lineup_config:
                lineup_config[key] = copy.deepcopy(archive.get(key))

    creation_origin = str(
        context.get("creation_origin")
        or (context.get("metadata") or {}).get("creation_origin")
        or (archive or {}).get("creation_origin")
        or ""
    ).strip()
    source_revision = _content_revision(context, archive)
    fp = _fingerprint(
        draft_id=draft_id,
        context_id=context_id,
        league_id=league_id,
        team=team,
        team_names=team_names,
        source_revision=source_revision,
    )
    cache_hit = False
    if not force and session.get(RESOLVED_CACHE_FP_KEY) == fp:
        cached = session.get(RESOLVED_CACHE_KEY)
        if isinstance(cached, ResolvedFantasyContext):
            cache_hit = True
            updated = ResolvedFantasyContext(
                **{**asdict(cached), "cache_hit": True}
            )
            session[RESOLVED_DIAG_KEY] = updated.to_diag()
            return updated

    coherent, err = validate_resolved_fantasy_context(
        active_team_name=team,
        team_names=team_names,
        league_rosters=league_rosters,
        active_draft_id=draft_id,
        context=context,
    )
    if not coherent:
        # Re-pull archival rosters and re-validate once before failing.
        try:
            from draft_archive_state import get_draft_archive

            fresh = get_draft_archive(session, draft_id) if draft_id else None
            if isinstance(fresh, dict) and isinstance(fresh.get("league_rosters"), dict):
                league_rosters = copy.deepcopy(fresh.get("league_rosters") or {})
                team_names = _roster_team_names(league_rosters) or team_names
                coherent, err = validate_resolved_fantasy_context(
                    active_team_name=team,
                    team_names=team_names,
                    league_rosters=league_rosters,
                    active_draft_id=draft_id,
                    context=context,
                )
        except ImportError:
            pass

    resolved = ResolvedFantasyContext(
        source_kind=str(desc.get("source_kind") or "saved_active_draft"),
        active_draft_id=draft_id,
        active_league_context_id=context_id,
        canonical_league_id=league_id,
        active_team_name=team,
        team_names=tuple(team_names),
        league_rosters=league_rosters,
        lineup_config=lineup_config,
        creation_origin=creation_origin,
        source_revision=source_revision,
        context_fingerprint=fp,
        coherent=coherent,
        coherence_error=err,
        cache_hit=cache_hit,
    )
    session[RESOLVED_CACHE_KEY] = resolved
    session[RESOLVED_CACHE_FP_KEY] = fp
    session[RESOLVED_DIAG_KEY] = resolved.to_diag()
    return resolved


def roster_dataframe_matches_resolved(roster_stats: Any, resolved: ResolvedFantasyContext) -> bool:
    """True when a cached roster DataFrame belongs to the resolved context."""
    if resolved is None or not resolved.coherent:
        return False
    if roster_stats is None:
        return False
    try:
        import pandas as pd

        if not isinstance(roster_stats, pd.DataFrame) or roster_stats.empty:
            return False
        if "Team" not in roster_stats.columns:
            return False
        teams = {str(t).strip() for t in roster_stats["Team"].dropna().astype(str).tolist() if str(t).strip()}
        expected = set(resolved.team_names) or set(_roster_team_names(resolved.league_rosters))
        if not expected:
            return False
        # Disjoint sets => wrong league (Upload Daniel vs Robins Donny/Team B).
        if teams and expected and teams.isdisjoint(expected):
            return False
        if resolved.active_team_name and resolved.active_team_name not in teams and teams:
            return False
        return True
    except Exception:
        return False


def invalidate_resolved_fantasy_context(session: dict[str, Any]) -> None:
    session.pop(RESOLVED_CACHE_KEY, None)
    session.pop(RESOLVED_CACHE_FP_KEY, None)
    session.pop(RESOLVED_DIAG_KEY, None)
    session.pop("_lineup_resolved_page_context", None)
    session.pop("_lineup_ctx_resolved_for_run", None)


def collect_resolved_fantasy_context_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(RESOLVED_DIAG_KEY)
    if isinstance(raw, dict) and raw:
        return dict(raw)
    resolved = resolve_fantasy_context_for_page(session, force=True)
    return resolved.to_diag()
