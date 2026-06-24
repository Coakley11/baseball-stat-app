"""Strict JSON serialization for shared draft room Supabase payloads."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


class SharedRoomJsonSerializeError(ValueError):
    """Raised when a shared room payload cannot be encoded as strict JSON."""

    def __init__(self, path: str, value: Any, cause: Exception | None = None) -> None:
        self.path = path
        self.value = value
        self.cause = cause
        detail = f"{type(value).__name__}"
        if cause is not None:
            detail = f"{detail}: {cause}"
        super().__init__(f"Shared room JSON not serializable at `{path}` ({detail})")


def sanitize_shared_room_json(value: Any) -> Any:
    """Recursively coerce shared room documents to strict JSON-safe Python values."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value.item())
    if isinstance(value, (np.integer,)):
        return int(value.item())
    if isinstance(value, (np.floating,)):
        v = float(value.item())
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, pd.DataFrame):
        return sanitize_shared_room_json(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return sanitize_shared_room_json(value.to_dict())
    if isinstance(value, np.ndarray):
        return sanitize_shared_room_json(value.tolist())
    if isinstance(value, dict):
        return {str(k): sanitize_shared_room_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_shared_room_json(v) for v in value]
    if hasattr(value, "item"):
        try:
            return sanitize_shared_room_json(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return sanitize_shared_room_json(value.tolist())
        except Exception:
            pass
    return str(value)


def find_non_serializable_path(value: Any, *, path: str = "$") -> tuple[str, Any] | None:
    """Return the first path/value pair that fails strict JSON encoding."""
    try:
        json.dumps(value, allow_nan=False)
        return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            found = find_non_serializable_path(child, path=child_path)
            if found is not None:
                return found
        return path, value

    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            found = find_non_serializable_path(child, path=child_path)
            if found is not None:
                return found
        return path, value

    return path, value


def validate_strict_json(value: Any, *, path: str = "$") -> None:
    """Raise SharedRoomJsonSerializeError if value is not strict JSON-serializable."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        located = find_non_serializable_path(value, path=path)
        if located is not None:
            bad_path, bad_value = located
            raise SharedRoomJsonSerializeError(bad_path, bad_value, exc) from exc
        raise SharedRoomJsonSerializeError(path, value, exc) from exc


def prepare_supabase_json_body(payload: dict[str, Any], *, path: str = "$") -> dict[str, Any]:
    """Sanitize and validate a PostgREST JSON body before requests.post/patch."""
    cleaned = sanitize_shared_room_json(payload)
    if not isinstance(cleaned, dict):
        raise SharedRoomJsonSerializeError(path, payload, ValueError("expected object"))
    validate_strict_json(cleaned, path=path)
    return cleaned
