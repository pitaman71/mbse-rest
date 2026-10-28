"""The endpoints hardened (mbse-basis CAP-012: logical view endpoints, and CAP-013, as built): error bodies and statuses, writes undone where the plugin has not journaled
them, plugin failures, and one transaction at a time."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import Plain

from mbse.Services.Rest import Persistence, Service


class Failing(Persistence.Memory):
    """The reference plugin, whose calls fail on demand."""

    def __init__(self) -> None:
        super().__init__()
        self.fail: set[str] = set()

    def load(self):
        if "load" in self.fail:
            raise ConnectionError("load: the database is unreachable")
        return super().load()

    def journal(self, transaction):
        if "journal" in self.fail:
            raise ConnectionError("journal: the database is unreachable")
        super().journal(transaction)

    def snapshot(self, snapshot):
        if "snapshot" in self.fail:
            raise ConnectionError("snapshot: the database is unreachable")
        super().snapshot(snapshot)


def store_of(client):
    return client.app.state.service.store


def write_task(store, id_, title):
    """A transaction that writes a new task in its directory, then binds it as the label view's `x`."""
    return Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.upsert(
        lambda u: u.exists([lambda p: p.symbols({"d": store.work.TaskDirectory, "x": store.work.Task}).spec([
            lambda _: _.d.tasks({id_: lambda e: e.task(_.x)}), lambda _: _.x.title(title)])]))])))


def titles(client):
    return [str(e.task.title) for e in store_of(client).singleton("work.Tasks").tasks]


def refusal(response, status):
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert list(body) == ["error"] and isinstance(body["error"], str) and body["error"]
    return body["error"]


@pytest.fixture
def client():
    return TestClient(Service.work_tracker())


@pytest.mark.parametrize("body", [b"", b"{bad", b'{"a": 1, "a": 2}', b"NaN", b"3", b'"x"', b"[]", b"null",
                                  b'{"mutations": "no"}', b'{"bogus": 1}', b'{"mutations": [{"update": {"apply": []}}]}'])
def test_a_malformed_transaction_is_a_400(client, body):
    refusal(client.post("/views/label", content=body, headers={"content-type": "application/json"}), 400)


def test_a_transaction_whose_frames_bind_no_symbol_is_a_400(client):
    assert "binds no x" in refusal(client.post("/views/label", json={}), 400)  # one empty frame
    store = store_of(client)
    only_x = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Task})]))])))
    assert "binds no y" in refusal(client.post("/views/adjacency", json=only_x), 400)


def test_a_write_refused_after_it_commits_is_undone():
    plugin = Persistence.Memory()
    client = TestClient(Service.work_tracker(plugin))
    body = write_task(store_of(client), "TSK-009", "Undone")
    assert "undone" in refusal(client.post("/views/adjacency", json=body), 400)  # it binds no y
    assert plugin.entries == [] and "Undone" not in titles(client)


def test_unknown_paths_and_methods_answer_the_error_body(client):
    refusal(client.get("/nothing"), 404)
    refusal(client.post("/views/summary", json={}), 404)
    refusal(client.delete("/views/label"), 405)
    refusal(client.get("/views/label"), 405)
    refusal(client.get("/schemas/work.Project"), 501)
    refusal(client.get("/schemas/work.Nothing"), 404)


def test_a_stream_of_no_frames_is_an_empty_200(client):
    store = store_of(client)
    none = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Task}).spec([lambda _: _.x.title("No such")])]))])))
    response = client.post("/views/label", json=none)
    assert response.status_code == 200 and response.headers["content-type"] == Service.NDJSON
    assert response.text == ""


def test_a_stream_is_one_frame_a_line(client):
    with client.stream("POST", "/views/label", json=write_task(store_of(client), "TSK-009", "Streamed")) as response:
        assert response.status_code == 200
        lines = list(response.iter_lines())
    assert len(lines) == 1 and json.loads(lines[0])["binds"]["x"]


def test_a_journal_that_fails_undoes_the_write_and_answers_503():
    plugin = Failing()
    client = TestClient(Service.work_tracker(plugin))
    plugin.fail = {"journal"}
    assert "undone" in refusal(client.post("/views/label", json=write_task(store_of(client), "TSK-009", "Lost")), 503)
    assert plugin.entries == [] and "Lost" not in titles(client)
    plugin.fail = set()  # the database is back: the service goes on
    assert client.post("/views/label", json=write_task(store_of(client), "TSK-009", "Kept")).status_code == 200
    assert len(plugin.entries) == 1 and titles(client)[-1] == "Kept"


def test_a_plugin_that_cannot_be_read_back_makes_the_service_unavailable():
    plugin = Failing()
    client = TestClient(Service.work_tracker(plugin))
    plugin.fail = {"journal", "load"}
    refusal(client.post("/views/label", json=write_task(store_of(client), "TSK-009", "Lost")), 503)
    plugin.fail = set()
    for response in (client.get("/schemas"), client.get("/views"), client.get("/schemas/work.Task"),
                     client.post("/views/label", json={})):
        assert "read back" in refusal(response, 503)


def test_a_snapshot_that_fails_is_tried_again_and_loses_nothing():
    plugin = Failing()
    client = TestClient(Service.app(Service.installs_of("mbse.Demos.Apps.WorkTracker"), plugin, snapshot_every=1))
    plugin.fail = {"snapshot"}
    assert client.post("/views/label", json=write_task(store_of(client), "TSK-009", "First")).status_code == 200
    assert len(plugin.snapshots) == 1 and len(plugin.entries) == 1  # journaled; no snapshot taken
    plugin.fail = set()
    assert client.post("/views/label", json=write_task(store_of(client), "TSK-010", "Second")).status_code == 200
    assert len(plugin.snapshots) == 2 and plugin.load()[1] == []  # taken after the next one
    again = TestClient(Service.app([], plugin))
    assert titles(again)[-2:] == ["First", "Second"]


def test_a_plugin_that_fails_at_startup_fails_the_start():
    plugin = Failing()
    plugin.fail = {"load"}
    with pytest.raises(ConnectionError):
        Service.work_tracker(plugin)
    plugin.fail = {"snapshot"}
    with pytest.raises(ConnectionError):
        Service.work_tracker(plugin)


def test_a_fault_of_the_services_own_is_a_500_with_the_error_body(client, monkeypatch):
    def broken(*_):
        raise RuntimeError("a bug")
    monkeypatch.setattr(Service.Views, "witness", broken)
    store = store_of(client)
    tasks = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Task})]))])))
    assert "a bug" in refusal(client.post("/views/label", json=tasks), 500)


class Overlapping(Persistence.Memory):
    """A slow journal that notes whether two transactions were ever journaled at once."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = 0
        self.overlapped = False

    def journal(self, transaction):
        self.inside += 1
        self.overlapped |= self.inside > 1
        time.sleep(0.01)
        super().journal(transaction)
        self.inside -= 1


def test_one_transaction_at_a_time():
    plugin = Overlapping()
    client = TestClient(Service.work_tracker(plugin))
    bodies = [write_task(store_of(client), f"TSK-{n:03}", f"Task {n}") for n in range(10, 22)]
    statuses = []

    def post(body):
        statuses.append(client.post("/views/label", json=body).status_code)

    threads = [threading.Thread(target=post, args=(body,)) for body in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert statuses == [200] * len(bodies) and not plugin.overlapped
    assert len(plugin.entries) == len(bodies)
    assert titles(TestClient(Service.app([], plugin))) == titles(client)  # the journal's order is the commit order
