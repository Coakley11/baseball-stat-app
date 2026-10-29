"""Realistic save → refresh → second-device → navigate harness for the Simulator board.

The real ``streamlit_app.py`` runs under ``AppTest`` as a signed-in account. Cloud storage is a
JSON-file fake shared by every "device" (a device is a fresh AppTest session); it enforces the
same compare-and-set on ``updated_at`` that the Supabase PATCH does, so a stale writer is refused
exactly as it is in production. Each case uses its own throwaway account, so nothing touches
real workspaces; its on-disk files are removed afterwards.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

from streamlit.testing.v1 import AppTest

import suite_cloud_state as scs

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "streamlit_app.py")


class FileStore:
    """Fake ``suite_app_current_state`` keyed by app key, shared through one JSON file."""

    def __init__(self, path: Path, account_fn=lambda: "acct"):
        self.path = Path(path)
        self.log: list[str] = []
        self.who = "?"
        self.fail = False
        self._account_fn = account_fn

    def key(self, app: str) -> str:
        """Reads name the bare app, writes a scoped key; both mean this account's row."""
        return app if "@" in app else f"{app}@{self._account_fn()}"

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def row(self, app_key: str) -> dict[str, Any] | None:
        return self._read().get(app_key)

    def normalize_app_key(self, key):
        return key

    def _check(self):
        if self.fail:
            raise ConnectionError("fake cloud outage")

    def load_current_state_meta_for_app(self, app_id):
        self._check()
        row = self._read().get(self.key(app_id))
        return {"updated_at": row["updated_at"]} if row else {}

    def load_current_state_for_app(self, app_id):
        self._check()
        row = self._read().get(self.key(app_id))
        if not row:
            return None
        return {"updated_at": row["updated_at"], "metrics": copy.deepcopy(row["metrics"]), "page": row.get("page")}

    def save_current_state(self, app_key, *, page, summary, metrics, skip_metrics_merge_read=False,
                           expected_updated_at=None, **_kw):
        self._check()
        app_key = self.key(app_key)
        data = self._read()
        cur = data.get(app_key)
        if expected_updated_at is not None and (cur or {}).get("updated_at", "") != str(expected_updated_at or ""):
            self.log.append(f"[{self.who}] REJECTED")
            return False
        rev = sum(1 for line in self.log if "write" in line) + 1
        stamp = f"2026-10-28T17:{rev // 60:02d}:{rev % 60:02d}.{rev:06d}+00:00"
        merged = dict((cur or {}).get("metrics") or {})
        merged.update(metrics)
        data[app_key] = {"updated_at": stamp, "metrics": merged, "page": page}
        self.path.write_text(json.dumps(data, default=str), encoding="utf-8")
        self.log.append(f"[{self.who}] write")
        return True

    def __getattr__(self, name):  # anything else the app probes gets a harmless empty answer
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: None

    def board(self, app_key: str) -> list[str]:
        row = self.row(app_key) or {}
        table = ((row.get("metrics") or {}).get("full_session") or {}).get("draft_room_table") or {}
        return [r["Player"] for r in (table.get("table_records") or []) if str(r.get("Player") or "").strip()]

    def snapshot_picks(self, app_key: str) -> int:
        snap = ((self.row(app_key) or {}).get("metrics") or {}).get("draft_room_verified_snapshot") or {}
        return int(snap.get("pick_count") or 0)


def auth_for(external_id: str) -> dict[str, Any]:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": f"uuid-{external_id}",
        "_suite_auth_user_email": f"{external_id}@example.com",
        "_suite_auth_external_id": external_id,
        "_suite_auth_tokens": {"access_token": "a.b.c", "refresh_token": "r"},
        "_suite_auth_profile": {"id": f"uuid-{external_id}", "email": f"{external_id}@example.com"},
    }


class Device:
    def __init__(self, store: FileStore, account: str, name: str, *, signed_in: bool = True, override: bool = False):
        self.store, self.account, self.name = store, account, name
        self.at = AppTest.from_file(APP, default_timeout=240)
        self.at.session_state["active_page"] = "Draft Room Simulator"
        if override:
            self.at.session_state["use_simulator_board_as_fantasy_context"] = True
        if signed_in:
            self.sign_in(run=False)

    def sign_in(self, run: bool = True) -> "Device":
        for key, value in auth_for(self.account).items():
            self.at.session_state[key] = value
        return self.run() if run else self

    def run(self) -> "Device":
        self.store.who = self.name
        self.at.run()
        return self

    def button(self, label: str):
        return [b for b in self.at.button if b.label.strip().endswith(label)][0]

    def click(self, label: str) -> "Device":
        self.store.who = self.name
        self.button(label).click().run()
        return self

    def pick(self, player: str) -> "Device":
        self.store.who = self.name
        self.at.text_input(key="dr_board_assign_search").set_value(player).run()
        return self.click("Set player on pick")

    def save(self) -> list[str]:
        self.click("Save Draft Board Now")
        return self.messages()

    def messages(self) -> list[str]:
        return [str(x.value) for x in list(self.at.success) + list(self.at.warning) + list(self.at.error)]

    def go(self, page_word: str) -> "Device":
        radio = self.at.radio(key="main_sidebar_page")
        radio.set_value([o for o in radio.options if page_word in o][0])
        return self.run()

    def state(self) -> dict[str, Any]:
        return {k: self.at.session_state[k] for k in self.at.session_state.filtered_state}

    def board(self) -> list[str]:
        table = self.state().get("draft_room_table")
        if table is None:
            return []
        return [str(p) for p in table["Player"] if str(p).strip()]

    def visible_pick_text(self) -> str | None:
        text = " ".join(str(m.value) for m in list(self.at.markdown) + list(self.at.caption))
        found = re.search(r"(\d+) pick\(s\) logged", text)
        return found.group(0) if found else None


class CloudRestoreHarness:
    """Mixin for TestCase: fake cloud, throwaway account, cleanup."""

    def start_cloud(self, account: str | None = None, *, real_workspace: bool = False) -> None:
        """``real_workspace``: the app resolves the signed-in account's workspace itself (no patch),
        and workspace files live in a private data directory (``self.data``) instead of ``data/``."""
        self.account = account or f"qa_restore_{uuid.uuid4().hex[:8]}"
        self._tmp = tempfile.mkdtemp(prefix="cloud_restore_")
        self.data = ROOT / "data"
        self.store = FileStore(Path(self._tmp) / "cloud.json", account_fn=self._current_account)
        self.app_key = self.account  # fake scoping key, see _scoped below
        self._stack = contextlib.ExitStack()
        env = mock.patch.dict(os.environ, {"SUITE_AUTH_ENABLED": "1", "SUITE_STORAGE_ISOLATED": "1"})
        self._stack.enter_context(env)
        patchers = [
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            mock.patch.object(scs, "_import_storage", return_value=(self.store, "fake")),
            # Supabase scopes every row by the account's user_id; this is that, whatever the workspace.
            mock.patch.object(scs, "_cloud_storage_app_id", side_effect=lambda app: f"{app}@{self._current_account()}"),
        ]
        if real_workspace:
            self.data = Path(self._tmp) / "data"
            (self.data / "workspaces").mkdir(parents=True)
            patchers += [
                mock.patch("suite_workspace.DATA_DIR", self.data),
                mock.patch("suite_workspace._PERSISTED_FILE", self.data / "suite_active_workspace.json"),
                mock.patch("suite_workspace_registry.DATA_DIR", self.data),
                mock.patch("suite_workspace_registry.REGISTRY_FILE", self.data / "workspaces" / "_ownership_registry.json"),
                mock.patch("suite_workspace_registry.ACTIVE_DIR", self.data / "workspaces" / "_active"),
                mock.patch("suite_user_persistence.DATA_DIR", self.data),
                mock.patch("suite_user_persistence._LEGACY_COMBINED_FILE", self.data / "app_state.json"),
            ]
        else:
            patchers.append(
                mock.patch("suite_workspace.get_active_workspace_id", side_effect=lambda *a, **k: self._current_account())
            )
        for patcher in patchers:
            self._stack.enter_context(patcher)
        self.addCleanup(self.stop_cloud)

    def _current_account(self) -> str:
        return getattr(self, "_acting_account", self.account)

    def stop_cloud(self) -> None:
        self._stack.close()
        shutil.rmtree(self._tmp, ignore_errors=True)
        data = ROOT / "data"
        if self.data != data:
            return  # a private data directory, removed with the temp dir
        for account in {self.account, *getattr(self, "_extra_accounts", ())}:
            shutil.rmtree(data / "workspaces" / account, ignore_errors=True)
            for leftover in data.glob(f"*{account}*"):
                if leftover.is_file():
                    leftover.unlink(missing_ok=True)

    def device(self, name: str, *, account: str | None = None, **kwargs) -> Device:
        who = account or self.account
        if who != self.account:
            self._extra_accounts = getattr(self, "_extra_accounts", set()) | {who}
        self._acting_account = who
        return Device(self.store, who, name, **kwargs)

    def acting_as(self, account: str | None) -> None:
        """Which account the patched cloud/workspace helpers resolve for the next run."""
        self._acting_account = account or self.account

    def wipe_local_disk(self) -> None:
        """A fresh phone: no local copy of this account's workspace."""
        data = self.data
        shutil.rmtree(data / "workspaces" / self.account, ignore_errors=True)
        for leftover in data.glob(f"*{self.account}*"):
            if leftover.is_file():
                leftover.unlink(missing_ok=True)

    @property
    def cloud_key(self) -> str:
        return f"baseball@{self.account}"
