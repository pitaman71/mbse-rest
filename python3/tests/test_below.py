"""mbse-schemas' suite BLW (`tests/36_Below.ipynb`, a cache layer over a layer below, the stacked stores proposal's
second stage), each case as mbse-schemas wrote it, run with mbse-rest between the two layers: the cache layer is
mbse-rest's client store (`Store.Store`), over the service, which serves the suite's layer below, `lower`, in this
process. Where the suite makes a cache layer over `lower`, `B.Store(lower)`, it makes it over REST, `over_rest(lower)`;
nothing else is changed but what `CHANGED` lists, each a line that reads what crossing a process changes."""

from __future__ import annotations

import pytest

from mbse.Services.Rest import Service, Store

from conftest import transport
from notebooks import cells, namespace

SUITE = cells("mbse-schemas", "36_Below.ipynb")
OVER = "B.Store(lower)"

CHANGED = {
    # The cache layer's layer below is the client, which the service serves `lower` to.
    "BLW-01": [("assert cache._below is lower and", "assert cache._below is served[lower] and")],
    # What has no reference crosses refused: a frame binding a counted object comes over with that symbol left out of
    # its journal, annotated with why, so that the transaction raises it at its end, where in a process the symbol is
    # bound refused, raising where it is read.
    "BLW-12": [
        ("""        with raises(LookupError, match="symbol 'n' of the frame: a counted 'crm.Note' has no reference"):
            noted["n"]""", """        assert "n" not in noted and noted.errors[0].message.startswith(
            "symbol 'n' of the frame: a counted 'crm.Note' has no reference")"""),
    ],
}


def over_rest(lower):
    """A cache layer over mbse-rest's client of a service, in this process, serving `lower`."""
    api = Service.app(store=lower)
    store = Store.Store(transport(api))
    served[lower] = store._below
    return store


served = {}


@pytest.fixture(scope="module")
def run():
    """Runs the setup cell, its cache layers over REST, then gives each case's cell to run, in order."""
    ((_, setup), *_) = SUITE
    assert setup.count(OVER) == 1
    scope = namespace()
    scope.update(over_rest=over_rest, served=served)
    exec(setup.replace(OVER, "over_rest(lower)"), scope)
    return lambda case, source: exec(_changed(case, source).replace(OVER, "over_rest(lower)"), scope)


def _changed(case, source):
    for before, after in CHANGED.get(case, []):
        assert before in source, (case, before)
        source = source.replace(before, after)
    return source


@pytest.mark.parametrize("case,source", [pytest.param(case, source, id=case) for case, source in SUITE[1:]])
def test_blw_case_over_rest(run, case, source):
    run(case, source)
