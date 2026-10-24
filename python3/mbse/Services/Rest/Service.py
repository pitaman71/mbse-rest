"""The REST service over an mbse-schemas store (VISUALIZATION.md, CAP-002 to CAP-004, CAP-012 and CAP-013).

`app(installs, plugin)` gives a FastAPI application holding one store in memory: at startup it replays what the
persistence plugin holds, or, where it holds nothing, runs each install (an app's `Schemas.install`, then its
`Seed.seed`) and gives the plugin a snapshot of what they wrote. The endpoints are `docs/CONTRACT.md`'s:

| Method and path | Capability | Response |
|---|---|---|
| `GET /schemas` | CAP-002 | the store's schema snapshot, the first transaction of its snapshot, while CAP-003 is blocked |
| `GET /schemas/{name}` | CAP-003 | 501 until mbse-schemas writes one schema object as a document (CONTRACT.md) |
| `GET /views` | CAP-004 | `{kind: template, ...}`, each a transaction's expression |
| `POST /views/{kind}` | CAP-012 | the frames, `References.OfFrame`, one JSON document a line (NDJSON) |

A view's request is a transaction's expression (`Plain.ToPlain(store).Transaction`). The service reads it
(`Plain.FromPlain(store).Transaction`), executes it, journals it if it writes, and fills each frame's `assigns` and
`entries` as the kind defines (`Views.witness`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse, Response

from mbse.Schemas.Framework import JSON, Builders, Plain

from . import Views
from .Persistence import Memory, Plugin, PlainData, replay

__all__ = ["NDJSON", "Service", "app", "writes"]

NDJSON = "application/x-ndjson"
UNWRITTEN = ("mbse-schemas writes no schema object as a document of its own: Plain.ToPlain(store).OfObject refuses "
             "one, owned through an anonymous adjacency (docs/CONTRACT.md, CAP-003)")


def writes(plain: PlainData) -> bool:
    """Whether a transaction's expression has a term that writes, an upsert or an update, so that it is journaled."""
    if isinstance(plain, dict):
        return "upsert" in plain or "update" in plain or any(writes(v) for v in plain.values())
    if isinstance(plain, list):
        return any(writes(v) for v in plain)
    return False


class Service:
    """One store, held in memory, and its persistence: what the endpoints call, apart from HTTP."""

    def __init__(self, installs: Iterable[Callable[[Any], Any]] = (), plugin: Plugin | None = None,
                 snapshot_every: int = 100) -> None:
        self.store = Builders.Store()
        self.plugin = plugin if plugin is not None else Memory()
        self.snapshot_every = snapshot_every
        self._journaled = 0  # transactions journaled since the latest snapshot
        self._lock = threading.Lock()  # one transaction at a time: transactions on one store do not nest
        if not replay(self.store, self.plugin):
            for install in installs:  # db initialization by schema: the installs, then a snapshot of what they wrote
                self.store.transaction(install)
            self.plugin.snapshot(Plain.ToPlain(self.store).Snapshot())

    def _commit(self, plain: PlainData) -> list[dict[str, Any]]:
        """Executes a transaction's expression; journals it, where it writes, once it commits."""
        frames = self.store.transaction(Plain.FromPlain(self.store).Transaction(plain))
        if writes(plain):
            self.plugin.journal(plain)
            self._journaled += 1
            if self._journaled >= self.snapshot_every:
                self.plugin.snapshot(Plain.ToPlain(self.store).Snapshot())
                self._journaled = 0
        return frames

    def names(self) -> list[str]:
        """Every named schema, by name."""
        return list(self.store.names())

    def schemas(self) -> PlainData:
        """CAP-002, while CAP-003 is blocked: the store's schemas, the first transaction of its snapshot, from which a
        client's store takes every schema."""
        with self._lock:
            return Plain.ToPlain(self.store).Snapshot()[0]

    def templates(self) -> dict[str, PlainData]:
        """CAP-004: each kind's template."""
        return {kind: Plain.ToPlain(self.store).Transaction(tx) for kind, tx in Views.templates(self.store).items()}

    def view(self, kind: str, plain: PlainData) -> list[str]:
        """CAP-012: the frames a transaction gives, each a `References.OfFrame` filled as `kind` defines, as JSON."""
        with self._lock:
            frames = self._commit(plain)
            out = []
            for frame in frames:
                witnessed = Views.witness(self.store, kind, frame)
                if witnessed is not None:
                    out.append(JSON.ToJSON(self.store)(witnessed.as_schema(), witnessed))
            return out


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def app(installs: Iterable[Callable[[Any], Any]] = (), plugin: Plugin | None = None,
        snapshot_every: int = 100) -> FastAPI:
    """The FastAPI application over a `Service`, which it holds as `app.state.service`."""
    service = Service(installs, plugin, snapshot_every)
    api = FastAPI(title="mbse-rest", description="Logical views over an mbse-schemas store (docs/CONTRACT.md)")
    api.state.service = service

    @api.get("/schemas")
    def schemas() -> Any:
        return service.schemas()

    @api.get("/schemas/{name}")
    def schema(name: str) -> Any:
        if name not in service.names():
            return _error(404, f"no schema is named {name!r}")
        return _error(501, UNWRITTEN)

    @api.get("/views")
    def templates() -> Any:
        return service.templates()

    @api.post("/views/{kind}")
    def view(kind: str, body: Any = Body(...)) -> Any:
        if kind not in Views.KINDS:
            return _error(404, f"no logical view kind is named {kind!r}: one of {', '.join(Views.KINDS)}")
        try:
            lines = service.view(kind, body)
        except (ValueError, TypeError, LookupError, KeyError) as error:  # DecodeError is a ValueError
            return _error(400, f"{type(error).__name__}: {error}")
        return Response("".join(line + "\n" for line in lines), media_type=NDJSON)

    return api


def work_tracker(plugin: Plugin | None = None) -> FastAPI:
    """The stub server: the service over the demo app's store (mbse-demo-apps, a development dependency), its schemas
    installed and seeded."""
    from mbse.Demos.Apps.WorkTracker import Schemas, Seed

    return app([Schemas.install, Seed.seed], plugin)

