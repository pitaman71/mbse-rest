"""mbse-rest's client, the service as a store below (`Store.Remote`, mbse-schemas' `Stores.Below`), a plain
`Builders.Store` over it (`Store.Store`), and the endpoints it is made of: an object's document, a transaction committed
or refused, the change feed, and the schemas as install transactions (mbse-basis CAP-290, CAP-306)."""

from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import JSON, Builders, Changes, Stores

from mbse.Services.Rest import Service, Store

from conftest import transport
from library import install, seed

SHELF = {"singleton": "lib.TheShelf", "next": {"target": {}}}
BK_1 = {"singleton": "lib.TheShelf", "next": {"entry": {"i": "books", "o": "shelf", "properties": {"id": "BK-1"},
                                                        "next": {"target": {}}}}}


@pytest.fixture
def api():
    return Service.app([install], seed=seed)


def names(store):
    """The books on the shelf, by name, sorted, read within a transaction."""
    with store.transaction():
        return sorted(str(e.book.name) for e in store.singleton("lib.TheShelf").books)


def book(store, id_):
    """A book on the shelf by its id, within the transaction open."""
    return next(e.book for e in store.singleton("lib.TheShelf").books if e.id.get() == id_)


def rename(store, id_, name):
    with store.transaction():
        store.lib.Book(book(store, id_), lambda b: b.name(name))


def counted(api):
    """A transport to `api`'s service, and the documents read through it, by path."""
    sent, read = transport(api), []

    def send(method, path, body):
        if path == "/documents":
            read.append(JSON.loads(body))
        return sent(method, path, body)
    return send, read


def test_made_it_holds_the_services_schemas_and_loads_nothing(api):
    send, read = counted(api)
    remote = Store.Remote(send)
    client = Store.Store(remote)
    assert isinstance(remote, Stores.Below) and type(client) is Builders.Store
    assert {"lib.Shelf", "lib.Book", "lib.OnShelf", "lib.Cites"} <= set(client.names())
    assert read == [] and JSON.dumps(remote.installs) == JSON.dumps(api.state.service.installs)
    assert names(client) == ["LISP 1.5", "SICP"] and len(read) == 3  # the shelf, then each book read
    assert len(api.state.service.installs) == 1  # its installs, run over it, not sent back


def test_a_store_above_stacks_over_it_as_over_a_store_in_memory(api):
    """A `Builders.Store` over the client loads on demand, writes through to the service, and is given what others
    commit there, each once, in the order the service committed them."""
    here, remote = Store.Store(transport(api)), Store.Remote(transport(api))
    there = Store.Store(remote)
    above = Builders.Store(there)
    above.transaction(install)
    effects = []
    Changes.observe(above, effects.append)
    assert names(above) == ["LISP 1.5", "SICP"]
    rename(here, "BK-1", "Structure")
    rename(here, "BK-2", "Lisp")
    assert names(above) == ["LISP 1.5", "SICP"]  # not yet read from the feed
    assert remote.poll() == 2 and remote.poll() == 0
    assert names(above) == ["Lisp", "Structure"] and len(effects) == 2
    rename(above, "BK-1", "SICP")  # written through: committed by the service first
    assert names(here) == ["Lisp", "Structure"]  # not yet read
    rename(here, "BK-2", "LISP")  # its own commit reads the change feed after it: the other's first
    assert names(here) == ["LISP", "SICP"]
    assert names(api.state.service.below) == ["LISP", "SICP"]


def test_its_followers_are_given_each_transaction_once_in_the_services_order(api):
    """Its own at its commit, as the service committed it, its record among it; others' read from the change feed,
    in the service's order, what they changed of the objects it holds: polled before its own, before it, else read
    after its own commits; its own, read from the change feed again, changes nothing, and its followers are told
    nothing more."""
    remote = Store.Remote(transport(api))
    here, there = Store.Store(remote), Store.Store(transport(api))
    assert names(here) == ["LISP 1.5", "SICP"]  # each book held
    seen = []
    here.follow(lambda journal: seen.append(JSON.dumps(journal)))
    rename(there, "BK-1", "A")  # another's, before its own: read from the feed as it polls
    remote.poll()
    rename(here, "BK-2", "B")  # its own: at its commit; read from the feed after it, it changes nothing
    rename(there, "BK-1", "C")  # another's, not yet read
    rename(here, "BK-2", "D")  # its own, then the other's, read after it
    remote.poll()
    assert [[f'"{n}"' in s for n in "ABCD"] for s in seen] == [
        [True, False, False, False], [False, True, False, False], [False, False, False, True],
        [False, False, True, False]]
    assert names(here) == ["C", "D"]


def test_a_following_ended_is_given_nothing_more(api):
    """Each following is its own, though one follower follow twice: ending one, once or again, ends it alone."""
    remote, seen = Store.Remote(transport(api)), []
    end = remote.follow(seen.append)
    remote.follow(seen.append)
    end()
    end()
    rename(api.state.service.store, "BK-1", "Once")
    assert remote.poll() == 1 and len(seen) == 1


def test_its_own_transaction_is_committed_as_the_service_committed_it():
    """A write is one transaction in the client, as in the service, under the client's uid: what the service answers
    with, its record (`Provenance`) among it, is taken into the client's transaction, and is what its followers are
    given, a journal of that one transaction under that uid, the service's store's."""
    api = Service.work_tracker(uids=lambda: "not-the-clients")
    remote, service = Store.Remote(transport(api)), api.state.service
    client = Store.Store(remote)
    count = len(service.journal)
    seen = []
    client.follow(seen.append)
    with client.transaction():
        comment = client.singleton("work.Comments").comments({"id": "CMT-001"})
        client.work.Comment(comment, lambda c: c.text("Edited."))
    remote.poll()
    assert len(service.journal) == count + 1 and len(seen) == 1  # one transaction, given once
    ([given],) = seen
    assert given["id"] == service.head != "not-the-clients"  # the uid the client sent with it
    assert "Provenance" in JSON.dumps(given) and JSON.dumps(given["id"]) in JSON.dumps(given["changes"])  # its record
    assert JSON.dumps(service.journal[-1]) == JSON.dumps(given)  # the journal the service's store gave


def test_a_refusal_below_refuses_the_transaction_as_the_error_it_is(api):
    """A transaction the service's store refuses is refused in the client, as the error its store raised, and writes
    nothing."""
    remote = Store.Remote(transport(api))
    client = Store.Store(remote)
    service = api.state.service
    head = service.head
    assert head is not None  # the seed's
    with pytest.raises(ValueError, match="has no property 'nope'"):
        remote.commit({"mutations": [{"upsert": {"exists": [{"symbols": {
            "x": {"reference": {"path": BK_1}}}, "spec": [{"x": [{"as_property": {
                "name": "nope", "mutations": [{"set": {"value": 1}}]}}]}]}]}}]})
    assert service.head == head and names(client) == ["LISP 1.5", "SICP"]


def test_a_refusal_kind_and_a_status_reach_the_client_as_errors():
    replies = iter([(200, b'{"feed": "f", "head": null, "journal": []}'), (200, b"[]"),
                    (400, b'{"error": "TypeError: read-only"}'), (400, b'{"error": "LookupError: no such path"}'),
                    (400, b'{"error": "malformed"}'), (503, b'{"error": "the database is unreachable"}'),
                    (410, b'{"error": "restarted"}'), (500, b"not json")])
    client = Store.Remote(lambda method, path, body: next(replies))
    with pytest.raises(TypeError, match="^read-only$"):
        client.commit({})
    with pytest.raises(LookupError, match="^no such path$"):
        client.commit({})
    with pytest.raises(Store.ServiceError) as refused:
        client.commit({})
    assert (refused.value.status, refused.value.error) == (400, "malformed")
    with pytest.raises(Store.Unavailable, match="unreachable"):
        client.commit({})
    with pytest.raises(Store.Gone, match="restarted"):
        client.poll()
    with pytest.raises(Store.ServiceError, match="500: not json"):
        client.document({})


def test_documents_by_path(api):
    client = TestClient(api)
    document = client.post("/documents", json=BK_1).json()
    (pattern,) = document["mutations"][0]["upsert"]["exists"]
    assert pattern["spec"][0]["0"][0] == {"as_property": {"name": "name", "mutations": [{"set": {"value": "SICP"}}]}}
    nobody = {"singleton": "lib.TheShelf", "next": {"entry": {"i": "books", "o": "shelf", "properties": {"id": "BK-9"},
                                                              "next": {"target": {}}}}}
    assert client.post("/documents", json=nobody).json() is None
    assert client.post("/documents", content=b"{bad").status_code == 400
    assert client.post("/documents", json={"singleton": 3}).json()["error"].startswith("ValueError: ")


def test_the_change_feed_read_from_any_position(api):
    """Each transaction once, in order, a journal, after any position the feed keeps, a transaction's id, or from its
    first; refused (410) where it is another feed's, a position it does not keep, or from its first once it has let one
    go."""
    client, service = TestClient(api), api.state.service
    for name in ("A", "B", "C"):
        rename(service.store, "BK-1", name)
    head = client.get("/changes").json()
    every = client.get(f"/changes?feed={service.feed}").json()["journal"]  # the seed, then each
    ids = [t["id"] for t in every]
    assert (head["head"], head["journal"], head["feed"]) == (ids[-1], [], service.feed) and len(set(ids)) == 4
    assert ids[0] == "lib.seed/1" and all(set(t) == {"id", "symbols", "changes"} for t in every)
    assert client.get(f"/changes?after={ids[1]}").json()["journal"] == every[2:]
    assert client.get(f"/changes?after={ids[3]}&feed={service.feed}").json()["journal"] == []
    for query in ("after=nothing", f"after={ids[0]}&feed=another", "feed=another"):
        assert client.get(f"/changes?{query}").status_code == 410
    small = TestClient(Service.app([install], seed=seed, window=2))
    for name in ("A", "B", "C"):
        rename(small.app.state.service.store, "BK-1", name)
    kept = [t["id"] for t in small.app.state.service.journal]
    assert [t["id"] for t in small.get(f"/changes?after={kept[0]}").json()["journal"]] == kept[1:]
    assert "keeps its latest 2 transactions" in small.get("/changes?after=lib.seed/1").json()["error"]
    feed_ = small.app.state.service.feed
    assert "not its first" in small.get(f"/changes?feed={feed_}").json()["error"]


def test_the_change_feed_in_pages(api, monkeypatch):
    monkeypatch.setattr(Service, "PAGE", 2)
    service = api.state.service
    for name in ("A", "B", "C", "D"):
        rename(service.store, "BK-1", name)
    client = Store.Remote(transport(api))
    client._head = None  # from the feed's first
    assert client.poll() == 5 and client._head == service.head  # in three reads, each of two at most


def test_a_read_of_the_change_feed_waits_for_a_commit(api):
    client, service = TestClient(api), api.state.service
    head = service.head
    started = time.monotonic()
    assert client.get(f"/changes?after={head}&wait=0.2").json()["journal"] == []  # none: held open, given none
    assert time.monotonic() - started >= 0.2
    later = threading.Timer(0.2, lambda: rename(service.store, "BK-1", "Later"))
    later.start()
    started = time.monotonic()
    journal = client.get(f"/changes?after={head}&wait=10").json()["journal"]
    later.join()
    assert [t["id"] for t in journal] == [service.head] != [head] and time.monotonic() - started < 5


def test_the_service_polls_a_store_below_followed_by_polling():
    class Polled(Builders.Store):
        polls = 0

        def poll(self):
            Polled.polls += 1
            return 0

    api = Service.app([install], Polled(), seed)
    client = Store.Store(transport(api))
    names(client)
    rename(client, "BK-1", "Polled")
    assert Polled.polls >= 4  # the head read, a document or more, the transaction, and the feed read after it
    head = api.state.service.head
    assert TestClient(api).get(f"/changes?after={head}&wait=1.5").json()["journal"] == []
    assert Service.fresh(Polled()) and not Service.fresh(type("Kept", (Builders.Store,), {"head": lambda self: "t"})())
    assert Service.fresh(type("Empty", (Builders.Store,), {"head": lambda self: None})())


def test_an_install_a_client_runs_is_sent_to_the_service():
    """The schemas a client is given are the install transactions that made them; an install the client runs is sent
    to the service, which runs it in its store and its store below, and serves it after the others, once."""
    api = Service.app()
    client = TestClient(api)
    assert client.get("/schemas").json() == []
    first = Store.Store(transport(api))
    first.transaction(install)
    first.transaction(install)  # run again: it writes nothing, and is served once
    [served] = client.get("/schemas").json()
    assert "lib.Book" in api.state.service.below.names() and "lib.Book" in api.state.service.names()
    remote = Store.Remote(transport(api))
    second = Store.Store(remote)
    assert "lib.Book" in second.names()
    first.transaction(seed)
    remote.poll()
    assert names(second) == ["LISP 1.5", "SICP"]
    assert JSON.dumps(served) == JSON.dumps(client.post("/schemas", json=served).json()[0])
    assert client.post("/schemas", json=[]).status_code == 400
    assert client.post("/schemas", content=b"{bad").status_code == 400
    assert client.post("/schemas", json={"mutations": "no"}).json()["error"].startswith("ValueError: ")


def test_a_client_over_http():
    """The client over the network, through the standard library, to the service uvicorn serves, its session sent
    with each request."""
    api = Service.app([install], seed=seed)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        client = Store.Store(Store.Http(f"http://127.0.0.1:{port}/", {"x-mbse-session": "tab-1"}))
        rename(client, "BK-1", "Over HTTP")
        other = Store.Store(f"http://127.0.0.1:{port}")
        assert names(other) == ["LISP 1.5", "Over HTTP"]
        with pytest.raises(Store.ServiceError) as refused:
            Store.Remote(f"http://127.0.0.1:{port}")._call("GET", "/nothing")
        assert refused.value.status == 404
    finally:
        server.should_exit = True
        thread.join(timeout=10)
