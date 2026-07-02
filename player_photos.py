"""Shared player headshot resolution and rendering for Baseball App modules."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

MLB_HEADSHOT_URL = (
    "https://img.mlbstatic.com/mlb-photos/image/upload/"
    "d_people:generic:headshot:83:current.png/w_{size},q_auto:best/"
    "v1/people/{mlbam_id}/headshot/silo/current.png"
)

_CACHE_FILENAME = "player_mlbam_cache.json"
_PEOPLE_PHOTO_COLS = ("playerID", "nameFirst", "nameLast", "birthYear", "bbrefID", "retroID")


def app_base_dir() -> Path:
    return Path(__file__).resolve().parent


def mlb_headshot_url(mlbam_id: int | str | None, *, size: int = 120) -> str | None:
    if mlbam_id is None:
        return None
    text = str(mlbam_id).strip()
    if not text or text == "nan":
        return None
    try:
        pid = int(float(text))
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    return MLB_HEADSHOT_URL.format(size=max(40, min(int(size), 400)), mlbam_id=pid)


def _cache_path(base_dir: Path | str | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else app_base_dir()
    return root / "data" / _CACHE_FILENAME


def _load_mlbam_cache(base_dir: Path | str | None = None) -> dict[str, int]:
    path = _cache_path(base_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, val in raw.items():
        try:
            out[str(key)] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def _save_mlbam_cache(cache: dict[str, int], base_dir: Path | str | None = None) -> None:
    path = _cache_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def load_people_photo_lookup(base_dir: Path | str | None = None) -> pd.DataFrame:
    """Lahman People.csv slice used for playerID → name / birthYear resolution."""
    root = Path(base_dir) if base_dir is not None else app_base_dir()
    path = root / "People.csv"
    if not path.is_file():
        return pd.DataFrame(columns=list(_PEOPLE_PHOTO_COLS))
    try:
        people = pd.read_csv(path, usecols=lambda c: c in _PEOPLE_PHOTO_COLS, low_memory=False)
    except (OSError, ValueError):
        try:
            people = pd.read_csv(path, low_memory=False)
        except OSError:
            return pd.DataFrame(columns=list(_PEOPLE_PHOTO_COLS))
        keep = [c for c in _PEOPLE_PHOTO_COLS if c in people.columns]
        people = people[keep].copy()
    if "playerID" not in people.columns:
        return pd.DataFrame(columns=list(_PEOPLE_PHOTO_COLS))
    people["playerID"] = people["playerID"].astype(str).str.strip()
    if "nameFirst" in people.columns and "nameLast" in people.columns:
        people["fullName"] = (
            people["nameFirst"].fillna("").astype(str).str.strip()
            + " "
            + people["nameLast"].fillna("").astype(str).str.strip()
        ).str.strip()
    return people


def _normalize_name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _lookup_people_row(
    *,
    player_id: str | None = None,
    full_name: str | None = None,
    people_df: pd.DataFrame | None = None,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    df = people_df if people_df is not None else load_people_photo_lookup(base_dir)
    if df is None or df.empty:
        return {}
    pid = str(player_id or "").strip()
    if pid and "playerID" in df.columns:
        match = df[df["playerID"].astype(str).str.strip().eq(pid)]
        if not match.empty:
            return match.iloc[0].to_dict()
    name = str(full_name or "").strip()
    if name and "fullName" in df.columns:
        exact = df[df["fullName"].astype(str).str.strip().eq(name)]
        if not exact.empty:
            return exact.iloc[0].to_dict()
        key = _normalize_name_key(name)
        if key:
            norm = df["fullName"].astype(str).map(_normalize_name_key)
            fuzzy = df[norm.eq(key)]
            if not fuzzy.empty:
                return fuzzy.iloc[0].to_dict()
    return {}


def _search_mlbam_via_api(full_name: str, birth_year: int | None = None) -> int | None:
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode({"names": full_name, "hydrate": "currentTeam"})
    url = f"https://statsapi.mlb.com/api/v1/people/search?{query}"
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    people = payload.get("people") if isinstance(payload, dict) else None
    if not isinstance(people, list) or not people:
        return None
    candidates: list[tuple[int, dict[str, Any]]] = []
    for person in people:
        if not isinstance(person, dict):
            continue
        pid = person.get("id")
        try:
            mlbam = int(pid)
        except (TypeError, ValueError):
            continue
        candidates.append((mlbam, person))
    if not candidates:
        return None
    if birth_year is not None and len(candidates) > 1:
        by_year = [
            (mlbam, p)
            for mlbam, p in candidates
            if str(p.get("birthDate") or "").startswith(str(int(birth_year)))
        ]
        if len(by_year) == 1:
            return by_year[0][0]
    return candidates[0][0]


def resolve_mlbam_id(
    *,
    player_id: str | None = None,
    full_name: str | None = None,
    mlbam_id: int | str | None = None,
    birth_year: int | None = None,
    people_df: pd.DataFrame | None = None,
    base_dir: Path | str | None = None,
    use_api: bool = True,
) -> int | None:
    """Resolve a Lahman playerID or name to an MLBAM person id (cached)."""
    if mlbam_id is not None:
        try:
            resolved = int(float(str(mlbam_id).strip()))
            if resolved > 0:
                return resolved
        except (TypeError, ValueError):
            pass

    pid = str(player_id or "").strip()
    cache = _load_mlbam_cache(base_dir)
    if pid and pid in cache:
        return cache[pid]

    row = _lookup_people_row(
        player_id=pid or None,
        full_name=full_name,
        people_df=people_df,
        base_dir=base_dir,
    )
    if not pid and row.get("playerID"):
        pid = str(row["playerID"]).strip()
        if pid in cache:
            return cache[pid]

    name = str(full_name or row.get("fullName") or "").strip()
    if not name:
        return None

    by = birth_year
    if by is None and row.get("birthYear") is not None:
        try:
            by = int(float(row["birthYear"]))
        except (TypeError, ValueError):
            by = None

    if not use_api:
        return None

    found = _search_mlbam_via_api(name, by)
    if found and pid:
        cache[pid] = found
        _save_mlbam_cache(cache, base_dir)
    return found


def get_player_photo_info(
    *,
    player_id: str | None = None,
    full_name: str | None = None,
    mlbam_id: int | str | None = None,
    row: Any = None,
    people_df: pd.DataFrame | None = None,
    base_dir: Path | str | None = None,
    use_api: bool = True,
    image_size: int = 120,
) -> dict[str, Any]:
    """Return headshot URL and identity fields for a player."""
    if row is not None:
        if player_id is None:
            player_id = str(getattr(row, "get", lambda _k, _d=None: None)("playerID") or getattr(row, "get", lambda _k, _d=None: None)("player_id") or "").strip() or None
        if full_name is None:
            full_name = str(getattr(row, "get", lambda _k, _d=None: None)("fullName") or getattr(row, "get", lambda _k, _d=None: None)("Player") or "").strip() or None
        if mlbam_id is None:
            for col in ("MLBAM ID", "mlbam_id", "mlbamId"):
                if hasattr(row, "get"):
                    val = row.get(col)
                    if val is not None and str(val).strip() not in ("", "nan"):
                        mlbam_id = val
                        break

    resolved = resolve_mlbam_id(
        player_id=player_id,
        full_name=full_name,
        mlbam_id=mlbam_id,
        people_df=people_df,
        base_dir=base_dir,
        use_api=use_api,
    )
    url = mlb_headshot_url(resolved, size=image_size) if resolved else None
    return {
        "player_id": str(player_id or "").strip() or None,
        "full_name": str(full_name or "").strip() or None,
        "mlbam_id": resolved,
        "headshot_url": url,
        "has_photo": bool(url),
    }


def _safe_markdown(st: Any, body: str, *, allow_html: bool = True) -> None:
    if allow_html:
        try:
            st.markdown(body, unsafe_allow_html=True)
            return
        except TypeError:
            pass
    st.markdown(body)


def inject_player_photo_styles(st: Any) -> None:
    _safe_markdown(
        st,
        """
        <style>
        .bb-player-photo-wrap {
            display: flex;
            align-items: center;
            gap: 14px;
            margin: 8px 0 14px 0;
        }
        .bb-player-photo {
            width: 96px;
            height: 96px;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid rgba(26, 95, 191, 0.35);
            background: #e8eef5;
            flex-shrink: 0;
        }
        .bb-player-photo-sm {
            width: 72px;
            height: 72px;
        }
        .bb-player-photo-xs {
            width: 56px;
            height: 56px;
        }
        .bb-player-photo-title {
            font-size: 1.35rem;
            font-weight: 800;
            line-height: 1.15;
            margin: 0;
        }
        .bb-player-photo-sub {
            font-size: 0.9rem;
            color: #5a6472;
            margin-top: 4px;
        }
        .ld-rec-card-header {
            display: flex;
            gap: 12px;
            align-items: flex-start;
            margin-bottom: 6px;
        }
        .ld-rec-card-photo img {
            width: 64px;
            height: 64px;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid rgba(26, 95, 191, 0.25);
            background: #edf2f7;
        }
        .ld-rec-card-meta {
            flex: 1;
            min-width: 0;
        }
        .ld-rec-stat-line {
            font-size: 0.82rem;
            color: #334155;
            margin: 2px 0 4px 0;
        }
        .ld-rec-grade {
            font-weight: 700;
            color: #0b3d6e;
        }
        .ld-pos-heat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
            gap: 8px;
            margin-top: 8px;
        }
        .ld-pos-heat-cell {
            border-radius: 10px;
            padding: 8px 6px;
            text-align: center;
            font-size: 12px;
            font-weight: 700;
            border: 1px solid rgba(0,0,0,0.06);
        }
        .ld-pos-heat-strong { background: #fee2e2; color: #991b1b; }
        .ld-pos-heat-moderate { background: #fef3c7; color: #92400e; }
        .ld-pos-heat-weak { background: #dcfce7; color: #166534; }
        .ld-pos-heat-label { display: block; font-size: 11px; font-weight: 800; }
        .ld-pos-heat-val { display: block; font-size: 10px; font-weight: 600; opacity: 0.9; }
        </style>
        """,
    )


def render_player_headshot_row(
    st: Any,
    photo_info: dict[str, Any],
    *,
    title: str = "",
    subtitle: str = "",
    size: int = 96,
) -> None:
    inject_player_photo_styles(st)
    url = str(photo_info.get("headshot_url") or "").strip()
    name = str(title or photo_info.get("full_name") or "Player").strip()
    sub = str(subtitle or "").strip()
    if url:
        img = f'<img class="bb-player-photo" src="{url}" alt="{name} headshot" width="{size}" height="{size}"/>'
    else:
        img = f'<div class="bb-player-photo" style="display:flex;align-items:center;justify-content:center;font-size:1.6rem;color:#64748b;">⚾</div>'
    sub_html = f'<div class="bb-player-photo-sub">{sub}</div>' if sub else ""
    _safe_markdown(
        st,
        f'<div class="bb-player-photo-wrap">{img}<div>'
        f'<div class="bb-player-photo-title">{name}</div>{sub_html}</div></div>',
    )


def render_rec_card_photo_html(photo_info: dict[str, Any], *, alt: str = "") -> str:
    url = str(photo_info.get("headshot_url") or "").strip()
    label = str(alt or photo_info.get("full_name") or "Player").strip()
    if url:
        return f'<div class="ld-rec-card-photo"><img src="{url}" alt="{label}"/></div>'
    return (
        '<div class="ld-rec-card-photo">'
        '<div style="width:64px;height:64px;border-radius:50%;background:#edf2f7;'
        'display:flex;align-items:center;justify-content:center;font-size:1.2rem;color:#64748b;">⚾</div></div>'
    )


def compact_fantasy_stat_line(row: Any) -> str:
    """One-line key fantasy contributions for recommendation cards."""
    parts: list[str] = []

    def _num(col: str, fmt: str = "{:.0f}") -> str | None:
        if not hasattr(row, "get"):
            return None
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            for alt in (f"proj_{col}", col.lower()):
                val = row.get(alt)
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    break
            else:
                return None
        try:
            num = float(val)
        except (TypeError, ValueError):
            return None
        if col in ("BA", "OBP", "SLG", "OPS"):
            return fmt.format(num)
        return fmt.format(num)

    for col, label in (("HR", "HR"), ("RBI", "RBI"), ("R", "R"), ("SB", "SB")):
        txt = _num(col)
        if txt is not None:
            parts.append(f"{label} {txt}")
    ba = _num("BA", "{:.3f}")
    obp = _num("OBP", "{:.3f}")
    if ba is not None:
        parts.append(f"BA {ba}")
    elif obp is not None:
        parts.append(f"OBP {obp}")
    if not parts:
        for col in ("W", "SO", "SV", "ERA", "WHIP", "K/9"):
            txt = _num(col, "{:.2f}" if col in ("ERA", "WHIP", "K/9") else "{:.0f}")
            if txt is not None:
                parts.append(f"{col} {txt}")
    return " · ".join(parts[:6])


def player_grade_display(row: Any) -> str:
    for col in ("Expected Fantasy Value", "Player Grade"):
        if hasattr(row, "get"):
            val = row.get(col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                try:
                    n = float(val)
                    if 0 < n <= 1.5:
                        return str(int(round(n * 100)))
                    return str(int(round(n)))
                except (TypeError, ValueError):
                    continue
    return "—"


def render_draft_pick_callout(
    st: Any,
    row: Any,
    *,
    headline: str,
    detail: str = "",
    variant: str = "success",
) -> None:
    """Draft Assistant / simulator callout with optional player photo."""
    inject_player_photo_styles(st)
    try:
        photo_info = get_player_photo_info(row=row)
    except Exception:
        photo_info = {}
    name = str(getattr(row, "get", lambda _k, _d="": _d)("fullName") or "Player")
    pos = str(getattr(row, "get", lambda _k, _d="": _d)("Primary Position") or "")
    team = str(getattr(row, "get", lambda _k, _d="": _d)("Team") or getattr(row, "get", lambda _k, _d="": _d)("teamName") or "")
    grade = player_grade_display(row)
    stats = compact_fantasy_stat_line(row)
    photo_html = render_rec_card_photo_html(photo_info, alt=name)
    meta = f"{pos}" + (f" · {team}" if team else "") + f" · Grade <span class='ld-rec-grade'>{grade}</span>"
    stats_html = f'<div class="ld-rec-stat-line">{stats}</div>' if stats else ""
    detail_html = f'<div style="font-size:0.88rem;margin-top:4px;">{detail}</div>' if detail else ""
    border = "#16a34a" if variant == "success" else "#2563eb"
    bg = "#f0fdf4" if variant == "success" else "#eff6ff"
    _safe_markdown(
        st,
        f'<div style="border:1px solid {border};background:{bg};border-radius:12px;padding:12px 14px;">'
        f'<div class="ld-rec-card-header">{photo_html}<div class="ld-rec-card-meta">'
        f'<div style="font-weight:800;">{headline}</div>'
        f'<div style="font-size:0.95rem;"><strong>{name}</strong> — {meta}</div>'
        f"{stats_html}{detail_html}</div></div></div>",
    )