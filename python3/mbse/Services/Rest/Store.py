"""mbse-rest's client: the service as a layer below, which a `Builders.Store` stacks on as on any layer below it, a
cache layer (mbse-basis [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290),
[CAP-308: stacking by mutation transactions, in one round trip](mbse:mbse-basis/docs/capabilities/README.md#CAP-308), as
[the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md#a-cache-layer-and-the-layer-below), its third stage, states),
written against mbse-schemas' public interface alone
([CAP-306: a public store-below interface](mbse:mbse-basis/docs/capabilities/README.md#CAP-306)).

`Remote(transport)` is the service at the other end of `transport`, `Http(base)` for one at a URL: a store, a
`Builders.Store` holding the schemas alone, whose transaction is one of the service's store, held open by the service
for as long as its own (`Service`'s request sequence):

- `transaction()` opens one (`POST /transactions`); its `exec(frame, remainder, allow_write, terminal)` is a request
  (`POST /transactions/{id}/exec`) carrying the expression, the subterm the remainder starts at, the input frames and
  whether terminal frames are asked for, answered with the stream of frames, each its journal, read back as a frame of
  this store's (`item_of`), its remainder a position in the expression given; the scope's end commits it (`POST /transactions/{id}/commit`), a refusal raised as the error
  the service's store raised (`ValueError`, `TypeError` or `LookupError`), or, where it raises, drops it
  (`DELETE /transactions/{id}`). What the service's follow gave of it as it committed is given to this store's
  followers within the commit, so that a cache layer over it takes it into its own transaction; where the change feed
  was read to just before it, the feed's position moves past it, else the feed gives it again, in its place among
  others', where applying it again changes nothing.
- An install, an expression binding a symbol of a meta-schema, executed from its root term, is run in this store too,
  within a transaction of its own that commits after the service's, so that it holds the schemas of the stores above
  it: an install a cache layer over it runs reaches it, and the service, first.
- `follow(follower)` gives `follower` each transaction the service's store committed, as a `Changes.Journal` of that
  one transaction, as plain data, once each, in the order it committed them, read from its change feed
  (`GET /changes`) after the last it was given, by its id, on `poll()`.

`Store(transport, follow=CATCH_UP)` is a cache layer over it, a `Builders.Store` given it as its layer below, holding
the schemas of the installs the service was given (`GET /schemas`), each run in it, and so through it. What others
commit reaches it by the follow, in a mode chosen where it is made (mbse-basis
[QUA-017: distributed or local, decided at runtime](mbse:mbse-basis/docs/QUALITIES.md#QUA-017)): `CATCH_UP`, the
default, reads the change feed to its head before each transaction, so that the cache layer reads what it holds as of
then; `POLLED` reads it when the program calls `poll()`, and reads what it holds a poll behind.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import re

from mbse.Schemas.Framework import JSON, Builders, Errors, Plain, References
from mbse.Schemas.Framework.Transactions import Frame, FrameError, Remainder

__all__ = ["Transport", "Http", "Remote", "Store", "Transaction", "ServiceError", "Gone", "Unavailable", "REFUSALS",
           "CATCH_UP", "POLLED", "item", "end", "frame_of", "item_of", "at"]

PlainData = Any

Transport = Callable[[str, str, bytes | None], tuple[int, bytes]]
"""How a store reaches the service: `transport(method, path, body)` gives the response's status and body. `path`
starts with `/` and holds its query; `body` is JSON, or None."""

REFUSALS = {"ValueError": ValueError, "TypeError": TypeError, "LookupError": LookupError}
"""Each kind of refusal the service reports, by the name its error message begins with, and the error raised for it."""

CATCH_UP = "catch-up"
"""The follow mode that reads the change feed to its head before each transaction of the cache layer: the default."""

POLLED = "polled"
"""The follow mode that reads the change feed on `poll()` alone, the cache layer reading what it holds a poll behind."""


# --- A frame stream, as mbse-schemas writes and reads its values ---
#
# Each item of a stream is a `References.OfItem` value, written and read by mbse-schemas' own `JSON`, one a line: no
# format of mbse-rest's own (mbse-basis [PRI-018: no model needs code to read or write](mbse:mbse-basis/docs/PRINCIPLES.md#PRI-018),
# [PRI-024: the plain form, carried as written](mbse:mbse-basis/docs/PRINCIPLES.md#PRI-024)). What a frame is made of
# in a process, a `Transactions.Frame`, is read from its value through the visitors: mbse-schemas gives `References.of`,
# a frame's value, and no function giving the frame of a value (reported as a gap of mbse-schemas 0.38.0); nor one
# reading a subterm, `$.mutations[0].map`, as the position a `Transactions.Remainder` holds, which `at` does.


def item(store: Any, given: Any) -> Any:
    """An item of a frame stream `txn.exec` gave, a frame or a completion marker, as a `References.OfItem` value."""
    reference = References.of(store, given)
    return store.References.OfItem(lambda u: u.frame(reference) if isinstance(given, Frame) else u.end(reference))


def end(store: Any) -> Any:
    """The completion marker of a whole stream, `{"end": None}`, as a `References.OfItem` value: a stream's last item."""
    return item(store, {"end": None})


_STEP = re.compile(r'\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\[("(?:[^"\\]|\\.)*")\]')


def at(subterm: str) -> tuple[str | int, ...]:
    """The position a subterm names, `$.mutations[0].map.then[0].update`, as `Transactions.Remainder` holds it, the
    inverse of mbse-schemas' `Errors.path`; refused (`ValueError`) where it is no subterm."""
    steps: list[str | int] = []
    rest = subterm[1:] if subterm.startswith("$") else None
    while rest:
        match = _STEP.match(rest)
        if match is None:
            break
        name, index, quoted = match.groups()
        steps.append(name if name is not None else int(index) if index is not None else json.loads(quoted))
        rest = rest[match.end():]
    if rest is None or rest or Errors.path(*steps) != subterm:
        raise ValueError(f"not a subterm: {subterm!r}")
    return tuple(steps)


def _object(member: Any) -> Any:
    """The value object a member or an element holds, as its visitor; None where it holds none."""
    found: list[Any] = []
    member.as_object(lambda o: found.append(o) or o)
    return found[0] if found and found[0].as_schema() is not None else None


def _elements(member: Any) -> list[tuple[Any, Any]]:
    """The elements of the container a member holds, each with its index, in order; none where it holds none (a visitor
    of nothing has no schema)."""
    found: list[tuple[Any, Any]] = []

    def entries(c: Any) -> Any:
        if c.as_schema() is not None:
            c.as_entries(found.extend)
        return c
    member.as_value(lambda a: a.as_container(entries) or a)
    return found


def frame_of(store: Any, value: Any, transaction: Any = None, given: bool = False) -> Frame:
    """The frame a `References.OfFrame` value of `store`'s is, read through its visitors: its bindings, its journal's
    symbols, each by its reference; its errors, each raised as its kind names it (`REFUSALS`, else `RuntimeError`);
    its scope; whether it is terminal; its journal, but where it is `given` to `txn.exec`, as a layer above gives one;
    and, where `transaction` is the expression it was executed over, its remainder in it."""
    journal = _object(value.journal)
    bound = {} if journal is None else {
        name: _object(_object(symbol).reference) for name, symbol in _elements(journal.symbols)}
    errors = []
    for _, element in _elements(value.errors):
        error = _object(element)
        kind, message = error.kind.get() or "RuntimeError", error.message.get() or ""
        errors.append(FrameError(error.subterm.get() or "$", kind, message, REFUSALS.get(kind, RuntimeError)(message)))
    remainder = value.remainder.get()
    return Frame(bound, errors, None if remainder is None or transaction is None else Remainder(transaction, at(remainder)),
                 value.scope.get(), None if given else journal, bool(value.terminal.get()))


def item_of(store: Any, value: Any, transaction: Any) -> Frame | dict[str, Any]:
    """What a `References.OfItem` value of `store`'s is, as `txn.exec` gives it in a process: a frame (`frame_of`), or
    the completion marker `{"end": scope}`."""
    held = value.frame
    if held.as_schema() is not None:
        return frame_of(store, held, transaction)
    return {"end": value.end.scope.get()}


class ServiceError(RuntimeError):
    """A response the service refused, other than a refusal of a transaction: its status and its `error`."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(f"{status}: {error}")
        self.status, self.error = status, error


class Gone(ServiceError):
    """410: what the store last read is no longer there: the service's change feed no longer holds it, or is another's,
    as after the service restarted, and a store is made again; or the transaction it names has ended, dropped."""


class Unavailable(ServiceError):
    """503: the service's store failed, a layer below it for one, or another client's transaction held it too long;
    the transaction is not committed, and may be run again."""


def Http(base: str, headers: Mapping[str, str] | None = None, timeout: float = 60.0) -> Transport:
    """A transport to the service at `base` (`http://localhost:8000`), through the standard library, sending `headers`
    with each request besides `content-type` (the session's, `x-mbse-session`, for one)."""
    root = base.rstrip("/")

    def send(method: str, path: str, body: bytes | None) -> tuple[int, bytes]:
        request = urllib.request.Request(root + path, data=body, method=method,
                                         headers={**(headers or {}), "content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    return send


class _Connection:
    """The service a `Remote` reaches: its transport, the change feed's name, the position its followers were given
    last, and its followers."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.followers: dict[object, Callable[[PlainData], None]] = {}
        self.polling = False
        head = self.call("GET", "/changes")
        self.feed, self.head = head["feed"], head["head"]

    def send(self, method: str, path: str, body: PlainData = None) -> str:
        """The service's answer to a request, as text; a refusal raised: a transaction's as the error its store raised,
        any other as a `ServiceError`."""
        data = None if body is None else JSON.dumps(body).encode()
        status, answer = self.transport(method, path, data)
        text = answer.decode()
        if status == 200:
            return text
        try:
            error = json.loads(text)["error"]
        except (ValueError, KeyError, TypeError):
            error = text
        if status == 400:
            kind, _, message = str(error).partition(": ")
            if kind in REFUSALS:
                raise REFUSALS[kind](message)
        raise {410: Gone, 503: Unavailable}.get(status, ServiceError)(status, str(error))

    def call(self, method: str, path: str, body: PlainData = None) -> PlainData:
        return JSON.loads(self.send(method, path, body))

    def give(self, journal: PlainData) -> None:
        for follower in list(self.followers.values()):
            follower(journal)

    def poll(self, until: str | None = None) -> int:
        """Gives the followers each transaction the service's store committed since they were last given one, in the
        order it committed them, each a one-transaction journal, read from the change feed after the last's id, to its
        head; how many. A read while it reads, as a follower's own transaction reads, reads nothing."""
        if self.polling:
            return 0
        self.polling = True
        try:
            count = 0
            while True:
                query = urllib.parse.urlencode({"feed": self.feed, **({} if self.head is None else {"after": self.head})})
                read = self.call("GET", f"/changes?{query}")
                for transaction in read["journal"]:
                    self.head = transaction["id"]
                    count += 1
                    self.give([transaction])
                if not read["journal"] or self.head == read["head"]:
                    return count
        finally:
            self.polling = False


def _meta(remote: Remote, plain: PlainData) -> bool:
    """Whether a symbol, as an expression's wire form writes it, is of a meta-schema: its objects are schema objects,
    the schema one the store was made holding in the module `Schemas`."""
    schema = plain.get("schema") if isinstance(plain, Mapping) else None
    for reference in schema if isinstance(schema, list) else [schema]:
        path = reference.get("path") if isinstance(reference, Mapping) else None
        held = remote.held(path) if isinstance(path, Mapping) and path.get("singleton") == "." else None
        if held is not None and remote.framework(held) and remote.name_of(held).startswith("Schemas."):
            return True
    return False


def _installs(remote: Remote, plain: PlainData) -> bool:
    """Whether an expression, as the wire carries it, is an install: an upsert or an update of it binds a symbol of a
    meta-schema, as a cache layer finds one."""
    if isinstance(plain, Mapping):
        for verb, patterns in (("upsert", "exists"), ("update", "apply")):
            body = plain.get(verb)
            if isinstance(body, Mapping) and any(
                    _meta(remote, symbol) for pattern in body.get(patterns) or [] if isinstance(pattern, Mapping)
                    for symbol in (pattern.get("symbols") or {}).values()):
                return True
        return any(_installs(remote, value) for value in plain.values())
    if isinstance(plain, list):
        return any(_installs(remote, value) for value in plain)
    return False


class Transaction:
    """A transaction of the service's store, open for one of this store's: what a cache layer over the store is given
    by `transaction()`. It lives as long as its scope, within this store's own transaction, `local`, which runs the
    installs it is given and commits after the service's."""

    def __init__(self, remote: Remote, id: str, local: Any) -> None:
        self._remote, self.id, self._local = remote, id, local
        self.ended = False

    def exec(self, frame: Any, remainder: Any, allow_write: bool, terminal: bool = False) -> Iterator[Any]:
        """Executes the suffix of a transaction's expression over input frames within the service's transaction, as
        `Transactions.Transaction.exec` does in a process: `frame`, a frame or a stream of them; `remainder`, a
        `Transactions.Remainder` or a whole transaction's expression, of this store's; terminal frames given where
        `terminal`, as a cache layer above asks for them. Gives the stream the service gave, each item read as this
        store's, each frame its journal, a frame's remainder a position in the same expression; an error of no one
        frame raised as the service's store raised it."""
        if self.ended:
            raise ValueError("a transaction's exec runs within it: this one has ended (store.transaction)")
        remote = self._remote
        expression = remainder.transaction if isinstance(remainder, Remainder) else remainder
        plain = Plain.ToPlain(remote).Transaction(expression)
        inputs = [frame] if isinstance(frame, Mapping) else list(frame)
        if (not isinstance(remainder, Remainder) or len(remainder.at) <= 3) and _installs(remote, plain):
            made = [item for item in self._local.exec(inputs, expression, allow_write) if isinstance(item, Frame)]
            failed = next((each for each in made if each.errors), None)
            if failed is not None and failed.errors[0].error is not None:
                raise failed.errors[0].error
        OfFrame, OfItem = remote.registered("References.OfFrame"), remote.registered("References.OfItem")
        body = {"expression": plain, "frames": [Plain.ToPlain(remote)(OfFrame, References.of(remote, given))
                                                for given in inputs], "write": allow_write, "terminal": terminal}
        if isinstance(remainder, Remainder):
            body["remainder"] = remainder.subterm
        text = remote._rest.send("POST", f"/transactions/{self.id}/exec", body)
        items = [item_of(remote, JSON.FromJSON(remote)(OfItem, line), expression)
                 for line in text.splitlines() if line.strip()]
        if not items or items[-1] != {"end": None}:
            raise Unavailable(503, "the service's stream ended before its completion marker: nothing it gave is whole")
        return iter(items[:-1])

    def commit(self) -> None:
        """Commits the service's transaction; what the service's follow gave of it given to the followers. A refusal
        raised, as the service's store raised it, nothing committed."""
        self.ended = True
        rest = self._remote._rest
        committed = rest.call("POST", f"/transactions/{self.id}/commit")
        if committed["journal"]:
            rest.give(committed["journal"])
            if committed.get("after") == rest.head:  # read to just before it: the feed holds nothing else to it
                rest.head = committed["journal"][-1]["id"]

    def abort(self) -> None:
        """Drops the service's transaction; a failure to reach the service is left to it, which drops one left idle."""
        self.ended = True
        with contextlib.suppress(ServiceError, OSError):
            self._remote._rest.call("DELETE", f"/transactions/{self.id}")


class Remote(Builders.Store):
    """The service that `transport` reaches, or the service at the URL `transport`, as a layer below: a store holding
    the schemas alone, whose transaction is the service's."""

    def __init__(self, transport: Transport | str) -> None:
        super().__init__()
        self._rest = _Connection(Http(transport) if isinstance(transport, str) else transport)

    def transaction(self, spec: Any = None) -> Any:
        """With no `spec`, the scope of a transaction of the service's store, giving it (`Transaction`): committed where
        the scope ends, dropped where it raises; this store's own transaction, which runs the installs it is given,
        commits after it. With a transaction's expression, it executed over one empty frame,
        writing, within one, its frames given back; the first error annotated on one raised."""
        if spec is None:
            return self._opened()
        with self._opened() as txn:
            frames = [item for item in txn.exec(Frame(), spec, True) if isinstance(item, Frame)]
            failed = next((frame for frame in frames if frame.errors), None)
            if failed is not None:
                raise failed.errors[0].error or RuntimeError(failed.errors[0].message)
        return frames

    @contextlib.contextmanager
    def _opened(self) -> Iterator[Transaction]:
        with Builders.Store.transaction(self) as local:  # this store's own: the installs it is given, committed after
            opened = self._rest.call("POST", "/transactions")
            txn = Transaction(self, opened["transaction"], local)
            try:
                yield txn
            except BaseException:
                txn.abort()
                raise
            txn.commit()

    def follow(self, follower: Callable[[PlainData], None]) -> Callable[[], None]:
        """Gives `follower` each transaction the service's store commits from now, once each, in its order, as a
        one-transaction journal, as plain data, read from the change feed; gives back a function that ends it."""
        token = object()  # this following, though the same follower follow twice
        self._rest.followers[token] = follower

        def end() -> None:
            self._rest.followers.pop(token, None)

        return end

    def poll(self) -> int:
        """Gives the followers each transaction the service's store committed since they were last given one, to the
        change feed's head; how many."""
        return self._rest.poll()

    def position(self) -> str | None:
        """The change feed's position its followers were given last: a transaction's id, None for none."""
        return self._rest.head


class _Cached(Builders.Store):
    """A cache layer over the service (`Store`), which reads the change feed to its head before each transaction, in
    the follow mode `CATCH_UP`."""

    def __init__(self, remote: Remote, mode: str) -> None:
        super().__init__(remote)
        self._rest_remote, self._rest_mode = remote, mode

    def transaction(self, spec: Any = None) -> Any:
        if self._rest_mode == CATCH_UP:
            self._rest_remote.poll()
        return super().transaction(spec)


def Store(transport: Transport | str | Remote, follow: str = CATCH_UP) -> Builders.Store:
    """A cache layer over the service that `transport` reaches, the service at the URL `transport`, or `remote`: a
    `Builders.Store` over it, given the service's schemas by running each install it was given, which reaches it
    through the layer below, as any install does. `follow` is the mode in which what others commit reaches it:
    `CATCH_UP`, before each transaction, or `POLLED`, on `poll()`."""
    if follow not in (CATCH_UP, POLLED):
        raise ValueError(f"a follow mode is {CATCH_UP!r} or {POLLED!r}, not {follow!r}")
    remote = transport if isinstance(transport, Remote) else Remote(transport)
    store = _Cached(remote, follow)
    for plain in remote._rest.call("GET", "/schemas"):
        store.transaction(Plain.FromPlain(store).Transaction(plain))
    return store
