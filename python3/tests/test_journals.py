"""mbse-journals' suite JRN (`tests/03_Journals.ipynb`, the journal conformance every backend passes unchanged,
mbse-basis CAP-288), run unchanged with each journal kept over REST (CAP-290): every store the suite makes,
`Builders.Store()`, is made over mbse-rest's client of a service of its own, over a store in memory,
`Builders.Store(Store(...))`, as an app stacks one.

A store above does not send its schema installs below, since a transaction that writes only schemas reports no changes
(`Changes.observe`): a store below is given its schemas apart, as an app gives its stores theirs. So that the suite runs
unchanged, the store made in its place installs into the store below it each install it is given, before itself: the
client, given an install, sends it to its service.
"""

from __future__ import annotations

import pytest
from mbse.Schemas.Framework import Builders

from mbse.Services.Rest import Service, Store

from conftest import transport
from notebooks import cells, namespace

SUITE = cells("mbse-journals", "03_Journals.ipynb")
InMemory = Builders.Store
SERVICES: list[Service.Service] = []


class Stacked(InMemory):
    """`Builders.Store()`, made over mbse-rest's client of a service of its own."""

    def __init__(self, below=None):
        if below is None:
            api = Service.app(below=InMemory())
            SERVICES.append(api.state.service)
            below = Store.Store(transport(api))
        super().__init__(below)

    def transaction(self, spec=None):
        if Builders._is_function(spec):  # an install: the store below's schemas first
            self._below.transaction(spec)
        return super().transaction(spec)


@pytest.fixture(scope="module")
def run():
    """Runs the setup cell, each store it makes kept over REST, then gives each case's cell to run, in order."""
    ((_, setup), *_) = SUITE
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Builders, "Store", Stacked)
        scope = namespace()
        exec(setup, scope)
        yield lambda source: exec(source, scope)


@pytest.mark.parametrize("source", [pytest.param(source, id=case) for case, source in SUITE[1:]])
def test_jrn_case_kept_over_rest(run, source):
    run(source)


def test_every_store_the_suite_made_is_kept_over_rest(run):
    """Each of the suite's stores wrote its journal through its own service, to the service's store below."""
    assert len(SERVICES) >= 6  # the model, the journals, the replica, again, here and there
    assert all(service.head > 0 for service in SERVICES)
