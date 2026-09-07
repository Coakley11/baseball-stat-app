"""Refresh restore: phantom local active code must not block a real disk room."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from draft_room_participant_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    MEMBERSHIP_KEY,
    restore_persisted_shared_room_membership,
)


class SharedRefreshMembershipDiskScanTests(unittest.TestCase):
    def test_phantom_active_code_reattaches_via_disk_participant_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = {
                "room_code": "SQHY57",
                "status": "in_progress",
                "draft_room_id": "ROOM_SQHY57",
                "updated_at": "2026-09-06T20:00:00+00:00",
                "participants": {
                    "workspace:daniel": {
                        "assigned_team": "Team A",
                        "participant_id": "workspace:daniel",
                    }
                },
                "room": {"draft_room_id": "ROOM_SQHY57", "status": "in_progress"},
            }
            (root / "SQHY57.json").write_text(json.dumps(real), encoding="utf-8")

            session: dict[str, Any] = {
                ACTIVE_SHARED_ROOM_CODE_KEY: "1EFVRQ",
                "draft_room_participant_id": "workspace:daniel",
                MEMBERSHIP_KEY: {
                    "1EFVRQ": {
                        "workspace:daniel": {
                            "participant_id": "workspace:daniel",
                            "assigned_team": "Team A",
                            "joined_at": "2026-09-06T19:00:00+00:00",
                        }
                    }
                },
                "live_draft_room": {
                    "draft_room_id": "PREDRAFT1",
                    "status": "not_started",
                    "room_code": "1EFVRQ",
                },
                "page_filter_state": {
                    "Live Draft Room": {
                        "live_draft_room": {
                            "draft_room_id": "PREDRAFT1",
                            "status": "not_started",
                            "room_code": "1EFVRQ",
                        }
                    }
                },
            }

            class _Store:
                def load_with_diagnostics(self, code: str) -> dict[str, Any]:
                    c = str(code or "").strip().upper()
                    path = root / f"{c}.json"
                    if path.is_file():
                        return {
                            "ok": True,
                            "document": json.loads(path.read_text(encoding="utf-8")),
                        }
                    return {"ok": False, "reason": "not_found"}

                def load(self, code: str) -> dict[str, Any] | None:
                    diag = self.load_with_diagnostics(code)
                    return diag.get("document") if diag.get("ok") else None

            store = _Store()

            def _load_doc(_session, code, force=False):  # noqa: ANN001, ARG001
                return store.load(code)

            with patch("draft_room_shared_state.DATA_DIR", root), patch(
                "draft_room_shared_state.shared_room_backend_name",
                return_value="local_file",
            ), patch(
                "draft_room_shared_state.get_local_shared_room_store",
                return_value=store,
            ), patch(
                "draft_room_shared_state.load_shared_room",
                side_effect=lambda code, store=None: _Store().load(code),
            ), patch(
                "shared_room_membership_gate.load_authoritative_shared_document",
                side_effect=_load_doc,
            ), patch(
                "shared_room_membership_gate.can_render_shared_live_draft",
                side_effect=lambda session, document=None, require_team_claim=False: (
                    (True, "ok")
                    if isinstance(document, dict)
                    and str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").upper()
                    in {
                        str(document.get("room_code") or "").upper(),
                        "SQHY57",
                    }
                    else (
                        (True, "ok")
                        if isinstance(document, dict)
                        else (False, "room_missing")
                    )
                ),
            ):
                attached = restore_persisted_shared_room_membership(session)

            self.assertEqual(attached, "SQHY57")
            self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "SQHY57")
            self.assertIsNotNone(session.get("_live_draft_restore_disk_scan"))

    def test_disk_scan_skipped_when_active_code_reattaches(self) -> None:
        session: dict[str, Any] = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "KEEP12",
            "draft_room_participant_id": "workspace:guest",
        }
        doc = {
            "room_code": "KEEP12",
            "status": "in_progress",
            "participants": {"workspace:guest": {"assigned_team": "Team B"}},
            "room": {"status": "in_progress"},
        }
        with patch(
            "shared_room_membership_gate.load_authoritative_shared_document",
            return_value=doc,
        ), patch(
            "shared_room_membership_gate.can_render_shared_live_draft",
            return_value=(True, "ok"),
        ), patch(
            "draft_room_participant_state._reattach_from_local_disk_participant_scan",
            return_value="SHOULD_NOT",
        ) as scan:
            attached = restore_persisted_shared_room_membership(session)
        self.assertEqual(attached, "KEEP12")
        scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
