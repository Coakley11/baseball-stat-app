"""Keep the address bar's ``?active_page=`` in step with the page shown, and follow Back/Forward.

Before this, the URL only carried the page the session was opened with: refresh went back to
that stale page and Back left the app. Now:

* Moving to another page pushes one history entry through ``st.query_params`` (Streamlit's own
  route, so ``suite_sid`` and other params are kept and the Cloud host is told).
* The first sync of a session replaces the current entry instead (a bare ``/`` or a stale link
  does not leave a dead Back step behind).
* Back/Forward fire ``popstate``; the hidden component (url_page_sync_component) reports the
  page now in the bar and the app navigates there through the normal scheduled-navigation path,
  without pushing again — so Forward still works.

Refresh then opens the page in the bar via the existing ``?active_page=`` deep-link handling.
"""

from __future__ import annotations

from typing import Any, Callable, Collection, MutableMapping

PARAM = "active_page"
EVENT_KEY = "_url_page_sync_event"  # component value {"page", "seq"} — one per popstate
SEEN_EVENT_KEY = "_url_page_sync_seen_seq"
BAR_PAGE_KEY = "_url_page_in_address_bar"  # page the address bar shows, as far as we know

MODE_PUSH = "push"
MODE_REPLACE = "replace"
MODE_NONE = "none"


def history_navigation_target(
    session: MutableMapping[str, Any],
    *,
    current_page: Any,
    valid_pages: Collection[str],
    normalize: Callable[[str], str],
) -> str | None:
    """Page to open because the user pressed Back/Forward, or None.

    Each popstate event is handled once. Entries without a known page (e.g. from before the
    app synced the URL) are ignored rather than guessed.
    """
    event = session.get(EVENT_KEY)
    if not isinstance(event, dict):
        return None
    seq = str(event.get("seq") or "")
    if not seq or session.get(SEEN_EVENT_KEY) == seq:
        return None
    session[SEEN_EVENT_KEY] = seq
    raw = str(event.get("page") or "").strip()
    target = normalize(raw) if raw else ""
    if target not in valid_pages:
        return None
    session[BAR_PAGE_KEY] = target
    return target if target != str(current_page or "") else None


def address_bar_mode(session: MutableMapping[str, Any], page: str) -> str:
    """How to bring the address bar to ``page`` this run (and record that it now shows it)."""
    if not page:
        return MODE_NONE
    shown = session.get(BAR_PAGE_KEY)
    session[BAR_PAGE_KEY] = page
    if shown is None:
        return MODE_REPLACE
    if shown == page:
        return MODE_NONE
    return MODE_PUSH


def sync_address_bar(st: Any, page: str) -> str:
    """Bring the URL to ``page`` and keep listening for Back/Forward. Call once per run, pre-body."""
    page = str(page or "").strip()
    mode = address_bar_mode(st.session_state, page)
    if mode == MODE_PUSH:
        try:
            st.query_params[PARAM] = page
        except Exception:
            mode = MODE_REPLACE
    try:
        from url_page_sync_component import mount_url_page_sync

        mount_url_page_sync(page, mode=mode, key=EVENT_KEY)
    except Exception:
        pass
    return mode
