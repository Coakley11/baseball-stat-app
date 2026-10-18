"""Predictable API errors. Every failure the API reports is one of these codes with a plain
message; tracebacks, file paths and Streamlit text never reach a response."""

from __future__ import annotations

from typing import Any

STATUS = {
    "player_not_found": 404,
    "ambiguous_player": 409,
    "invalid_metric": 422,
    "invalid_date_range": 422,
    "invalid_parameter": 422,
    "no_active_league": 404,
    "unauthorized_team": 403,
    "missing_finalized_weeks": 409,
    "data_unavailable": 503,
    "not_found": 404,
    "internal_error": 500,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        assert code in STATUS, code
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status = STATUS[code]

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        return {"error": err}
