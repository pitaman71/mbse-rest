"""The REST service over an mbse-schemas store (mbse-basis [CAP-002: named schema list](../../../../../mbse-basis/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](../../../../../mbse-basis/docs/capabilities/CAP-004.md), [CAP-012: logical view endpoints](../../../../../mbse-basis/docs/capabilities/CAP-012.md) and [CAP-013: an in-memory store journaled to DynamoDB](../../../../../mbse-basis/docs/capabilities/CAP-013.md)).

`app(installs, plugin)` gives a FastAPI application over any MBSE app: one store held in memory, which at startup
replays what the persistence plugin holds, or, where it holds nothing, runs each install (the app's `Schemas.install`,
then, optionally, its `Seed.seed`) and gives the plugin a snapshot of what they wrote. `installs_of(module)` finds an
app's installs by that convention; `from_environment()` builds the application from `MBSE_REST_*` variables, as
`python -m mbse.Services.Rest` serves it. The endpoints are `docs/CONTRACT.md`'s:

| Method and path | Capability | Response |
|---|---|---|
| `GET /schemas` | [CAP-002: named schema list](../../../../../mbse-basis/docs/capabilities/CAP-002.md) | the store's schema snapshot, the first transaction of its snapshot, while [CAP-003: schema inspector](../../../../../mbse-basis/docs/capabilities/CAP-003.md) is blocked |
| `GET /schemas/{name}` | [CAP-003: schema inspector](../../../../../mbse-basis/docs/capabilities/CAP-003.md) | 501 until mbse-schemas writes one schema object as a document (CONTRACT.md) |
| `GET /views` | [CAP-004: logical view templates](../../../../../mbse-basis/docs/capabilities/CAP-004.md) | `{kind: template, ...}`, each a transaction's expression |
| `POST /views/{kind}` | [CAP-012: logical view endpoints](../../../../../mbse-basis/docs/capabilities/CAP-012.md) | the frames, `References.OfFrame`, one JSON document a line (NDJSON) |

A view's request is a transaction's expression (`Plain.ToPlain(store).Transaction`). The service reads it
(`JSON.loads`, `Plain.FromPlain(store).Transaction`), executes it, journals it if it writes, and fills each frame's
`assigns` and `entries` as the kind defines (`Views.witness`). One transaction runs at a time. What the plugin has not
journaled is undone: where a transaction that writes is refused after it commits, or its journal fails, the store is
read back from the plugin (`Service.restore`). Every refusal is `{"error": message}` (CONTRACT.md, Wire format).
"""

from __future__ import annotations

import importlib
import logging
import os
import datetime
import threading
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from types import ModuleType
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from mbse.Schemas.Framework import JSON, Builders, Plain

from . import Views
from .Persistence import Memory, Plugin, PlainData, replay

__all__ = ["NDJSON", "Install", "Refused", "Unavailable", "Service", "app", "installs_of", "plugin_of",
           "from_environment", "work_tracker", "writes"]

NDJSON = "application/x-ndjson"
UNWRITTEN = ("mbse-schemas writes no schema object as a document of its own: Plain.ToPlain(store).OfObject refuses "
             "one, owned through an anonymous adjacency (docs/CONTRACT.md, CAP-003)")
WORK_TRACKER = "mbse.Demos.Apps.WorkTracker"

Install = Callable[[Any], Any]
"""An install: a callback given a transaction, `store.transaction(install)`, as an app's `Schemas.install` and
`Seed.seed` are."""

log = logging.getLogger("mbse.Services.Rest")

# What the executor and mbse-schemas' readers raise for a transaction they refuse: `DecodeError` is a `ValueError`,
# `ReadOnlyError` a `TypeError`, a symbol or path to nothing a `LookupError`.
REFUSALS = (ValueError, TypeError, LookupError)


def writes(plain: PlainData) -> bool:
    """Whether a transaction's expression has a term that writes, an upsert or an update, so that it is journaled."""
    if isinstance(plain, dict):
        return "upsert" in plain or "update" in plain or any(writes(v) for v in plain.values())
    if isinstance(plain, list):
        return any(writes(v) for v in plain)
    return False


class Refused(Exception):
    """A request the service refuses, with the status it answers and why."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class Unavailable(Refused):
    """The plugin failed: what it holds is not known to agree with the store (503)."""

    def __init__(self, message: str) -> None:
        super().__init__(503, message)


SESSION_HEADER = "x-mbse-session"
"""The request header that names the client's session ([CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md)): the demo's stand-in for a validated token's
session, which the service trusts (tech debt, TODO.md)."""


Clock = Callable[[], datetime.datetime]
Uids = Callable[[], str]


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def _iso(moment: datetime.datetime) -> str:
    """A moment as UTC ISO 8601 text, to the second: `2026-10-26T14:30:05Z`."""
    return moment.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamp(plain: PlainData, session: str | None, who: str, clock: Clock = _now, uids: Uids = _uuid) -> PlainData:
    """[CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md): a transaction that writes, as the service journals and executes it: given a `uid` where it has none,
    so that a replay finds the same record, and its `when`, and its session's `id` and `who`, the service's; the
    client's `locale`, `device` and `where` are kept. Where the client names no session, the identity's own,
    `<who>:default`. A transaction that only reads is given back as it is."""
    if not writes(plain) or not isinstance(plain, dict):
        return plain
    stamped = dict(plain)
    stamped.setdefault("uid", uids())
    stamped["when"] = _iso(clock())
    # no session named: one of the identity's own, since a session has one identity (Provenance.Who)
    stamped["session"] = {**(plain.get("session") or {}), "id": session or f"{who}:default", "who": who}
    return stamped


class Service:
    """One store, held in memory, and its persistence: what the endpoints call, apart from HTTP."""

    def __init__(self, installs: Iterable[Install] = (), plugin: Plugin | None = None,
                 snapshot_every: int = 100, *, user: str = "demo", clock: Clock = _now, uids: Uids = _uuid) -> None:
        self.user = user  # the demo's identity, standing in for a validated token's ([CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md); tech debt, TODO.md)
        self.clock, self.uids = clock, uids  # a write's `when` and, where it has none, its `uid` (`stamp`)
        self.installs = list(installs)
        self.plugin = plugin if plugin is not None else Memory()
        self.snapshot_every = snapshot_every
        self._journaled = 0  # transactions journaled since the latest snapshot the plugin took
        self._lock = threading.Lock()  # one transaction at a time: transactions on one store do not nest
        self._broken: str | None = None  # why the store could not be read back from the plugin, once it could not
        self.store = self._open()

    def _open(self) -> Any:
        """A store filled from the plugin; where it holds nothing, the installs run, then the plugin takes a snapshot
        of what they wrote (db initialization by schema)."""
        store = Builders.Store()
        if not replay(store, self.plugin):
            for install in self.installs:  # each given `when` by the service's clock, as a write is ([CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md))
                store.transaction(lambda t, i=install, w=_iso(self.clock()): i(t).when(w))
            self.plugin.snapshot(Plain.ToPlain(store).Snapshot())
        return store

    def restore(self) -> None:
        """Undoes what the plugin has not journaled: the store is read back from the plugin. Where that fails, the
        service answers 503 to every request from then on."""
        try:
            self.store = self._open()
            self._journaled = 0
        except Exception as error:  # the plugin's own, whatever it raises
            log.exception("the store could not be read back from the persistence plugin")
            self._broken = f"the store could not be read back from the persistence plugin: {_describe(error)}"

    def _available(self) -> None:
        if self._broken is not None:
            raise Unavailable(self._broken)

    def _commit(self, kind: str, plain: PlainData) -> list[dict[str, Any]]:
        """Executes a transaction's expression, its frames each binding the kind's symbols; journals it, where it
        writes, once it commits. Refused (400) where the executor refuses it, or where a frame lacks a symbol; then
        nothing it wrote is kept."""
        try:
            transaction = Plain.FromPlain(self.store).Transaction(plain)
            frames = self.store.transaction(transaction)
        except REFUSALS as error:  # refused before or as it ends: nothing was written
            raise Refused(400, _describe(error)) from error
        missing = _missing(kind, frames)
        if not writes(plain):
            if missing:
                raise Refused(400, missing)
            return frames
        if missing:
            self.restore()  # committed in memory, never journaled: undone
            raise Refused(400, f"{missing}; what it wrote is undone")
        try:
            self.plugin.journal(plain)
        except Exception as error:  # the plugin's own, whatever it raises
            log.exception("a committed transaction could not be journaled")
            self.restore()
            raise Unavailable(f"the transaction could not be journaled, and is undone: {_describe(error)}") from error
        self._journaled += 1
        if self._journaled >= self.snapshot_every:
            try:
                self.plugin.snapshot(Plain.ToPlain(self.store).Snapshot())
                self._journaled = 0
            except Exception:  # the journal holds every transaction: the snapshot is tried again after the next one
                log.exception("a snapshot could not be taken; the journal still holds every transaction")
        return frames

    def names(self) -> list[str]:
        """Every named schema, by name."""
        with self._lock:
            self._available()
            return list(self.store.names())

    def schemas(self) -> PlainData:
        """[CAP-002: named schema list](../../../../../mbse-basis/docs/capabilities/CAP-002.md), while [CAP-003: schema inspector](../../../../../mbse-basis/docs/capabilities/CAP-003.md) is blocked: the store's schemas, the first transaction of its snapshot, from which a
        client's store takes every schema."""
        with self._lock:
            self._available()
            return Plain.ToPlain(self.store).Snapshot()[0]

    def templates(self) -> dict[str, PlainData]:
        """[CAP-004: logical view templates](../../../../../mbse-basis/docs/capabilities/CAP-004.md): each kind's template."""
        with self._lock:
            self._available()
            return {kind: Plain.ToPlain(self.store).Transaction(tx) for kind, tx in Views.templates(self.store).items()}

    def view(self, kind: str, plain: PlainData, session: str | None = None) -> list[str]:
        """[CAP-012: logical view endpoints](../../../../../mbse-basis/docs/capabilities/CAP-012.md): the frames a transaction gives, each a `References.OfFrame` filled as `kind` defines, as JSON. A
        transaction that writes is stamped first ([CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md), `stamp`), in `session`."""
        with self._lock:
            self._available()
            out = []
            for frame in self._commit(kind, stamp(plain, session, self.user, self.clock, self.uids)):
                witnessed = Views.witness(self.store, kind, frame)
                if witnessed is not None:
                    out.append(JSON.ToJSON(self.store)(witnessed.as_schema(), witnessed))
            return out


def _missing(kind: str, frames: list[dict[str, Any]]) -> str | None:
    """Why a view of `kind` cannot be filled from `frames`: a frame that does not bind each of its symbols."""
    for frame in frames:
        absent = [name for name in Views.SYMBOLS[kind] if name not in frame]
        if absent:
            return (f"the {kind} view's frames each bind {', '.join(Views.SYMBOLS[kind])}; a frame binds no "
                    f"{', '.join(absent)}")
    return None


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _lines(lines: list[str]) -> Iterator[str]:
    for line in lines:
        yield line + "\n"


def app(installs: Iterable[Install] = (), plugin: Plugin | None = None, snapshot_every: int = 100, *,
        origins: Iterable[str] = (), user: str = "demo", clock: Clock = _now, uids: Uids = _uuid) -> FastAPI:
    """The FastAPI application over a `Service` of the app that `installs` write, persisted by `plugin`
    (`Persistence.Memory` where None). It holds the service as `app.state.service`. `origins` are those a browser may
    call it from (CORS), the UI's: none by default."""
    service = Service(installs, plugin, snapshot_every, user=user, clock=clock, uids=uids)
    api = FastAPI(title="mbse-rest", description="Logical views over an mbse-schemas store (docs/CONTRACT.md)")
    api.state.service = service
    allowed = list(origins)
    if allowed:
        api.add_middleware(CORSMiddleware, allow_origins=allowed, allow_methods=["GET", "POST"],
                           allow_headers=["accept", "content-type", SESSION_HEADER])

    @api.exception_handler(HTTPException)
    async def refused(_: Request, error: HTTPException) -> JSONResponse:  # a path or method it does not serve
        return JSONResponse({"error": str(error.detail)}, status_code=error.status_code, headers=error.headers)

    @api.exception_handler(RequestValidationError)
    async def invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        return _error(400, str(error))

    def answer(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except Refused as error:
            return _error(error.status, str(error))
        except Exception as error:  # a fault of the service's own: 500, with the contract's error body
            log.exception("a request failed")
            return _error(500, _describe(error))

    @api.get("/schemas")
    def schemas() -> Any:
        return answer(service.schemas)

    @api.get("/schemas/{name}")
    def schema(name: str) -> Any:
        def call() -> Any:
            if name not in service.names():
                return _error(404, f"no schema is named {name!r}")
            return _error(501, UNWRITTEN)
        return answer(call)

    @api.get("/views")
    def templates() -> Any:
        return answer(service.templates)

    @api.post("/views/{kind}")
    async def view(kind: str, request: Request) -> Any:
        if kind not in Views.KINDS:
            return _error(404, f"no logical view kind is named {kind!r}: one of {', '.join(Views.KINDS)}")
        body = await request.body()
        try:
            plain = JSON.loads(body)
        except ValueError as error:  # DecodeError: not strict JSON
            return _error(400, f"the request's body is not a transaction's expression as JSON: {_describe(error)}")

        def call() -> Any:
            frames = service.view(kind, plain, request.headers.get(SESSION_HEADER))
            return StreamingResponse(_lines(frames), media_type=NDJSON)
        return await run_in_threadpool(answer, call)  # it waits on the store's lock: not on the event loop

    return api


def installs_of(module: str | ModuleType, seed: bool = True) -> list[Install]:
    """An app's installs, by mbse-demo-apps' layout: its package's `Schemas.INSTALLS`, in order, where it lists them
    (its schemas, then, for one with a history, `Provenance.install` and its `Provenance.extend`), else its
    `Schemas.install`; then, where `seed` and it has one, its `Seed.seed`."""
    package = importlib.import_module(module) if isinstance(module, str) else module
    name = package.__name__
    schemas = importlib.import_module(f"{name}.Schemas")
    installs: list[Install] = list(getattr(schemas, "INSTALLS", [schemas.install]))
    if seed:
        try:
            seeds = importlib.import_module(f"{name}.Seed")
        except ModuleNotFoundError as error:
            if error.name != f"{name}.Seed":
                raise
        else:
            installs.append(seeds.seed)
    return installs


def plugin_of(name: str) -> Plugin:
    """A persistence plugin by name: `memory`, or `module:attribute`, a class or function that makes one when called
    with no arguments (its own configuration is its own, from the environment for instance)."""
    if name.strip().lower() in ("", "memory"):
        return Memory()
    module, _, attribute = name.partition(":")
    if not attribute:
        raise ValueError(f"a persistence plugin is 'memory' or 'module:attribute', not {name!r}")
    made = getattr(importlib.import_module(module), attribute)()
    if not isinstance(made, Plugin):
        raise TypeError(f"{name} makes no persistence plugin: it lacks load, journal or snapshot")
    return made


def _flag(value: str) -> bool:
    if value.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if value.strip().lower() in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected 1 or 0, true or false, not {value!r}")


def from_environment(environ: Mapping[str, str] | None = None) -> FastAPI:
    """The application as the environment configures it (README.md, Running the service):

    - `MBSE_REST_APP`: the app's package, its installs found by `installs_of` (`mbse.Demos.Apps.WorkTracker`);
    - `MBSE_REST_SEED`: whether its `Seed.seed` runs at first start (`1`);
    - `MBSE_REST_PLUGIN`: the persistence plugin, `plugin_of`'s name (`memory`);
    - `MBSE_REST_SNAPSHOT_EVERY`: journaled transactions between snapshots (`100`);
    - `MBSE_REST_ORIGINS`: the UI's origins a browser may call from, comma-separated (none).
    """
    env = os.environ if environ is None else environ
    installs = installs_of(env.get("MBSE_REST_APP", WORK_TRACKER), _flag(env.get("MBSE_REST_SEED", "1")))
    origins = [origin.strip() for origin in env.get("MBSE_REST_ORIGINS", "").split(",") if origin.strip()]
    return app(installs, plugin_of(env.get("MBSE_REST_PLUGIN", "memory")),
               int(env.get("MBSE_REST_SNAPSHOT_EVERY", "100")), origins=origins,
               user=env.get("MBSE_REST_USER", "demo"))


def work_tracker(plugin: Plugin | None = None, **options: Any) -> FastAPI:
    """The stub server: the service over the demo app's store (mbse-demo-apps, a development dependency), its schemas
    installed and seeded."""
    return app(installs_of(WORK_TRACKER), plugin, **options)
