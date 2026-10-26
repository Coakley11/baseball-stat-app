"""Side-effect-free reads of the active fantasy league (for AMI and other read-only callers).

The page resolvers (``resolved_fantasy_context.resolve_fantasy_context_for_page``,
``fantasy_league_context.get_active_league_context``) are read-only in intent but write
session caches and may normalize stored state while they work. These wrappers run the very
same resolvers against an isolated view of the session:

* every value the resolver reads is a deep copy, taken on first access;
* every write, pop or setdefault lands in the view's private overlay;
* the caller's session is never touched, and what you get back is yours to keep.

So the answer is exactly what the page would resolve, without changing what the page sees
next. No network: nothing on these paths calls the shared-league sync (that only runs on
explicit activation/claims), and neither wrapper fetches stats.

Production sessions are Streamlit's ``SessionStateProxy`` (a MutableMapping, not a dict);
tests use dicts. The view mirrors the source type so ``isinstance(session, dict)`` branches
behave the same as with the real session.
"""

from __future__ import annotations

import copy
from collections.abc import MutableMapping
from typing import Any, Iterator

_MISSING = object()


class _Overlay:
    """Copy-on-read, write-to-overlay storage over a source mapping."""

    def __init__(self, source: Any) -> None:
        self.source = source
        self.values: dict[Any, Any] = {}
        self.deleted: set[Any] = set()
        self.written: set[Any] = set()
        self.uncopyable: set[Any] = set()

    def _source_has(self, key: Any) -> bool:
        try:
            return key in self.source
        except Exception:
            return False

    def has(self, key: Any) -> bool:
        if key in self.deleted:
            return False
        return key in self.values or self._source_has(key)

    def get(self, key: Any) -> Any:
        if key in self.deleted:
            raise KeyError(key)
        if key in self.values:
            return self.values[key]
        if not self._source_has(key):
            raise KeyError(key)
        raw = self.source[key]
        try:
            value = copy.deepcopy(raw)
        except Exception:
            # Not deep-copyable (rare: locks, open handles). Hand back a shallow copy where
            # possible; such values are never league data.
            self.uncopyable.add(key)
            try:
                value = copy.copy(raw)
            except Exception:
                value = raw
        self.values[key] = value
        return value

    def set(self, key: Any, value: Any) -> None:
        self.deleted.discard(key)
        self.values[key] = value
        self.written.add(key)

    def delete(self, key: Any) -> None:
        if not self.has(key):
            raise KeyError(key)
        self.values.pop(key, None)
        self.deleted.add(key)
        self.written.add(key)

    def keys(self) -> list[Any]:
        try:
            src_keys = list(self.source.keys())
        except Exception:
            src_keys = []
        out = [k for k in src_keys if k not in self.deleted]
        out += [k for k in self.values if k not in out]
        return out


class _MappingView(MutableMapping):
    """Isolated view for non-dict sessions (Streamlit's SessionStateProxy)."""

    def __init__(self, source: Any) -> None:
        self._overlay = _Overlay(source)

    def __getitem__(self, key: Any) -> Any:
        return self._overlay.get(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._overlay.set(key, value)

    def __delitem__(self, key: Any) -> None:
        self._overlay.delete(key)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._overlay.keys())

    def __len__(self) -> int:
        return len(self._overlay.keys())

    def __contains__(self, key: object) -> bool:
        return self._overlay.has(key)


class _DictView(dict):
    """Isolated view for dict sessions. The dict storage itself stays empty; every access
    method goes through the overlay so nothing reaches the caller's dict."""

    def __init__(self, source: Any) -> None:
        super().__init__()
        self._overlay = _Overlay(source)

    def __getitem__(self, key: Any) -> Any:
        return self._overlay.get(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._overlay.set(key, value)

    def __delitem__(self, key: Any) -> None:
        self._overlay.delete(key)

    def __contains__(self, key: object) -> bool:
        return self._overlay.has(key)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._overlay.keys())

    def __len__(self) -> int:
        return len(self._overlay.keys())

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self._overlay.get(key)
        except KeyError:
            return default

    def keys(self):  # type: ignore[override]
        return list(self._overlay.keys())

    def values(self):  # type: ignore[override]
        return [self[k] for k in self._overlay.keys()]

    def items(self):  # type: ignore[override]
        return [(k, self[k]) for k in self._overlay.keys()]

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if self._overlay.has(key):
            return self._overlay.get(key)
        self._overlay.set(key, default)
        return default

    def pop(self, key: Any, default: Any = _MISSING) -> Any:
        if self._overlay.has(key):
            value = self._overlay.get(key)
            self._overlay.delete(key)
            return value
        if default is _MISSING:
            raise KeyError(key)
        return default

    def popitem(self):  # type: ignore[override]
        keys = self._overlay.keys()
        if not keys:
            raise KeyError("popitem(): view is empty")
        key = keys[-1]
        return key, self.pop(key)

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        for key, value in dict(*args, **kwargs).items():
            self._overlay.set(key, value)

    def clear(self) -> None:
        for key in list(self._overlay.keys()):
            self._overlay.delete(key)

    def copy(self) -> dict[Any, Any]:  # type: ignore[override]
        return dict(self.items())

    def __repr__(self) -> str:
        return f"<isolated session view: {len(self)} keys>"


def isolated_session_view(session: Any) -> MutableMapping:
    """A view of ``session`` that reads deep copies and keeps all writes to itself."""
    if session is None:
        return _DictView({})
    return _DictView(session) if isinstance(session, dict) else _MappingView(session)


def view_writes(view: Any) -> set[Any]:
    """Keys a resolver wrote/popped in the view (diagnostics; the real session is untouched)."""
    overlay = getattr(view, "_overlay", None)
    return set(overlay.written) if overlay is not None else set()


def peek_resolved_fantasy_context(session: Any):
    """``resolve_fantasy_context_for_page`` without side effects.

    Returns a ``ResolvedFantasyContext`` (frozen; ``league_rosters`` is a private deep copy).
    ``coherent`` / ``coherence_error`` say whether the page would trust it.
    """
    from resolved_fantasy_context import resolve_fantasy_context_for_page

    return resolve_fantasy_context_for_page(isolated_session_view(session))


def peek_active_league_context(session: Any, *, respect_source_priority: bool = True) -> dict[str, Any] | None:
    """``get_active_league_context`` without side effects. Returns a private deep copy (or None).

    ``respect_source_priority=True`` (default) gives the league the fantasy pages show
    (live draft > temporary override > saved Active League > simulator board);
    False gives only the saved Active League.
    """
    from fantasy_league_context import get_active_league_context

    context = get_active_league_context(isolated_session_view(session), respect_source_priority=respect_source_priority)
    return copy.deepcopy(context) if isinstance(context, dict) else None
