"""Extract explicit fields from Streamlit RegisterWidgetResult (never bool(object))."""

from __future__ import annotations

from typing import Any


def extract_register_widget_result_fields(result: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "register_widget_result_repr": repr(result)[:200],
        "register_widget_result_value": None,
        "register_widget_value_changed": None,
        "register_widget_incoming_serialized_value": None,
    }
    if result is None:
        return out
    val = getattr(result, "value", None)
    if val is not None or hasattr(result, "value"):
        out["register_widget_result_value"] = bool(val) if isinstance(val, bool) else val
    vc = getattr(result, "value_changed", None)
    if vc is not None or hasattr(result, "value_changed"):
        out["register_widget_value_changed"] = bool(vc)
    inv = getattr(result, "incoming_serialized_value", None)
    if inv is not None or hasattr(result, "incoming_serialized_value"):
        out["register_widget_incoming_serialized_value"] = inv
    if out["register_widget_result_value"] is None and isinstance(result, bool):
        out["register_widget_result_value"] = bool(result)
    return out
