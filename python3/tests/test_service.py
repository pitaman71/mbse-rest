"""The service: its endpoints (mbse-basis CAP-012: logical view endpoints), its views (Views) and its store below (CAP-290)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import Builders, Plain, References

from mbse.Services.Rest import Conformance, Service, Views


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


def installed(installs):
    """A store holding the schemas the install transactions given make, each executed in order."""
    store = Builders.Store()
    for plain in installs:
        store.transaction(Plain.FromPlain(store).Transaction(plain))
    return store


def test_the_named_schema_list_is_the_install_transactions(client):
    """CAP-002, while CAP-003 is blocked, and CAP-290: the install transactions that made the store's schemas, no
    snapshot; a store executing them holds every named schema the service's store holds."""
    installs = client.get("/schemas").json()
    assert isinstance(installs, list) and all("mutations" in plain for plain in installs)
    assert list(installed(installs).names()) == list(store_of(client).names())


def test_the_schema_inspector_waits_on_mbse_schemas(client):
    assert client.get("/schemas/work.Project").status_code == 501
    assert client.get("/schemas/work.Nothing").status_code == 404


def test_a_store_reads_the_schemas_a_client_needs():
    store = installed(TestClient(Service.work_tracker()).get("/schemas").json())
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
    got = frames(client.post("/views/chip", json=body))
    assert [label_of(f) for f in got] == [  # a thread, then its two replies, the second resolving it
        {"text": "Should chips show adjacencies?"},
        {"text": "Not by default: a chip stays small. The inspector lists them.", "resolves_thread": False},
        {"text": "Agreed, *no adjacencies* on chips.", "resolves_thread": True},
    ]
    assert all(f["entries"] == [] for f in got)


def test_detail_view_gives_every_adjacency_and_each_linked_label(client):
    store = store_of(client)
    with store.transaction():
        goal = References.of(store, store.singleton("work.Goals").goals({"id": "GOL-001"}))
    body = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": goal})]))])))
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
    with store.transaction():
        book = References.of(store, store.singleton("t.TheBook"))
    detail = Views.witness(store, "detail", {"x": book})
    plain = Plain.ToPlain(store)(detail.as_schema(), detail)
    assert plain["entries"] == [] and [a["properties"] for a in plain["assigns"]] == [{"title": {"str": "Book"}}]


def test_errors(client):
    assert client.post("/views/summary", json={}).status_code == 404
    assert client.post("/views/label", json={"mutations": "no"}).status_code == 400


def test_an_edit_is_committed_below_and_kept():
    """CAP-014: an edit through the detail view writes the object's properties, gives its detail as the edit left it,
    is committed by the store below, and survives a restart over it; None clears a property."""
    client = TestClient(Service.work_tracker())
    below = client.app.state.service.below
    store = store_of(client)
    body = Conformance._edit(store, lambda s: by_path(s, TSK_1), {"title": "**Bold**", "description": None})
    [frame] = frames(client.post("/views/detail", json=body))
    assert label_of(frame) == {"title": "**Bold**"}
    with below.transaction():
        assert str(below.singleton("work.Tasks").tasks({"id": "TSK-001"}).title) == "**Bold**"
    again = TestClient(Service.app(Service.installs_of(Service.WORK_TRACKER), below))  # not seeded again
    [kept] = frames(again.post("/views/detail", json=Conformance._map(store_of(again), lambda s: {"x": by_path(s, TSK_1)})))
    assert label_of(kept) == {"title": "**Bold**"}


TSK_1 = {"singleton": "work.Tasks", "next": {"entry": {"i": "tasks", "o": "directory", "properties": {"id": "TSK-001"},
                                                       "next": {"target": {}}}}}
CMT_1 = {"singleton": "work.Comments", "next": {"entry": {"i": "comments", "o": "directory",
                                                          "properties": {"id": "CMT-001"}, "next": {"target": {}}}}}


def by_path(store, path):
    """The reference of the object at `path`, in `store`."""
    return Plain.FromPlain(store)(store.References.OfObject.as_schema(), {"path": path})


def test_a_write_after_a_restart_of_an_app_with_a_history():
    """A service over a store below that already holds the write's session, as after a restart, commits it."""
    client = TestClient(Service.work_tracker())
    body = Conformance._edit(store_of(client), lambda s: by_path(s, TSK_1), {"title": "Once"})
    frames(client.post("/views/detail", json=body))  # its session, `demo:default`, now held below
    again = TestClient(Service.app(Service.installs_of(Service.WORK_TRACKER), client.app.state.service.below))
    body = Conformance._edit(store_of(client), lambda s: by_path(s, TSK_1), {"title": "Again"})
    frames(again.post("/views/detail", json=body))


def test_a_proposed_object_is_created_with_its_entry_and_owned():
    """CAP-018: a reply proposed through a thread's replies is made with its entry, placed in its directory (its
    ID given there), committed by the store below, and the thread's detail given back with it."""
    client = TestClient(Service.work_tracker())
    below = client.app.state.service.below
    store = store_of(client)
    body = Conformance._propose(store, lambda s: by_path(s, CMT_1), "replies", "reply", "work.Comment",
                                {"text": "Closing this.", "resolves_thread": True})
    [frame] = frames(client.post("/views/detail", json=body))
    with store.transaction():
        thread = store.singleton("work.Comments").comments({"id": "CMT-001"})
        assert [str(e.reply.text) for e in thread.replies][-1] == "Closing this."
        reply = [e.reply for e in thread.replies][-1]
        assert [str(e.id) for e in reply.directory] == ["CMT-004"]
    assert len(frame["entries"]) > 0
    with below.transaction():
        assert [str(e.reply.text) for e in below.singleton("work.Comments").comments({"id": "CMT-001"}).replies][-1] \
            == "Closing this."


def _stamped_edit():
    """An edit of the thread CMT-001 through a service with a fixed clock and uid, in the session `tab-7`: the store,
    the store below, and the detail frame the edit gave."""
    import datetime
    moment = datetime.datetime(2026, 10, 26, 9, 15, tzinfo=datetime.timezone.utc)
    client = TestClient(Service.work_tracker(user="ada", clock=lambda: moment, uids=lambda: "tx-1"))
    store = store_of(client)
    body = Conformance._edit(store, lambda s: by_path(s, CMT_1), {"text": "Edited."})
    body["session"] = {"locale": "en-GB"}  # the client's part
    [frame] = frames(client.post("/views/detail", json=body, headers={"x-mbse-session": "tab-7"}))
    return store, client.app.state.service.below, frame


def test_a_write_is_stamped_and_its_provenance_is_in_the_detail():
    """CAP-015: the service stamps a write's `when`, uid, session id and identity, keeping the client's locale; the
    detail of a comment carries the record that created it and the one that last wrote it, with their session and
    identity; the store below records the same transaction, found by its uid, not one of its own."""
    _, below, frame = _stamped_edit()
    with below.transaction():
        records = below.singleton("Provenance.Transactions")
        assert [str(e.uid) for e in records.transactions] == ["work.seed/1", "tx-1"]
        record = records.transactions({"uid": "tx-1"})
        [session] = [e.session for e in record.session]
        assert str(record.when) == "2026-10-26T09:15:00Z"
        assert [str(session.locale), [str(e.id) for e in session.directory]] == ["en-GB", ["tab-7"]]
    relations = [e["relation"]["next"]["entry"]["next"]["entry"]["properties"]["name"] for e in frame["entries"]]
    assert {"CreatedBy", "ModifiedBy", "InSession", "Who"} <= set(relations)
    values = [a["properties"] for a in frame["assigns"]]
    assert {"when": {"str": "2026-10-26T09:15:00Z"}} in values  # the edit's record
    assert any(v.get("locale") == {"str": "en-GB"} for v in values)  # its session


def test_a_restart_reads_the_same_records():
    """CAP-015: a restart over the same store below reads the same records from it, on demand."""
    store, below, _ = _stamped_edit()
    replayed = store_of(TestClient(Service.app(Service.installs_of(Service.WORK_TRACKER), below)))

    def uids(store):
        with store.transaction():
            return sorted(str(e.uid) for e in store.singleton("Provenance.Transactions").transactions)
    assert uids(replayed) == uids(store)


def test_stamp_leaves_a_read_as_it_is():
    read = {"mutations": [{"map": {"symbols": [{}]}}]}
    assert Service.stamp(read, "tab-1", "ada") is read
