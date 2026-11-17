"""mbse-schemas' suite BLW (`tests/36_Below.ipynb`, a store given a store below, mbse-basis CAP-283 to CAP-285), each case
as mbse-schemas wrote it, run with mbse-rest's client as the store below in place of the store in memory: its setup's
`below = B.Store()` alone is changed (CAP-290). The client is over a service of its own, over a store in memory, which
starts holding nothing: the suite's install, run in the client, is sent to it.

BLW-15 fails here, and BLW-18 after it, for a fault of mbse-schemas 0.29.0's: an upsert finds a counted object it made
before by its key, its symbol and the frame that reached it (`Transactions._upsert_index`), with no key and an empty
frame alike in every transaction, so that the service's store, long-lived, binds a counted `crm.Badge` written under a
symbol to the `crm.Tag` an earlier transaction made under the same symbol, and refuses BLW-15's transaction after the
store below it has committed it. Each is marked to fail, strictly, until mbse-schemas tells them apart."""

from __future__ import annotations

import pytest

from mbse.Services.Rest import Service, Store

from conftest import transport
from notebooks import cells, namespace

SUITE = cells("mbse-schemas", "36_Below.ipynb")
IN_MEMORY = "below = B.Store()\n"


@pytest.fixture(scope="module")
def run():
    """Runs the setup cell, its store below mbse-rest's client, then gives each case's cell to run, in order."""
    ((_, setup), *_) = SUITE
    assert setup.count(IN_MEMORY) == 1
    scope = namespace()
    api = Service.app()
    scope["served_over_rest"] = lambda: Store.Store(transport(api))
    exec(setup.replace(IN_MEMORY, "below = served_over_rest()\n"), scope)
    scope["__service__"] = api.state.service
    return lambda source: exec(source, scope)


ALIASED = pytest.mark.xfail(strict=True, reason="mbse-schemas 0.29.0 binds a counted object of one transaction to "
                                                "another's made under the same symbol (Transactions._upsert_index)")
FAILING = {"BLW-15": ALIASED, "BLW-18": ALIASED}  # BLW-18 as BLW-15 left it


@pytest.mark.parametrize("source", [pytest.param(source, id=case, marks=FAILING.get(case, ()))
                                    for case, source in SUITE[1:]])
def test_blw_case_over_rest(run, source):
    run(source)


@ALIASED  # BLW-15's lux, committed below the service's store, whose own refused it
def test_the_service_holds_what_the_suite_wrote_below(run):
    """What the suite wrote to the store below, the client, the service's store below holds, and its feed reported."""
    run("with __service__.below.transaction(), below.transaction():\n"
        "    assert sorted(e.key.get() for e in __service__.below.singleton('crm.TheBook').contacts) == "
        "sorted(e.key.get() for e in below.singleton('crm.TheBook').contacts) != []")
    run("assert __service__.head is not None and 'crm.Person' in __service__.names()")
