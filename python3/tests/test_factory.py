"""The service for any MBSE app (`Service.app`), its installs by convention (`installs_of`), its configuration
(`from_environment`, `plugin_of`) and its entry point (`python -m mbse.Services.Rest`)."""

from __future__ import annotations

import json
import sys
import types

import pytest
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import Builders, Plain, References

from mbse.Demos.Apps.WorkTracker import Schemas, Seed
from mbse.Services.Rest import Persistence, Service


def install(txn):
    """A library: a shelf, a singleton, owning its books by `id`; a book cites books."""
    S = txn.Schemas
    return txn.uid("lib/1").mutations([lambda mu: mu.upsert(lambda u: u.exists([lambda p: p
        .symbols({"Shelf": S.OfObject, "Book": S.OfObject, "OnShelf": S.OfRelation, "Cites": S.OfRelation})
        .spec([
            lambda _: _.OnShelf.name("lib.OnShelf").links([lambda t: t.name("shelf"), lambda t: t.name("book")])
            .properties({"id": S.OfStr}).uniques([["shelf", "id"], ["book"]]),
            lambda _: _.Cites.name("lib.Cites").links([lambda t: t.name("citing"), lambda t: t.name("cited")])
            .properties({"page": S.OfInt}),
            lambda _: _.Shelf.name("lib.Shelf").ref(True).singleton("lib.TheShelf").adjacencies({
                "books": lambda a: a.relation([_.OnShelf]).me("shelf")}),
            lambda _: _.Book.name("lib.Book").ref(True)
            .properties({"name": S.OfStr, "summary": S.OfStr, "pages": S.OfInt, "year": S.OfInt, "isbn": S.OfStr,
                         "language": S.OfStr})
            .adjacencies([
                lambda t: t.name("shelf").relation([_.OnShelf]).me("book").owner(True),
                lambda t: t.name("cites").relation([_.Cites]).me("citing"),
                lambda t: t.relation([_.Cites]).me("cited"),
            ]),
        ])]))])


def seed(txn):
    """Two books on the shelf, the first citing the second."""
    L = txn.lib
    return txn.uid("lib.seed/1").mutations([lambda mu: mu.upsert(lambda u: u.exists([lambda p: p
        .symbols({"shelf": L.Shelf, "sicp": L.Book, "lisp": L.Book})
        .spec([
            lambda _: _.shelf.books({"BK-1": lambda e: e.book(_.sicp), "BK-2": lambda e: e.book(_.lisp)}),
            lambda _: _.sicp.name("SICP").summary("Programs as processes.").pages(657).year(1985).isbn("0262010771")
            .language("en").cites([lambda e: e.cited(_.lisp).page(12)]),
            lambda _: _.lisp.name("LISP 1.5").pages(106),
        ])]))])


@pytest.fixture
def library():
    return TestClient(Service.app([install, seed]))


def frames(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(Service.NDJSON)
    return [json.loads(line) for line in response.text.splitlines()]


def assigned(frame, symbol="x"):
    """The properties the frame assigns the object `symbol` binds, each its value."""
    [found] = [a for a in frame["assigns"] if a["object"] == frame["binds"][symbol]]
    return {name: next(iter(value.values())) for name, value in found["properties"].items()}


def test_another_app_serves_its_schemas(library):
    store = Builders.Store()
    Plain.FromPlain(store).Snapshot([library.get("/schemas").json()])
    assert {"lib.Shelf", "lib.Book", "lib.OnShelf", "lib.Cites"} <= set(store.names())
    assert library.get("/schemas/lib.Book").status_code == 501
    assert library.get("/schemas/work.Task").status_code == 404
    assert list(library.get("/views").json()) == ["label", "chip", "detail", "adjacency"]


def test_another_app_label_and_chip(library):
    store = library.app.state.service.store
    books = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.lib.Book})]))])))
    assert [assigned(f) for f in frames(library.post("/views/label", json=books))] == [
        {"name": "SICP", "summary": "Programs as processes."}, {"name": "LISP 1.5"}]
    chips = [assigned(f) for f in frames(library.post("/views/chip", json=books))]
    assert chips == [{"name": "SICP", "summary": "Programs as processes.", "pages": 657, "year": 1985,
                      "isbn": "0262010771"}, {"name": "LISP 1.5", "pages": 106}]


def test_another_app_detail_and_adjacency(library):
    store = library.app.state.service.store
    sicp = References.of(store, store.singleton("lib.TheShelf").books({"id": "BK-1"}))
    detail = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": sicp})]))])))
    [frame] = frames(library.post("/views/detail", json=detail))
    assert len(frame["entries"]) == 2  # its owning entry, and what it cites
    assert [a["properties"].get("name") for a in frame["assigns"]] == [
        {"str": "SICP"}, {"str": "LISP 1.5"}]  # the shelf holds no property, so nothing is assigned it
    cites = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": sicp, "y": store.lib.Book}).spec([
            lambda _: _.x.cites([_.y])])]))])))
    [frame] = frames(library.post("/views/adjacency", json=cites))
    [entry] = frame["entries"]
    assert entry["properties"] == {"page": {"int": 12}}
    assert assigned(frame, "y") == {"name": "LISP 1.5", "pages": 106}


def test_another_app_writes_and_restarts():
    plugin = Persistence.Memory()
    library = TestClient(Service.app([install, seed], plugin))
    store = library.app.state.service.store
    add = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.upsert(
        lambda u: u.exists([lambda p: p.symbols({"s": store.lib.Shelf, "x": store.lib.Book}).spec([
            lambda _: _.s.books({"BK-3": lambda e: e.book(_.x)}), lambda _: _.x.name("HtDP")])]))])))
    assert [assigned(f) for f in frames(library.post("/views/label", json=add))] == [{"name": "HtDP"}]
    again = TestClient(Service.app([], plugin))  # no installs: the plugin holds the store
    store = again.app.state.service.store
    assert [str(b.book.name) for b in store.singleton("lib.TheShelf").books] == ["SICP", "LISP 1.5", "HtDP"]


def test_an_app_without_a_seed():
    bare = TestClient(Service.app([install]))
    store = bare.app.state.service.store
    books = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.lib.Book})]))])))
    response = bare.post("/views/label", json=books)
    assert response.status_code == 200 and response.text == ""  # no frames: an empty body


def test_installs_by_the_apps_layout(monkeypatch):
    assert Service.installs_of("mbse.Demos.Apps.WorkTracker") == [Schemas.install, Seed.seed]
    assert Service.installs_of("mbse.Demos.Apps.WorkTracker", seed=False) == [Schemas.install]
    package, schemas = types.ModuleType("library"), types.ModuleType("library.Schemas")
    package.__path__ = []  # a package, whose Seed is not found
    schemas.install = install
    monkeypatch.setitem(sys.modules, "library", package)
    monkeypatch.setitem(sys.modules, "library.Schemas", schemas)
    assert Service.installs_of("library") == [install]


class Recorder(Persistence.Memory):
    """A plugin made by name, `module:attribute`."""


def test_plugins_by_name(monkeypatch):
    assert isinstance(Service.plugin_of("memory"), Persistence.Memory)
    assert isinstance(Service.plugin_of(""), Persistence.Memory)
    monkeypatch.setitem(sys.modules, "recorders", types.SimpleNamespace(Recorder=Recorder, Nothing=object))
    assert isinstance(Service.plugin_of("recorders:Recorder"), Recorder)
    with pytest.raises(TypeError, match="no persistence plugin"):
        Service.plugin_of("recorders:Nothing")
    with pytest.raises(ValueError, match="module:attribute"):
        Service.plugin_of("recorders")


def test_from_the_environment():
    api = Service.from_environment({"MBSE_REST_SEED": "0", "MBSE_REST_SNAPSHOT_EVERY": "7",
                                    "MBSE_REST_ORIGINS": "http://localhost:5173, http://ui.example"})
    service = api.state.service
    assert service.installs == [Schemas.install] and service.snapshot_every == 7
    assert isinstance(service.plugin, Persistence.Memory)
    assert list(service.store.singleton("work.Tasks").tasks) == []  # not seeded
    client = TestClient(api)
    preflight = client.options("/views/label", headers={
        "origin": "http://ui.example", "access-control-request-method": "POST",
        "access-control-request-headers": "content-type"})
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://ui.example"
    other = client.get("/views", headers={"origin": "http://elsewhere.example"})
    assert other.status_code == 200 and "access-control-allow-origin" not in other.headers
    with pytest.raises(ValueError):
        Service.from_environment({"MBSE_REST_SEED": "maybe"})


def test_no_origins_no_cors():
    client = TestClient(Service.from_environment({}))
    assert "access-control-allow-origin" not in client.get("/views", headers={"origin": "http://ui.example"}).headers


def test_the_entry_point_serves_from_the_environment(monkeypatch):
    """`python -m mbse.Services.Rest` hands uvicorn the application `from_environment` makes, where the environment
    says. No server runs here: what it would serve is the application the other tests call."""
    from mbse.Services.Rest import __main__ as entry

    served = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda api, **where: served.update(api=api, **where))
    monkeypatch.setenv("MBSE_REST_HOST", "0.0.0.0")
    monkeypatch.setenv("MBSE_REST_PORT", "8123")
    monkeypatch.setenv("MBSE_REST_SEED", "0")
    entry.main()
    assert (served["host"], served["port"]) == ("0.0.0.0", 8123)
    assert served["api"].state.service.installs == [Schemas.install]
    monkeypatch.delenv("MBSE_REST_HOST")
    monkeypatch.delenv("MBSE_REST_PORT")
    entry.main()
    assert (served["host"], served["port"]) == ("127.0.0.1", 8000)
