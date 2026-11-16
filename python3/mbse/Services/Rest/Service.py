"""The REST service over an mbse-schemas store (mbse-basis [CAP-002: named schema list](mbse:mbse-basis/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md), [CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md) and [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290)).

`app(installs, below)` gives a FastAPI application that serves a store given a store below it, a database's in
production (mbse-dynamodb's `Store`), one in memory by default: the service's store, a `Builders.Store` over `below`,
which loads what it is asked for from it and writes each transaction through to it, so that it
persists by the journal of the store below alone, and no snapshot is taken or read. Each install (an app's
`Schemas.install`, or each of its `Schemas.INSTALLS`) runs in the store below and in the service's store, and is served
to clients as the install transaction that made the schemas; the seed, where given, runs after, as any transaction.
`installs_of(module)` and `seed_of(module)` find an app's by mbse-demo-apps' layout; `from_environment()` builds the
application from `MBSE_REST_*` variables, as `python -m mbse.Services.Rest` serves it. The endpoints:

| Method and path | Capability | Response |
|---|---|---|
| `GET /schemas` | [CAP-002: named schema list](mbse:mbse-basis/docs/capabilities/CAP-002.md) | the install transactions that made the store's schemas, in order, each a transaction's expression |
| `POST /schemas` | [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290) | an install transaction, run in the store below and the service's store, then served with the others; the installs |
| `GET /schemas/{name}` | [CAP-003: schema inspector](mbse:mbse-basis/docs/capabilities/CAP-003.md) | 501 until mbse-schemas writes one schema object as a document (CAP-003, Blocked) |
| `POST /documents` | [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290) | the document of the object at the path given, a one-transaction document, or null |
| `POST /transactions` | [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290) | a transaction's expression, committed: `{"position": n, "effect": e}`, the change feed's position once it has, and the transaction as the store committed it, its record among it (null where it changed nothing) |
| `GET /changes?after=n&feed=id&wait=s` | [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290) | `{"feed", "head", "changes"}`: each transaction the store committed after position `n`, in order, as `{"position", "effect"}` |
| `GET /views` | [CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md) | `{kind: template, ...}`, each a transaction's expression |
| `POST /views/{kind}` | [CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md) | the frames, `References.OfFrame`, one JSON document a line (NDJSON) |

A transaction's expression is `Plain.ToPlain(store).Transaction`'s. The service reads it (`JSON.loads`,
`Plain.FromPlain(store).Transaction`), stamps it where it writes (`stamp`), and executes it; the store below commits
what it writes first, and where the store below refuses it or fails, nothing is written. One transaction runs at a
time.

The change feed is the store's committed transactions, each its effect (mbse-schemas' `Changes`), numbered from 1 in
the order the store committed them, read by position: a client reads from where it last read, so that it is given each
once, none missed. The service keeps the latest `window` of them: a position before those it keeps, or one it never
gave (as after it restarted, the feed then another, named by its `feed` id), is refused (410), and the client's store is
made again. `wait` holds a read that finds nothing new open for up to that many seconds (30 at most), until one
commits: long polling, so that a client hears of a commit at once, through any proxy, without a stream held open.

Every refusal is `{"error": message}` ([CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md), the wire format); a transaction's refusal (400) begins
with the kind of error its store raised, `ValueError: `, `TypeError: ` or `LookupError: `.
"""

from __future__ import annotations

import collections
import datetime
import importlib
import logging
import os
import threading
import time
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

from mbse.Schemas.Framework import JSON, Builders, Changes, Plain, References, Stores

from . import Views

__all__ = ["NDJSON", "Install", "Refused", "Unavailable", "Service", "app", "installs_of", "seed_of", "store_of", "fresh",
           "from_environment", "work_tracker", "writes", "stamp", "WINDOW", "WAIT"]

PlainData = Any  # mbse-schemas' plain data: mappings, lists, strings, numbers, booleans and None
NDJSON = "application/x-ndjson"
UNWRITTEN = ("mbse-schemas writes no schema object as a document of its own: Plain.ToPlain(store).OfObject refuses "
             "one, owned through an anonymous adjacency (mbse-basis CAP-003: schema inspector, Blocked)")
WORK_TRACKER = "mbse.Demos.Apps.WorkTracker"
WINDOW = 10_000  # the latest committed transactions the change feed keeps
WAIT = 30.0  # the longest a read of the change feed is held open, in seconds
PAGE = 1_000  # the most changes one read of the feed gives

Install = Callable[[Any], Any]
"""An install: a callback given a transaction, `store.transaction(install)`, as an app's `Schemas.install` and
`Seed.seed` are."""

log = logging.getLogger("mbse.Services.Rest")

# What the executor and mbse-schemas' readers raise for a transaction they refuse: `DecodeError` is a `ValueError`,
# `ReadOnlyError` a `TypeError`, a symbol or path to nothing a `LookupError`; each reported by the first it is.
REFUSALS = (ValueError, TypeError, LookupError)


def writes(plain: PlainData) -> bool:
    """Whether a transaction's expression has a term that writes, an upsert or an update."""
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
    """The store failed, its store below for one: nothing was written (503)."""

    def __init__(self, message: str) -> None:
        super().__init__(503, message)


SESSION_HEADER = "x-mbse-session"
"""The request header that names the client's session ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md)): the demo's stand-in for a validated token's
session, which the service trusts until [CAP-177: sessions and identities from a validated token](mbse:mbse-basis/docs/capabilities/CAP-177.md)."""


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
    """[CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md): a transaction that writes, as the service executes it: given a `uid` where it has none, so that
    each store it is written through finds the same record, and its `when`, and its session's `id` and `who`, the
    service's; the client's `locale`, `device` and `where` are kept. Where the client names no session, the identity's
    own, `<who>:default`. A transaction that only reads is given back as it is."""
    if not writes(plain) or not isinstance(plain, dict):
        return plain
    stamped = dict(plain)
    stamped.setdefault("uid", uids())
    stamped["when"] = _iso(clock())
    # no session named: one of the identity's own, since a session has one identity (Provenance.Who)
    stamped["session"] = {**(plain.get("session") or {}), "id": session or f"{who}:default", "who": who}
    return stamped


def _plain(store: Any, effect: Any) -> PlainData:
    """A transaction expression of `store`'s as plain data, as it is sent."""
    return JSON.loads(JSON.dumps(Plain.ToPlain(store).Transaction(effect)))


class _Below:
    """The store below the service's store, as that store sees it (`Stores.Below`): the store below it is given, each
    install the service's store gives it, a transaction that writes schemas, kept as plain data, in order, which the
    service serves as the install transactions that made its schemas."""

    def __init__(self, below: Any) -> None:
        self.below = below
        self.records = below.records
        self.installs: list[PlainData] = []

    def document(self, path: PlainData) -> PlainData:
        return self.below.document(path)

    def commit(self, plain: PlainData) -> PlainData:
        return self.below.commit(plain)

    def install(self, plain: PlainData) -> None:
        self.below.install(plain)
        plain = JSON.loads(JSON.dumps(plain))
        if all(JSON.dumps(plain) != JSON.dumps(held) for held in self.installs):
            self.installs.append(plain)

    def follow(self, follower: Callable[[PlainData], None]) -> Callable[[], None]:
        return self.below.follow(follower)


class Service:
    """A store given a store below, and its change feed: what the endpoints call, apart from HTTP."""

    def __init__(self, installs: Iterable[Install | PlainData] = (), below: Any = None, seed: Install | None = None, *,
                 window: int = WINDOW, user: str = "demo", clock: Clock = _now, uids: Uids = _uuid) -> None:
        self.user = user  # the demo's identity, standing in for a validated token's ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md); [CAP-177: sessions and identities from a validated token](mbse:mbse-basis/docs/capabilities/CAP-177.md))
        self.clock, self.uids = clock, uids  # a write's `when` and, where it has none, its `uid` (`stamp`)
        self.below = below if below is not None else Builders.Store()
        self._recorded = _Below(self.below)  # which keeps each install the store gives the store below
        self.store = Builders.Store(self._recorded)
        self._lock = threading.RLock()  # one transaction at a time: transactions on one store do not nest
        self._committed = threading.Condition(self._lock)  # notified as each transaction is fed
        self.feed = _uuid()  # this feed's own name: a position is this feed's alone
        self.head = 0  # the position of the last transaction fed
        self._before = 0  # the position fed before the transaction executing
        self._changes: collections.deque[tuple[int, PlainData]] = collections.deque(maxlen=window)
        # a store kept in a database, followed by polling: what other processes committed (a method of its class, since
        # a store's own attributes are its schemas' paths)
        self._poll = self.below.poll if callable(getattr(type(self.below), "poll", None)) else None
        self._reference = self.store.References.OfObject.as_schema()
        Changes.observe(self.store, self._fed)
        for install in installs:
            self.install(install)
        if seed is not None:  # as any transaction, its `when` the service's (CAP-015)
            self.store.transaction(lambda t: seed(t).when(_iso(self.clock())))

    def _fed(self, effect: Any) -> None:
        """A transaction the store committed, fed: numbered, kept among the latest, and those waiting told."""
        with self._lock:  # held already, but where the store commits apart from a request: at the seed
            self.head += 1
            self._changes.append((self.head, _plain(self.store, effect)))
            self._committed.notify_all()

    def _polled(self) -> None:
        """What other processes committed to the store below, given to the service's store, where the store below is
        one followed by polling, as a store kept in a database is."""
        if self._poll is not None:
            self._poll()

    @property
    def installs(self) -> list[PlainData]:
        """The install transactions that made the store's schemas, in order, each as the store gave it the store below."""
        return list(self._recorded.installs)

    def install(self, install: Install | PlainData) -> list[PlainData]:
        """Runs an install, a callback or its transaction expression, in the service's store, which runs it in the
        store below first (`Stores.Below.install`), and serves it after the others where it is not among them already;
        the installs."""
        with self._lock:
            try:
                if isinstance(install, dict):
                    self.store.install(install)
                else:  # its `when` the service's (CAP-015)
                    when = _iso(self.clock())
                    self.store.transaction(lambda txn: install(txn).when(when))
            except REFUSALS as error:
                raise Refused(400, _describe(error)) from error
            return self.installs

    def names(self) -> list[str]:
        """Every named schema, by name."""
        with self._lock:
            return list(self.store.names())

    def schemas(self) -> list[PlainData]:
        """[CAP-002: named schema list](mbse:mbse-basis/docs/capabilities/CAP-002.md), while [CAP-003: schema inspector](mbse:mbse-basis/docs/capabilities/CAP-003.md) is blocked: the install transactions that made the store's
        schemas, in order, from which a client's store takes every schema by executing each."""
        with self._lock:
            return self.installs

    def templates(self) -> dict[str, PlainData]:
        """[CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md): each kind's template."""
        with self._lock:
            return {kind: Plain.ToPlain(self.store).Transaction(tx) for kind, tx in Views.templates(self.store).items()}

    def document(self, path: PlainData) -> PlainData:
        """The document of the object at `path`, None where the store holds none: what a store above loads."""
        with self._lock:
            self._polled()
            try:
                return self.store.document(path)
            except REFUSALS as error:
                raise Refused(400, _describe(error)) from error

    def _execute(self, plain: PlainData) -> list[dict[str, Any]]:
        """Executes a transaction's expression; refused (400) where its store refuses it, unavailable (503) where its
        store fails otherwise. Either way, nothing it wrote is kept."""
        self._polled()
        try:
            self._load(plain)
            self._before = self.head  # the transaction, where it changes anything, is fed next
            return self.store.transaction(Plain.FromPlain(self.store).Transaction(plain))
        except REFUSALS as error:
            raise Refused(400, _describe(error)) from error
        except Exception as error:  # the store below's own, whatever it raises
            log.exception("a transaction could not be committed")
            raise Unavailable(f"the transaction could not be committed, and nothing is written: "
                              f"{type(error).__name__}: {error}") from error

    def _load(self, plain: PlainData) -> None:
        """Loads each object a transaction's expression binds to a symbol by its reference, before the expression is
        read: mbse-schemas reads a spec written on an object it has not loaded no further than to load it, within the
        expression it builds, and refuses that (`AttributeError: _working`), where loaded first it does not."""
        for path in _referenced(plain):
            References.resolve(self.store, Plain.FromPlain(self.store)(self._reference, {"path": path}))

    def transaction(self, plain: PlainData, session: str | None = None) -> dict[str, Any]:
        """Commits a transaction's expression, stamped where it writes ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md), `stamp`), in `session`:
        `{"position", "effect"}`, the change feed's position once it has, its own where it changed anything, and the
        transaction as the store committed it, as plain data, its record (`Provenance`) among it, as the change feed
        gives it; None where it changed nothing. A client takes it into its transaction, as a store above takes what
        the store below reports it committed while it sends it (CAP-285)."""
        with self._lock:
            self._execute(stamp(plain, session, self.user, self.clock, self.uids))
            fed = [e for n, e in self._changes if n == self._before + 1] if self.head > self._before else []
            return {"position": self.head, "effect": fed[0] if fed else None}

    def changes(self, after: int | None = None, feed: str | None = None, wait: float = 0.0) -> dict[str, Any]:
        """The change feed after position `after`, at most `PAGE` of them: the current head alone where `after` is
        None. Where none is after it, held open until one is committed, or `wait` seconds pass. Refused (410) where
        `feed` is another's, or `after` is before the transactions it keeps, or after its head."""
        deadline = time.monotonic() + min(max(wait, 0.0), WAIT)
        with self._lock:
            self._polled()
            if after is None:
                return {"feed": self.feed, "head": self.head, "changes": []}
            if feed is not None and feed != self.feed:
                raise Refused(410, f"the change feed {feed!r} is not this service's, {self.feed!r}: it restarted, and "
                                   "what a store holds may have changed unreported; make the store again")
            first = self._changes[0][0] if self._changes else self.head + 1
            if after > self.head or after < first - 1:
                raise Refused(410, f"the change feed keeps positions {first - 1} to {self.head}, not {after}: make the "
                                   "store again")
            while self.head == after and (left := deadline - time.monotonic()) > 0:
                self._committed.wait(min(left, 1.0))  # woken by a commit here; polling the store below meanwhile
                self._polled()
            changes = [{"position": n, "effect": e} for n, e in self._changes if n > after][:PAGE]
            return {"feed": self.feed, "head": self.head, "changes": changes}

    def view(self, kind: str, plain: PlainData, session: str | None = None) -> list[str]:
        """[CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md): the frames a transaction gives, each a `References.OfFrame` filled as `kind` defines, as JSON. A
        transaction that writes is stamped first ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md), `stamp`), in `session`, and refused before it is
        executed where its frames cannot each bind the kind's symbols, since what it writes is committed below first."""
        with self._lock:
            if writes(plain):
                unbound = _unbound(kind, plain)
                if unbound:
                    raise Refused(400, unbound)
            frames = self._execute(stamp(plain, session, self.user, self.clock, self.uids))
            missing = _missing(kind, frames)
            if missing:
                raise Refused(400, missing)
            out = []
            for frame in frames:
                witnessed = Views.witness(self.store, kind, frame)
                if witnessed is not None:
                    out.append(JSON.ToJSON(self.store)(witnessed.as_schema(), witnessed))
            return out


def _referenced(plain: PlainData) -> Iterator[PlainData]:
    """The path of each object a transaction's expression binds to a symbol by its reference."""
    if isinstance(plain, dict):
        for name, value in plain.items():
            if name == "symbols" and isinstance(value, dict):
                for bound in value.values():
                    path = bound.get("reference", {}).get("path") if isinstance(bound, dict) else None
                    if isinstance(path, dict) and path.get("singleton") != ".":  # a schema object's is not loaded
                        yield path
            yield from _referenced(value)
    elif isinstance(plain, list):
        for value in plain:
            yield from _referenced(value)


PATTERNS = {"map": "symbols", "upsert": "exists", "update": "apply"}  # where each term that has one gives its patterns


def _unbound(kind: str, plain: PlainData) -> str | None:
    """Why a view of `kind` cannot be filled from what a transaction that writes gives: its chain of terms, from its
    root through each `then`, declares no symbol of the kind's in its patterns."""
    declared: set[str] = set()
    terms = plain.get("mutations") if isinstance(plain, dict) else None
    term = terms[0] if isinstance(terms, list) and terms and isinstance(terms[0], dict) else None
    while term:
        verb, body = next(iter(term.items()))
        if not isinstance(body, dict):
            break
        for pattern in body.get(PATTERNS.get(verb, ""), None) or []:
            if isinstance(pattern, dict) and isinstance(pattern.get("symbols"), dict):
                declared.update(pattern["symbols"])
        after = body.get("then")
        term = after[0] if isinstance(after, list) and after and isinstance(after[0], dict) else None
    absent = [name for name in Views.SYMBOLS[kind] if name not in declared]
    if absent:
        return (f"the {kind} view's frames each bind {', '.join(Views.SYMBOLS[kind])}; a frame binds no "
                f"{', '.join(absent)}")
    return None


def _missing(kind: str, frames: list[dict[str, Any]]) -> str | None:
    """Why a view of `kind` cannot be filled from `frames`: a frame that does not bind each of its symbols."""
    for frame in frames:
        absent = [name for name in Views.SYMBOLS[kind] if name not in frame]
        if absent:
            return (f"the {kind} view's frames each bind {', '.join(Views.SYMBOLS[kind])}; a frame binds no "
                    f"{', '.join(absent)}")
    return None


def _describe(error: BaseException) -> str:
    """A refusal's message, beginning with the kind of error raised: the first of `REFUSALS` it is."""
    kind = next((k.__name__ for k in REFUSALS if isinstance(error, k)), type(error).__name__)
    return f"{kind}: {error}"


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _lines(lines: list[str]) -> Iterator[str]:
    for line in lines:
        yield line + "\n"


def app(installs: Iterable[Install | PlainData] = (), below: Any = None, seed: Install | None = None, *,
        origins: Iterable[str] = (), window: int = WINDOW, user: str = "demo", clock: Clock = _now,
        uids: Uids = _uuid) -> FastAPI:
    """The FastAPI application over a `Service` of the store given `below` (one in memory where None), which
    `installs` give their schemas and `seed`, where given, its data. It holds the service as `app.state.service`.
    `origins` are those a browser may call it from (CORS), the UI's: none by default."""
    service = Service(installs, below, seed, window=window, user=user, clock=clock, uids=uids)
    api = FastAPI(title="mbse-rest", description="A store served over REST, and logical views over it (mbse-basis "
                                                 "FEA-003: no-code logical views, CAP-290)")
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
            return _error(500, f"{type(error).__name__}: {error}")

    async def body_of(request: Request, what: str) -> Any:
        """The request's body, read from strict JSON; a `Refused` where it is not JSON."""
        try:
            return JSON.loads(await request.body())
        except ValueError as error:  # DecodeError: not strict JSON
            raise Refused(400, f"the request's body is not {what} as JSON: {_describe(error)}") from error

    async def threaded(call: Callable[[], Any]) -> Any:  # it waits on the store's lock: not on the event loop
        return await run_in_threadpool(answer, call)

    @api.get("/schemas")
    def schemas() -> Any:
        return answer(service.schemas)

    @api.post("/schemas")
    async def install(request: Request) -> Any:
        try:
            plain = await body_of(request, "an install transaction's expression")
        except Refused as error:
            return _error(error.status, str(error))
        if not isinstance(plain, dict):
            return _error(400, "an install is a transaction's expression, a JSON object")
        return await threaded(lambda: service.install(plain))

    @api.get("/schemas/{name}")
    def schema(name: str) -> Any:
        def call() -> Any:
            if name not in service.names():
                return _error(404, f"no schema is named {name!r}")
            return _error(501, UNWRITTEN)
        return answer(call)

    @api.post("/documents")
    async def document(request: Request) -> Any:
        try:
            path = await body_of(request, "an object's path")
        except Refused as error:
            return _error(error.status, str(error))
        return await threaded(lambda: JSONResponse(service.document(path)))

    @api.post("/transactions")
    async def transaction(request: Request) -> Any:
        try:
            plain = await body_of(request, "a transaction's expression")
        except Refused as error:
            return _error(error.status, str(error))
        return await threaded(lambda: service.transaction(plain, request.headers.get(SESSION_HEADER)))

    @api.get("/changes")
    async def changes(after: int | None = None, feed: str | None = None, wait: float = 0.0) -> Any:
        return await threaded(lambda: service.changes(after, feed, wait))

    @api.get("/views")
    def templates() -> Any:
        return answer(service.templates)

    @api.post("/views/{kind}")
    async def view(kind: str, request: Request) -> Any:
        if kind not in Views.KINDS:
            return _error(404, f"no logical view kind is named {kind!r}: one of {', '.join(Views.KINDS)}")
        try:
            plain = await body_of(request, "a transaction's expression")
        except Refused as error:
            return _error(error.status, str(error))

        def call() -> Any:
            frames = service.view(kind, plain, request.headers.get(SESSION_HEADER))
            return StreamingResponse(_lines(frames), media_type=NDJSON)
        return await threaded(call)

    return api


def installs_of(module: str | ModuleType) -> list[Install]:
    """An app's installs, by mbse-demo-apps' layout: its package's `Schemas.INSTALLS`, in order, where it lists them
    (its schemas, then, for one with a history, `Provenance.install` and its `Provenance.extend`), else its
    `Schemas.install`."""
    package = importlib.import_module(module) if isinstance(module, str) else module
    schemas = importlib.import_module(f"{package.__name__}.Schemas")
    return list(getattr(schemas, "INSTALLS", [schemas.install]))


def seed_of(module: str | ModuleType) -> Install | None:
    """An app's seed, by mbse-demo-apps' layout: its package's `Seed.seed`, None where it has no `Seed`."""
    package = importlib.import_module(module) if isinstance(module, str) else module
    name = package.__name__
    try:
        return importlib.import_module(f"{name}.Seed").seed
    except ModuleNotFoundError as error:
        if error.name != f"{name}.Seed":
            raise
        return None


def store_of(name: str) -> Any:
    """The store below by name: `memory`, a store in memory, or `module:attribute`, a class or function that makes one
    when called with no arguments (its own configuration is its own, from the environment for instance), a store
    below (mbse-schemas' `Stores.Below`): `mbse.Persistence.DynamoDB.Store:Store`, mbse-dynamodb's, for one."""
    if name.strip().lower() in ("", "memory"):
        return Builders.Store()
    module, _, attribute = name.partition(":")
    if not attribute:
        raise ValueError(f"a store below is 'memory' or 'module:attribute', not {name!r}")
    made = getattr(importlib.import_module(module), attribute)()
    if not isinstance(made, Stores.Below):
        raise TypeError(f"{name} makes no store below (mbse-schemas' Stores.Below)")
    return made


def fresh(below: Any) -> bool:
    """Whether a store below has committed nothing, so that an app's seed is run in it: one that keeps a journal
    (`journal()`, as mbse-dynamodb's does) where it holds no entry; one that keeps none, as a store in memory, made new
    with the service, always. A seed is not run again over what it wrote, which may have been edited since."""
    journal = getattr(type(below), "journal", None)  # a method of its class: a store's own attributes are its paths
    return not callable(journal) or next(iter(below.journal()), None) is None


def _flag(value: str) -> bool:
    if value.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if value.strip().lower() in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected 1 or 0, true or false, not {value!r}")


RETIRED = {"MBSE_REST_PLUGIN": "MBSE_REST_STORE names the store below instead",
           "MBSE_REST_SNAPSHOT_EVERY": "no snapshot is taken: the store below's journal is the record"}


def from_environment(environ: Mapping[str, str] | None = None) -> FastAPI:
    """The application as the environment configures it (README.md, Running the service):

    - `MBSE_REST_APP`: the app's package, its installs found by `installs_of` (`mbse.Demos.Apps.WorkTracker`);
    - `MBSE_REST_SEED`: whether its `Seed.seed` runs at start (`1`), where the store below is new (`fresh`);
    - `MBSE_REST_STORE`: the store below, `store_of`'s name (`memory`);
    - `MBSE_REST_WINDOW`: how many of the latest committed transactions the change feed keeps (`10000`);
    - `MBSE_REST_ORIGINS`: the UI's origins a browser may call from, comma-separated (none);
    - `MBSE_REST_USER`: the identity each write is stamped with (`demo`).

    `MBSE_REST_PLUGIN` and `MBSE_REST_SNAPSHOT_EVERY` are retired, and refused where set.
    """
    env = os.environ if environ is None else environ
    for name, instead in RETIRED.items():
        if name in env:
            raise ValueError(f"{name} is retired: {instead}")
    module = env.get("MBSE_REST_APP", WORK_TRACKER)
    below = store_of(env.get("MBSE_REST_STORE", "memory"))
    seed = seed_of(module) if _flag(env.get("MBSE_REST_SEED", "1")) and fresh(below) else None
    origins = [origin.strip() for origin in env.get("MBSE_REST_ORIGINS", "").split(",") if origin.strip()]
    return app(installs_of(module), below, seed, origins=origins,
               window=int(env.get("MBSE_REST_WINDOW", str(WINDOW))), user=env.get("MBSE_REST_USER", "demo"))


def work_tracker(below: Any = None, **options: Any) -> FastAPI:
    """The stub server: the service over the demo app's store (mbse-demo-apps, a development dependency), its schemas
    installed and seeded, over `below`, one in memory where None."""
    return app(installs_of(WORK_TRACKER), below, seed_of(WORK_TRACKER), **options)
