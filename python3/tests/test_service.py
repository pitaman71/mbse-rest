"""The service: its endpoints (docs/CONTRACT.md), its views (Views) and its persistence (CAP-013)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import Builders, Plain, References

from mbse.Services.Rest import Conformance, Persistence, PersistenceCases, Service, Views


@pytest.fixture
def client():
    return TestClient(Service.work_tracker())


def store_of(client):
    return client.app.state.service.store


def frames(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(Service.NDJSON)
    return [json.loads(line) for line in response.text.splitlines()]


def label_of(frame):
    """The label view's properties of the frame's `x`."""
    [assigned] = [a for a in frame["assigns"] if a["object"] == frame["binds"]["x"]]
    return {name: next(iter(value.values())) for name, value in assigned["properties"].items()}


def test_the_corpus_is_current():
    assert Conformance.check() == []


def test_the_named_schema_list_is_the_schema_snapshot(client):
    """CAP-002, while CAP-003 is blocked: a store reading it holds every named schema the service's store holds."""
    store = Builders.Store()
    Plain.FromPlain(store).Snapshot([client.get("/schemas").json()])
    assert list(store.names()) == list(store_of(client).names())


def test_the_schema_inspector_waits_on_mbse_schemas(client):
    assert client.get("/schemas/work.Project").status_code == 501
    assert client.get("/schemas/work.Nothing").status_code == 404


def test_a_store_reads_the_schemas_a_client_needs():
    served = TestClient(Service.work_tracker()).get("/schemas").json()
    store = Builders.Store()
    Plain.FromPlain(store).Snapshot([served])
    assert list(store.registered("work.Plans").entry.properties) == ["original", "forecast", "completed", "progress"]


def test_templates_one_per_kind_with_unassigned_symbols(client):
    templates = client.get("/views").json()
    assert list(templates) == list(Views.KINDS)
    for kind, template in templates.items():
        [term] = template["mutations"]
        [pattern] = term["map"]["symbols"]
        assert pattern["symbols"] == {name: {} for name in Views.SYMBOLS[kind]}


def test_label_view_of_every_capability(client):
    store = store_of(client)
    body = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Capability})]))])))
    got = [label_of(f) for f in frames(client.post("/views/label", json=body))]
    assert [g["title"] for g in got] == ["No-code index view", "Logical view as chip", "Logical view of object as detail"]
    assert all(set(g) == {"title", "description"} for g in got)


def test_chip_view_falls_back_to_the_first_scalars(client):
    store = store_of(client)
    body = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Comment})]))])))
    [frame] = frames(client.post("/views/chip", json=body))
    assert label_of(frame) == {"text": "Should chips show adjacencies?", "resolved": False}
    assert frame["entries"] == []


def test_detail_view_gives_every_adjacency_and_each_linked_label(client):
    store = store_of(client)
    goal = store.singleton("work.Goals").goals({"id": "GOL-001"})
    body = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": References.of(store, goal)})]))])))
    [frame] = frames(client.post("/views/detail", json=body))
    relations = [e["relation"]["next"]["entry"]["next"]["entry"]["properties"]["name"] for e in frame["entries"]]
    assert relations == ["InGoals", "HasGoal", "Plans", "Plans"]
    titles = [a["properties"].get("title", {}).get("str") for a in frame["assigns"]]
    assert titles == ["Demoable index site", "MVP", "No-code index view", "Logical view as chip"]


def test_adjacency_view_gives_entry_properties_and_chips(client):
    [frame, _] = [json.loads(line) for line in
                  (Conformance.ROOT / "adjacency-goal-capabilities.response.ndjson").read_text().splitlines()]
    [entry] = frame["entries"]
    assert entry["properties"]["progress"] == {"float": 0.25}
    assert label_of({"assigns": frame["assigns"], "binds": {"x": frame["binds"]["y"]}})["title"] == "No-code index view"


def install_notes(txn):
    """A book, a singleton, that lists notes it does not own: each note counted."""
    S = txn.Schemas
    return txn.uid("notes/1").mutations([lambda mu: mu.upsert(lambda u: u.exists([lambda p: p
        .symbols({"Book": S.OfObject, "Note": S.OfObject, "Lists": S.OfRelation})
        .spec([
            lambda _: _.Lists.name("t.Lists").links([lambda t: t.name("book"), lambda t: t.name("note")]),
            lambda _: _.Note.name("t.Note").ref(True).properties({"title": S.OfStr}),
            lambda _: _.Book.name("t.Book").ref(True).singleton("t.TheBook").properties({"title": S.OfStr})
            .adjacencies({"notes": lambda a: a.relation([_.Lists]).me("book")}),
        ])]))])


def test_a_counted_object_is_left_out():
    store = Builders.Store()
    store.transaction(install_notes)
    with store.transaction():
        note = store.t.Note(lambda n: n.title("counted"))
        store.t.Book(store.singleton("t.TheBook"), lambda b: b.title("Book").notes([note]))
    [frame] = store.transaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.t.Note})]))]))
    assert Views.witness(store, "label", frame) is None  # a frame binding a counted object: no reference
    detail = Views.witness(store, "detail", {"x": store.singleton("t.TheBook")})
    plain = Plain.ToPlain(store)(detail.as_schema(), detail)
    assert plain["entries"] == [] and [a["properties"] for a in plain["assigns"]] == [{"title": {"str": "Book"}}]


def test_errors(client):
    assert client.post("/views/summary", json={}).status_code == 404
    assert client.post("/views/label", json={"mutations": "no"}).status_code == 400


@pytest.mark.parametrize("case", PersistenceCases.CASES, ids=lambda case: case.__name__)
def test_persistence_with_the_reference_plugin(case):
    """The cases every plugin must pass (CAP-013), with `Memory`; mbse-dynamodb runs them with its own."""
    case(Persistence.Memory)
