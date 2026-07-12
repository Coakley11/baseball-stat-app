"""AST/source audit for Fantasy Lineup Assistant variable scope."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LINEUP_ONLY_VARS = {
    "lineup_format",
    "custom_weights",
    "bench_rows_to_show",
    "team_roster",
    "scored",
    "starters",
    "slot_list",
    "lineup_pkg",
    "use_util",
    "custom_slots_text",
    "_context_lineup_slots",
    "_context_no_slot_config",
}


def _leaked_lines_in_streamlit() -> list[tuple[int, int, str]]:
    lines = (ROOT / "streamlit_app.py").read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if 'elif _assistant_tab == "Lineup Management":' in l)
    end = next(i for i, l in enumerate(lines[start:], start) if l.strip().startswith("save_page_state"))
    parent = len(lines[start]) - len(lines[start].lstrip(" "))
    leaked: list[tuple[int, int, str]] = []
    for i in range(start + 1, end):
        if not lines[i].strip():
            continue
        ind = len(lines[i]) - len(lines[i].lstrip(" "))
        if ind <= parent:
            leaked.append((i + 1, ind, lines[i][:100]))
    return leaked


def _lineup_module_scope_violations() -> list[str]:
    source = (ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_lineup_management_page"
    )
    assigned: dict[str, int] = {}
    referenced_outside: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in LINEUP_ONLY_VARS:
                    assigned[target.id] = self.depth
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            if node.id in LINEUP_ONLY_VARS and isinstance(node.ctx, ast.Load):
                if node.id not in assigned:
                    referenced_outside.append(f"{node.id} referenced before assignment")
            self.generic_visit(node)

        def visit_If(self, node: ast.If) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        def visit_With(self, node: ast.With) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        def visit_Try(self, node: ast.Try) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

    Visitor().visit(fn)
    return referenced_outside


def main() -> int:
    leaked = _leaked_lines_in_streamlit()
    print("streamlit leaked", len(leaked))
    for row in leaked[:10]:
        print(row)

    violations = _lineup_module_scope_violations()
    print("lineup module violations", len(violations))
    for row in violations[:20]:
        print(row)
    return 1 if leaked or violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
