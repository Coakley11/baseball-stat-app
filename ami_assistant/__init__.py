"""AMI in-app assistant — read-only, grounded answers about Baseball Explorer data and pages.

Layers (each importable without Streamlit except ``ui``):

* ``capabilities`` — what AMI can, will later, and must never do.
* ``page_help`` / ``glossary`` — authoritative app-help registry built from the app's own copy.
* ``data`` / ``players`` — the app's Lahman season frame and player-name resolution.
* ``tools`` — structured read-only tools wrapping the app's tested business functions.
* ``context`` / ``conversation`` — narrow page context and follow-up memory.
* ``router`` — deterministic question → intent → tool plan.
* ``compose`` / ``provider`` — grounded answer writing behind a provider interface.
* ``engine`` — ``ask()`` ties it together; ``ui`` is the minimal Streamlit panel.

Nothing here mutates fantasy, draft, league, or account state.
"""

from __future__ import annotations

from ami_assistant.engine import AmiResponse, ask

__all__ = ["AmiResponse", "ask"]
