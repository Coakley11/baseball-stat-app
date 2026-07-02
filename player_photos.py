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


def _normalize_name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


# Built-in Lahman playerID → MLBAM map for common modern players (works without API/cache).
_KNOWN_MLBAM_BY_PLAYER_ID: dict[str, int] = {
    "harpebr03": 547180,  # Bryce Harper
    "troutmi01": 545361,  # Mike Trout
    "freemfr01": 518692,  # Freddie Freeman
    "pujolal01": 405395,  # Albert Pujols
    "sotodo01": 665742,   # Juan Soto
    "bettsmo01": 605141,  # Mookie Betts
    "judgeaa01": 592450,  # Aaron Judge
    "acunaro01": 660670,  # Ronald Acuña Jr.
    "oneiltr01": 656941,  # Tyler O'Neill
    "goldspau01": 502671, # Paul Goldschmidt
    "arenano01": 571448,  # Nolan Arenado
    "machama01": 592518,  # Manny Machado
    "tatisfe02": 665487,  # Fernando Tatis Jr.
    "guerrvl02": 665489,  # Vladimir Guerrero Jr.
    "bichetb01": 666182,  # Bo Bichette
    "alonspe01": 624413,  # Pete Alonso
    "deverra01": 646240,  # Rafael Devers
    "lindofr01": 596019,  # Francisco Lindor
    "seagerco01": 608369,  # Corey Seager
    "turneju01": 607208,  # Justin Turner
    "stantmi03": 519317,  # Giancarlo Stanton
    "kershcl01": 477132,  # Clayton Kershaw
    "degromj01": 594798,  # Jacob deGrom
    "colege01": 543037,   # Gerrit Cole
    "schmima01": 592191,  # Max Scherzer
    "verlaju01": 453286,  # Justin Verlander
}

# Normalized full-name keys for players when only a display name is available.
_KNOWN_MLBAM_BY_NAME: dict[str, int] = {
    _normalize_name_key(name): mlbam
    for name, mlbam in {
        "Bryce Harper": 547180,
        "Mike Trout": 545361,
        "Freddie Freeman": 518692,
        "Albert Pujols": 405395,
        "Juan Soto": 665742,
        "Mookie Betts": 605141,
        "Aaron Judge": 592450,
        "Ronald Acuna Jr.": 660670,
        "Ronald Acuña Jr.": 660670,
        "Paul Goldschmidt": 502671,
        "Nolan Arenado": 571448,
        "Manny Machado": 592518,
        "Fernando Tatis Jr.": 665487,
        "Vladimir Guerrero Jr.": 665489,
        "Pete Alonso": 624413,
        "Francisco Lindor": 596019,
        "Giancarlo Stanton": 519317,
    }.items()
}


def _seed_mlbam_id(
    *,
    player_id: str | None = None,
    full_name: str | None = None,
) -> int | None:
    pid = str(player_id or "").strip().lower()
    if pid and pid in _KNOWN_MLBAM_BY_PLAYER_ID:
        return _KNOWN_MLBAM_BY_PLAYER_ID[pid]
    name_key = _normalize_name_key(full_name or "")
    if name_key and name_key in _KNOWN_MLBAM_BY_NAME:
        return _KNOWN_MLBAM_BY_NAME[name_key]
    return None


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


def _cache_lookup(
    cache: dict[str, int],
    *,
    player_id: str | None = None,
    full_name: str | None = None,
) -> int | None:
    pid = str(player_id or "").strip()
    if pid and pid in cache:
        return cache[pid]
    name_key = _normalize_name_key(full_name or "")
    if name_key:
        by_name = cache.get(f"name:{name_key}")
        if by_name is not None:
            return int(by_name)
    return None


def _cache_store(
    cache: dict[str, int],
    mlbam_id: int,
    *,
    player_id: str | None = None,
    full_name: str | None = None,
) -> None:
    pid = str(player_id or "").strip()
    if pid:
        cache[pid] = mlbam_id
    name_key = _normalize_name_key(full_name or "")
    if name_key:
        cache[f"name:{name_key}"] = mlbam_id


def resolve_mlbam_id(
    *,
    player_id: str | None = None,
    full_name: str | None = None,
    mlbam_id: int | str | None = None,
    birth_year: int | None = None,
    people_df: pd.DataFrame | None = None,
    base_dir: Path | str | None = None,
    use_api: bool = True,
) -> tuple[int | None, str]:
    """Resolve a Lahman playerID or name to an MLBAM person id (cached)."""
    if mlbam_id is not None:
        try:
            resolved = int(float(str(mlbam_id).strip()))
            if resolved > 0:
                return resolved, "mlbam_column"
        except (TypeError, ValueError):
            pass

    pid = str(player_id or "").strip()
    row = _lookup_people_row(
        player_id=pid or None,
        full_name=full_name,
        people_df=people_df,
        base_dir=base_dir,
    )
    if not pid and row.get("playerID"):
        pid = str(row["playerID"]).strip()

    name = str(full_name or row.get("fullName") or "").strip()

    seeded = _seed_mlbam_id(player_id=pid or None, full_name=name)
    if seeded:
        return seeded, "seed_map"

    cache = _load_mlbam_cache(base_dir)
    cached = _cache_lookup(cache, player_id=pid or None, full_name=name)
    if cached:
        return cached, "cache"

    if not use_api or not name:
        return None, "placeholder_no_mlbam_id"

    by = birth_year
    if by is None and row.get("birthYear") is not None:
        try:
            by = int(float(row["birthYear"]))
        except (TypeError, ValueError):
            by = None

    found = _search_mlbam_via_api(name, by)
    if found:
        _cache_store(cache, found, player_id=pid or None, full_name=name)
        _save_mlbam_cache(cache, base_dir)
        return found, "api_lookup"
    return None, "placeholder_no_mlbam_id"


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

    resolved, resolve_source = resolve_mlbam_id(
        player_id=player_id,
        full_name=full_name,
        mlbam_id=mlbam_id,
        people_df=people_df,
        base_dir=base_dir,
        use_api=use_api,
    )
    url = mlb_headshot_url(resolved, size=image_size) if resolved else None
    fallback_reason = resolve_source if url else resolve_source
    return {
        "player_id": str(player_id or "").strip() or None,
        "full_name": str(full_name or "").strip() or None,
        "mlbam_id": resolved,
        "headshot_url": url,
        "has_photo": bool(url),
        "resolve_source": resolve_source,
        "fallback_reason": fallback_reason,
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
        .bb-profile-card {
            border: 1px solid rgba(15, 23, 42, 0.12);
            border-radius: 12px;
            padding: 12px 14px;
            background: #fafbfc;
            margin-bottom: 10px;
        }
        .bb-profile-card-compact { padding: 10px 12px; }
        .bb-queue-headshot img, .bb-queue-headshot .bb-queue-placeholder {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            object-fit: cover;
            border: 1px solid rgba(26, 95, 191, 0.25);
            background: #edf2f7;
            flex-shrink: 0;
        }
        .bb-queue-headshot .bb-queue-placeholder {
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.95rem;
            color: #64748b;
        }
        .bb-queue-row {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .bb-comparison-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 12px;
            margin: 10px 0 16px 0;
        }
        .bb-roster-recap-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 12px;
            margin: 12px 0 18px 0;
        }
        .bb-roster-slot-label {
            font-size: 0.78rem;
            font-weight: 800;
            color: #0b3d6e;
            letter-spacing: 0.04em;
            margin-bottom: 4px;
        }
        .bb-profile-na {
            font-size: 0.82rem;
            color: #64748b;
            font-style: italic;
        }
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


PROJECTION_STAT_LIMITS: dict[str, float] = {"HR": 80, "RBI": 180, "R": 180, "SB": 100}
_PROJECTION_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "HR": ("proj_HR", "Projected HR"),
    "RBI": ("proj_RBI", "Projected RBI"),
    "R": ("proj_R", "Projected R"),
    "SB": ("proj_SB", "Projected SB"),
    "BA": ("proj_BA", "Projected AVG", "Projected BA"),
    "OBP": ("proj_OBP", "Projected OBP"),
    "SLG": ("proj_SLG", "Projected SLG"),
    "OPS": ("proj_OPS", "Projected OPS"),
}
_ROSTER_RECAP_SLOTS = ("C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL")


def _row_get(row: Any, col: str) -> Any:
    if row is None:
        return None
    if hasattr(row, "get"):
        return row.get(col)
    try:
        return row[col]
    except (KeyError, TypeError, IndexError):
        return None


def _coerce_float(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if pd.isna(num):
        return None
    return num


def extract_projection_value(row: Any, stat: str) -> float | None:
    """Read a single-season fantasy projection — never raw career counting totals."""
    if not hasattr(row, "get"):
        return None
    for col in _PROJECTION_COLUMN_ALIASES.get(stat, (f"proj_{stat}",)):
        val = _coerce_float(_row_get(row, col))
        if val is not None:
            return val
    return None


def projection_stat_plausible(stat: str, value: float | None) -> bool:
    if value is None:
        return False
    limit = PROJECTION_STAT_LIMITS.get(stat)
    if limit is not None and value > limit:
        return False
    if stat == "BA" and (value <= 0 or value > 0.450):
        return False
    return True


def compact_fantasy_stat_line(row: Any, *, prefix: str = "Proj:", require_projection: bool = True) -> str:
    """One-line projected fantasy stats for draft recommendation cards."""
    parts: list[str] = []

    for stat, label in (("HR", "HR"), ("RBI", "RBI"), ("R", "R"), ("SB", "SB")):
        val = extract_projection_value(row, stat)
        if val is None and not require_projection:
            val = _coerce_float(_row_get(row, stat))
        if val is None:
            continue
        if not projection_stat_plausible(stat, val):
            continue
        parts.append(f"{int(round(val))} {label}")

    ba_val = extract_projection_value(row, "BA")
    if ba_val is None and not require_projection:
        ba_val = _coerce_float(_row_get(row, "BA"))
    if ba_val is not None and projection_stat_plausible("BA", ba_val):
        parts.append(f"{ba_val:.3f} AVG")
    elif not parts:
        obp_val = extract_projection_value(row, "OBP")
        if obp_val is not None:
            parts.append(f"OBP {obp_val:.3f}")

    if not parts and not require_projection:
        for col in ("W", "SO", "SV", "ERA", "WHIP", "K/9"):
            val = _coerce_float(_row_get(row, col))
            if val is not None:
                fmt = "{:.2f}" if col in ("ERA", "WHIP", "K/9") else "{:.0f}"
                parts.append(f"{col} {fmt.format(val)}")

    body = " · ".join(parts[:6])
    if not body:
        return ""
    pref = str(prefix or "").strip()
    return f"{pref} {body}".strip() if pref else body


def is_current_draft_pool_player(player_id: str, yearly_df: pd.DataFrame | None) -> bool:
    """True when the player is active/recent in the dataset (draft-pool eligible)."""
    if yearly_df is None or yearly_df.empty:
        return False
    if "playerID" not in yearly_df.columns or "yearID" not in yearly_df.columns:
        return False
    years = pd.to_numeric(
        yearly_df.loc[yearly_df["playerID"] == player_id, "yearID"],
        errors="coerce",
    ).dropna()
    if years.empty:
        return False
    latest_player_year = int(years.max())
    all_years = pd.to_numeric(yearly_df["yearID"], errors="coerce").dropna()
    latest_dataset_year = int(all_years.max()) if not all_years.empty else latest_player_year
    return latest_player_year in (2025, 2026) or latest_player_year >= latest_dataset_year - 1


def lookup_row_by_player_name(
    name: str,
    lookup_df: pd.DataFrame | None,
    *,
    name_col: str = "fullName",
) -> pd.Series | None:
    target = str(name or "").strip().lower()
    if not target or lookup_df is None or lookup_df.empty:
        return None
    col = name_col if name_col in lookup_df.columns else None
    if col is None:
        for alt in ("fullName", "Player", "player"):
            if alt in lookup_df.columns:
                col = alt
                break
    if col is None:
        return None
    for _, row in lookup_df.iterrows():
        full = str(row.get(col) or "").strip()
        if full.lower() == target or full == str(name or "").strip():
            return row
    return None


def roster_fit_display(row: Any) -> str:
    for col in ("Draft Fit Score", "Roster Fit Score", "Positional Fit", "Team fit"):
        val = _row_get(row, col)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            try:
                num = float(val)
                if 0 < num <= 1.5:
                    return str(int(round(num * 100)))
                return str(int(round(num)))
            except (TypeError, ValueError):
                text = str(val).strip()
                if text:
                    return text
    return "—"


def adp_display(row: Any) -> str:
    for col in ("ADP", "ADP Rank", "Market Rank"):
        val = _row_get(row, col)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            try:
                return str(int(round(float(val))))
            except (TypeError, ValueError):
                text = str(val).strip()
                if text:
                    return text
    return "—"


def render_queue_headshot_html(photo_info: dict[str, Any], *, size: int = 36) -> str:
    url = str(photo_info.get("headshot_url") or "").strip()
    label = str(photo_info.get("full_name") or "Player").strip()
    if url:
        return (
            f'<div class="bb-queue-headshot">'
            f'<img src="{url}" alt="{label}" width="{size}" height="{size}"/>'
            f"</div>"
        )
    return (
        '<div class="bb-queue-headshot">'
        '<div class="bb-queue-placeholder" aria-hidden="true">⚾</div>'
        "</div>"
    )


def build_draft_profile_card_html(
    row: Any,
    photo_info: dict[str, Any],
    *,
    slot_label: str = "",
    reason: str = "",
    show_projection: bool = True,
    show_grade: bool = True,
    show_roster_fit: bool = True,
    show_adp: bool = False,
    compact: bool = False,
    historical_note: str = "",
) -> str:
    name = str(_row_get(row, "fullName") or _row_get(row, "Player") or photo_info.get("full_name") or "Player")
    pos = str(_row_get(row, "Primary Position") or _row_get(row, "Position") or "—")
    team = str(
        _row_get(row, "Team")
        or _row_get(row, "MLB Team")
        or _row_get(row, "teamName")
        or ""
    ).strip()
    photo_html = render_rec_card_photo_html(photo_info, alt=name)
    meta_bits = [pos]
    if team:
        meta_bits.append(team)
    meta_line = " · ".join(meta_bits)
    detail_lines: list[str] = []
    if show_projection:
        stats = compact_fantasy_stat_line(row)
        if stats:
            detail_lines.append(f'<div class="ld-rec-stat-line">{stats}</div>')
        elif historical_note:
            detail_lines.append(f'<div class="bb-profile-na">{historical_note}</div>')
    elif historical_note:
        detail_lines.append(f'<div class="bb-profile-na">{historical_note}</div>')
    grade_bits: list[str] = []
    if show_grade:
        grade_bits.append(f'Grade <span class="ld-rec-grade">{player_grade_display(row)}</span>')
    if show_roster_fit:
        grade_bits.append(f'Roster fit <span class="ld-rec-grade">{roster_fit_display(row)}</span>')
    if show_adp:
        adp = adp_display(row)
        if adp != "—":
            grade_bits.append(f"ADP/Mkt {adp}")
    if grade_bits:
        detail_lines.append(f'<div style="font-size:0.84rem;margin-top:2px;">{" · ".join(grade_bits)}</div>')
    if reason:
        detail_lines.append(f'<div style="font-size:0.86rem;margin-top:4px;color:#334155;">{reason}</div>')
    slot_html = f'<div class="bb-roster-slot-label">{slot_label}</div>' if slot_label else ""
    card_class = "bb-profile-card bb-profile-card-compact" if compact else "bb-profile-card"
    details_html = "".join(detail_lines)
    return (
        f'<div class="{card_class}">{slot_html}'
        f'<div class="ld-rec-card-header">{photo_html}<div class="ld-rec-card-meta">'
        f'<div style="font-size:1.02rem;font-weight:800;">{name}</div>'
        f'<div style="font-size:0.88rem;color:#475569;">{meta_line}</div>'
        f"{details_html}</div></div></div>"
    )


def render_draft_player_profile_card(
    st: Any,
    row: Any,
    *,
    slot_label: str = "",
    reason: str = "",
    show_projection: bool = True,
    show_grade: bool = True,
    show_roster_fit: bool = True,
    show_adp: bool = False,
    compact: bool = False,
    historical_note: str = "",
) -> None:
    inject_player_photo_styles(st)
    try:
        photo_info = get_player_photo_info(row=row)
    except Exception:
        photo_info = {}
    html = build_draft_profile_card_html(
        row,
        photo_info,
        slot_label=slot_label,
        reason=reason,
        show_projection=show_projection,
        show_grade=show_grade,
        show_roster_fit=show_roster_fit,
        show_adp=show_adp,
        compact=compact,
        historical_note=historical_note,
    )
    _safe_markdown(st, html)


def render_draft_player_profile_cards(
    st: Any,
    rows: list[Any],
    *,
    columns: int = 2,
    **card_kwargs: Any,
) -> None:
    if not rows:
        return
    inject_player_photo_styles(st)
    cols = max(1, min(int(columns), 3))
    for start in range(0, len(rows), cols):
        chunk = rows[start : start + cols]
        st_cols = st.columns(len(chunk))
        for col, row in zip(st_cols, chunk):
            with col:
                render_draft_player_profile_card(st, row, **card_kwargs)


def render_insight_player_header(st: Any, row: Any) -> None:
    """Photo + name row above player-specific insight summaries."""
    if row is None:
        return
    inject_player_photo_styles(st)
    try:
        photo_info = get_player_photo_info(row=row)
    except Exception:
        photo_info = {}
    name = str(_row_get(row, "fullName") or _row_get(row, "Player") or "Player")
    pos = str(_row_get(row, "Primary Position") or "")
    team = str(_row_get(row, "Team") or _row_get(row, "MLB Team") or "").strip()
    subtitle = " · ".join(x for x in (pos, team) if x)
    render_player_headshot_row(st, photo_info, title=name, subtitle=subtitle, size=72)


def _split_position_tokens(primary_val: Any) -> list[str]:
    if primary_val is None or (isinstance(primary_val, float) and pd.isna(primary_val)):
        return []
    s = str(primary_val).upper().replace(" ", "")
    parts = re.split(r"[,/\+]", s)
    out = [p.strip() for p in parts if p.strip()]
    if not out:
        out = [str(primary_val).upper().strip()]
    return list(dict.fromkeys(out))


def _eligible_for_slot(pos_tokens: list[str], slot: str) -> bool:
    if slot == "UTIL":
        return not any(p in ("P", "SP", "RP") for p in pos_tokens)
    if slot == "OF":
        return any(p == "OF" for p in pos_tokens)
    if slot in ("C", "1B", "2B", "3B", "SS"):
        if pos_tokens == ["DH"]:
            return False
        if slot in pos_tokens:
            return True
        if slot == "1B" and "3B" in pos_tokens:
            return True
        if slot == "3B" and "1B" in pos_tokens:
            return True
        if slot == "2B" and "SS" in pos_tokens:
            return True
        if slot == "SS" and "2B" in pos_tokens:
            return True
    return False


def assign_roster_recap_slots(roster_df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    """Map roster rows to fantasy lineup slots for completed-draft recap cards."""
    if roster_df is None or roster_df.empty:
        return []
    df = roster_df.copy()
    name_col = "fullName" if "fullName" in df.columns else "Player"
    if name_col not in df.columns:
        return []
    score_col = "Expected Fantasy Value" if "Expected Fantasy Value" in df.columns else None
    if score_col:
        df["_slot_score"] = pd.to_numeric(df[score_col], errors="coerce").fillna(0)
    else:
        df["_slot_score"] = 0.0
    pos_col = "Primary Position" if "Primary Position" in df.columns else None
    if pos_col:
        df["_pos_tokens"] = df[pos_col].apply(_split_position_tokens)
    else:
        df["_pos_tokens"] = [[] for _ in range(len(df))]
    assigned: set[Any] = set()
    slots_out: list[tuple[str, pd.Series]] = []
    of_count = 0
    for slot in _ROSTER_RECAP_SLOTS:
        display_slot = slot
        if slot == "OF":
            of_count += 1
            display_slot = f"OF{of_count}"
        best_ix = None
        best_score = -1.0
        for ix in df.index:
            if ix in assigned:
                continue
            toks = df.at[ix, "_pos_tokens"]
            if not isinstance(toks, list):
                toks = []
            if _eligible_for_slot(toks, slot):
                score = float(df.at[ix, "_slot_score"])
                if score > best_score:
                    best_score = score
                    best_ix = ix
        if best_ix is not None:
            assigned.add(best_ix)
            slots_out.append((display_slot, df.loc[best_ix]))
    for ix in df.index:
        if ix in assigned:
            continue
        name = str(df.at[ix, name_col])
        slots_out.append((str(df.at[ix, pos_col] if pos_col else "BN"), df.loc[ix]))
    return slots_out


def render_completed_roster_recap(
    st: Any,
    roster_df: pd.DataFrame,
    *,
    team_name: str = "",
    title: str = "Draft recap by position",
) -> None:
    """Position-slot recap cards with photo, name, team, and projected stat line."""
    if roster_df is None or roster_df.empty:
        return
    inject_player_photo_styles(st)
    heading = title if not team_name else f"{title} — {team_name}"
    st.markdown(f"**{heading}**")
    slots = assign_roster_recap_slots(roster_df)
    if not slots:
        return
    cards_html = "".join(
        build_draft_profile_card_html(
            row,
            get_player_photo_info(row=row),
            slot_label=f"{slot}:",
            show_adp=False,
            compact=True,
        )
        for slot, row in slots
    )
    _safe_markdown(st, f'<div class="bb-roster-recap-grid">{cards_html}</div>')


def render_comparison_profile_cards(
    st: Any,
    *,
    labels: list[str],
    player_ids: list[str],
    yearly_df: pd.DataFrame | None,
    projection_lookup_df: pd.DataFrame | None = None,
    projection_lookup_name_col: str = "fullName",
    strengths_map: dict[str, str] | None = None,
) -> None:
    """Side-by-side profile cards for the Comparison Tool."""
    if not labels:
        return
    inject_player_photo_styles(st)
    cards: list[str] = []
    for label, pid in zip(labels, player_ids):
        active = is_current_draft_pool_player(pid, yearly_df)
        proj_row = lookup_row_by_player_name(label, projection_lookup_df, name_col=projection_lookup_name_col)
        display_row = proj_row if proj_row is not None else pd.Series({"fullName": label, "playerID": pid})
        if active and proj_row is None:
            display_row = pd.Series({"fullName": label, "playerID": pid})
        try:
            photo_info = get_player_photo_info(player_id=pid, full_name=label, row=display_row)
        except Exception:
            photo_info = get_player_photo_info(full_name=label)
        reason = (strengths_map or {}).get(label, "")
        if active:
            cards.append(
                build_draft_profile_card_html(
                    display_row,
                    photo_info,
                    reason=reason,
                    show_projection=True,
                    show_grade=True,
                    show_roster_fit=True,
                    show_adp=True,
                )
            )
        else:
            cards.append(
                build_draft_profile_card_html(
                    display_row,
                    photo_info,
                    show_projection=False,
                    show_grade=False,
                    show_roster_fit=False,
                    show_adp=False,
                    historical_note="Not applicable — historical player",
                    reason=reason,
                )
            )
    _safe_markdown(st, f'<div class="bb-comparison-cards">{"".join(cards)}</div>')


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