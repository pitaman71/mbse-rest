"""The REST service over an mbse-schemas store (mbse-basis [CAP-002: named schema list](mbse:mbse-basis/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md), [CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md) and [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290)).

`app(installs, store)` gives a FastAPI application that serves a store: one in memory by default, or any other, a
`Builders.Store` over a database's store in production (mbse-dynamodb's), so that it persists by that store's journal
alone, and no snapshot is taken or read. It serves the store as a layer below for a cache layer in another process
(mbse-basis [the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md#a-cache-layer-and-the-layer-below), its third stage): the
store's transaction, held open for the client's, and its `exec`, each call a request answered with a stream of frames;
and its follow, as a change feed. Each install (an app's `Schemas.install`, or each of its `Schemas.INSTALLS`) runs in
the store and is served as the install transaction that made the schemas; the seed, where given, runs after, as any
transaction. `installs_of(module)` and `seed_of(module)` find an app's by mbse-demo-apps' layout; `from_environment()`
builds the application from `MBSE_REST_*` variables, as `python -m mbse.Services.Rest` serves it. The endpoints:

| Method and path | Capability | Response |
|---|---|---|
| `GET /schemas` | [CAP-002: named schema list](mbse:mbse-basis/docs/capabilities/CAP-002.md) | the install transactions the service was given, in order, each a transaction's expression: a client given no installs of its own runs them |
| `GET /schemas/{name}` | [CAP-003: schema inspector](mbse:mbse-basis/docs/capabilities/CAP-003.md) | 501 until mbse-schemas writes one schema object as a document (CAP-003, Blocked) |
| `POST /transactions` | [CAP-308: stacking by mutation transactions, in one round trip](mbse:mbse-basis/docs/capabilities/README.md#CAP-308) | a transaction of the store opened for the client's: `{"transaction": id, "feed", "head"}`, the change feed's position as it opened |
| `POST /transactions/{id}/exec` | [CAP-308: stacking by mutation transactions, in one round trip](mbse:mbse-basis/docs/capabilities/README.md#CAP-308) | `{"expression", "remainder", "frames", "write"}` executed within it, `txn.exec`: its stream, one `References.OfItem` a line (NDJSON), the last `{"end": {}}` |
| `POST /transactions/{id}/commit` | [CAP-308: stacking by mutation transactions, in one round trip](mbse:mbse-basis/docs/capabilities/README.md#CAP-308) | committed: `{"head", "journal"}`, the change feed's position once it has, and what the store's follow gave of it, a `Changes.Journal` |
| `DELETE /transactions/{id}` | [CAP-308: stacking by mutation transactions, in one round trip](mbse:mbse-basis/docs/capabilities/README.md#CAP-308) | dropped, nothing written: `{}` |
| `GET /changes?after=id&feed=id&wait=s` | [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290) | `{"feed", "head", "journal"}`: the transactions the store committed after the one of id `after`, in order, a `Changes.Journal` as plain data; `head`, the id of the last |
| `GET /views` | [CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md) | `{kind: template, ...}`, each a transaction's expression |
| `POST /views/{kind}` | [CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md) | the frames, `References.OfFrame`, one JSON document a line (NDJSON) |

A client's transaction is a request sequence: `POST /transactions` opens one of the store's; each `exec` of the
client's is a `POST /transactions/{id}/exec`, whose body is the expression, `Plain.ToPlain(store).Transaction`'s, the
subterm its `remainder` starts at (none: the whole of it), the input frames, each a `References.OfFrame` as plain
data, and whether it writes; then `POST /transactions/{id}/commit`, or `DELETE /transactions/{id}` where the client's
transaction raises. The service reads the expression in its store, stamps it where it writes (`stamp`), and executes it
within the transaction open; its stream is written as `Frames` writes it. The store commits, the layers below it first,
where the client commits: the client's layer below commits before the client does, as in a process. One transaction is
open at a time: another client's waits for it, up to `WAIT` seconds, else is refused (503); one left idle for `lease`
seconds is dropped, as a client gone away leaves it, and the next request on it is refused (410).

The change feed is the store's committed transactions, as its `follow` gives them, each a one-transaction
`Changes.Journal` as plain data, joined into one journal in the order the store committed them (mbse-journals'
`Journals.join`), read by position: a position is a transaction's `id`, and a client reads the transactions after the
last it was given (`Journals.after`), so that it is given each once, none missed. A read naming its `feed` and no
position is given the feed from its first transaction; one naming neither, the head alone. The service keeps the latest
`window` transactions: a position it does not keep, before those it keeps or one it never gave (as after it restarted,
the feed then another, named by its `feed` id), or a read from the first once it has let one go, is refused (410), and
the client's store is made again. `wait` holds a read that finds nothing new open for up to that many seconds (30 at
most), until one commits: long polling, so that a client hears of a commit at once, through any proxy, without a stream
held open. Where the store is over one followed by polling, as a store kept in a database is, the service polls it
(`poll`) while no transaction is open, before a read of the feed and while one is held open.

Every refusal is `{"error": message}` ([CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md), the wire format); a transaction's refusal (400) begins
with the kind of error its store raised, `ValueError: `, `TypeError: ` or `LookupError: `.
"""

from __future__ import annotations

import contextlib
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

from mbse.Journals.Framework import Journals
from mbse.Schemas.Framework import JSON, Builders, Plain
from mbse.Schemas.Framework.Transactions import Remainder

from . import Frames, Views

__all__ = ["NDJSON", "Install", "Refused", "Unavailable", "Service", "app", "installs_of", "seed_of", "store_of", "fresh",
           "from_environment", "work_tracker", "writes", "stamp", "WINDOW", "WAIT", "LEASE"]

PlainData = Any  # mbse-schemas' plain data: mappings, lists, strings, numbers, booleans and None
NDJSON = "application/x-ndjson"
UNWRITTEN = ("mbse-schemas writes no schema object as a document of its own: Plain.ToPlain(store).OfObject refuses "
             "one, owned through an anonymous adjacency (mbse-basis CAP-003: schema inspector, Blocked)")
WORK_TRACKER = "mbse.Demos.Apps.WorkTracker"
WINDOW = 10_000  # the latest committed transactions the change feed keeps
WAIT = 30.0  # the longest a read of the change feed, or a request waiting for the store, is held, in seconds
PAGE = 1_000  # the most changes one read of the feed gives
LEASE = 60.0  # how long a client's transaction is kept open with no request on it, in seconds

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
    """The store failed, a layer below it for one: nothing was written (503)."""

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


class _Named:
    """What an install's callback is given, as `store.transaction(install)` gives it: the transaction's builder, and the
    store's schemas by name besides, `txn.Schemas.OfObject`."""

    def __init__(self, store: Any, builder: Any) -> None:
        self._store, self._builder = store, builder

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        schema = self._builder.as_schema()
        if name in schema.properties or name in schema.adjacencies:
            return getattr(self._builder, name)
        return getattr(self._store, name)


def _read(store: Any, txn: Any, plain: PlainData) -> Any:
    """A transaction's expression, read in `store` while `txn`, its transaction, is open, built outside the
    transaction's proposals, as an expression is (object identity 94 in mbse-basis
    [CAP-138: mutation expressions over frame streams](mbse:mbse-basis/docs/capabilities/CAP-138.md#decided)): by the
    callback `txn.exec` builds an expression with, the expression it builds empty but for the expression's `uid`,
    `when`, `session` and `where`, so that nothing is executed, and where it is the first a transaction is given, its
    record (`Provenance`) is the expression's. Its stream is read only where `txn.exec` builds no expression until it
    is, as one that wraps a store's own may."""
    built: list[Any] = []
    schema = store.registered("Mutations.OfTransaction")

    def build(t: Any) -> Any:
        built.append(Plain.FromPlain(store).Transaction(plain))
        for name, value in plain.items():
            if name in schema.properties and value is not None:
                t = getattr(t, name)(Plain.FromPlain(store).Value(schema.properties[name].schema, value)
                                     if isinstance(value, dict) else value)
        return t

    stream = txn.exec(Frames.Frame(), build, False)
    if not built:
        list(stream)
    return built[0]


class _Open:
    """A client's transaction, open in the store: its scope, the store's transaction (`Transactions.Transaction`),
    opened once its first expression is read, so that that one is read outside it; its session, its `when` and its
    `uid`, the same for each of its writes, and when it was last used."""

    def __init__(self, session: str | None, when: datetime.datetime, uid: str) -> None:
        self.id = _uuid()
        self.session, self.when, self.uid = session, when, uid
        self.scope: Any = None  # the store's transaction, opened as its first exec is read: none before
        self.txn: Any = None
        self.first: str | None = None  # the uid of its first expression, under which the store commits it
        self.journal: Journals.Journal = []  # what the store's follow gave of it, as it committed
        self.last = time.monotonic()


class _Dropped(Exception):
    """A client's transaction ended without its commit: aborted, or left idle."""


class Service:
    """A store, the transaction open for a client in it, and its change feed: what the endpoints call, apart from
    HTTP."""

    def __init__(self, installs: Iterable[Install | PlainData] = (), store: Any = None, seed: Install | None = None, *,
                 poll: Callable[[], Any] | None = None, window: int = WINDOW, user: str = "demo", clock: Clock = _now,
                 uids: Uids = _uuid, lease: float = LEASE) -> None:
        self.user = user  # the demo's identity, standing in for a validated token's ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md); [CAP-177: sessions and identities from a validated token](mbse:mbse-basis/docs/capabilities/CAP-177.md))
        self.clock, self.uids = clock, uids  # a write's `when` and, where it has none, its `uid` (`stamp`)
        self.store = store if store is not None else Builders.Store()
        self.lease = lease
        self._lock = threading.RLock()  # the store, used by one request at a time
        self._free = threading.Condition(self._lock)  # notified as a client's transaction ends
        self._open: _Open | None = None  # the client's transaction open, held across its requests
        self._committing: _Open | None = None
        self._fed_lock = threading.Lock()
        self._committed = threading.Condition(self._fed_lock)  # notified as each transaction is fed
        self.feed = _uuid()  # this feed's own name: a position is this feed's alone
        self.head: str | None = None  # the position of the last transaction fed: its id
        self.window = window
        self.journal: Journals.Journal = []  # the latest `window` transactions fed, a `Changes.Journal` as plain data
        self._dropped = False  # whether the feed has let a transaction go: then it is not read from its first
        self._poll = poll  # what others committed below the store, given to it, where it is followed by polling
        self._installs: list[PlainData] = []
        self.store.follow(self._fed)
        for install in installs:
            self.install(install)
        if seed is not None:  # as any transaction, its `when` the service's (CAP-015)
            with self._turn():
                self.store.transaction(lambda t: seed(t).when(_iso(self.clock())))

    # --- The change feed ---

    def _fed(self, journal: Journals.Journal) -> None:
        """A transaction the store committed, a one-transaction journal as its follow gives it, fed: joined to the
        latest, its id the head, and those waiting told; the client's transaction committing given it, where it is
        its own."""
        committing = self._committing
        if committing is not None:
            committing.journal += [t for t in journal if t["id"] in (committing.first, committing.uid)]
        with self._fed_lock:
            joined = Journals.join(self.journal, journal)
            self._dropped = self._dropped or len(joined) > self.window
            self.journal = joined[-self.window:]
            self.head = journal[-1]["id"]
            self._committed.notify_all()

    def _polled(self) -> None:
        """What others committed below the store, given to it, where it is followed by polling and no client's
        transaction is open in it."""
        if self._poll is not None and self._lock.acquire(blocking=False):
            try:
                if self._open is None:
                    self._poll()
            finally:
                self._lock.release()

    def changes(self, after: str | None = None, feed: str | None = None, wait: float = 0.0) -> dict[str, Any]:
        """The change feed, `{"feed", "head", "journal"}`: its transactions after the one of id `after`, or, where
        `feed` is named and `after` is not, from its first, at most `PAGE` of them, a journal as plain data; the head
        alone where neither is named. Where none is after it, held open until one is committed, or `wait` seconds pass.
        Refused (410) where `feed` is another's, `after` is a transaction it does not keep, or it is read from its first
        once it has let one go."""
        deadline = time.monotonic() + min(max(wait, 0.0), WAIT)
        self._polled()
        with self._fed_lock:
            if after is None and feed is None:
                return {"feed": self.feed, "head": self.head, "journal": []}
            if feed is not None and feed != self.feed:
                raise Refused(410, f"the change feed {feed!r} is not this service's, {self.feed!r}: it restarted, and "
                                   "what a store holds may have changed unreported; make the store again")
            if after is None and self._dropped:
                raise Refused(410, f"the change feed keeps only its latest {self.window} transactions, not its first: "
                                   "make the store again")
            self._after(after)
            while self.head == after and (left := deadline - time.monotonic()) > 0:
                self._committed.wait(min(left, 1.0))  # woken by a commit here; polling the store below meanwhile
                self._fed_lock.release()
                try:
                    self._polled()
                finally:
                    self._fed_lock.acquire()
            return {"feed": self.feed, "head": self.head, "journal": self._after(after)[:PAGE]}

    def _after(self, after: str | None) -> Journals.Journal:
        """The transactions the feed keeps after the one of id `after`, from its first where None; refused (410) where
        it keeps none of that id."""
        try:
            return Journals.after(self.journal, after)
        except LookupError as error:
            raise Refused(410, f"the change feed keeps its latest {len(self.journal)} transactions, to "
                               f"{JSON.dumps(self.head)}, not {JSON.dumps(after)}: make the store again") from error

    # --- The store, one use at a time ---

    def _await(self) -> None:
        """Waits, holding the store, until no client's transaction is open in it, up to `WAIT` seconds, else refused
        (503); one idle for `lease` seconds is dropped."""
        deadline = time.monotonic() + WAIT
        while self._open is not None:
            held = self._open
            if time.monotonic() - held.last > self.lease:
                log.warning("a client's transaction left idle for %s seconds is dropped", self.lease)
                self._drop(held, f"left idle for {self.lease} seconds")
                break
            left = min(deadline, held.last + self.lease) - time.monotonic()
            if time.monotonic() >= deadline:
                raise Unavailable(f"another client's transaction holds the store: try again (after {WAIT} seconds)")
            self._free.wait(max(min(left, 1.0), 0.01))

    @contextlib.contextmanager
    def _turn(self) -> Iterator[None]:
        """The store, while no client's transaction is open in it: for an install, the seed or a view."""
        with self._lock:
            self._await()
            yield

    def _drop(self, held: _Open, why: str) -> None:
        """Ends a client's transaction without its commit, nothing written."""
        if self._open is held:
            self._open = None
        error = _Dropped(why)
        try:
            if held.scope is not None:
                held.scope.__exit__(_Dropped, error, None)
        finally:
            self._free.notify_all()

    def _holding(self, transaction: str) -> _Open:
        """The client's transaction of id `transaction`, open; refused (410) where it is not."""
        held = self._open
        if held is None or held.id != transaction:
            raise Refused(410, f"no transaction {transaction!r} is open: it has ended, committed or dropped, or the "
                               f"service restarted; one left idle for {self.lease} seconds is dropped")
        return held

    # --- Installs ---

    @property
    def installs(self) -> list[PlainData]:
        """The install transactions the service was given, in order, each a transaction's expression."""
        return list(self._installs)

    def install(self, install: Install | PlainData) -> list[PlainData]:
        """Runs an install, a callback or its transaction expression, in the store, and serves it after the others
        where it is not among them already; the installs."""
        with self._turn():
            try:
                if isinstance(install, dict):
                    expression = Plain.FromPlain(self.store).Transaction(install)
                else:  # its `when` the service's (CAP-015)
                    when = _iso(self.clock())
                    expression = self.store.Mutations.OfTransaction(
                        lambda t: install(_Named(self.store, t)).when(when))
                plain = JSON.loads(JSON.dumps(Plain.ToPlain(self.store).Transaction(expression)))
                self.store.transaction(expression)
            except REFUSALS as error:
                raise Refused(400, _describe(error)) from error
            if all(JSON.dumps(plain) != JSON.dumps(held) for held in self._installs):
                self._installs.append(plain)
            return self.installs

    def names(self) -> list[str]:
        """Every named schema, by name."""
        with self._lock:
            return list(self.store.names())

    def schemas(self) -> list[PlainData]:
        """[CAP-002: named schema list](mbse:mbse-basis/docs/capabilities/CAP-002.md), while [CAP-003: schema inspector](mbse:mbse-basis/docs/capabilities/CAP-003.md) is blocked: the install transactions the service
        was given, in order, from which a client's store takes every schema by executing each."""
        return self.installs

    def templates(self) -> dict[str, PlainData]:
        """[CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md): each kind's template."""
        with self._turn():
            return {kind: Plain.ToPlain(self.store).Transaction(tx) for kind, tx in Views.templates(self.store).items()}

    # --- A client's transaction ---

    def open(self, session: str | None = None) -> dict[str, Any]:
        """Opens a transaction of the store for a client's, in `session`, once no other is open: `{"transaction",
        "feed", "head"}`, its id, and the change feed's position as it opened, so that a client may read the feed up
        to it before it reads what it holds (the follow mode that catches up)."""
        with self._lock:
            self._await()
            if self._poll is not None:
                self._poll()
            self._open = _Open(session, self.clock(), self.uids())
            with self._fed_lock:
                head = self.head
            return {"transaction": self._open.id, "feed": self.feed, "head": head}

    def exec(self, transaction: str, body: PlainData) -> list[str]:
        """Executes, within the client's transaction of id `transaction`, `body`'s `expression`, a transaction's
        expression, from the subterm its `remainder` names (the whole of it where none), over its input `frames`, each
        a `References.OfFrame` (one, empty, where none are given), writing where `write` (the default): the stream
        `txn.exec` gives, each item as JSON text (`Frames.item`), then `{"end": {}}`. Refused (400) where the store
        refuses what no one frame met, or the body is malformed; the transaction stays open, for the client to abort.
        Where the store fails otherwise, the transaction is dropped (503)."""
        with self._lock:
            held = self._holding(transaction)
            held.last = time.monotonic()
            try:
                if not isinstance(body, dict) or not isinstance(body.get("expression"), dict):
                    raise ValueError("an exec is {\"expression\", \"remainder\", \"frames\", \"write\"}, its expression "
                                     "a transaction's, a JSON object")
                plain = stamp(body["expression"], held.session, self.user, lambda: held.when, lambda: held.uid)
                if held.first is None:
                    held.first = plain.get("uid") if isinstance(plain.get("uid"), str) else None
                if held.scope is None:  # its first: read, then the store's transaction opened
                    expression = Plain.FromPlain(self.store).Transaction(plain)
                    scope = self.store.transaction()
                    held.txn, held.scope = scope.__enter__(), scope
                else:
                    expression = _read(self.store, held.txn, plain)
                subterm = body.get("remainder")
                given = expression if subterm is None else Remainder(expression, Frames.at(subterm))
                inputs = [Frames.read_frame(self.store, frame) for frame in (body.get("frames") or [{}])]
                items = [JSON.dumps(Frames.item(self.store, x)) for x in held.txn.exec(
                    inputs, given, bool(body.get("write", True)))]
            except REFUSALS as error:
                raise Refused(400, _describe(error)) from error
            except Exception as error:  # the store's own, a layer below it for one, whatever it raises
                log.exception("a transaction's exec failed")
                self._drop(held, "its exec failed")
                raise Unavailable(f"the transaction could not be executed, and nothing is written: "
                                  f"{type(error).__name__}: {error}") from error
            finally:
                held.last = time.monotonic()
            return [*items, JSON.dumps(Frames.END)]

    def commit(self, transaction: str) -> dict[str, Any]:
        """Commits the client's transaction of id `transaction`, the layers below the store first: `{"head",
        "journal"}`, the change feed's position once it has, and what the store's follow gave of it, a
        `Changes.Journal` as plain data, empty where it changed nothing. Refused (400) as the store refuses it, or
        unavailable (503) where it fails otherwise: either way, nothing it wrote is kept."""
        with self._lock:
            held = self._holding(transaction)
            self._open, self._committing = None, held
            try:
                if held.scope is not None:
                    held.scope.__exit__(None, None, None)
            except REFUSALS as error:
                raise Refused(400, _describe(error)) from error
            except Exception as error:
                log.exception("a transaction could not be committed")
                raise Unavailable(f"the transaction could not be committed, and nothing is written: "
                                  f"{type(error).__name__}: {error}") from error
            finally:
                self._committing = None
                self._free.notify_all()
            with self._fed_lock:
                return {"head": self.head, "journal": held.journal}

    def abort(self, transaction: str) -> dict[str, Any]:
        """Drops the client's transaction of id `transaction`, nothing written: `{}`."""
        with self._lock:
            self._drop(self._holding(transaction), "aborted by its client")
            return {}

    # --- Logical views ---

    def view(self, kind: str, plain: PlainData, session: str | None = None) -> list[str]:
        """[CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md): the frames a transaction gives, each a `References.OfFrame` filled as `kind` defines, as JSON. A
        transaction that writes is stamped first ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md), `stamp`), in `session`, and refused before it is
        executed where its frames cannot each bind the kind's symbols, since what it writes is committed below first."""
        with self._turn():
            if writes(plain):
                unbound = _unbound(kind, plain)
                if unbound:
                    raise Refused(400, unbound)
            try:
                frames = self.store.transaction(Plain.FromPlain(self.store).Transaction(
                    stamp(plain, session, self.user, self.clock, self.uids)))
            except REFUSALS as error:
                raise Refused(400, _describe(error)) from error
            except Exception as error:  # the store's own, a layer below it for one, whatever it raises
                log.exception("a transaction could not be committed")
                raise Unavailable(f"the transaction could not be committed, and nothing is written: "
                                  f"{type(error).__name__}: {error}") from error
            missing = _missing(kind, frames)
            if missing:
                raise Refused(400, missing)
            out = []
            for frame in frames:
                witnessed = Views.witness(self.store, kind, frame)
                if witnessed is not None:
                    out.append(JSON.ToJSON(self.store)(witnessed.as_schema(), witnessed))
            return out


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


def app(installs: Iterable[Install | PlainData] = (), store: Any = None, seed: Install | None = None, *,
        poll: Callable[[], Any] | None = None, origins: Iterable[str] = (), window: int = WINDOW, user: str = "demo",
        clock: Clock = _now, uids: Uids = _uuid, lease: float = LEASE) -> FastAPI:
    """The FastAPI application over a `Service` of `store` (one in memory where None), which `installs` give their
    schemas and `seed`, where given, its data; `poll`, where given, gives the store what others committed below it. It
    holds the service as `app.state.service`. `origins` are those a browser may call it from (CORS), the UI's: none by
    default."""
    service = Service(installs, store, seed, poll=poll, window=window, user=user, clock=clock, uids=uids, lease=lease)
    api = FastAPI(title="mbse-rest", description="A store served over REST, and logical views over it (mbse-basis "
                                                 "FEA-003: no-code logical views, CAP-290, CAP-308)")
    api.state.service = service
    allowed = list(origins)
    if allowed:
        api.add_middleware(CORSMiddleware, allow_origins=allowed, allow_methods=["GET", "POST", "DELETE"],
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

    @api.get("/schemas/{name}")
    def schema(name: str) -> Any:
        def call() -> Any:
            if name not in service.names():
                return _error(404, f"no schema is named {name!r}")
            return _error(501, UNWRITTEN)
        return answer(call)

    @api.post("/transactions")
    async def open_transaction(request: Request) -> Any:
        return await threaded(lambda: service.open(request.headers.get(SESSION_HEADER)))

    @api.post("/transactions/{transaction}/exec")
    async def exec_transaction(transaction: str, request: Request) -> Any:
        try:
            body = await body_of(request, "an exec, {\"expression\", \"remainder\", \"frames\", \"write\"}")
        except Refused as error:
            return _error(error.status, str(error))
        return await threaded(lambda: StreamingResponse(_lines(service.exec(transaction, body)), media_type=NDJSON))

    @api.post("/transactions/{transaction}/commit")
    async def commit_transaction(transaction: str) -> Any:
        return await threaded(lambda: service.commit(transaction))

    @api.delete("/transactions/{transaction}")
    async def abort_transaction(transaction: str) -> Any:
        return await threaded(lambda: service.abort(transaction))

    @api.get("/changes")
    async def changes(after: str | None = None, feed: str | None = None, wait: float = 0.0) -> Any:
        return await threaded(lambda: service.changes(after, feed, wait))

    @api.get("/views")
    async def templates() -> Any:
        return await threaded(service.templates)

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
    """The store below the service's by name: None for `memory`, the service's store holding what it is written in
    memory; or `module:attribute`, a class or function that makes one when called with no arguments (its own
    configuration is its own, from the environment for instance), a layer below that a `Builders.Store` is stacked on:
    a store, with its `transaction` and its `follow`. `mbse.Persistence.DynamoDB.Store:Store`, mbse-dynamodb's, for
    one."""
    if name.strip().lower() in ("", "memory"):
        return None
    module, _, attribute = name.partition(":")
    if not attribute:
        raise ValueError(f"a store below is 'memory' or 'module:attribute', not {name!r}")
    made = getattr(importlib.import_module(module), attribute)()
    if not all(callable(getattr(type(made), member, None)) for member in ("transaction", "follow")):
        raise TypeError(f"{name} makes no layer below: a store, with its transaction and its follow")
    return made


def fresh(below: Any) -> bool:
    """Whether a store below has committed nothing, so that an app's seed is run in it: one that gives the position of
    the last transaction it committed, its id (`head()`, as mbse-dynamodb's does), where it gives none; one that keeps
    none, as a store in memory, made new with the service, always. A seed is not run again over what it wrote, which may
    have been edited since."""
    head = getattr(type(below), "head", None)  # a method of its class: a store's own attributes are its paths
    return not callable(head) or below.head() is None


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
    - `MBSE_REST_STORE`: the store below the service's, `store_of`'s name (`memory`); the service serves a
      `Builders.Store` over it, polling it where it is followed by polling (`poll()`);
    - `MBSE_REST_WINDOW`: how many of the latest committed transactions the change feed keeps (`10000`);
    - `MBSE_REST_LEASE`: how long a client's transaction is kept open with no request on it, in seconds (`60`);
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
    seed = seed_of(module) if _flag(env.get("MBSE_REST_SEED", "1")) and (below is None or fresh(below)) else None
    origins = [origin.strip() for origin in env.get("MBSE_REST_ORIGINS", "").split(",") if origin.strip()]
    poll = below.poll if below is not None and callable(getattr(type(below), "poll", None)) else None
    return app(installs_of(module), None if below is None else Builders.Store(below), seed, poll=poll, origins=origins,
               window=int(env.get("MBSE_REST_WINDOW", str(WINDOW))), user=env.get("MBSE_REST_USER", "demo"),
               lease=float(env.get("MBSE_REST_LEASE", str(LEASE))))


def work_tracker(store: Any = None, **options: Any) -> FastAPI:
    """The stub server: the service over the demo app's store (mbse-demo-apps, a development dependency), its schemas
    installed and seeded, `store`, one in memory where None."""
    return app(installs_of(WORK_TRACKER), store, seed_of(WORK_TRACKER), **options)
