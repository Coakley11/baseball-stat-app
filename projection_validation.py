"""Reusable player groups for cross-system projection validation."""

from __future__ import annotations

ML_PROJECTION_VALIDATION_GROUPS: dict[str, list[str]] = {
    "elite": [
        "Aaron Judge",
        "Shohei Ohtani",
        "Juan Soto",
        "Bobby Witt Jr.",
        "Gunnar Henderson",
    ],
    "mid_tier": [
        "Bryan Reynolds",
        "Seiya Suzuki",
        "Alex Bregman",
        "Teoscar Hernández",
        "Christian Walker",
    ],
    "breakout": [
        "Ben Rice",
        "Pete Crow-Armstrong",
        "Junior Caminero",
        "Jackson Merrill",
        "Isaac Collins",
    ],
    "aging_risky": [
        "Giancarlo Stanton",
        "George Springer",
        "Paul Goldschmidt",
        "Nolan Arenado",
    ],
}

ML_PROJECTION_VALIDATION_PLAYERS: list[str] = [
    name for names in ML_PROJECTION_VALIDATION_GROUPS.values() for name in names
]
