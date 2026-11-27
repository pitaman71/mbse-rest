"""A frame stream across HTTP: frames and completion markers as mbse-schemas writes them, `References.OfFrame` and
`References.OfItem` as plain data, read and written by the service and its client alike (mbse-basis
[the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md#a-cache-layer-and-the-layer-below), its third stage).

A frame stream has no wire format of its own (mbse-basis
[PRI-018: no model needs code to read or write](mbse:mbse-basis/docs/PRINCIPLES.md#PRI-018)): each item is
`References.of(store, item)`, wrapped as a `References.OfItem`, written by `Plain.ToPlain(store)`, one JSON document a
line, `{"frame": ...}` or `{"end": ...}`; the stream's last item is the completion marker of the whole stream,
`{"end": {}}`, the plain form of `{"end": None}`, so that a reader knows that nothing is missing. An input frame is a
`References.OfFrame` as plain data. What crosses is carried as written
([PRI-024: the plain form, carried as written](mbse:mbse-basis/docs/PRINCIPLES.md#PRI-024)).

Each frame is its journal (mbse-schemas 0.38, mbse-basis
[CAP-318: support for decoupled code](mbse:mbse-basis/docs/capabilities/README.md#CAP-318)): `{"frame": {"journal", "scope",
"remainder", "errors", "terminal"}}`, its journal a `Changes.Transaction` whose `symbols` are the frame's bindings,
an object by its `References.OfObject`, a schema object by its `References.OfSchema`, and whose `changes` are the
state its path's clauses referenced or changed. A completion marker is `{"end": {"scope"}}`, and carries nothing else.
A frame written before a frame was its journal, with `binds` and `assigns`, is refused where it is read.

Reading one back gives a `Transactions.Frame` of the reading store's: each symbol's object by its reference (a
`References.OfObject` of that store, a schema object's a `References.OfSchema`), read from its journal; its errors, each error as its kind names it (`ValueError`, `TypeError`, `LookupError`, else
`RuntimeError`); its scope; its remainder, a position in the expression the reader gave (`Transactions.Remainder`);
its journal, a `Changes.Transaction` of the reading store's; and whether it is terminal, a routing mark passed through
to the layer that commits.

What cannot cross is refused, not lost: a frame binding an object that has no reference, a counted one, has that
symbol left out of its journal, and is annotated with the error saying why (`LookupError`), as mbse-schemas writes it
(`References.of`), so that the transaction raises it at its end (mbse-basis
[CAP-309: errors annotated on frames](mbse:mbse-basis/docs/capabilities/README.md#CAP-309)). A schema object crosses by
its reference from the root module, a `References.OfSchema`, data, which the layer it goes to resolves where it holds
what it designates.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from mbse.Schemas.Framework import Errors, Plain, References, Transactions
from mbse.Schemas.Framework.Transactions import Frame, FrameError, Remainder

__all__ = ["ERRORS", "END", "item", "frame", "read_frame", "read_item", "at", "error_of", "is_frame"]

PlainData = Any

ERRORS: dict[str, type[Exception]] = {"ValueError": ValueError, "TypeError": TypeError, "LookupError": LookupError}
"""The errors a frame's error annotation is read back as, by the name of its kind; any other kind is a `RuntimeError`."""

END: PlainData = {"end": {}}
"""The last item of a stream: the completion marker of the whole stream, `{"end": None}`, as mbse-schemas writes it."""

_STEP = re.compile(r'\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\[("(?:[^"\\]|\\.)*")\]')


def at(subterm: str) -> tuple[str | int, ...]:
    """The position a subterm names, `$.mutations[0].map.then[0].update`, as a `Transactions.Remainder` holds it:
    `("mutations", 0, "map", "then", 0, "update")`; refused (`ValueError`) where it is no subterm."""
    if not subterm.startswith("$"):
        raise ValueError(f"not a subterm: {subterm!r}")
    steps: list[str | int] = []
    rest = subterm[1:]
    while rest:
        match = _STEP.match(rest)
        if match is None:
            raise ValueError(f"not a subterm: {subterm!r}")
        name, index, quoted = match.groups()
        steps.append(name if name is not None else int(index) if index is not None else json.loads(quoted))
        rest = rest[match.end():]
    if Errors.path(*steps) != subterm:
        raise ValueError(f"not a subterm: {subterm!r}")
    return tuple(steps)


def error_of(kind: str, message: str) -> Exception:
    """The error an annotation of `kind` stands for, raised where the transaction ends."""
    return ERRORS.get(kind, RuntimeError)(message)


def frame(store: Any, given: Mapping[str, Any]) -> PlainData:
    """An input frame as plain data, a `References.OfFrame` of `store`'s: its journal, its bindings each by its
    reference, and whether it is terminal; a symbol binding what has no reference left out, and annotated."""
    return Plain.ToPlain(store)(store.registered("References.OfFrame"), References.of(store, given))


def item(store: Any, given: Mapping[str, Any]) -> PlainData:
    """An item of a frame stream `txn.exec` gave, as plain data: a `References.OfItem` holding the frame, its journal,
    or the completion marker."""
    reference = References.of(store, given)
    wrapped = store.References.OfItem(lambda u: u.frame(reference) if isinstance(given, Frame) else u.end(reference))
    return Plain.ToPlain(store)(store.registered("References.OfItem"), wrapped)


_OLD = ("binds", "assigns", "entries", "variables")  # a frame's parts before it was its journal (mbse-schemas 0.38)


def read_frame(store: Any, plain: PlainData, transaction: Any = None, given: bool = False) -> Frame:
    """A `References.OfFrame`, as plain data, as a frame of `store`'s (`Transactions.Frame`): its bindings, read from its
    journal's symbols, each a reference, data, a schema object's a `References.OfSchema`, which the layer it goes to
    resolves; its errors, scope, journal and whether it is terminal; and, where `transaction` is the expression it was
    executed over, its remainder in it. An input frame, `given` to `txn.exec`, carries no journal, as a layer above
    gives one in a process: its journal is how its bindings cross. One written before a frame was its journal, with
    `binds` or `assigns`, is refused (`ValueError`)."""
    if not isinstance(plain, Mapping) or not isinstance(plain.get("errors", []), list):
        raise ValueError("a frame is a References.OfFrame, a JSON object: its journal a Changes.Transaction, its "
                         "errors a list")
    old = [name for name in _OLD if name in plain]
    if old:
        raise ValueError(f"a frame is a References.OfFrame, its journal a Changes.Transaction (mbse-schemas 0.38): "
                         f"its {', '.join(old)} are gone")
    journal_plain = plain.get("journal") or {}
    if not isinstance(journal_plain, Mapping) or not isinstance(journal_plain.get("symbols", {}), Mapping):
        raise ValueError("a frame's journal is a Changes.Transaction, a JSON object: its symbols an object")
    errors = [FrameError(e.get("subterm", "$"), e.get("kind", "RuntimeError"), e.get("message", ""),
                         error_of(e.get("kind", "RuntimeError"), e.get("message", "")))
              for e in (plain.get("errors") or [])]
    journal = Plain.FromPlain(store)(store.registered("Changes.Transaction"), journal_plain)
    reference = store.registered("References.OfObject")
    bound = {name: Plain.FromPlain(store)(reference, (symbol or {}).get("reference"))
             for name, symbol in (journal_plain.get("symbols") or {}).items()}
    remainder = plain.get("remainder")
    return Frame(bound, errors, None if remainder is None or transaction is None else Remainder(transaction, at(remainder)),
                 plain.get("scope"), None if given else journal, bool(plain.get("terminal", False)))


def read_item(store: Any, plain: PlainData, transaction: Any) -> Frame | dict[str, Any]:
    """An item of a frame stream, a `References.OfItem` as plain data, as `txn.exec` gives it in a process: a frame
    (`read_frame`), or the completion marker `{"end": scope}`, which carries nothing else."""
    if not isinstance(plain, Mapping) or len(plain) != 1:
        raise ValueError("an item of a frame stream is a References.OfItem: {\"frame\": ...} or {\"end\": ...}")
    if "frame" in plain:
        return read_frame(store, plain["frame"], transaction)
    end = plain.get("end")
    if not isinstance(end, Mapping):
        raise ValueError("an item of a frame stream is a References.OfItem: {\"frame\": ...} or {\"end\": ...}")
    return {"end": end.get("scope")}


def is_frame(x: Any) -> bool:
    """Whether an item of a stream is a frame, not a completion marker."""
    return isinstance(x, Transactions.Frame)
