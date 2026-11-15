"""The endpoints hardened (mbse-basis CAP-012: logical view endpoints, and CAP-290): error bodies and statuses, nothing
written where the store below refuses or fails, and one transaction at a time."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import Builders, Plain

from mbse.Services.Rest import Service


class Failing(Builders.Store):
    """A store below in memory, whose transactions fail on demand, as a database's that cannot be reached."""

    def __init__(self) -> None:
        super().__init__()
        self.failing = False

    def transaction(self, spec=None):
        if self.failing:
            raise ConnectionError("the database is unreachable")
        return super().transaction(spec)


def store_of(client):
    return client.app.state.service.store


def write_task(store, id_, title):
    """A transaction that writes a new task in its directory, then binds it as the label view's `x`."""
    return Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.upsert(
        lambda u: u.exists([lambda p: p.symbols({"d": store.work.TaskDirectory, "x": store.work.Task}).spec([
            lambda _: _.d.tasks({id_: lambda e: e.task(_.x)}), lambda _: _.x.title(title)])]))])))


def titles(client):
    return [str(e.task.title) for e in store_of(client).singleton("work.Tasks").tasks]


def held_below(client):
    """The titles of the tasks the store below holds."""
    return [str(e.task.title) for e in client.app.state.service.below.singleton("work.Tasks").tasks]


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


def test_a_write_whose_frames_bind_no_symbol_is_refused_before_it_is_written():
    client = TestClient(Service.work_tracker())
    body = write_task(store_of(client), "TSK-009", "Unwritten")
    assert "binds no y" in refusal(client.post("/views/adjacency", json=body), 400)  # it binds no y
    assert "Unwritten" not in titles(client) and "Unwritten" not in held_below(client)
    assert client.get("/changes").json()["head"] == 2  # the seed's alone, then its record, from the store below


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


def test_a_store_below_that_fails_writes_nothing_and_answers_503():
    below = Failing()
    client = TestClient(Service.work_tracker(below))
    below.failing = True
    assert "nothing is written" in refusal(
        client.post("/views/label", json=write_task(store_of(client), "TSK-009", "Lost")), 503)
    assert "nothing is written" in refusal(
        client.post("/transactions", json=write_task(store_of(client), "TSK-009", "Lost")), 503)
    assert "Lost" not in titles(client) and "Lost" not in held_below(client)
    below.failing = False  # the database is back: the service goes on
    assert client.post("/views/label", json=write_task(store_of(client), "TSK-009", "Kept")).status_code == 200
    assert titles(client)[-1] == "Kept" and held_below(client)[-1] == "Kept"


def test_a_store_below_that_fails_at_startup_fails_the_start():
    below = Failing()
    below.failing = True
    with pytest.raises(ConnectionError):
        Service.work_tracker(below)


def test_a_store_below_that_refuses_refuses_the_transaction():
    """What the store below refuses, the service refuses, as the kind of error it is, and writes nothing."""
    client = TestClient(Service.work_tracker())
    store = store_of(client)
    body = write_task(store, "TSK-009", "Doubled")
    below = client.app.state.service.below
    with below.transaction():  # another writes TSK-009 below, not yet seen above
        below.work.Task(lambda t: t.directory(lambda a: a.insert(lambda e: e.id("TSK-009").directory(
            below.singleton("work.Tasks")))).title("Theirs"))
    response = client.post("/transactions", json=body)
    assert response.status_code in (200, 400)  # an upsert finds theirs, or is refused: never two by one key
    assert [t for t in held_below(client) if t in ("Theirs", "Doubled")] in (["Theirs"], ["Doubled"])


def test_a_transaction_the_store_refuses_names_the_kind_of_error():
    client = TestClient(Service.work_tracker())
    assert refusal(client.post("/transactions", json={"mutations": "no"}), 400).startswith("ValueError: ")
    directory = {"mutations": [{"upsert": {"exists": [{"symbols": {"x": {"reference": {"path": {
        "singleton": "work.Tasks", "next": {"target": {}}}}}}, "spec": [{"x": [{"as_property": {
            "name": "nope", "mutations": [{"set": {"value": "Z"}}]}}]}]}]}}]}
    assert refusal(client.post("/transactions", json=directory), 400).endswith("has no property 'nope'")
    assert client.get("/changes").json()["head"] == 2  # the seed's alone, then its record, from the store below


def test_a_fault_of_the_services_own_is_a_500_with_the_error_body(client, monkeypatch):
    def broken(*_):
        raise RuntimeError("a bug")
    monkeypatch.setattr(Service.Views, "witness", broken)
    store = store_of(client)
    tasks = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Task})]))])))
    assert "a bug" in refusal(client.post("/views/label", json=tasks), 500)


class Overlapping(Builders.Store):
    """A slow store below that notes whether two transactions were ever sent to it at once."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = 0
        self.overlapped = False

    def transaction(self, spec=None):
        self.inside += 1
        self.overlapped |= self.inside > 1
        time.sleep(0.01)
        try:
            return super().transaction(spec)
        finally:
            self.inside -= 1


def test_one_transaction_at_a_time():
    below = Overlapping()
    client = TestClient(Service.work_tracker(below))
    bodies = [write_task(store_of(client), f"TSK-{n:03}", f"Task {n}") for n in range(10, 22)]
    statuses = []

    def post(body):
        statuses.append(client.post("/views/label", json=body).status_code)

    threads = [threading.Thread(target=post, args=(body,)) for body in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert statuses == [200] * len(bodies) and not below.overlapped
    assert held_below(client) == titles(client)  # the store below's order is the commit order
    changes = client.get("/changes?after=0").json()["changes"]
    assert [c["position"] for c in changes] == list(range(1, 2 * len(bodies) + 3))  # the seed, then each, once, each
    # followed by its record, which the store below made (mbse-schemas' Provenance, recorded in the lowest store)
