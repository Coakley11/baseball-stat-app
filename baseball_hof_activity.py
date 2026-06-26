"""Command Center activity for Hall of Fame Case Mode."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from hall_of_fame_data import hof_case_target_slug

HOF_CASE_RESUME_ITEM_TYPE = "hof_case_resume"
HOF_CASE_ACTIVITY_EVENT = "hof_case_analysis_submitted"

HOF_WORKFLOW_SUPPLEMENT_KEYS = frozenset(
    {
        "workflow_recently_viewed",
        "workflow_favorite_targets",
        "draft_assistant_focus_players",
        "draft_queue",
    }
)


def build_hof_case_resume_bundle(
    st: Any,
    *,
    target_player: str,
    packet: dict[str, Any],
    source_state: dict[str, Any] | None = None,
    question_id: str = "",
    action_url: str = "",
    insight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture full Baseball Analytics workspace state at HOF case submit time."""
    try:
        from baseball_persistent_state import build_baseball_disk_state

        workspace_snapshot = build_baseball_disk_state(st)
    except ImportError:
        workspace_snapshot = {}

    ss = st.session_state
    supplement: dict[str, Any] = {}
    for key in HOF_WORKFLOW_SUPPLEMENT_KEYS:
        if key in ss:
            try:
                supplement[key] = copy.deepcopy(ss[key])
            except Exception:
                supplement[key] = ss[key]

    slug = hof_case_target_slug(target_player)
    resume_key = f"bb:hof_case:{slug}"
    return {
        "resume_key": resume_key,
        "target_player": str(target_player or "").strip(),
        "question_id": str(question_id or "").strip(),
        "action_url": str(action_url or "").strip(),
        "source_state": copy.deepcopy(source_state) if isinstance(source_state, dict) else {},
        "workspace_snapshot": copy.deepcopy(workspace_snapshot) if workspace_snapshot else {},
        "session_supplement": supplement,
        "hof_case_packet": copy.deepcopy(packet) if isinstance(packet, dict) else {},
        "insight": copy.deepcopy(insight) if isinstance(insight, dict) else {},
    }


def persist_hof_case_resume_bundle(bundle: dict[str, Any]) -> bool:
    """Persist submit-time bundle for Command Center Continue (saved items + local fallback)."""
    resume_key = str(bundle.get("resume_key") or "").strip()
    if not resume_key:
        return False
    target = str(bundle.get("target_player") or "").strip()
    stored = False
    try:
        from suite_account import remember_saved_item

        remember_saved_item(
            "baseball",
            HOF_CASE_RESUME_ITEM_TYPE,
            resume_key,
            title=f"Hall of Fame case — {target}" if target else "Hall of Fame case",
            payload=bundle,
        )
        stored = True
    except Exception:
        pass
    try:
        from suite_activity_client import LOCAL_FALLBACK_DIR

        path = LOCAL_FALLBACK_DIR / "hof_case_resume_bundles.json"
        rows: dict[str, Any] = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    rows = raw
            except (OSError, json.JSONDecodeError):
                rows = {}
        rows[resume_key] = bundle
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        stored = True
    except Exception:
        pass
    return stored


def load_hof_case_resume_bundle(resume_key: str) -> dict[str, Any]:
    """Load submit-time HOF resume bundle by ``bb:hof_case:{slug}`` key."""
    key = str(resume_key or "").strip()
    if not key:
        return {}

    try:
        from suite_account import load_saved_items

        for row in load_saved_items(app="baseball", item_type=HOF_CASE_RESUME_ITEM_TYPE, limit=40):
            if str(row.get("item_key") or "") == key:
                payload = row.get("payload")
                if isinstance(payload, dict):
                    return copy.deepcopy(payload)
    except Exception:
        pass

    try:
        from suite_activity_client import LOCAL_FALLBACK_DIR

        path = LOCAL_FALLBACK_DIR / "hof_case_resume_bundles.json"
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                hit = raw.get(key)
                if isinstance(hit, dict):
                    return copy.deepcopy(hit)
    except Exception:
        pass

    try:
        from suite_activity_client import LOCAL_FALLBACK_DIR

        for fb_path in sorted(LOCAL_FALLBACK_DIR.glob("*_activity_fallback.json"), reverse=True):
            try:
                raw = json.loads(fb_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, list):
                continue
            for row in reversed(raw):
                if not isinstance(row, dict):
                    continue
                if str(row.get("event") or "") != HOF_CASE_ACTIVITY_EVENT:
                    continue
                metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
                if str(metrics.get("resume_key") or "") != key:
                    continue
                bundle = metrics.get("hof_case_resume_bundle")
                if isinstance(bundle, dict):
                    return copy.deepcopy(bundle)
    except Exception:
        pass

    return {}


def log_hof_case_analysis_submitted(
    session: dict[str, Any] | None,
    *,
    target_player: str,
    packet: dict[str, Any],
    question_id: str = "",
    ami_insight_id: str = "",
    source_state: dict[str, Any] | None = None,
    resume_bundle: dict[str, Any] | None = None,
) -> None:
    try:
        from suite_activity_client import record_activity
    except ImportError:
        return
    target = str(target_player or "").strip()
    slug = hof_case_target_slug(target)
    resume_key = f"bb:hof_case:{slug}"
    filters_used = packet.get("filters_used") if isinstance(packet.get("filters_used"), dict) else {}
    bundle = resume_bundle if isinstance(resume_bundle, dict) else {}
    metrics: dict[str, Any] = {
        "activity_type": HOF_CASE_ACTIVITY_EVENT,
        "feature": "Hall of Fame Case Mode",
        "target_player": target,
        "hof_case_mode": True,
        "hof_case_target": target,
        "resume_key": resume_key,
        "total_players_returned": packet.get("total_players_returned"),
        "hall_of_famers_returned": packet.get("hall_of_famers_returned"),
        "hall_of_fame_rate_pct": packet.get("hall_of_fame_rate_pct"),
        "target_rank": packet.get("target_rank"),
        "sort_stat": packet.get("sort_stat"),
        "primary_position": packet.get("primary_position"),
        "filters_used": filters_used,
        "hof_case_summary": packet.get("hof_case_summary"),
    }
    if question_id:
        metrics["question_id"] = question_id
        metrics["ami_question_id"] = question_id
        metrics["suite_ai_question_id"] = question_id
    if ami_insight_id:
        metrics["ami_insight"] = ami_insight_id
    if isinstance(source_state, dict) and source_state:
        metrics["hof_case_source_state"] = source_state
    if bundle:
        metrics["hof_case_resume_bundle"] = bundle
        if bundle.get("workspace_snapshot"):
            metrics["hof_case_workspace_snapshot"] = bundle["workspace_snapshot"]
        if bundle.get("insight"):
            metrics["hof_case_insight"] = bundle["insight"]
        if bundle.get("action_url"):
            metrics["hof_case_action_url"] = bundle["action_url"]
    try:
        from suite_deep_links import build_resume_action_url

        metrics["continue_url"] = build_resume_action_url(
            "baseball",
            resume_key=resume_key,
            page="Career Totals",
            metrics={
                "target_player": target,
                "hof_case_mode": True,
                "question_id": question_id,
            },
        )
    except ImportError:
        pass
    if bundle:
        persist_hof_case_resume_bundle(bundle)
    record_activity(
        "baseball",
        HOF_CASE_ACTIVITY_EVENT,
        page="Career Totals",
        metrics=metrics,
        summary=f"Hall of Fame case analysis — {target}",
        resume_key=resume_key,
        resume_title="Review Hall of Fame Case",
        resume_subtitle=target,
        action_url=str(bundle.get("action_url") or metrics.get("continue_url") or ""),
    )
    if isinstance(session, dict) and bundle:
        session["_hof_case_last_resume_bundle"] = copy.deepcopy(bundle)
