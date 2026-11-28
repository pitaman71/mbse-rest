"""mbse-rest's client: the service as a layer below (`Store.Remote`), its transaction the service's, held open across
its requests, and a cache layer over it (`Store.Store`), given what others commit by the change feed in either follow
mode (mbse-basis CAP-290, CAP-308, the stacked stores proposal's third stage)."""

from __future__ import annotations

import itertools
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mbse.Schemas.Framework import JSON, Builders, Changes, Plain
from mbse.Schemas.Framework.Transactions import Frame

from mbse.Services.Rest import Service, Store

from conftest import transport
from library import install, seed

BK_1 = {"singleton": "lib.TheShelf", "next": {"entry": {"i": "books", "o": "shelf", "properties": {"id": "BK-1"},
                                                        "next": {"target": {}}}}}
counter = itertools.count()


@pytest.fixture
def api():
    return Service.app([install], seed=seed)


def requests(api):
    """A transport to `api`'s service, and the requests made through it, each its method and its path."""
    sent, made = transport(api), []

    def send(method, path, body):
        made.append((method, path.split("?")[0]))
        return sent(method, path, body)
    return send, made


def names(store):
    """The books on the shelf, by name, sorted, read within a transaction of a store that holds them all."""
    with store.transaction():
        return sorted(str(e.book.name) for e in store.singleton("lib.TheShelf").books)


def named(t, name):
    """A map of each book named `name`."""
    return t.uid(f"named/{next(counter)}").mutations([lambda mu: mu.map(lambda m: m.symbols([lambda p: p.symbols(
        {"b": t.lib.Book}).spec([lambda _: _.b.name(name)])]))])


def renamed(id_, name):
    """A transaction: the book `id_` is named `name`."""
    return lambda t: t.uid(f"renamed/{next(counter)}").mutations([lambda mu: mu.map(lambda m: m.symbols([
        lambda p: p.symbols({"s": t.lib.Shelf, "b": t.lib.Book}).spec([
            lambda _: _.s.books({id_: lambda e: e.book(_.b)})])])).then([lambda w: w.update(lambda u: u.apply([
                lambda p: p.symbols({"b": t.lib.Book}).spec([lambda _: _.b.name(name)])]))])])


def added(id_, name):
    """A transaction: a book `id_` on the shelf, named `name`."""
    return lambda t: t.uid(f"added/{id_}").mutations([lambda mu: mu.upsert(lambda u: u.exists([lambda p: p.symbols(
        {"s": t.lib.Shelf, "b": t.lib.Book}).spec([lambda _: _.s.books({id_: lambda e: e.book(_.b)}),
                                                   lambda _: _.b.name(name)])]))])


def name_of(store, id_):
    """The name of the book `id_`, read within a transaction of `store`, a cache layer that holds it."""
    with store.transaction():
        return str(store.singleton("lib.TheShelf").books({"id": id_}).name)


def test_made_it_holds_the_services_schemas_and_nothing_else(api):
    """A cache layer over the client runs the installs the service was given, through it; it holds none of the
    service's data, and a transaction's frames come from the service."""
    send, made = requests(api)
    client = Store.Store(send)
    assert type(client._below) is Store.Remote and isinstance(client, Builders.Store)
    assert {"lib.Shelf", "lib.Book", "lib.OnShelf", "lib.Cites"} <= set(client.names())
    assert {"lib.Shelf", "lib.Book"} <= set(client._below.names())  # the install ran in the client too
    assert made[:2] == [("GET", "/changes"), ("GET", "/schemas")]
    assert [method for method, _ in made[2:]] == ["GET", "POST", "POST", "POST"]  # caught up; open, exec, commit
    assert len(api.state.service.installs) == 1  # the install, run again over it, writes nothing and is served once
    assert names(client) == []  # it holds none of the books: nothing is loaded
    assert len(client.transaction(lambda t: named(t, "SICP"))) == 1


def test_a_transaction_spans_several_exec_calls_in_one_transaction_of_the_service(api):
    """The client's transaction is one of the service's store, held open across each exec: what an exec wrote, the
    next reads, and the service's store commits it once the client's scope ends, a halted frame resumed in it."""
    send, made = requests(api)
    remote = Store.Remote(send)
    remote.transaction(Plain.FromPlain(remote).Transaction(api.state.service.installs[0]))
    service = api.state.service
    expressions = {name: remote.Mutations.OfTransaction(lambda t, spec=spec: spec(Service._Named(remote, t)))
                   for name, spec in (
        ("add", added("BK-3", "HtDP")), ("rename", renamed("BK-3", "How to Design Programs")),
        ("find", lambda t: named(t, "How to Design Programs")))}
    head, del_made = service.head, made.clear()
    with remote.transaction() as txn:
        (added_,) = [x for x in txn.exec(Frame(), expressions["add"], True) if isinstance(x, Frame)]
        (halted,) = [x for x in txn.exec(Frame(), expressions["rename"], False) if isinstance(x, Frame)]
        assert halted.remainder.subterm == "$.mutations[0].map.then[0].update"  # read-only: halted where it writes
        assert halted.remainder.transaction is expressions["rename"]  # a position in the expression it was given
        (resumed,) = [x for x in txn.exec(halted, halted.remainder, True) if isinstance(x, Frame)]
        (found,) = [x for x in txn.exec(Frame(), expressions["find"], True) if isinstance(x, Frame)]
        assert service.head == head  # nothing committed yet
    assert [method for method, _ in made] == ["POST"] * 6  # open, four execs, commit: one transaction
    assert made[0][1] == "/transactions" and made[-1][1].endswith("/commit")
    assert names(service.store) == ["How to Design Programs", "LISP 1.5", "SICP"] and service.head != head
    sets = lambda frame: [change["property"]["set"] for change in Plain.ToPlain(remote)(
        frame.journal.as_schema(), frame.journal)["changes"] if "set" in change.get("property", {})]
    assert sets(found) == [{"holder": "b", "name": "name", "value": "How to Design Programs"}]  # each frame its journal
    assert sets(added_) == [{"holder": "b", "name": "name", "value": "HtDP"}] and sets(resumed) == sets(found)


def test_a_refusal_below_aborts_both(api):
    """A transaction the service's store refuses, a book put on the shelf under a second id, which the cache layer
    cannot see, holding neither, refuses the cache layer's: neither commits anything, and the service's transaction is
    dropped."""
    client = Store.Store(transport(api))
    service = api.state.service
    head = service.head
    doubled = lambda t: t.uid("doubled/1").mutations([lambda mu: mu.map(lambda m: m.symbols([lambda p: p.symbols(
        {"s": t.lib.Shelf, "b": t.lib.Book}).spec([lambda _: _.s.books({"BK-1": lambda e: e.book(_.b)})])])).then([
            lambda w: w.update(lambda u: u.apply([lambda p: p.symbols({"s": t.lib.Shelf, "b": t.lib.Book}).spec([
                lambda _: _.s.books({"BK-9": lambda e: e.book(_.b)})])]))])])
    with pytest.raises(LookupError, match="has more than one owner"):
        client.transaction(doubled)
    assert service.head == head and names(service.store) == ["LISP 1.5", "SICP"] and names(client) == []
    assert service._open is None  # the service's transaction dropped with it
    with pytest.raises(RuntimeError, match="stop"):
        with client.transaction() as txn:
            list(txn.exec(Frame(), added("BK-3", "Dropped"), True))
            raise RuntimeError("stop")  # the cache layer's raises: the service's is dropped
    assert service.head == head and names(service.store) == ["LISP 1.5", "SICP"] and names(client) == []
    assert service._open is None


def test_the_follow_mode_catches_up_before_each_transaction_by_default(api):
    """In the follow mode `CATCH_UP`, a cache layer reads the change feed to its head before each transaction: what
    another committed since is applied to what it holds before it reads it."""
    here, there = Store.Store(transport(api)), Store.Store(transport(api))
    here.transaction(added("BK-3", "HtDP"))  # made through it: it holds all of it
    assert name_of(here, "BK-3") == "HtDP"
    there.transaction(renamed("BK-3", "How to Design Programs"))
    assert name_of(here, "BK-3") == "How to Design Programs"  # caught up as its transaction began


def test_the_follow_mode_polled_reads_a_poll_behind(api):
    """In the follow mode `POLLED`, a cache layer reads the change feed when polled alone: it reads what it holds a
    poll behind, until it polls."""
    remote = Store.Remote(transport(api))
    here, there = Store.Store(remote, follow=Store.POLLED), Store.Store(transport(api))
    here.transaction(added("BK-3", "HtDP"))
    there.transaction(renamed("BK-3", "How to Design Programs"))
    assert name_of(here, "BK-3") == "HtDP"  # a poll behind
    assert remote.poll() >= 1 and remote.poll() == 0
    assert name_of(here, "BK-3") == "How to Design Programs"
    with pytest.raises(ValueError, match="follow mode"):
        Store.Store(remote, follow="sometimes")


def test_its_followers_are_given_each_transaction_once_in_the_services_order(api):
    """Its own as it commits, as the service committed it, within its commit; others' read from the change feed, in
    the service's order; its own, read from the feed again, changes nothing, and its followers are told nothing more."""
    remote = Store.Remote(transport(api))
    here, there = Store.Store(remote, follow=Store.POLLED), Store.Store(transport(api))
    here.transaction(added("BK-3", "A"))
    seen = []
    Changes.observe(here, lambda journal: seen.append(JSON.dumps(Plain.ToPlain(here)(
        here.registered("Changes.Journal"), journal))))
    there.transaction(renamed("BK-3", "B"))  # another's: read from the feed as it polls
    remote.poll()
    here.transaction(renamed("BK-3", "C"))  # its own: at its commit; read from the feed after it, it changes nothing
    there.transaction(renamed("BK-3", "D"))  # another's, not yet read
    remote.poll()
    assert [[f'"{n}"' in s for n in "BCD"] for s in seen] == [[True, False, False], [False, True, False],
                                                             [False, False, True]]
    assert name_of(here, "BK-3") == "D"


def test_a_following_ended_is_given_nothing_more(api):
    """Each following is its own, though one follower follow twice: ending one, once or again, ends it alone."""
    remote, seen = Store.Remote(transport(api)), []
    end = remote.follow(seen.append)
    remote.follow(seen.append)
    end()
    end()
    api.state.service.store.transaction(renamed("BK-1", "Once"))
    assert remote.poll() == 1 and len(seen) == 1 and remote.position() == api.state.service.head


def test_its_own_transaction_is_committed_as_the_service_committed_it():
    """A write is one transaction in the cache layer, as in the service, under the cache layer's uid: what the
    service's follow gave of it, its record (`Provenance`) among it, is taken into the cache layer's transaction, and is
    what its followers are given, a journal of that one transaction."""
    api = Service.work_tracker(uids=lambda: "not-the-clients")
    service = api.state.service
    client = Store.Store(transport(api), follow=Store.POLLED)
    count = len(service.journal)
    seen = []
    Changes.observe(client, seen.append)
    client.transaction(lambda t: t.uid("edited/1").mutations([lambda mu: mu.map(lambda m: m.symbols([
        lambda p: p.symbols({"d": t.work.CommentDirectory, "c": t.work.Comment}).spec([
            lambda _: _.d.comments({"CMT-001": lambda e: e.comment(_.c)})])])).then([lambda w: w.update(
                lambda u: u.apply([lambda p: p.symbols({"c": t.work.Comment}).spec([lambda _: _.c.text("Edited.")])]))])]))
    assert len(service.journal) == count + 1 and len(seen) == 1  # one transaction, given once
    (given,) = Plain.ToPlain(client)(client.registered("Changes.Journal"), seen[0])
    assert given["id"] == service.head == "edited/1"  # the uid the cache layer sent with it
    assert "Provenance" in JSON.dumps(service.journal[-1])  # recorded once, in the service's store
    assert "Provenance.Transactions" in JSON.dumps(given)  # its record among it, taken in


def test_an_install_a_client_runs_reaches_the_service_and_the_client():
    """An install a cache layer runs runs in the service's store first, then in the client, then in the cache layer;
    the service serves only the installs it was given."""
    api = Service.app()
    client = TestClient(api)
    assert client.get("/schemas").json() == []
    first = Store.Store(transport(api))
    first.transaction(install)
    first.transaction(install)  # run again: it writes nothing
    assert client.get("/schemas").json() == []
    assert "lib.Book" in api.state.service.store.names() and "lib.Book" in first._below.names()
    first.transaction(seed)
    assert names(api.state.service.store) == ["LISP 1.5", "SICP"]
    second = Store.Store(transport(api))
    assert "lib.Book" not in second.names()  # given no installs: it holds no schemas of the service's
    second.transaction(install)
    assert len(second.transaction(lambda t: named(t, "SICP"))) == 1


def test_a_refusal_kind_and_a_status_reach_the_client_as_errors():
    replies = iter([(200, b'{"feed": "f", "head": null, "journal": []}'), (200, b'{"transaction": "t1"}'),
                    (400, b'{"error": "TypeError: read-only"}'), (200, b"{}"), (200, b'{"transaction": "t2"}'),
                    (400, b'{"error": "LookupError: no such path"}'), (200, b"{}"),
                    (200, b'{"transaction": "t3"}'), (400, b'{"error": "malformed"}'), (200, b"{}"),
                    (200, b'{"transaction": "t4"}'), (503, b'{"error": "the database is unreachable"}'),
                    (503, b"{}"), (410, b'{"error": "restarted"}'), (500, b"not json"),
                    (200, b'{"transaction": "t5"}'), (200, b'{"frame": {"journal": {}}}\n'), (200, b"{}")])
    remote = Store.Remote(lambda method, path, body: next(replies))
    expression = remote.Mutations.OfTransaction(lambda t: t.mutations([]))
    for error, match in ((TypeError, "^read-only$"), (LookupError, "^no such path$")):
        with pytest.raises(error, match=match):
            remote.transaction(expression)
    with pytest.raises(Store.ServiceError) as refused:
        remote.transaction(expression)
    assert (refused.value.status, refused.value.error) == (400, "malformed")
    with pytest.raises(Store.Unavailable, match="unreachable"):
        remote.transaction(expression)  # its abort, refused too, is left to the service
    with pytest.raises(Store.Gone, match="restarted"):
        remote.poll()
    with pytest.raises(Store.ServiceError, match="500: not json"):
        remote.transaction(expression)
    with pytest.raises(Store.Unavailable, match="before its completion marker"):
        with remote.transaction() as txn:
            txn.exec(Frame(), expression, True)


def test_a_transaction_ended_refuses_its_exec(api):
    remote = Store.Remote(transport(api))
    with remote.transaction() as txn:
        pass
    with pytest.raises(ValueError, match="has ended"):
        txn.exec(Frame(), remote.Mutations.OfTransaction(lambda t: t.mutations([])), True)


def test_the_change_feed_read_from_any_position(api):
    """Each transaction once, in order, a journal, after any position the feed keeps, a transaction's id, or from its
    first; refused (410) where it is another feed's, a position it does not keep, or from its first once it has let one
    go."""
    client, service = TestClient(api), api.state.service
    for name in ("A", "B", "C"):
        service.store.transaction(renamed("BK-1", name))
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
        small.app.state.service.store.transaction(renamed("BK-1", name))
    kept = [t["id"] for t in small.app.state.service.journal]
    assert [t["id"] for t in small.get(f"/changes?after={kept[0]}").json()["journal"]] == kept[1:]
    assert "keeps its latest 2 transactions" in small.get("/changes?after=lib.seed/1").json()["error"]
    feed_ = small.app.state.service.feed
    assert "not its first" in small.get(f"/changes?feed={feed_}").json()["error"]


def test_the_change_feed_in_pages(api, monkeypatch):
    monkeypatch.setattr(Service, "PAGE", 2)
    service = api.state.service
    remote = Store.Remote(transport(api))
    for name in ("A", "B", "C", "D", "E"):
        service.store.transaction(renamed("BK-1", name))
    assert remote.poll() == 5 and remote.position() == service.head  # in three reads, each of two at most


def test_a_read_of_the_change_feed_waits_for_a_commit(api):
    client, service = TestClient(api), api.state.service
    head = service.head
    started = time.monotonic()
    assert client.get(f"/changes?after={head}&wait=0.2").json()["journal"] == []  # none: held open, given none
    assert time.monotonic() - started >= 0.2
    later = threading.Timer(0.2, lambda: service.store.transaction(renamed("BK-1", "Later")))
    later.start()
    started = time.monotonic()
    journal = client.get(f"/changes?after={head}&wait=10").json()["journal"]
    later.join()
    assert [t["id"] for t in journal] == [service.head] != [head] and time.monotonic() - started < 5


def test_the_service_polls_a_store_followed_by_polling():
    polls = []
    api = Service.app([install], None, seed, poll=lambda: polls.append(1))
    client = Store.Store(transport(api))
    client.transaction(renamed("BK-1", "Polled"))
    assert len(polls) >= 3  # the head read; the feed read before each transaction; each transaction opened
    count = len(polls)
    head = api.state.service.head
    assert TestClient(api).get(f"/changes?after={head}&wait=1.5").json()["journal"] == []
    assert len(polls) > count  # while the read was held open
    assert Service.fresh(Builders.Store()) and not Service.fresh(
        type("Kept", (Builders.Store,), {"head": lambda self: "t"})())
    assert Service.fresh(type("Empty", (Builders.Store,), {"head": lambda self: None})())


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
        client.transaction(added("BK-3", "Over HTTP"))
        other = Store.Store(f"http://127.0.0.1:{port}")
        assert len(other.transaction(lambda t: named(t, "Over HTTP"))) == 1
        assert names(api.state.service.store) == ["LISP 1.5", "Over HTTP", "SICP"]
        with pytest.raises(Store.ServiceError) as refused:
            Store.Remote(f"http://127.0.0.1:{port}")._rest.call("GET", "/nothing")
        assert refused.value.status == 404
    finally:
        server.should_exit = True
        thread.join(timeout=10)
