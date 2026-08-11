"""Ultra-simple Cloud runtime identity from the filesystem (diagnostic-only)."""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
import time
from pathlib import Path
from typing import Any

PROBE_ELEMENT_ID = "solo-cloud-fs-probe"
PROBE_QUERY_PARAM = "solo_cloud_fs_probe"
PROBE_ASSET_INTRO_SHA = "6394eb6"
REPO_STATIC_PROBE_RELATIVE = Path("static/s3_oob/__repo_static_probe_v1.json")
EXPECTED_REPO_STATIC_PROBE = "s3_oob_repo_static_probe_v1"
EXPECTED_REPO_STATIC_SOURCE = "git_committed_static_file"
P6_DIAG_NAME = "live_draft_solo_parity_p6_persistent_diag.py"

_CANDIDATE_ROOTS = (
    Path(__file__).resolve().parent,
    Path("/mount/src/baseball-stat-app"),
)


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def _git_head_contains_probe_asset(repo_root: Path, git_head: str) -> bool:
    probe_path = repo_root / REPO_STATIC_PROBE_RELATIVE
    if not probe_path.is_file():
        return False
    if not git_head or str(git_head).startswith("error:"):
        return True
    try:
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", PROBE_ASSET_INTRO_SHA, "HEAD"],
                cwd=repo_root,
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        )
    except Exception:
        return str(git_head).lower().startswith(PROBE_ASSET_INTRO_SHA)


def _read_deploy_commit_raw(root: Path) -> str:
    path = root / "deploy_commit.txt"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def parse_deploy_pin(raw: str) -> str:
    line = str(raw or "").splitlines()[0] if raw else ""
    return line.split("#", 1)[0].strip()[:7]


def _file_short_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest[:12]
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def _read_enable_static_serving_from_toml(config_path: Path) -> tuple[bool | None, bool]:
    exists = config_path.is_file()
    if not exists:
        return None, False
    try:
        text = config_path.read_text(encoding="utf-8")
    except Exception:
        return None, True
    in_server = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_server = stripped.lower() == "[server]"
            continue
        if in_server and stripped.lower().startswith("enablestaticserving"):
            val = stripped.split("=", 1)[1].strip().lower()
            return val in ("true", "1", "yes"), True
    return None, True


def _read_repo_static_probe_sentinel(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "exists": path.is_file(),
        "abspath": str(path.resolve()) if path.exists() else str(path),
        "size_bytes": 0,
        "probe": "",
        "source": "",
        "sentinel_ok": False,
        "read_error": "",
    }
    if not path.is_file():
        return out
    try:
        out["size_bytes"] = int(path.stat().st_size)
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            out["probe"] = str(parsed.get("probe") or "")
            out["source"] = str(parsed.get("source") or "")
            out["sentinel_ok"] = (
                out["probe"] == EXPECTED_REPO_STATIC_PROBE
                and out["source"] == EXPECTED_REPO_STATIC_SOURCE
            )
    except Exception as exc:
        out["read_error"] = f"{type(exc).__name__}:{exc}"[:120]
    return out


def _resolve_repo_root(module_root: Path) -> Path:
    for candidate in _CANDIDATE_ROOTS:
        if (candidate / "deploy_commit.txt").is_file() or (candidate / ".git").exists():
            return candidate
    return module_root


def _streamlit_version() -> str:
    try:
        import streamlit

        return str(getattr(streamlit, "__version__", "") or "")
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def collect_cloud_runtime_fs_probe(*, st: Any | None = None) -> dict[str, Any]:
    """Fresh filesystem/git snapshot every call — never cached."""
    module_root = Path(__file__).resolve().parent
    cwd = Path.cwd()
    streamlit_entry = module_root / "streamlit_app.py"
    repo_root = _resolve_repo_root(module_root)

    git_head = _run_git(["rev-parse", "HEAD"], repo_root)
    git_branch = _run_git(["branch", "--show-current"], repo_root)
    git_log1 = _run_git(["log", "-1", "--oneline"], repo_root)
    head_short = (
        git_head[:7]
        if git_head and not str(git_head).startswith("error:")
        else ""
    )

    deploy_reads: dict[str, str] = {}
    for candidate in _CANDIDATE_ROOTS:
        deploy_reads[str(candidate / "deploy_commit.txt")] = _read_deploy_commit_raw(candidate)

    mount_deploy = deploy_reads.get("/mount/src/baseball-stat-app/deploy_commit.txt", "")
    module_deploy = deploy_reads.get(str(module_root / "deploy_commit.txt"), "")
    deploy_raw = mount_deploy or module_deploy
    deploy_pin = parse_deploy_pin(deploy_raw)
    deploy_commit_exists = bool(deploy_raw and not deploy_raw.startswith("error:"))

    config_path = repo_root / ".streamlit" / "config.toml"
    config_exists = config_path.is_file()
    config_enable_static, _ = _read_enable_static_serving_from_toml(config_path)
    effective_enable_static = config_enable_static
    if st is not None:
        try:
            effective_enable_static = bool(st.get_option("server.enableStaticServing"))
        except Exception:
            pass

    static_dir = repo_root / "static" / "s3_oob"
    repo_probe_path = repo_root / REPO_STATIC_PROBE_RELATIVE
    repo_probe = _read_repo_static_probe_sentinel(repo_probe_path)
    head_contains_probe_asset = _git_head_contains_probe_asset(repo_root, git_head)

    p6_path = repo_root / P6_DIAG_NAME
    p6_mount = Path("/mount/src/baseball-stat-app") / P6_DIAG_NAME
    p6_exists = p6_path.is_file() or p6_mount.is_file()
    p6_hash = _file_short_hash(p6_path if p6_path.is_file() else p6_mount)

    return {
        "probe_ts": time.time(),
        "git_head": git_head,
        "git_head_short": head_short,
        "git_branch": git_branch,
        "git_log1": git_log1,
        "git_head_contains_probe_asset": head_contains_probe_asset,
        "cwd": str(cwd.resolve()),
        "module_dir": str(module_root),
        "repo_root": str(repo_root.resolve()),
        "streamlit_app_abspath": str(streamlit_entry.resolve()),
        "streamlit_version": _streamlit_version(),
        "config_path": str(config_path.resolve()) if config_exists else str(config_path),
        "config_exists": config_exists,
        "config_enable_static_serving": config_enable_static,
        "effective_enable_static_serving": effective_enable_static,
        "static_dir_abspath": str(static_dir.resolve()) if static_dir.exists() else str(static_dir),
        "static_dir_exists": static_dir.is_dir(),
        "repo_static_probe_abspath": repo_probe.get("abspath"),
        "repo_static_probe_exists": bool(repo_probe.get("exists")),
        "repo_static_probe_size_bytes": repo_probe.get("size_bytes"),
        "repo_static_probe_sentinel_probe": repo_probe.get("probe"),
        "repo_static_probe_sentinel_source": repo_probe.get("source"),
        "repo_static_probe_sentinel_ok": bool(repo_probe.get("sentinel_ok")),
        "deploy_commit_exists": deploy_commit_exists,
        "deploy_commit_raw": deploy_raw.splitlines()[0][:120] if deploy_raw else "",
        "deploy_pin": deploy_pin,
        "app_runtime_deploy_marker": deploy_pin,
        "deploy_commit_reads": deploy_reads,
        "p6_diag_exists": p6_exists,
        "p6_diag_short_hash": p6_hash,
    }


def solo_cloud_fs_probe_enabled(st: Any) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_get
    except ImportError:
        return False
    return str(_qp_get(st, PROBE_QUERY_PARAM) or "").strip().lower() in ("1", "true", "yes")


def maybe_render_cloud_runtime_fs_probe(st: Any) -> bool:
    if not solo_cloud_fs_probe_enabled(st):
        return False
    render_cloud_runtime_fs_probe(st)
    return True


def render_cloud_runtime_fs_probe(st: Any) -> None:
    """Render hidden DOM probe; diagnostic query param only."""
    payload = collect_cloud_runtime_fs_probe(st=st)
    attrs = {
        "id": PROBE_ELEMENT_ID,
        "data-git-head": payload.get("git_head") or "",
        "data-git-head-short": payload.get("git_head_short") or "",
        "data-git-branch": payload.get("git_branch") or "",
        "data-git-log1": payload.get("git_log1") or "",
        "data-cwd": payload.get("cwd") or "",
        "data-streamlit-app": payload.get("streamlit_app_abspath") or "",
        "data-streamlit-version": payload.get("streamlit_version") or "",
        "data-repo-root": payload.get("repo_root") or "",
        "data-config-path": payload.get("config_path") or "",
        "data-config-exists": "1" if payload.get("config_exists") else "0",
        "data-effective-enable-static-serving": str(payload.get("effective_enable_static_serving")).lower(),
        "data-static-dir": payload.get("static_dir_abspath") or "",
        "data-static-dir-exists": "1" if payload.get("static_dir_exists") else "0",
        "data-repo-static-probe-path": payload.get("repo_static_probe_abspath") or "",
        "data-repo-static-probe-exists": "1" if payload.get("repo_static_probe_exists") else "0",
        "data-repo-static-probe-size": str(payload.get("repo_static_probe_size_bytes") or 0),
        "data-repo-static-probe-sentinel-ok": "1" if payload.get("repo_static_probe_sentinel_ok") else "0",
        "data-deploy-commit-raw": payload.get("deploy_commit_raw") or "",
        "data-deploy-pin": payload.get("deploy_pin") or "",
        "data-app-runtime-deploy-marker": payload.get("app_runtime_deploy_marker") or "",
        "data-git-head-contains-probe-asset": "1" if payload.get("git_head_contains_probe_asset") else "0",
        "data-p6-diag-exists": "1" if payload.get("p6_diag_exists") else "0",
        "data-p6-diag-hash": payload.get("p6_diag_short_hash") or "",
    }
    attr_html = " ".join(
        f'{html.escape(k, quote=True)}="{html.escape(str(v), quote=True)}"'
        for k, v in attrs.items()
        if k != "id"
    )
    json_blob = html.escape(json.dumps(payload, sort_keys=True, default=str), quote=True)
    st.markdown(
        f"<!-- {PROBE_ELEMENT_ID} -->\n"
        f'<div id="{PROBE_ELEMENT_ID}" {attr_html} data-json="{json_blob}"></div>',
        unsafe_allow_html=True,
    )


def payload_excludes_secrets(payload: dict[str, Any]) -> bool:
    blob = json.dumps(payload, default=str).lower()
    forbidden = (
        "access_token",
        "refresh_token",
        "supabase",
        "password",
        "bridge_sid",
        "suite_sid",
        "api_key",
        "secret",
    )
    return not any(token in blob for token in forbidden)
