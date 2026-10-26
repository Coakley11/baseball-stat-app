"""AMI's read-only tools. Importing this package registers every tool in ``REGISTRY``."""

from __future__ import annotations

from ami_assistant.tools import app_help, draft, fantasy, stats, value  # noqa: F401  (registration)
from ami_assistant.tools.registry import REGISTRY, ToolResult, ToolSpec

__all__ = ["REGISTRY", "ToolResult", "ToolSpec"]
