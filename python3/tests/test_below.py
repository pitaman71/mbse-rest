"""mbse-schemas' suite BLW (`tests/36_Below.ipynb`, a store given a store below, mbse-basis CAP-283 to CAP-285), each case
as mbse-schemas wrote it, run with mbse-rest's client as the store below in place of the store in memory: its setup's
`below = B.Store()` alone is changed (CAP-290). The client is over a service of its own, over a store in memory, which
starts holding nothing: the suite's install, run in the client, is sent to it."""

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


@pytest.mark.parametrize("source", [pytest.param(source, id=case) for case, source in SUITE[1:]])
def test_blw_case_over_rest(run, source):
    run(source)


def test_the_service_holds_what_the_suite_wrote_below(run):
    """What the suite wrote to the store below, the client, the service's store below holds, and its feed reported."""
    run("with __service__.below.transaction(), below.transaction():\n"
        "    assert sorted(e.key.get() for e in __service__.below.singleton('crm.TheBook').contacts) == "
        "sorted(e.key.get() for e in below.singleton('crm.TheBook').contacts) != []")
    run("assert __service__.head is not None and 'crm.Person' in __service__.names()")
