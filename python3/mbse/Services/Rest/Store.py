"""mbse-rest's client: the service as a store below, which a `Builders.Store` stacks on as on any store below it
(mbse-basis [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290),
as [the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md) states), written against mbse-schemas'
public store-below interface alone, `Stores.Below`
([CAP-306: a public store-below interface](mbse:mbse-basis/docs/capabilities/README.md#CAP-306)).

`Remote(transport)` is the service at the other end of `transport`, `Http(base)` for one at a URL, as a store below
(`Stores.Below`):

- `document(path)` gives the object at `path` as a one-transaction document, None where the service holds none
  (`POST /documents`): what a store over it loads, on demand.
- `commit(plain)` sends a transaction's changes, as plain data, to the service (`POST /transactions`), which commits
  them first; its refusal is raised as the error the service's store raised (`ValueError`, `TypeError` or
  `LookupError`). It gives back the transaction as the service's store committed it, its record (`Provenance`) among
  it, which a store over it takes into its own transaction, as it takes what any store below gives back.
- `install(plain)` sends an install, a transaction that writes schemas, to the service (`POST /schemas`), which runs
  it in its store and the store below that; one of the installs the service gave it, run again over it, is not sent
  back.
- `follow(follower)` gives `follower` each transaction the service's store committed, as a `Changes.Journal` of that
  one transaction, as plain data, once each, in the order it committed them, read from its change feed (`GET /changes`)
  after the last it was given, by its id, on `poll()` and after each commit, its own among them.
- `records` is true: the service's lowest store records each transaction, so that a store over it records none.

`Store(transport)`, or `Store(remote)`, is a plain `Builders.Store` over it, given the service's schemas: it runs each
of the install transactions that made them (`GET /schemas`). An app reads and writes it as any store, and gives it its
own installs, which reach the service. `remote.poll()` reads the change feed, so that what others committed reaches
it; a program that reads others' writes before it writes polls first.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from mbse.Schemas.Framework import JSON, Builders

__all__ = ["Transport", "Http", "Remote", "Store", "ServiceError", "Gone", "Unavailable", "REFUSALS"]

PlainData = Any

Transport = Callable[[str, str, bytes | None], tuple[int, bytes]]
"""How a store reaches the service: `transport(method, path, body)` gives the response's status and body. `path`
starts with `/` and holds its query; `body` is JSON, or None."""

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


class Remote:
    """The service that `transport` reaches, or the service at the URL `transport`, as a store below (`Stores.Below`)."""

    records = True
    """The service records each transaction (`Provenance`), in its lowest store: a store over it records none."""

    def __init__(self, transport: Transport | str) -> None:
        self._transport = Http(transport) if isinstance(transport, str) else transport
        self._followers: dict[object, Callable[[PlainData], None]] = {}
        head = self._call("GET", "/changes")
        # the change feed, and the position its followers were given last: the id of a transaction, None for none
        self._feed, self._head = head["feed"], head["head"]
        self.installs: list[PlainData] = self._call("GET", "/schemas")  # those that made the service's schemas, in order
        self._served = 0  # how deep in running the service's own installs over it (`Store`): those are not sent back

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

    # --- Stores.Below ---

    def document(self, path: PlainData) -> PlainData:
        """The document of the object at `path`, None where the service holds none."""
        return self._call("POST", "/documents", path)

    def commit(self, plain: PlainData) -> PlainData:
        """Commits a transaction's changes in the service, refused as its store refuses them; gives back the transaction
        as its store committed it, its record among it, None where it changed nothing. The change feed is read after it,
        its own among what it gives the followers; a failure to read it is left to the next `poll()`, since the
        transaction has committed."""
        committed = self._call("POST", "/transactions", plain)["effect"]
        with contextlib.suppress(ServiceError, OSError):
            self.poll()
        return committed

    def install(self, plain: PlainData) -> None:
        """Runs an install in the service, its store and the store below that, refused as they refuse it; one of the
        service's own installs, run over it as `Store` runs them, is not sent back."""
        if not self._served:
            self.installs = self._call("POST", "/schemas", plain)

    def follow(self, follower: Callable[[PlainData], None]) -> Callable[[], None]:
        """Gives `follower` each transaction the service's store commits from now, once each, in its order, as a
        one-transaction journal, as plain data; gives back a function that ends it."""
        token = object()  # this following, though the same follower follow twice
        self._followers[token] = follower

        def end() -> None:
            self._followers.pop(token, None)

        return end

    # --- The change feed ---

    def poll(self) -> int:
        """Gives the followers each transaction the service's store committed since they were last given one, in the
        order it committed them, each a one-transaction journal, read from the change feed after the last's id; how
        many."""
        count = 0
        while True:
            query = urllib.parse.urlencode({"feed": self._feed, **({} if self._head is None else {"after": self._head})})
            read = self._call("GET", f"/changes?{query}")
            for transaction in read["journal"]:
                self._head = transaction["id"]
                count += 1
                for follower in list(self._followers.values()):
                    follower([transaction])
            if not read["journal"] or self._head == read["head"]:
                return count


def Store(transport: Transport | str | Remote) -> Builders.Store:
    """A store over the service that `transport` reaches, the service at the URL `transport`, or `remote`: a plain
    `Builders.Store` over it, given the service's schemas by running each install that made them."""
    remote = transport if isinstance(transport, Remote) else Remote(transport)
    store = Builders.Store(remote)
    remote._served += 1
    try:
        for plain in remote.installs:
            store.install(plain)
    finally:
        remote._served -= 1
    return store
