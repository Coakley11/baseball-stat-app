"""Time ML training-set build only (uses Streamlit cache when run under shim)."""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


class _StreamlitShim(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = types.SimpleNamespace()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in ("cache_data", "cache_resource"):
            return lambda *a, **kwargs: (lambda fn: fn)
        return lambda *a, **k: None


sys.modules["streamlit"] = _StreamlitShim()
for mod_name in ("workflow_sidebar", "page_transfers", "page_state", "draft_strategy_intel", "draft_team_fit"):
    __import__(mod_name)

import importlib.util

spec = importlib.util.spec_from_file_location("streamlit_app_ml", BASE / "streamlit_app.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["streamlit_app_ml"] = mod
spec.loader.exec_module(mod)

if __name__ == "__main__":
    print("Loading data…")
    t0 = time.perf_counter()
    _, yearly_df, _ = mod.load_data()
    print(f"  load: {time.perf_counter() - t0:.1f}s  rows={len(yearly_df):,}")
    t1 = time.perf_counter()
    train_df, cols = mod.build_ml_training_set(yearly_df, 3, 150, tuple(mod.ML_TARGET_STATS), refresh_token=0)
    print(f"  build_ml_training_set: {time.perf_counter() - t1:.1f}s  rows={len(train_df):,}  features={len(cols)}")
