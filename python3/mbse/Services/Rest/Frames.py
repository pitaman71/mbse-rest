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

Reading one back gives a `Transactions.Frame` of the reading store's: each symbol's object by its reference (a
`References.OfObject` of that store), a schema object, by its path from the root module, as the schema object the
store holds; what it assigns, by symbol, each value read by the schema the reading store gives it; its errors, each
error as its kind names it (`ValueError`, `TypeError`, `LookupError`, else `RuntimeError`); its scope; its remainder, a
position in the expression the reader gave (`Transactions.Remainder`); and its journal, a one-transaction
`Changes.Journal`. A completion marker is `{"end": scope}`, with its `journal` where it carries one.

What cannot cross is refused, not lost: a frame binding an object that has no reference, a counted one, or that the
store reading it does not hold, a schema object, has that symbol left out, and is annotated with the error saying why
(`LookupError`), as a term's error is annotated (mbse-basis
[CAP-309: errors annotated on frames](mbse:mbse-basis/docs/capabilities/README.md#CAP-309)), so that the transaction
raises it at its end.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from mbse.Schemas.Framework import Errors, Plain, References, Transactions
from mbse.Schemas.Framework.Transactions import Frame, FrameError, Remainder

__all__ = ["ERRORS", "END", "item", "frame", "read_frame", "read_item", "at", "error_of", "crossing"]

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


def _refusal(name: str, error: LookupError) -> str:
    message = str(error)
    return message if message.startswith(f"symbol {name!r} of the frame") else f"symbol {name!r} of the frame: {message}"


def crossing(given: Frame) -> Frame:
    """A frame as it crosses: where a symbol binds what has no reference, a counted object, it is left out, and the
    frame annotated with why (`LookupError`), at its remainder, else at `$`."""
    bound: dict[str, Any] = {}
    errors = list(given.errors)
    for name in dict.keys(given):
        try:
            bound[name] = given[name]
        except LookupError as error:
            message = _refusal(name, error)
            errors.append(FrameError(given.remainder.subterm if given.remainder is not None else "$",
                                     "LookupError", message, LookupError(message)))
    if len(bound) == len(given):
        return given
    assigns = {name: values for name, values in given.assigns.items() if name in bound}
    return Frame(bound, errors, assigns, given.remainder, given.scope, given.journal)


def frame(store: Any, given: Mapping[str, Any]) -> PlainData:
    """An input frame as plain data, a `References.OfFrame` of `store`'s, refused where it binds what has no
    reference."""
    return Plain.ToPlain(store)(store.registered("References.OfFrame"), References.of(store, given))


def item(store: Any, given: Mapping[str, Any]) -> PlainData:
    """An item of a frame stream `txn.exec` gave, as plain data: a `References.OfItem` holding the frame
    (`crossing`) or the completion marker."""
    if isinstance(given, Frame):
        reference = References.of(store, crossing(given))
        wrapped = store.References.OfItem(lambda u: u.frame(reference))
    else:
        reference = References.of(store, given)
        wrapped = store.References.OfItem(lambda u: u.end(reference))
    return Plain.ToPlain(store)(store.registered("References.OfItem"), wrapped)


def _object(store: Any, plain: PlainData) -> Any:
    """What a symbol binds, read in `store`: a schema object by its path from the root module, as the schema object
    it holds, None where it holds none; else the object's reference, a `References.OfObject` of the store's."""
    path = plain.get("path") if isinstance(plain, Mapping) else None
    if isinstance(path, Mapping) and path.get("singleton") == ".":
        return store.held(path)
    return Plain.FromPlain(store)(store.registered("References.OfObject"), plain)


def _value(store: Any, plain: PlainData) -> Any:
    """A value of any schema, as `References.OfValue` reads one in `store`."""
    holder = Plain.FromPlain(store)(store.registered("References.OfValue"), {"value": plain})
    return store.member(holder, "value")


def _journal(store: Any, plain: PlainData) -> Any:
    """A frame's or a marker's journal, a `Changes.Transaction` as plain data, as the one-transaction `Changes.Journal`
    a frame carries in a process."""
    return Plain.FromPlain(store)(store.registered("Changes.Journal"), [plain])


def read_frame(store: Any, plain: PlainData, transaction: Any = None) -> Frame:
    """A `References.OfFrame`, as plain data, as a frame of `store`'s (`Transactions.Frame`): its bindings, errors,
    scope, what it assigns, its journal and, where `transaction` is the expression it was executed over, its
    remainder in it. A symbol binding a schema object the store does not hold is left out, and the frame annotated."""
    if not isinstance(plain, Mapping):
        raise ValueError("a frame is a References.OfFrame, a JSON object")
    bound: dict[str, Any] = {}
    errors = [FrameError(e.get("subterm", "$"), e.get("kind", "RuntimeError"), e.get("message", ""),
                         error_of(e.get("kind", "RuntimeError"), e.get("message", "")))
              for e in (plain.get("errors") or [])]
    paths: list[tuple[str, str]] = []
    for name, reference in (plain.get("binds") or {}).items():
        found = _object(store, reference)
        if found is None:
            message = f"symbol {name!r} of the frame: a schema object the layer it goes to does not hold"
            errors.append(FrameError(plain.get("remainder") or "$", "LookupError", message, LookupError(message)))
            continue
        bound[name] = found
        paths.append((name, json.dumps(reference, sort_keys=True)))
    assigns: dict[str, dict[str, Any]] = {}
    for witnessed in plain.get("assigns") or []:
        key = json.dumps(witnessed.get("object"), sort_keys=True)
        values = {name: _value(store, value) for name, value in (witnessed.get("properties") or {}).items()}
        for name, path in paths:
            if path == key:
                assigns.setdefault(name, {}).update(values)
    remainder = plain.get("remainder")
    return Frame(bound, errors, assigns,
                 None if remainder is None or transaction is None else Remainder(transaction, at(remainder)),
                 plain.get("scope"), None if plain.get("journal") is None else _journal(store, plain["journal"]))


def read_item(store: Any, plain: PlainData, transaction: Any) -> Frame | dict[str, Any]:
    """An item of a frame stream, a `References.OfItem` as plain data, as `txn.exec` gives it in a process: a frame
    (`read_frame`), or the completion marker `{"end": scope}`, with its `journal` where it carries one."""
    if not isinstance(plain, Mapping) or len(plain) != 1:
        raise ValueError("an item of a frame stream is a References.OfItem: {\"frame\": ...} or {\"end\": ...}")
    if "frame" in plain:
        return read_frame(store, plain["frame"], transaction)
    end = plain.get("end")
    if not isinstance(end, Mapping):
        raise ValueError("an item of a frame stream is a References.OfItem: {\"frame\": ...} or {\"end\": ...}")
    marker: dict[str, Any] = {"end": end.get("scope")}
    if end.get("journal") is not None:
        marker["journal"] = _journal(store, end["journal"])
    return marker


def is_frame(x: Any) -> bool:
    """Whether an item of a stream is a frame, not a completion marker."""
    return isinstance(x, Transactions.Frame)
