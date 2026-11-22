"""Read-only reference tables shared by every session (memory: one copy per process, not per script run).

Lahman batting / yearly / people are public reference data, identical for every visitor and never edited.
``st.cache_data`` returns a fresh copy on every call, and Streamlit keeps earlier script runs alive through
the widget callbacks and fragments they defined (each pins that run's globals), so a visitor touring the
pages held several full copies (~126 MB each for batting). Served from ``st.cache_resource`` they are one
object, so a retained run costs no extra table memory.

Sharing is only safe if nobody can change the shared object, so ``freeze`` makes any in-place change fail
loudly instead of silently altering data for every session:

* value writes (``loc`` / ``iloc`` / ``at`` assignment) hit read-only NumPy buffers;
* adding, replacing or deleting columns (``df[col] = …``, ``insert``, ``pop``, ``del``) raise;
* every ``inplace=True`` method (``fillna``, ``rename``, ``sort_values``, ``drop``, …) raises.

Anything derived from a shared table (filters, ``copy()``, merges, groupbys, arithmetic) is an ordinary,
writable ``pandas.DataFrame``, so page code that copies before editing keeps working unchanged.
No account-specific data is ever stored here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

READ_ONLY_MESSAGE = (
    "This is a shared read-only reference table (one copy for every session). "
    "Make a copy first, e.g. df = df.copy(), then change the copy."
)


class SharedReadOnlyError(TypeError):
    """An in-place change was attempted on a shared reference table."""


class SharedFrame(pd.DataFrame):
    """A DataFrame whose in-place changes raise; everything derived from it is a plain DataFrame."""

    _metadata: list[str] = []

    @property
    def _constructor(self):  # derived results are ordinary, writable DataFrames
        return pd.DataFrame

    def __setitem__(self, key: Any, value: Any) -> None:
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    def __delitem__(self, key: Any) -> None:
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    def insert(self, *args: Any, **kwargs: Any) -> None:
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    def update(self, *args: Any, **kwargs: Any) -> None:  # always in place
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    def _update_inplace(self, *args: Any, **kwargs: Any) -> None:  # every ``inplace=True`` path
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    # ``rename`` / ``set_index`` / ``reset_index`` with ``inplace=True`` change the axis labels before they
    # reach ``_update_inplace``, and ``df.columns = …`` / ``df.index = …`` set them directly: refuse at the source.
    def _set_axis_nocheck(self, *args: Any, **kwargs: Any) -> Any:
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    def _set_axis(self, *args: Any, **kwargs: Any) -> None:
        raise SharedReadOnlyError(READ_ONLY_MESSAGE)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("columns", "index"):
            raise SharedReadOnlyError(READ_ONLY_MESSAGE)
        super().__setattr__(name, value)

    def __reduce__(self):  # pickles (e.g. into st.cache_data) as an ordinary DataFrame
        return (pd.DataFrame, (pd.DataFrame(self, copy=True),))


def _freeze_buffers(df: pd.DataFrame) -> None:
    for arr in getattr(df._mgr, "arrays", []):
        for buf in (arr, getattr(arr, "_ndarray", None), getattr(arr, "_data", None), getattr(arr, "_mask", None)):
            flags = getattr(buf, "flags", None)
            if flags is not None:
                try:
                    flags.writeable = False
                except (ValueError, AttributeError):
                    pass


def freeze(df: pd.DataFrame) -> pd.DataFrame:
    """A shared, read-only view of ``df`` (no data copy). ``None`` and non-frames pass through."""
    if not isinstance(df, pd.DataFrame):
        return df
    shared = SharedFrame(df, copy=False)
    _freeze_buffers(shared)
    return shared


def is_shared(df: Any) -> bool:
    return isinstance(df, SharedFrame)
