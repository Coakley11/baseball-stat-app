"""
Portable client for Daniel AI suite persistence.

Cloud-first: when Supabase is configured (same secrets on every Streamlit app),
writes go to the shared store even on isolated Streamlit Cloud containers.
Falls back to sibling Command Center SQLite, then per-app JSON fallback.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

COMMAND_CENTER_ROOT_CANDIDATES = (
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parent.parent / "daniel-ai-command-center",
    Path.home() / "Documents" / "GitHub" / "daniel-ai-command-center",
)

LOCAL_FALLBACK_DIR = Path(__file__).resolve().parent / "data"


def _load_storage_module():
    for root in COMMAND_CENTER_ROOT_CANDIDATES:
        storage_path = root / "suite_storage.py"
        if not storage_path.is_file():
            continue
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        import suite_storage  # noqa: WPS433

        return suite_storage
    return None


def _record_via_cloud(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
    summary: str = "",
    resume_key: str = "",
    resume_title: str = "",
    resume_subtitle: str = "",
    action_url: str = "",
) -> bool:
    try:
        from suite_storage_config import cloud_storage_enabled
        from suite_storage_supabase import record_activity as cloud_record
    except ImportError:
        return False
    if not cloud_storage_enabled():
        return False
    try:
        cloud_record(
            app,
            event,
            page=page,
            metrics=metrics or {},
            summary=summary,
            resume_key=resume_key,
            resume_title=resume_title,
            resume_subtitle=resume_subtitle,
            action_url=action_url,
        )
        return True
    except Exception:
        return False


def _fallback_path(app: str) -> Path:
    LOCAL_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_FALLBACK_DIR / f"{app}_activity_fallback.json"


def _fallback_append(app: str, event: str, page: str, metrics: dict[str, Any], summary: str) -> None:
    path = _fallback_path(app)
    rows: list[dict[str, Any]] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                rows = raw
        except (OSError, json.JSONDecodeError):
            rows = []
    rows.append(
        {
            "app": app,
            "event": event,
            "page": page,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "metrics": metrics,
            "summary": summary,
        }
    )
    path.write_text(json.dumps(rows[-200:], indent=2), encoding="utf-8")


def save_local_app_state(app: str, state: dict[str, Any]) -> None:
    """Per-app JSON snapshot for reload persistence within a single deployment."""
    LOCAL_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_FALLBACK_DIR / "app_state.json"
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload = raw
        except (OSError, json.JSONDecodeError):
            payload = {}
    payload[app] = {
        **state,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_local_app_state(app: str) -> dict[str, Any]:
    path = LOCAL_FALLBACK_DIR / "app_state.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    block = raw.get(app)
    return block if isinstance(block, dict) else {}


def record_activity(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
    summary: str = "",
    resume_key: str = "",
    resume_title: str = "",
    resume_subtitle: str = "",
    action_url: str = "",
    local_state: dict[str, Any] | None = None,
) -> None:
    metrics = metrics or {}
    if _record_via_cloud(
        app,
        event,
        page=page,
        metrics=metrics,
        summary=summary,
        resume_key=resume_key,
        resume_title=resume_title,
        resume_subtitle=resume_subtitle,
        action_url=action_url,
    ):
        if local_state is not None:
            save_local_app_state(app, local_state)
        return

    storage = _load_storage_module()
    if storage is not None:
        try:
            storage.record_activity(
                app,
                event,
                page=page,
                metrics=metrics,
                summary=summary,
                resume_key=resume_key,
                resume_title=resume_title,
                resume_subtitle=resume_subtitle,
                action_url=action_url,
            )
        except OSError:
            _fallback_append(app, event, page, metrics, summary)
    else:
        _fallback_append(app, event, page, metrics, summary)

    if app == "music":
        _fallback_append(app, event, page, metrics, summary)

    if local_state is not None:
        save_local_app_state(app, local_state)


def log_event(app: str, event: str, *, page: str = "", metrics: dict[str, Any] | None = None) -> None:
    record_activity(app, event, page=page, metrics=metrics)


def invalidate_resume_item(app: str, item_key: str) -> None:
    try:
        from suite_storage_config import cloud_storage_enabled
        from suite_storage_supabase import invalidate_resume_item as cloud_invalidate

        if cloud_storage_enabled():
            cloud_invalidate(app, item_key)
            return
    except ImportError:
        pass
    except Exception:
        pass

    storage = _load_storage_module()
    if storage is not None:
        try:
            storage.invalidate_resume_item(app, item_key)
        except OSError:
            pass
