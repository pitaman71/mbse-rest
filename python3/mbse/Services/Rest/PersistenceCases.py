"""The cases every persistence plugin must pass (CAP-013), for any implementation's tests to run with its own plugin.

Each case takes a function making a fresh, empty plugin, and checks what the service does with it through the
protocol alone (`Persistence.Plugin`: `load`, `journal`, `snapshot`), never a plugin's own attributes:

    import pytest
    from mbse.Services.Rest import PersistenceCases

    @pytest.mark.parametrize("case", PersistenceCases.CASES, ids=lambda case: case.__name__)
    def test_persistence(case):
        case(lambda: MyPlugin(...))

They run the WorkTracker (mbse-demo-apps) through the stub server, so an implementation's tests need it and FastAPI's
test client (httpx2) installed, as mbse-rest's own do.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from mbse.Schemas.Framework import Plain

from . import Persistence, Service

__all__ = ["Counting", "CASES", "journaled_and_replayed", "snapshot_every", "refused_writes_nothing"]


class Counting:
    """A plugin that counts what the service gives the plugin it wraps: how many transactions it journals, and how
    many snapshots it takes."""

    def __init__(self, plugin: Persistence.Plugin) -> None:
        self.plugin, self.journaled, self.snapshots = plugin, 0, 0

    def load(self) -> tuple[list[Persistence.PlainData] | None, list[Persistence.PlainData]]:
        return self.plugin.load()

    def journal(self, transaction: Persistence.PlainData) -> None:
        self.plugin.journal(transaction)
        self.journaled += 1

    def snapshot(self, snapshot: list[Persistence.PlainData]) -> None:
        self.plugin.snapshot(snapshot)
        self.snapshots += 1


def _client(api: Any) -> Any:
    from fastapi.testclient import TestClient  # a development dependency of whoever runs the cases
    return TestClient(api)


def _store(client: Any) -> Any:
    return client.app.state.service.store


def _titles(response: Any) -> list[str]:
    """The `title` each frame's `x` holds, in frame order, from a label view's response."""
    assert response.status_code == 200, response.text
    titles = []
    for line in response.text.splitlines():
        frame = json.loads(line)
        [assigned] = [a for a in frame["assigns"] if a["object"] == frame["binds"]["x"]]
        titles.append(next(iter(assigned["properties"]["title"].values())))
    return titles


def _write_task(store: Any, title: str) -> Any:
    """A transaction that writes: a new task in its directory, bound as the label view's `x`."""
    return Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.upsert(
        lambda u: u.exists([lambda p: p.symbols({"d": store.work.TaskDirectory, "x": store.work.Task}).spec([
            lambda _: _.d.tasks({"TSK-009": lambda e: e.task(_.x)}),
            lambda _: _.x.title(title),
        ])]))])))


def _read_tasks(store: Any) -> Any:
    """A transaction that only reads: every task, as the label view's `x`."""
    return Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Task})]))])))


def journaled_and_replayed(make: Callable[[], Persistence.Plugin]) -> None:
    """First start installs and snapshots; a write is journaled and a read is not; a restart replays them."""
    plugin = Counting(make())
    client = _client(Service.work_tracker(plugin))
    snapshot, journal = plugin.load()
    assert snapshot is not None and journal == [] and plugin.snapshots == 1  # first start: the installs, a snapshot
    assert _titles(client.post("/views/label", json=_write_task(_store(client), "Journal it"))) == ["Journal it"]
    client.post("/views/label", json=_read_tasks(_store(client)))
    assert len(plugin.load()[1]) == 1 and plugin.journaled == 1  # the write journaled; the read not
    again = _client(Service.app([], plugin))  # a restart: the snapshot, then the journal after it
    assert _titles(again.post("/views/label", json=_read_tasks(_store(again)))) == \
        ["Install the schemas", "Seed the demo", "Journal it"]


def snapshot_every(make: Callable[[], Persistence.Plugin]) -> None:
    """With a snapshot after every journaled transaction, `load` gives the latest snapshot and nothing after it."""
    from mbse.Demos.Apps.WorkTracker import Schemas, Seed  # a development dependency, as for the stub server
    plugin = Counting(make())
    client = _client(Service.app([Schemas.install, Seed.seed], plugin, snapshot_every=1))
    client.post("/views/label", json=_write_task(_store(client), "Snapshot it"))
    assert plugin.snapshots == 2
    snapshot, journal = plugin.load()
    assert snapshot is not None and journal == []
    again = _client(Service.app([], plugin))
    assert "Snapshot it" in _titles(again.post("/views/label", json=_read_tasks(_store(again))))


def refused_writes_nothing(make: Callable[[], Persistence.Plugin]) -> None:
    """A refused transaction is never journaled."""
    plugin = Counting(make())
    client = _client(Service.work_tracker(plugin))
    body = _write_task(_store(client), "Refused")
    body["mutations"][0]["upsert"]["exists"][0]["symbols"]["y"] = {}  # a symbol given neither: refused
    assert client.post("/views/label", json=body).status_code == 400
    assert plugin.load()[1] == [] and plugin.journaled == 0


CASES = [journaled_and_replayed, snapshot_every, refused_writes_nothing]
