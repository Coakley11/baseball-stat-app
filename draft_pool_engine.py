"""Pure draft pool/scoring engine — loads app defs without Streamlit UI render."""

from __future__ import annotations

import sys
import types
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent


class _StreamlitShim(types.ModuleType):
    """No-op Streamlit stand-in for offline exec of pool builder definitions."""

    def __init__(self) -> None:
        super().__init__("streamlit")
        self.session_state: dict[str, Any] = {}
        self.sidebar = types.SimpleNamespace()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in ("cache_data", "cache_resource", "dialog"):
            return lambda *a, **kwargs: (lambda fn: fn)
        if name == "spinner":
            return lambda *a, **k: types.SimpleNamespace(
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if name == "expander":
            return lambda *a, **k: types.SimpleNamespace(
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if name == "columns":
            def _columns(spec: Any) -> list[Any]:
                count = len(spec) if isinstance(spec, (list, tuple)) else int(spec or 1)
                return [types.SimpleNamespace()] * count

            return _columns
        if name in ("error", "stop", "warning", "info", "success", "markdown", "button"):
            return lambda *a, **k: None
        return lambda *a, **k: None


def _app_source_path() -> Path:
    for name in ("streamlit_app.py", "Streamlit_app.py"):
        path = _ROOT / name
        if path.is_file():
            return path
    raise FileNotFoundError("streamlit_app.py / Streamlit_app.py not found")


@lru_cache(maxsize=1)
def _pool_engine_globals() -> dict[str, Any]:
    """Exec draft pool function defs only — stops before module-level load_data / page render."""
    app_path = _app_source_path()
    app_src = app_path.read_text(encoding="utf-8").splitlines()
    cut = next(i for i, line in enumerate(app_src) if line.startswith("_APP_RENDER_START"))

    shim = _StreamlitShim()
    saved_streamlit = sys.modules.get("streamlit")
    sys.modules["streamlit"] = shim

    tutorial_stub = types.SimpleNamespace(
        render_tutorial_header_bar=lambda: None,
        maybe_open_tutorial_dialog=lambda: None,
    )
    tutorial_patches: list[tuple[Any, str, Any]] = []
    try:
        import app_tutorial as app_tutorial_mod

        for attr in ("render_tutorial_header_bar", "maybe_open_tutorial_dialog"):
            if hasattr(app_tutorial_mod, attr):
                tutorial_patches.append((app_tutorial_mod, attr, getattr(app_tutorial_mod, attr)))
                setattr(app_tutorial_mod, attr, getattr(tutorial_stub, attr))
    except ImportError:
        app_tutorial_mod = None

    preload = (
        "workflow_sidebar",
        "page_transfers",
        "page_state",
        "draft_strategy_intel",
        "draft_team_fit",
    )
    for mod_name in preload:
        if mod_name not in sys.modules:
            try:
                __import__(mod_name)
            except ImportError:
                pass

    g: dict[str, Any] = {
        "__file__": str(app_path),
        "__name__": "draft_pool_engine_defs",
        "np": np,
        "pd": pd,
        "Path": Path,
        "re": __import__("re"),
        "time": __import__("time"),
        "uuid": __import__("uuid"),
        "Counter": __import__("collections").Counter,
        "plt": __import__("matplotlib.pyplot"),
        "alt": __import__("altair"),
        "MaxNLocator": __import__("matplotlib.ticker", fromlist=["MaxNLocator"]).MaxNLocator,
        "io": __import__("io"),
        "unicodedata": __import__("unicodedata"),
        "hashlib": __import__("hashlib"),
        "st": shim,
        "wf_sb": sys.modules.get("workflow_sidebar"),
        "pg_xfer": sys.modules.get("page_transfers"),
        "pg_state": sys.modules.get("page_state"),
        "app_tutorial": tutorial_stub,
        "SKLEARN_AVAILABLE": False,
    }
    for mod_name in ("draft_strategy_intel", "draft_team_fit"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            if mod_name == "draft_strategy_intel":
                g["draft_strategy_line"] = getattr(mod, "draft_strategy_line", lambda *a, **k: "")
            if mod_name == "draft_team_fit":
                g["team_fit_summary_line"] = getattr(mod, "team_fit_summary_line", lambda *a, **k: "")

    try:
        from projection_style import PROJECTION_STYLE_OPTIONS, get_draft_projection_factors

        g["PROJECTION_STYLE_OPTIONS"] = PROJECTION_STYLE_OPTIONS
        g["get_draft_projection_factors"] = get_draft_projection_factors
    except ImportError:
        pass

    for mod_name in (
        "projection_calibration",
        "projection_validation",
        "projection_breakdown",
        "ml_training_build",
        "player_actions",
        "projection_style",
    ):
        if mod_name not in sys.modules:
            try:
                __import__(mod_name)
            except ImportError:
                pass

    import projection_calibration as proj_cal
    import projection_validation as proj_val
    import projection_breakdown as proj_bd
    import ml_training_build as mltb

    g.update(
        {
            "proj_cal": proj_cal,
            "proj_val": proj_val,
            "proj_bd": proj_bd,
            "mltb": mltb,
            "ML_INFERENCE_MIN_LATEST_AB": getattr(mltb, "ML_INFERENCE_MIN_LATEST_AB", 0),
            "ML_INFERENCE_MIN_LATEST_G": getattr(mltb, "ML_INFERENCE_MIN_LATEST_G", 0),
        }
    )

    code = compile("\n".join(app_src[:cut]), str(app_path), "exec")
    try:
        exec(code, g, g)  # noqa: S102
    finally:
        for mod, attr, original in tutorial_patches:
            setattr(mod, attr, original)

    if saved_streamlit is not None:
        sys.modules["streamlit"] = saved_streamlit
    elif "streamlit" in sys.modules and sys.modules["streamlit"] is shim:
        del sys.modules["streamlit"]

    return g


def _fn(name: str) -> Callable[..., Any]:
    g = _pool_engine_globals()
    fn = g.get(name)
    if not callable(fn):
        raise RuntimeError(f"draft pool engine missing {name}")
    return fn


def load_yearly_stat_data() -> pd.DataFrame:
    _bat, yearly_df, _people = _fn("load_data")()
    return yearly_df


def load_draft_market_data() -> pd.DataFrame:
    return _fn("load_fantasypros_market_data")()


def build_unified_draft_player_pool(yearly_source, market_df, **kwargs) -> pd.DataFrame:
    return _fn("build_unified_draft_player_pool")(yearly_source, market_df, **kwargs)


def apply_draft_pick_scoring(available, roster_df, **kwargs):
    return _fn("apply_draft_pick_scoring")(available, roster_df, **kwargs)
