"""Fantasy workflow sidebar — pure list helpers (no Streamlit).

Session keys are documented for callers; Streamlit wiring lives in streamlit_app.py.
"""

RECENT_VIEW_CAP = 12
RECENT_COMPARE_CAP = 8
FAVORITES_CAP = 20

# Keys written by streamlit_app / this module's render helpers
SESSION_DRAFT_QUEUE = "draft_queue"
SESSION_RECENT_VIEWED = "workflow_recently_viewed"
SESSION_RECENT_COMPARE_PAIRS = "workflow_recent_compare_pairs"
SESSION_FAVORITES = "workflow_favorite_targets"
SESSION_SIDEBAR_FLASH = "workflow_sidebar_flash"
SESSION_TRANSFER_BATCHES = "workflow_transfer_batches"

TRANSFER_BATCH_CAP = 8


def normalize_dedupe_queue(raw):
    """Return ordered unique non-empty string names."""
    if not isinstance(raw, list):
        return []
    seen = set()
    out = []
    for x in raw:
        if isinstance(x, dict):
            s = str(x.get("fullName") or x.get("Player") or x.get("name") or "").strip()
        else:
            s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def merge_mru(existing, item, cap):
    """Most-recent-last list: bump item to end, cap length."""
    if item is None or not str(item).strip():
        return list(existing) if isinstance(existing, list) else []
    if not isinstance(existing, list):
        existing = []
    name = str(item).strip()
    lst = [x for x in existing if str(x).strip() != name]
    lst.append(name)
    return lst[-int(cap) :]


def merge_mru_batch(existing, items, cap):
    """Bump multiple items to MRU end in order; cap final length."""
    if not isinstance(existing, list):
        existing = []
    lst = list(existing)
    for item in items or []:
        lst = merge_mru(lst, item, max(int(cap) * 2, int(cap) + len(items or [])))
    return lst[-int(cap) :]


def append_transfer_batch(existing, *, label, players, source=None, target=None, cap=TRANSFER_BATCH_CAP):
    """Record a labeled contextual-transfer batch (deduped by player set)."""
    names = normalize_dedupe_queue(players)
    if not names:
        return list(existing) if isinstance(existing, list) else []
    if not isinstance(existing, list):
        existing = []
    sig = tuple(names)
    kept = [
        b
        for b in existing
        if isinstance(b, dict) and tuple(b.get("players") or []) != sig
    ]
    batch_label = str(label or "").strip() or "Transferred players"
    kept.append({
        "label": batch_label,
        "players": names,
        "source": str(source).strip() if source else None,
        "target": str(target).strip() if target else None,
    })
    return kept[-int(cap) :]


def merge_comparison_pairs(existing, label_a, label_b, cap):
    """Prepend a new ordered pair; drop prior duplicate unordered pair; cap length."""
    a = str(label_a).strip() if label_a else ""
    b = str(label_b).strip() if label_b else ""
    if not a or not b or a == b:
        return list(existing) if isinstance(existing, list) else []
    if not isinstance(existing, list):
        existing = []
    sig = tuple(sorted((a, b)))
    pairs = [
        p
        for p in existing
        if isinstance(p, (list, tuple))
        and len(p) >= 2
        and tuple(sorted((str(p[0]).strip(), str(p[1]).strip()))) != sig
    ]
    pairs.append([a, b])
    return pairs[-int(cap) :]


def toggle_favorite(existing, name, cap):
    """Toggle name in favorites list; cap length."""
    if not name or not str(name).strip():
        return list(existing) if isinstance(existing, list) else []
    if not isinstance(existing, list):
        existing = []
    n = str(name).strip()
    if n in existing:
        return [f for f in existing if f != n]
    out = existing + [n]
    return out[-int(cap) :]


def remove_favorite(existing, name):
    if not isinstance(existing, list):
        return []
    n = str(name).strip()
    return [f for f in existing if str(f).strip() != n]
