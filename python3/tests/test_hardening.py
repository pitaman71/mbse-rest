"""The endpoints hardened (mbse-basis CAP-012: logical view endpoints, and CAP-290): error bodies and statuses, nothing
written where the store refuses or fails, and one transaction at a time, a client's held open across its requests."""

from __future__ import annotations

import contextlib
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import Builders, Plain

from mbse.Services.Rest import Service


class Failing(Builders.Store):
    """A store in memory, whose transactions fail on demand, as a database's that cannot be reached."""

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


def titles(client, store=None):
    """The titles of the tasks the service's store holds, read within a transaction."""
    store = store_of(client) if store is None else store
    with store.transaction():
        return [str(e.task.title) for e in store.singleton("work.Tasks").tasks]


def fed(client):
    """The change feed's journal, from its first transaction."""
    return client.get(f"/changes?feed={client.app.state.service.feed}").json()["journal"]


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
    assert "Unwritten" not in titles(client) and "Unwritten" not in titles(client)
    assert len(fed(client)) == 1  # the seed's alone, its record among it, as the store below committed it: one
    # transaction per write


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
    assert len(lines) == 1 and json.loads(lines[0])["journal"]["symbols"]["x"]["reference"]


def test_a_store_that_fails_writes_nothing_and_answers_503():
    store = Failing()
    client = TestClient(Service.work_tracker(store))
    store.failing = True
    assert "nothing is written" in refusal(
        client.post("/views/label", json=write_task(store, "TSK-009", "Lost")), 503)
    opened = client.post("/transactions").json()["transaction"]  # its store's transaction opened at its first exec
    assert "nothing is written" in refusal(client.post(f"/transactions/{opened}/exec", json={
        "expression": write_task(store, "TSK-009", "Lost")}), 503)
    refusal(client.post(f"/transactions/{opened}/commit"), 410)  # dropped as it failed
    store.failing = False  # the database is back: the service goes on
    assert "Lost" not in titles(client)
    assert client.post("/views/label", json=write_task(store, "TSK-009", "Kept")).status_code == 200
    assert titles(client)[-1] == "Kept"


def test_a_store_that_fails_at_startup_fails_the_start():
    store = Failing()
    store.failing = True
    with pytest.raises(ConnectionError):
        Service.work_tracker(store)


def test_a_store_that_refuses_refuses_the_transaction():
    """What the store refuses, the service refuses, as the kind of error it is, and writes nothing."""
    client = TestClient(Service.work_tracker())
    store = store_of(client)
    body = write_task(store, "TSK-009", "Doubled")
    with store.transaction():  # another writes TSK-009 in the store, as another process writes a database
        store.work.Task(lambda t: t.directory(lambda a: a.insert(lambda e: e.id("TSK-009").directory(
            store.singleton("work.Tasks")))).title("Theirs"))
    response = client.post("/views/label", json=body)
    assert response.status_code in (200, 400)  # an upsert finds theirs, or is refused: never two by one key
    assert [t for t in titles(client) if t in ("Theirs", "Doubled")] in (["Theirs"], ["Doubled"])


def test_a_transaction_the_store_refuses_names_the_kind_of_error():
    client = TestClient(Service.work_tracker())
    opened = client.post("/transactions").json()["transaction"]
    assert refusal(client.post(f"/transactions/{opened}/exec", json={"expression": {"mutations": "no"}}),
                   400).startswith("ValueError: ")
    directory = {"mutations": [{"upsert": {"exists": [{"symbols": {"x": {"reference": {"path": {
        "singleton": "work.Tasks", "next": {"target": {}}}}}}, "spec": [{"x": [{"as_property": {
            "name": "nope", "mutations": [{"set": {"value": "Z"}}]}}]}]}]}}]}
    assert refusal(client.post(f"/transactions/{opened}/exec", json={"expression": directory}),
                   400).endswith("has no property 'nope'")
    assert client.delete(f"/transactions/{opened}").json() == {}
    assert len(fed(client)) == 1  # the seed's alone, its record among it: one transaction per write


@pytest.mark.parametrize("body", [b"{bad", b"[]", b"{}", b'{"expression": []}', b'{"expression": {}, "remainder": "x"}',
                                  b'{"expression": {}, "frames": [3]}', b'{"expression": {}, "frames": [{"journal": 3}]}',
                                  b'{"expression": {}, "frames": [{"binds": {}}]}'])
def test_a_malformed_exec_is_a_400_and_the_transaction_stays_open(client, body):
    opened = client.post("/transactions").json()["transaction"]
    refusal(client.post(f"/transactions/{opened}/exec", content=body, headers={"content-type": "application/json"}), 400)
    assert client.post(f"/transactions/{opened}/commit").json()["journal"] == []


def test_a_transaction_not_open_is_gone(client):
    for request in (lambda t: client.post(f"/transactions/{t}/exec", json={"expression": {}}),
                    lambda t: client.post(f"/transactions/{t}/commit"), lambda t: client.delete(f"/transactions/{t}")):
        assert "no transaction 'nothing' is open" in refusal(request("nothing"), 410)
    opened = client.post("/transactions").json()["transaction"]
    assert client.post(f"/transactions/{opened}/commit").status_code == 200
    refusal(client.post(f"/transactions/{opened}/commit"), 410)  # committed: ended


def test_an_exec_answers_a_stream_of_items_its_last_the_end_of_the_stream(client):
    store = store_of(client)
    tasks = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Task})]))])))
    opened = client.post("/transactions").json()
    assert set(opened) == {"transaction", "feed", "head"} and opened["head"] == fed(client)[-1]["id"]
    with client.stream("POST", f"/transactions/{opened['transaction']}/exec", json={"expression": tasks}) as response:
        assert response.status_code == 200 and response.headers["content-type"] == Service.NDJSON
        lines = [json.loads(line) for line in response.iter_lines()]
    assert [list(line) for line in lines] == [["frame"]] * (len(lines) - 2) + [["end"], ["end"]]
    assert lines[-2] == {"end": {"scope": "0"}} and lines[-1] == {"end": {}} and len(lines) > 2
    assert all(line["frame"]["scope"] == "0" and list(line["frame"]["journal"]["symbols"]) == ["x"]
               for line in lines[:-2])  # each frame its journal, its symbols its bindings
    client.delete(f"/transactions/{opened['transaction']}")


def test_one_client_transaction_at_a_time_another_waits_then_is_refused(client, monkeypatch):
    monkeypatch.setattr(Service, "WAIT", 0.3)
    opened = client.post("/transactions").json()["transaction"]
    started = time.monotonic()
    assert "another client's transaction holds the store" in refusal(client.post("/transactions"), 503)
    assert time.monotonic() - started >= 0.3
    refusal(client.post("/views/label", json={}), 503)  # a view waits for it too
    later = threading.Timer(0.1, lambda: client.post(f"/transactions/{opened}/commit"))
    later.start()
    assert client.post("/transactions").status_code == 200  # given the store once the other commits
    later.join()


def test_a_transaction_left_idle_is_dropped_and_writes_nothing():
    client = TestClient(Service.work_tracker(lease=0.2))
    store = store_of(client)
    opened = client.post("/transactions").json()["transaction"]
    assert client.post(f"/transactions/{opened}/exec", json={
        "expression": write_task(store, "TSK-009", "Abandoned")}).status_code == 200
    time.sleep(0.3)
    assert client.post("/transactions").status_code == 200  # the idle one dropped for it
    assert "dropped" in refusal(client.post(f"/transactions/{opened}/commit"), 410)
    assert "Abandoned" not in titles(client)


def test_a_fault_of_the_services_own_is_a_500_with_the_error_body(client, monkeypatch):
    def broken(*_):
        raise RuntimeError("a bug")
    monkeypatch.setattr(Service.Views, "witness", broken)
    store = store_of(client)
    tasks = Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": store.work.Task})]))])))
    assert "a bug" in refusal(client.post("/views/label", json=tasks), 500)


class Overlapping(Builders.Store):
    """A slow store that notes whether two transactions were ever open in it at once."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = 0
        self.overlapped = False

    def transaction(self, spec=None):
        if spec is not None:
            return super().transaction(spec)
        return self._watched()

    @contextlib.contextmanager
    def _watched(self):
        self.inside += 1
        self.overlapped |= self.inside > 1
        time.sleep(0.01)
        try:
            with super().transaction() as txn:
                yield txn
        finally:
            self.inside -= 1


def test_one_transaction_at_a_time():
    store = Overlapping()
    client = TestClient(Service.work_tracker(store))
    bodies = [write_task(store_of(client), f"TSK-{n:03}", f"Task {n}") for n in range(10, 22)]
    statuses = []

    def post(body):
        opened = client.post("/transactions").json()["transaction"]
        statuses.append(client.post(f"/transactions/{opened}/exec", json={"expression": body}).status_code)
        statuses.append(client.post(f"/transactions/{opened}/commit").status_code)

    threads = [threading.Thread(target=post, args=(body,)) for body in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert statuses == [200] * 2 * len(bodies) and not store.overlapped
    assert len(titles(client)) == 2 + len(bodies)
    journal = fed(client)
    assert len(journal) == len(bodies) + 1 == len({t["id"] for t in journal})  # the seed, then each, once
