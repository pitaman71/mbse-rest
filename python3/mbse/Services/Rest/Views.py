"""The logical view kinds (mbse-basis [FEA-003: no-code logical views](../../../../../mbse-basis/docs/features/FEA-003.md)): what each includes, and its template ([CAP-004: logical view templates](../../../../../mbse-basis/docs/capabilities/CAP-004.md)).

One definition, shared by the server, which fills each frame's `assigns` and `entries` ([CAP-012: logical view endpoints](../../../../../mbse-basis/docs/capabilities/CAP-012.md)), and the client
(`typescript5/mbse/Services/Rest/Views.ts`), which reads them. `docs/CONTRACT.md` is the prose; the golden corpus in
`conformance/` checks that both agree.

| Kind | Symbols | Includes, for each frame |
|---|---|---|
| `label` ([CAP-005: label and summary view](../../../../../mbse-basis/docs/capabilities/CAP-005.md)) | `x` | the label and summary properties `x` holds |
| `chip` ([CAP-006: chip view](../../../../../mbse-basis/docs/capabilities/CAP-006.md)) | `x` | `label`'s, then the first three other scalar properties `x`'s schema declares that it holds |
| `detail` ([CAP-007: detail view](../../../../../mbse-basis/docs/capabilities/CAP-007.md)) | `x` | every property `x` holds; every entry of its named adjacencies; each linked object's `label`; `x`'s provenance |
| `adjacency` ([CAP-008: adjacency as a list of chips](../../../../../mbse-basis/docs/capabilities/CAP-008.md)) | `x`, `y` | every entry of `x`'s named adjacencies that links `y`; `y`'s `chip`; `y`'s provenance |

An object's provenance ([CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md)), where its schema has a history: the records of the transactions that created it and
last wrote it (`when`, `where`), each one's session (`started`, `locale`, `device`) and the session's identity, and the
entries linking them (`CreatedBy`, `ModifiedBy`, `InSession`, `Who`).

A template is a transaction of one map whose pattern declares the kind's symbols, each given neither a schema nor a
reference: the client gives each one exactly one ([CAP-004: logical view templates](../../../../../mbse-basis/docs/capabilities/CAP-004.md)). The `adjacency` template's spec is added by the client,
`_.x.<adjacency>([_.y])`, once `x` is given, since an adjacency is a member of `x`'s schema.

Counted objects have no reference, so a frame that binds one, and an entry that links one, are left out ([FEA-003: no-code logical views](../../../../../mbse-basis/docs/features/FEA-003.md)).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mbse.Schemas.Framework import Plain, References
from mbse.Schemas.Framework import Schemas as S

__all__ = ["KINDS", "SYMBOLS", "LABELS", "SUMMARIES", "CHIP_SCALARS", "template", "templates", "label_property",
           "summary_property", "chip_properties", "witness"]

KINDS = ("label", "chip", "detail", "adjacency")
SYMBOLS = {"label": ("x",), "chip": ("x",), "detail": ("x",), "adjacency": ("x", "y")}
LABELS = ("label", "name", "title")  # [CAP-005: label and summary view](../../../../../mbse-basis/docs/capabilities/CAP-005.md): the label is the first of these
SUMMARIES = ("summary", "description")  # [CAP-005: label and summary view](../../../../../mbse-basis/docs/capabilities/CAP-005.md): the summary is the first of these
CHIP_SCALARS = 3  # [CAP-006: chip view](../../../../../mbse-basis/docs/capabilities/CAP-006.md): the other scalar properties a chip includes


def template(store: Any, kind: str) -> Any:
    """The kind's template, a `Mutations.OfTransaction` of the store's: one map over the kind's symbols, unassigned."""
    names = SYMBOLS[kind]
    return store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(lambda m: m.symbols([lambda p: p
        .symbols([lambda s, n=n: s.name(n) for n in names])]))]))


def templates(store: Any) -> dict[str, Any]:
    """Each kind's template, by kind, in `KINDS` order."""
    return {kind: template(store, kind) for kind in KINDS}


def _held(obj: Any, name: str) -> bool:
    return name in obj.as_schema().properties and getattr(obj, name).get() is not None


def label_property(obj: Any) -> str | None:
    """The property that gives `obj`'s label: the first of `LABELS` it holds; None where it holds none."""
    return next((name for name in LABELS if _held(obj, name)), None)


def summary_property(obj: Any) -> str | None:
    """The property that gives `obj`'s summary: the first of `SUMMARIES` it holds; None where it holds none."""
    return next((name for name in SUMMARIES if _held(obj, name)), None)


def chip_properties(obj: Any) -> list[str]:
    """A chip's properties ([CAP-006: chip view](../../../../../mbse-basis/docs/capabilities/CAP-006.md)): the label's and the summary's, then the first `CHIP_SCALARS` other scalar
    properties the schema declares that `obj` holds, in the schema's order."""
    first = [name for name in (label_property(obj), summary_property(obj)) if name is not None]
    others = [name for name, prop in obj.as_schema().properties.items()
              if name not in first and isinstance(prop.schema, S.OfScalar.Data) and _held(obj, name)]
    return first + others[:CHIP_SCALARS]


def _properties(obj: Any, kind: str) -> list[str]:
    if kind == "label":
        return [name for name in (label_property(obj), summary_property(obj)) if name is not None]
    if kind == "chip":
        return chip_properties(obj)
    return [name for name in obj.as_schema().properties if _held(obj, name)]  # detail: every property it holds


def _reference(store: Any, obj: Any) -> Any | None:
    try:
        return References.of(store, obj)
    except LookupError:  # a counted object: nothing names it
        return None


class _Witness:
    """What one frame witnesses: each object's assigned properties, once, and each entry, once, in the order met."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.assigns: list[Any] = []
        self.entries: list[Any] = []
        self._assigned: dict[int, int] = {}  # each object assigned, by id: its position in `assigns`
        self._entered: set[str] = set()  # each entry witnessed, by its reference

    def assign(self, obj: Any, kind: str) -> None:
        if id(obj) in self._assigned:
            return
        reference = _reference(self.store, obj)
        names = _properties(obj, kind)
        if reference is None or not names:
            return
        values = {name: getattr(obj, name).get() for name in names}
        self._assigned[id(obj)] = len(self.assigns)
        self.assigns.append(lambda x: x.as_object(lambda p: p.object(reference).properties(values)))

    def enter(self, entry: Any) -> bool:
        """Witnesses `entry`, unless it links a counted object; whether it is witnessed."""
        try:
            reference = References.of(self.store, entry)
        except LookupError:
            return False
        key = json.dumps(Plain.ToPlain(self.store)(reference.as_schema(), reference), sort_keys=True)
        if key not in self._entered:
            self._entered.add(key)
            self.entries.append(reference)
        return True


def _history(store: Any, reference: Any) -> list[tuple[str, Mapping[str, Any]]]:
    """The provenance of the object `reference` designates ([CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md)): for `created` and `modified`, each frame binding
    `t`, the transaction record that created (or last wrote) it, `s`, its session, and `i`, the session's identity.
    Read from the records' side, since an object's adjacencies to them are anonymous; none where the store has no
    `Provenance`, or the object's schema no history."""
    try:
        records, sessions, identities = (store.registered(name) for name in (
            "Provenance.OfTransaction", "Provenance.OfSession", "Provenance.OfIdentity"))
    except LookupError:  # Provenance is not installed
        return []
    found = []
    for relation in ("created", "modified"):
        frames = store.transaction(lambda t, r=relation: t.mutations([lambda mu: mu.map(lambda m: m.symbols([lambda p: p
            .symbols({"c": reference, "t": records, "s": sessions, "i": identities})
            .spec([lambda _: getattr(_.t, r)([_.c]), lambda _: _.t.session([_.s]), lambda _: _.s.who([_.i])])]))]))
        found.extend((relation, frame) for frame in frames)
    return found


def _witness_history(seen: "_Witness", obj: Any) -> None:
    """Witnesses `obj`'s provenance ([CAP-015: transaction provenance](../../../../../mbse-basis/docs/capabilities/CAP-015.md)): each record, its session and identity, with what they hold, and the
    entries linking them: `CreatedBy` and `ModifiedBy` (from the record), `InSession`, `Who`."""
    reference = _reference(seen.store, obj)
    if reference is None:
        return
    for relation, frame in _history(seen.store, reference):
        record, session, identity = frame["t"], frame["s"], frame["i"]
        for entry in getattr(record, relation):
            if entry.object is obj:
                seen.enter(entry)
        for entry in record.session:
            seen.enter(entry)
        for entry in session.who:
            seen.enter(entry)
        seen.assign(record, "detail")
        seen.assign(session, "detail")
        seen.assign(identity, "detail")


def _linked(obj: Any, entry: Any, adjacency: Any) -> list[Any]:
    """What `entry`, held by `obj`'s `adjacency`, links besides `obj`."""
    return [getattr(entry, link) for link in adjacency.relation.entry.links if link != adjacency.me]


def witness(store: Any, kind: str, frame: Mapping[str, Any]) -> Any | None:
    """The frame's `References.OfFrame`, its `assigns` and `entries` filled as `kind` defines; None where it binds a
    counted object, which has no reference."""
    binds = {}
    for name, obj in frame.items():
        binds[name] = _reference(store, obj)
        if binds[name] is None:
            return None
    seen = _Witness(store)
    x = frame["x"]
    if kind in ("label", "chip", "detail"):
        seen.assign(x, kind)
    if kind == "detail":
        _witness_history(seen, x)
        for name, adjacency in x.as_schema().adjacencies.items():
            for entry in getattr(x, name):
                if seen.enter(entry):
                    for other in _linked(x, entry, adjacency):
                        seen.assign(other, "label")
    if kind == "adjacency":
        y = frame["y"]
        for name, adjacency in x.as_schema().adjacencies.items():
            for entry in getattr(x, name):
                if any(other is y for other in _linked(x, entry, adjacency)):
                    seen.enter(entry)
        seen.assign(y, "chip")
        _witness_history(seen, y)
    return store.References.OfFrame(lambda f: f.binds(binds).assigns(seen.assigns).entries(seen.entries))
