"""The service for any MBSE app (`Service.app`), its installs and seed by convention (`installs_of`, `seed_of`), its
configuration (`from_environment`, `store_of`) and its entry point (`python -m mbse.Services.Rest`)."""

from __future__ import annotations

import json
import sys
import types

import pytest
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import Builders, Plain, References

from mbse.Demos.Apps.WorkTracker import Schemas, Seed
from mbse.Services.Rest import Service

from library import install, seed


@pytest.fixture
def library():
    return TestClient(Service.app([install], seed=seed))


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
    for plain in library.get("/schemas").json():  # the install transactions that made them
        store.transaction(Plain.FromPlain(store).Transaction(plain))
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
    """What the service writes, its store below holds; a service started again over that store below holds it, loading
    what it is asked for from it, and its seed, run again, writes nothing."""
    library = TestClient(Service.app([install], seed=seed))
    store = library.app.state.service.store
    add = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.upsert(
        lambda u: u.exists([lambda p: p.symbols({"s": store.lib.Shelf, "x": store.lib.Book}).spec([
            lambda _: _.s.books({"BK-3": lambda e: e.book(_.x)}), lambda _: _.x.name("HtDP")])]))])))
    assert [assigned(f) for f in frames(library.post("/views/label", json=add))] == [{"name": "HtDP"}]
    below = library.app.state.service.below
    assert [str(b.book.name) for b in below.singleton("lib.TheShelf").books] == ["SICP", "LISP 1.5", "HtDP"]
    again = TestClient(Service.app([install], below, seed))
    store = again.app.state.service.store
    assert again.get("/changes").json()["head"] == 0  # the seed, run again, wrote nothing
    assert sorted(str(b.book.name) for b in store.singleton("lib.TheShelf").books) == ["HtDP", "LISP 1.5", "SICP"]


def test_an_app_without_a_seed():
    bare = TestClient(Service.app([install]))
    assert Service.seed_of("mbse.Demos.Apps.WorkTracker") is Seed.seed
    store = bare.app.state.service.store
    books = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.lib.Book})]))])))
    response = bare.post("/views/label", json=books)
    assert response.status_code == 200 and response.text == ""  # no frames: an empty body


def test_installs_by_the_apps_layout(monkeypatch):
    assert Service.installs_of("mbse.Demos.Apps.WorkTracker") == list(Schemas.INSTALLS)
    assert Service.seed_of("mbse.Demos.Apps.WorkTracker") is Seed.seed
    package, schemas = types.ModuleType("library_app"), types.ModuleType("library_app.Schemas")
    package.__path__ = []  # a package, whose Seed is not found
    schemas.install = install
    monkeypatch.setitem(sys.modules, "library_app", package)
    monkeypatch.setitem(sys.modules, "library_app.Schemas", schemas)
    assert Service.installs_of("library_app") == [install] and Service.seed_of(package) is None


class Recorder(Builders.Store):
    """A store below made by name, `module:attribute`."""


def test_stores_below_by_name(monkeypatch):
    assert type(Service.store_of("memory")) is Builders.Store
    assert type(Service.store_of("")) is Builders.Store
    monkeypatch.setitem(sys.modules, "recorders", types.SimpleNamespace(Recorder=Recorder, Nothing=object))
    assert isinstance(Service.store_of("recorders:Recorder"), Recorder)
    with pytest.raises(TypeError, match="no store below"):
        Service.store_of("recorders:Nothing")
    with pytest.raises(ValueError, match="module:attribute"):
        Service.store_of("recorders")


@pytest.mark.parametrize("name", ["MBSE_REST_PLUGIN", "MBSE_REST_SNAPSHOT_EVERY"])
def test_the_retired_settings_are_refused(name):
    with pytest.raises(ValueError, match=f"{name} is retired"):
        Service.from_environment({name: "memory"})


def test_from_the_environment():
    api = Service.from_environment({"MBSE_REST_SEED": "0", "MBSE_REST_WINDOW": "7", "MBSE_REST_STORE": "memory",
                                    "MBSE_REST_ORIGINS": "http://localhost:5173, http://ui.example"})
    service = api.state.service
    assert len(service.installs) == len(Schemas.INSTALLS) and service._changes.maxlen == 7
    assert type(service.below) is Builders.Store
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
    assert len(served["api"].state.service.installs) == len(Schemas.INSTALLS)
    monkeypatch.delenv("MBSE_REST_HOST")
    monkeypatch.delenv("MBSE_REST_PORT")
    entry.main()
    assert (served["host"], served["port"]) == ("127.0.0.1", 8000)
