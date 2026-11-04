"""Draft Assistant demo loader still fills a board. The page button is intentionally absent."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import portfolio_demo as pdemo


class _St:
    def __init__(self) -> None:
        self.session_state: dict = {}

    def button(self, *_args, **_kwargs):
        raise AssertionError("demo button must not be rendered")

    def success(self, *_args, **_kwargs):
        return None

    def rerun(self) -> None:
        return None


def test_loader_still_populates_board() -> None:
    st = _St()
    pdemo.request_draft_demo(st)
    table = st.session_state["draft_room_table"]
    filled = table[table["Player"].astype(str).str.strip() != ""]
    assert len(filled) == 12, len(filled)
    pdemo.render_draft_demo_button(st, "Draft Assistant Simulator")
    print("OK: demo loader works and the button is not rendered")


if __name__ == "__main__":
    test_loader_still_populates_board()
