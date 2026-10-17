"""Read-only Baseball analytics API (proof of concept, WEB-PREP2).

A separate ASGI app from both Streamlit and the trusted billing service: it holds no secrets, reads
no cookies, accepts only GET, and serves only public historical analytics. Run it with
``uvicorn baseball_api.app:app``.

Every handler: parse and validate the query → call ``baseball_api.services`` (the app's own
functions) → serialize the typed model. Responses carry ``Server-Timing`` with the business and
serialization time, so API cost can be compared with a Streamlit rerun.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from typing import Any, Callable

from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from baseball_api import services as svc
from baseball_api.errors import ApiError
from baseball_api.openapi import build_openapi

log = logging.getLogger("baseball_api")
PREFIX = "/api/v1"
JSON = "application/json"


def _json(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), status_code=status,
                    media_type=JSON, headers=headers)


def _error(err: ApiError) -> Response:
    return _json(err.body(), status=err.status)


# ---------------------------------------------------------------- query parsing (strict, typed)

def _int(request: Request, name: str, default: int | None = None) -> int | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ApiError("invalid_parameter", f"'{name}' must be a whole number.")


def _bool(request: Request, name: str, default: bool) -> bool:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    if raw.lower() in ("1", "true", "yes"):
        return True
    if raw.lower() in ("0", "false", "no"):
        return False
    raise ApiError("invalid_parameter", f"'{name}' must be true or false.")


def _list(request: Request, name: str) -> list[str]:
    return [x.strip() for x in request.query_params.get(name, "").split(",") if x.strip()]


def _minimums(request: Request) -> dict[str, float]:
    out = {}
    for key, raw in request.query_params.items():
        if key.startswith("min_") and key != "min_ab":
            try:
                out[key[4:]] = float(raw)
            except ValueError:
                raise ApiError("invalid_parameter", f"'{key}' must be a number.")
    return out


def _weights(request: Request) -> dict[str, float] | None:
    raw = request.query_params.get("weights")
    if raw is None:
        return None
    out = {}
    for part in [p for p in raw.split(",") if p.strip()]:
        stat, _, val = part.partition(":")
        try:
            out[stat.strip()] = float(val)
        except ValueError:
            raise ApiError("invalid_parameter", "weights look like HR:1,RBI:1,SB:0.5.")
    return out


def _endpoint(fn: Callable[[Request], BaseModel]):
    """Wrap a handler: business call timed separately from serialization; errors → JSON."""
    async def handler(request: Request) -> Response:
        t0 = time.perf_counter()
        try:
            model = fn(request)
        except ApiError as err:
            return _error(err)
        except Exception:  # never leak a traceback or internal text
            log.exception("api handler failed: %s", request.url.path)
            return _error(ApiError("internal_error", "Something went wrong. Try again."))
        t1 = time.perf_counter()
        body = model.model_dump(mode="json", by_alias=True)
        resp = _json(body)
        t2 = time.perf_counter()
        resp.headers["Server-Timing"] = f"business;dur={(t1 - t0) * 1000:.1f}, serialize;dur={(t2 - t1) * 1000:.1f}"
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp
    return handler


# ---------------------------------------------------------------- routes

def _health(request: Request):
    return svc.health()


def _search(request: Request):
    return svc.search_players(request.query_params.get("q", ""), limit=_int(request, "limit"))


def _resolve(request: Request):
    return svc.resolve_player(request.query_params.get("name", ""))


def _seasons_for_player(request: Request):
    return svc.player_seasons(request.path_params["player_id"], start=_int(request, "start"), end=_int(request, "end"),
                              split=request.query_params.get("split", "team"))


def _season_leaders(request: Request):
    return svc.season_leaders(
        start=_int(request, "start"), end=_int(request, "end"), metric=request.query_params.get("metric", "HR"),
        order=request.query_params.get("order", "desc"), limit=_int(request, "limit"), bats=_list(request, "bats"),
        positions=_list(request, "positions"), position_source=request.query_params.get("position_source", "season"),
        teams=_list(request, "teams"), combine=_bool(request, "combine", False), min_ab=_int(request, "min_ab"),
        qualified=_bool(request, "qualified", True), minimums=_minimums(request))


def _leaderboard(request: Request):
    return svc.leaderboard(
        start=_int(request, "start"), end=_int(request, "end"), metric=request.query_params.get("metric", "score"),
        limit=_int(request, "limit"), weights=_weights(request), min_ab=_int(request, "min_ab"),
        qualified=_bool(request, "qualified", True), minimums=_minimums(request))


async def _openapi(_request: Request) -> Response:
    return _json(build_openapi())


async def _http_error(_request: Request, exc: HTTPException) -> Response:
    code = "not_found" if exc.status_code == 404 else "invalid_parameter"
    msg = "No such endpoint." if exc.status_code == 404 else ("Only GET is supported." if exc.status_code == 405 else "Bad request.")
    return _json({"error": {"code": code, "message": msg}}, status=exc.status_code)


async def _server_error(_request: Request, _exc: Exception) -> Response:
    return _error(ApiError("internal_error", "Something went wrong. Try again."))


ROUTES = [
    Route(f"{PREFIX}/health", _endpoint(_health), methods=["GET"]),
    Route(f"{PREFIX}/players/search", _endpoint(_search), methods=["GET"]),
    Route(f"{PREFIX}/players/resolve", _endpoint(_resolve), methods=["GET"]),
    Route(PREFIX + "/players/{player_id:str}/seasons", _endpoint(_seasons_for_player), methods=["GET"]),
    Route(f"{PREFIX}/seasons", _endpoint(_season_leaders), methods=["GET"]),
    Route(f"{PREFIX}/leaderboards", _endpoint(_leaderboard), methods=["GET"]),
    Route(f"{PREFIX}/openapi.json", _openapi, methods=["GET"]),
]


@contextlib.asynccontextmanager
async def _lifespan(_app: Starlette):
    # Load the Lahman frames in the background at startup so the first request doesn't pay for it
    # (BASEBALL_API_PRELOAD=0 turns this off, e.g. in tests).
    if os.environ.get("BASEBALL_API_PRELOAD", "1") != "0":
        threading.Thread(target=_preload, name="baseball-api-preload", daemon=True).start()
    yield


def _preload() -> None:
    try:
        svc.STORE.get()
    except Exception:
        log.exception("api data preload failed")


def create_app() -> Starlette:
    # CORS is off unless origins are configured (e.g. the Next.js dev server).
    origins = [o.strip() for o in os.environ.get("BASEBALL_API_CORS_ORIGINS", "").split(",") if o.strip()]
    middleware = [Middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=[],
                             allow_credentials=False)] if origins else []
    return Starlette(routes=ROUTES, middleware=middleware, debug=False, lifespan=_lifespan,
                     exception_handlers={HTTPException: _http_error, Exception: _server_error})


app = create_app()
