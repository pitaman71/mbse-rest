"""The persistence plugin interface (mbse-basis CAP-013), and its in-memory reference implementation.

The service holds its store in memory and executes transactions over it. A plugin makes that store outlive the
process: `load` fills a fresh store at startup from the latest snapshot and the journal after it, `journal` records a
committed transaction that writes, and `snapshot` records the whole store, after which the journal before it is no
longer needed. What a plugin is given and gives back is mbse-schemas' wire form, so a plugin never sees a proxy:

- a transaction is its expression, `Plain.ToPlain(store).Transaction(tx)`, read back with
  `Plain.FromPlain(store).Transaction(plain)` and executed;
- a snapshot is `Plain.ToPlain(store).Snapshot()`, two transactions, read back with
  `Plain.FromPlain(store).Snapshot(snapshot)`.

`mbse.Persistence.DynamoDB` (mbse-dynamodb) implements this protocol over DynamoDB; `Memory`, below, is the reference
every implementation must agree with, and `replay` is the startup every implementation shares.
"""

from __future__ import annotations

import copy
from typing import Any, Protocol, runtime_checkable

from mbse.Schemas.Framework import Plain

__all__ = ["PlainData", "Plugin", "Memory", "replay"]

PlainData = Any  # mbse-schemas' plain data: mappings, lists, strings, numbers, booleans and None


@runtime_checkable
class Plugin(Protocol):
    """What the service needs of its persistence."""

    def load(self) -> tuple[list[PlainData] | None, list[PlainData]]:
        """At startup: the latest snapshot (None where there is none) and every transaction journaled after it, in the
        order they committed."""
        ...

    def journal(self, transaction: PlainData) -> None:
        """Records one committed transaction that writes, its expression. Called after it commits, in commit order;
        a transaction that is refused is never journaled."""
        ...

    def snapshot(self, snapshot: list[PlainData]) -> None:
        """Records the whole store as it stands after every transaction journaled so far; `load` then gives it, and
        only what is journaled after it."""
        ...


def replay(store: Any, plugin: Plugin) -> bool:
    """Fills `store`, fresh, from what `plugin` holds: its latest snapshot, then its journal after it, each
    transaction executed in order. Whether the plugin held anything."""
    snapshot, journal = plugin.load()
    if snapshot is not None:
        Plain.FromPlain(store).Snapshot(snapshot)
    for plain in journal:
        store.transaction(Plain.FromPlain(store).Transaction(plain))
    return snapshot is not None or bool(journal)


class Memory:
    """The reference plugin: a snapshot and a journal held in memory, as a database would hold them. A copy of what is
    given is kept, so that what the service does after cannot change it."""

    def __init__(self) -> None:
        self.snapshots: list[list[PlainData]] = []
        self.entries: list[PlainData] = []  # the journal, every transaction since the store was made
        self._since = 0  # the journal's length when the latest snapshot was taken

    def load(self) -> tuple[list[PlainData] | None, list[PlainData]]:
        latest = copy.deepcopy(self.snapshots[-1]) if self.snapshots else None
        return latest, copy.deepcopy(self.entries[self._since:])

    def journal(self, transaction: PlainData) -> None:
        self.entries.append(copy.deepcopy(transaction))

    def snapshot(self, snapshot: list[PlainData]) -> None:
        self.snapshots.append(copy.deepcopy(snapshot))
        self._since = len(self.entries)
