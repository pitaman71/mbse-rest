"""mbse-rest's client: a store served over REST, which a `Builders.Store` stacks on as on any store below it
(mbse-basis [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290),
as [the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md) states).

`Store(transport)` is an mbse-schemas store (`Builders.Store`) whose store below is the service at the other end of
`transport`, `Http(base)` for one at a URL. Made, it holds the service's schemas, executing the install transactions
that made them (`GET /schemas`); a store above it is made over it, `Builders.Store(Store(...))`, as over a store in
memory:

- `document(path)` gives the object at `path` as a one-transaction document, None where neither it nor the service
  holds one: an object it does not hold is loaded from the service (`POST /documents`), on demand.
- `transaction(...)` interprets a transaction with mbse-schemas' own interpreter, and sends its changes, as plain data,
  to the service before it commits (`POST /transactions`): the service commits them first, and its refusal refuses
  the transaction, raised as the error the service's store raised (`ValueError`, `TypeError` or `LookupError`). An
  install, a transaction that writes schemas, is sent to the service first as it was given (`POST /schemas`), so that
  the service's store, and the store below it, hold the schemas too.
- `Changes.observe(store, observer)` gives `observer` each transaction the service's store committed, in the order it
  committed them, from the service's change feed (`GET /changes`): its own among them, each given once, and others',
  read before each of its transactions, after each, and on `poll()`. Each is applied to the objects it holds first.

Each transaction carries its record's `uid`, `when`, `session` and `where` to the store below, where its expression
gives them (`Stacked`), so that a store below with `Provenance` installed finds the record the store above made rather
than making another.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from mbse.Schemas.Framework import JSON, Builders, Plain

__all__ = ["Transport", "Http", "Stacked", "Store", "ServiceError", "Gone", "Unavailable", "PROVENANCE", "REFUSALS"]

PlainData = Any

Transport = Callable[[str, str, bytes | None], tuple[int, bytes]]
"""How a store reaches the service: `transport(method, path, body)` gives the response's status and body. `path`
starts with `/` and holds its query; `body` is JSON, or None."""

PROVENANCE = ("uid", "when", "session", "where")
"""The members of a transaction's expression its record is made from (mbse-schemas' `Provenance`), carried below."""

REFUSALS = {"ValueError": ValueError, "TypeError": TypeError, "LookupError": LookupError}
"""Each kind of refusal the service reports, by the name its error message begins with, and the error raised for it."""


class ServiceError(RuntimeError):
    """A response the service refused, other than a refusal of a transaction: its status and its `error`."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(f"{status}: {error}")
        self.status, self.error = status, error


class Gone(ServiceError):
    """410: the service's change feed holds no longer what the store last read, or is another's, as after the service
    restarted: what the store holds may have changed unreported, and a store is made again."""


class Unavailable(ServiceError):
    """503: the service's store failed, its store below for one; the transaction is not committed, and may be sent
    again."""


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


class Stacked(Builders.Store):
    """A `Builders.Store` given a store below, which carries to it, with each transaction's changes, the `uid`, `when`,
    `session` and `where` its expression gives, so that a store below with `Provenance` installed records the same
    transaction, found by its `uid`, rather than one of its own."""

    def _carried(self, plain: PlainData) -> PlainData:
        expression = None if self._proposals is None else self._proposals.expression
        if expression is None:  # an imperative scope: no expression, nothing to carry
            return plain
        whole = Plain.ToPlain(self).Transaction(expression)
        return {**{name: whole[name] for name in PROVENANCE if name in whole}, **plain}

    def _send(self, plain: PlainData) -> None:
        super()._send(self._carried(plain))


class _Service:
    """The service, as the store below the client's own objects: it gives an object's document."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def document(self, path: PlainData) -> PlainData:
        return self.store._call("POST", "/documents", path)


class Store(Stacked):
    """A store over the service that `transport` reaches, or the service at the URL `transport`."""

    def __init__(self, transport: Transport | str) -> None:
        super().__init__()
        self._transport = Http(transport) if isinstance(transport, str) else transport
        self._below = _Service(self)  # its own objects load from the service, on demand (CAP-284)
        self._installing = 0  # how deep in executing the service's installs: those are not sent back
        head = self._call("GET", "/changes")
        self._feed, self._seq = head["feed"], head["head"]  # the change feed, and the last change it was given
        self._installing += 1
        try:
            for plain in self._call("GET", "/schemas"):
                Stacked.transaction(self, Plain.FromPlain(self).Transaction(plain))  # Builders.Store's, not its own
        finally:
            self._installing -= 1

    # --- The service ---

    def _call(self, method: str, path: str, body: PlainData = None, sent: bool = False) -> PlainData:
        """The service's answer to a request, read from JSON; a refusal raised: a transaction's as the error its store
        raised, any other as a `ServiceError`."""
        data = None if body is None and not sent else JSON.dumps(body).encode()
        status, answer = self._transport(method, path, data)
        text = answer.decode()
        if status == 200:
            return JSON.loads(text)
        try:
            error = json.loads(text)["error"]
        except (ValueError, KeyError, TypeError):
            error = text
        if status == 400:
            kind, _, message = str(error).partition(": ")
            if kind in REFUSALS:
                raise REFUSALS[kind](message)
        raise {410: Gone, 503: Unavailable}.get(status, ServiceError)(status, str(error))

    def poll(self) -> int:
        """Gives the objects this store holds, and its followers, each transaction the service's store committed since
        it was last given one, in the order it committed them; how many. Within a transaction of this store's, none."""
        if self._proposals is not None or self._loading or self._applying:
            return 0
        count = 0
        while True:
            query = urllib.parse.urlencode({"after": self._seq, "feed": self._feed})
            read = self._call("GET", f"/changes?{query}")
            for change in read["changes"]:
                self._seq = change["position"]
                count += 1
                self._deliver(change["effect"])
            if self._seq >= read["head"]:
                return count

    def _deliver(self, plain: PlainData) -> None:
        """A transaction the service's store committed: applied to the objects present, as a store above applies the
        store below's (CAP-285), and its followers given the whole of it, as committed."""
        observers, self._observers = self._observers, []
        try:
            self._apply(plain)
        finally:
            self._observers = observers
        if observers:
            effect = Plain.FromPlain(self).Transaction(plain)
            for observer in list(observers):
                observer(effect)

    # --- Transactions ---

    def transaction(self, spec: Any = None) -> Any:
        """A transaction (`Builders.Store.transaction`), interpreted once the store has read the service's changes, and
        committed by the service first; its followers are given it from the service's change feed, in order, read
        once it ends."""
        if self._loading or self._applying or self._proposals is not None:  # within one of its own: no other
            return super().transaction(spec)
        self.poll()
        if spec is None:
            return self._block()
        done = super().transaction(spec)
        self.poll()
        return done

    @contextlib.contextmanager
    def _block(self) -> Iterator[None]:
        with super().transaction():
            yield
        self.poll()

    def _settled(self, proposals: Any) -> None:
        """Sends a transaction's schemas, where it writes any, then its changes, to the service; its followers are not
        given it here, but from the service's change feed, in the order the service committed it."""
        writes_schemas = self._held > proposals.existing or bool(proposals.deferred)
        if writes_schemas and not (self._installing or self._applying) and proposals.expression is not None:
            self._call("POST", "/schemas", Plain.ToPlain(self).Transaction(proposals.expression))
        super()._settled(proposals)
        self._changes = None

    def _send(self, plain: PlainData) -> None:
        """A transaction's changes, sent to the service, which commits them first (CAP-285)."""
        self._call("POST", "/transactions", self._carried(plain))
