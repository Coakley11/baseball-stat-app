"""Supabase backend for cross-account shared league documents."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from fantasy_shared_league_store import SharedLeagueStore

_TABLE = "baseball_shared_leagues"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _request(method: str, path: str, **kwargs: Any) -> Any:
    from suite_storage_supabase import _invalidate_read_cache_for_table, _request as supabase_request

    try:
        result = supabase_request(method, path, **kwargs)
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    if method.upper() != "GET":
        _invalidate_read_cache_for_table(_TABLE)
    return result


def document_to_row(document: dict[str, Any], *, created: bool = False) -> dict[str, Any]:
    doc = copy.deepcopy(document)
    league_id = str(doc.get("league_id") or "").strip()
    now = _utc_now_iso()
    row = {
        "league_id": league_id,
        "draft_fingerprint": str(doc.get("draft_fingerprint") or "").strip(),
        "shared_league_json": doc,
        "revision": int(doc.get("revision") or 1),
        "updated_at": str(doc.get("updated_at") or now),
    }
    if created:
        row["created_at"] = str(doc.get("created_at") or now)
    return row


def row_to_document(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    raw = row.get("shared_league_json")
    if not isinstance(raw, dict):
        return None
    doc = copy.deepcopy(raw)
    doc["league_id"] = str(row.get("league_id") or doc.get("league_id") or "").strip()
    doc["draft_fingerprint"] = str(row.get("draft_fingerprint") or doc.get("draft_fingerprint") or "").strip()
    doc["revision"] = int(row.get("revision") or doc.get("revision") or 1)
    doc["updated_at"] = str(row.get("updated_at") or doc.get("updated_at") or "")
    doc.setdefault("schema_version", 1)
    return doc


class SupabaseSharedLeagueStore:
    def exists(self, league_id: str) -> bool:
        lid = str(league_id or "").strip()
        if not lid:
            return False
        try:
            rows = _request(
                "GET",
                _TABLE,
                params={"select": "league_id", "league_id": f"eq.{lid}", "limit": "1"},
                prefer="return=representation",
            )
        except RuntimeError:
            return False
        return isinstance(rows, list) and bool(rows)

    def load(self, league_id: str) -> dict[str, Any] | None:
        lid = str(league_id or "").strip()
        if not lid:
            return None
        try:
            rows = _request(
                "GET",
                _TABLE,
                params={"select": "*", "league_id": f"eq.{lid}", "limit": "1"},
                prefer="return=representation",
            )
        except RuntimeError:
            return None
        if not isinstance(rows, list) or not rows:
            return None
        return row_to_document(rows[0])

    def save(self, document: dict[str, Any]) -> dict[str, Any]:
        league_id = str(document.get("league_id") or "").strip()
        if not league_id:
            raise ValueError("shared league document missing league_id")
        existing = self.load(league_id)
        row = document_to_row(document, created=existing is None)
        if existing is None:
            rows = _request("POST", _TABLE, json_body=row, prefer="return=representation")
        else:
            patch = {
                "draft_fingerprint": row["draft_fingerprint"],
                "shared_league_json": row["shared_league_json"],
                "revision": row["revision"],
                "updated_at": row["updated_at"],
            }
            rows = _request(
                "PATCH",
                _TABLE,
                params={"league_id": f"eq.{league_id}"},
                json_body=patch,
                prefer="return=representation",
            )
        del rows
        saved = self.load(league_id)
        return saved if isinstance(saved, dict) else row["shared_league_json"]

    def save_if_revision(
        self,
        document: dict[str, Any],
        *,
        expected_revision: int | None,
    ) -> tuple[bool, dict[str, Any] | None]:
        league_id = str(document.get("league_id") or "").strip()
        existing = self.load(league_id)
        if expected_revision is not None and isinstance(existing, dict):
            current = int(existing.get("revision") or 0)
            if current != int(expected_revision):
                return False, existing
        saved = self.save(document)
        return True, saved

    def list_documents(self) -> list[dict[str, Any]]:
        try:
            rows = _request(
                "GET",
                _TABLE,
                params={"select": "shared_league_json", "limit": "200"},
                prefer="return=representation",
            )
        except RuntimeError:
            return []
        docs: list[dict[str, Any]] = []
        if not isinstance(rows, list):
            return docs
        for row in rows:
            doc = row_to_document(row if isinstance(row, dict) else None)
            if isinstance(doc, dict):
                docs.append(doc)
        return docs


_SUPABASE_STORE: SupabaseSharedLeagueStore | None = None


def get_supabase_shared_league_store() -> SupabaseSharedLeagueStore:
    global _SUPABASE_STORE
    if _SUPABASE_STORE is None:
        _SUPABASE_STORE = SupabaseSharedLeagueStore()
    return _SUPABASE_STORE
