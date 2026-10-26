"""Can a roster fill a set of lineup slots? Each player fills at most one slot.

Slot rules: a position slot takes players listed there (OF takes LF/CF/RF; P takes SP/RP);
UTIL/DH takes any hitter (a two-way TWP counts); BN takes anyone. Uses maximum
bipartite matching, filling specific positions before flexible ones, so the slots
reported open are the ones the roster really cannot cover.
"""

from __future__ import annotations

from collections.abc import Iterable

PITCHER_TOKENS = frozenset({"P", "SP", "RP"})
FLEX_HITTER_SLOTS = frozenset({"DH", "UTIL"})
BENCH_SLOTS = frozenset({"BN", "BENCH"})
_SLOT_ALIASES = {"OF": frozenset({"OF", "LF", "CF", "RF"}), "P": PITCHER_TOKENS}


def _tokens(raw: Iterable[str]) -> frozenset[str]:
    return frozenset(str(t).strip().upper() for t in raw if str(t).strip())


def can_fill(tokens: Iterable[str], slot: str) -> bool:
    toks = _tokens(tokens)
    slot = str(slot or "").strip().upper()
    if slot in BENCH_SLOTS:
        return bool(toks)
    if slot in FLEX_HITTER_SLOTS:
        return any(t not in PITCHER_TOKENS for t in toks)
    if slot in PITCHER_TOKENS:
        return bool(toks & PITCHER_TOKENS) or "TWP" in toks
    return bool(toks & _SLOT_ALIASES.get(slot, frozenset({slot})))


def _slot_order(slot: str) -> int:
    s = str(slot or "").strip().upper()
    return 2 if s in BENCH_SLOTS else 1 if s in FLEX_HITTER_SLOTS else 0


def unfilled_slots(players: list[Iterable[str]], slots: list[str]) -> list[str]:
    """Slots left open after the best assignment of ``players`` (position tokens each)."""
    player_tokens = [_tokens(p) for p in players]
    order = sorted(range(len(slots)), key=lambda i: (_slot_order(slots[i]), i))
    slot_of_player: dict[int, int] = {}

    def assign(slot_idx: int, seen: set[int]) -> bool:
        for p_idx, toks in enumerate(player_tokens):
            if p_idx in seen or not can_fill(toks, slots[slot_idx]):
                continue
            seen.add(p_idx)
            if p_idx not in slot_of_player or assign(slot_of_player[p_idx], seen):
                slot_of_player[p_idx] = slot_idx
                return True
        return False

    for slot_idx in order:
        assign(slot_idx, set())
    taken = set(slot_of_player.values())
    return [slots[i] for i in order if i not in taken]
