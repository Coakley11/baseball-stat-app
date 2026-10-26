"""The running Baseball app module, without executing a second copy of the Streamlit script."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType


def running_app_module() -> ModuleType:
    """Inside the app the script runs as ``__main__``: return it. ``import streamlit_app`` there would execute the
    whole script again inside the same run, which raises StreamlitDuplicateElementKey('main_sidebar_page') in the
    copy. Callers swallowed that, so a Solo draft never left Ready on a server without the prewarm pool. Outside the
    app (tests, tools) the module is imported normally."""
    main = sys.modules.get("__main__")
    main_file = str(getattr(main, "__file__", "") or "")
    if main is not None and Path(main_file).name.lower() == "streamlit_app.py":
        return main
    return importlib.import_module("streamlit_app")
