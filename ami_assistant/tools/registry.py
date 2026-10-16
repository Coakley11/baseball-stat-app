"""Tool contracts: every AMI tool is a named, schema-described, read-only function.

A ``ToolSpec`` with ``mutates=True`` cannot be registered — future write actions are
*declared* in ``capabilities.FUTURE_ACTIONS`` but never callable from AMI. When they are
wired they must call the same canonical transaction functions as the UI, after explicit
user confirmation (see docs/AMI_ASSISTANT_FOUNDATION.md).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Error codes the composer turns into plain-language failures.
UNKNOWN_PLAYER = "unknown_player"
AMBIGUOUS_PLAYER = "ambiguous_player"
UNAVAILABLE_SEASON = "unavailable_season"
INSUFFICIENT_HISTORY = "insufficient_history"
MISSING_DRAFT_CONTEXT = "missing_draft_context"
MISSING_ACTIVE_LEAGUE = "missing_active_league"
NOT_WIRED = "not_wired"
NOT_IN_POOL = "not_in_pool"
BAD_ARGUMENT = "bad_argument"
INTERNAL_ERROR = "internal_error"


@dataclass
class ToolResult:
    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "data": self.data,
            "error_code": self.error_code,
            "message": self.message,
        }


def fail(tool: str, code: str, message: str, **data: Any) -> ToolResult:
    return ToolResult(tool=tool, ok=False, data=dict(data), error_code=code, message=message)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    capability: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., ToolResult]
    # Where the numbers come from — shown in answers and docs.
    reuses: tuple[str, ...] = ()
    needs_dataset: bool = False
    needs_session: bool = False
    mutates: bool = False
    wired: bool = True

    def schema(self) -> dict[str, Any]:
        """Provider-neutral JSON-schema description (works for Claude tools or OpenAI functions)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", **self.parameters},
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.mutates:
            raise ValueError(f"AMI tools are read-only; refusing to register mutating tool {spec.name!r}")
        if spec.name in self._tools:
            raise ValueError(f"duplicate AMI tool {spec.name!r}")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    def schemas(self, *, wired_only: bool = True) -> list[dict[str, Any]]:
        return [s.schema() for s in self.specs() if s.wired or not wired_only]

    def call(self, name: str, args: dict[str, Any], *, dataset: Any = None, session: Any = None) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return fail(name, BAD_ARGUMENT, f"No AMI tool named {name!r}.")
        kwargs = dict(args or {})
        if spec.needs_dataset:
            kwargs["dataset"] = dataset
        if spec.needs_session:
            kwargs["session"] = session if session is not None else {}
        start = time.perf_counter()
        try:
            result = spec.func(**kwargs)
        except TypeError as exc:
            result = fail(name, BAD_ARGUMENT, f"Bad arguments for {name}: {exc}")
        except Exception as exc:  # a tool bug must not take the page down
            result = fail(name, INTERNAL_ERROR, f"{name} failed: {type(exc).__name__}")
        result.elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return result


REGISTRY = ToolRegistry()


def tool(
    name: str,
    *,
    capability: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    reuses: tuple[str, ...] = (),
    needs_dataset: bool = False,
    needs_session: bool = False,
    wired: bool = True,
) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult]]:
    def deco(func: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        REGISTRY.register(
            ToolSpec(
                name=name,
                capability=capability,
                description=description,
                parameters=parameters or {"properties": {}},
                func=func,
                reuses=reuses,
                needs_dataset=needs_dataset,
                needs_session=needs_session,
                wired=wired,
            )
        )
        return func

    return deco
