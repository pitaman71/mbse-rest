"""The logical view kinds (mbse-basis [FEA-003: no-code logical views](mbse:mbse-basis/docs/features/FEA-003.md)): what each includes, and its template ([CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md)).

One definition, shared by the server, which writes each frame's journal ([CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md)), and the client
(`typescript5/mbse/Services/Rest/Views.ts`), which reads them. [FEA-003: no-code logical views](mbse:mbse-basis/docs/features/FEA-003.md#view-kinds) is the prose; the golden corpus in
`conformance/` checks that both agree.

| Kind | Symbols | Includes, for each frame |
|---|---|---|
| `label` ([CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md)) | `x` | the label and summary properties `x` holds |
| `chip` ([CAP-006: chip view](mbse:mbse-basis/docs/capabilities/CAP-006.md)) | `x` | `label`'s, then the first three other scalar properties `x`'s schema declares that it holds |
| `detail` ([CAP-007: detail view](mbse:mbse-basis/docs/capabilities/CAP-007.md)) | `x` | every property `x` holds; every entry of its named adjacencies; each linked object's `label`; `x`'s provenance |
| `adjacency` ([CAP-008: adjacency as a list of chips](mbse:mbse-basis/docs/capabilities/CAP-008.md)) | `x`, `y` | every entry of `x`'s named adjacencies that links `y`; `y`'s `chip`; `y`'s provenance |

An object's provenance ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md)), where its schema has a history: the records of the transactions that created it and
last wrote it (`when`, `where`), each one's session (`started`, `locale`, `device`) and the session's identity, and the
entries linking them (`CreatedBy`, `ModifiedBy`, `InSession`, `Who`).

A template is a transaction of one map whose pattern declares the kind's symbols, each given neither a schema nor a
reference: the client gives each one exactly one ([CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md)). The `adjacency` template's spec is added by the client,
`_.x.<adjacency>([_.y])`, once `x` is given, since an adjacency is a member of `x`'s schema.

Counted objects have no reference, so a frame that binds one, and an entry that links one, are left out ([FEA-003: no-code logical views](mbse:mbse-basis/docs/features/FEA-003.md)).

A frame a transaction gives back holds each object by its reference, and what reads an object lives only within a
transaction ([CAP-315: every read within a transaction or through a follow](mbse:mbse-basis/docs/capabilities/CAP-315.md)):
`witness` reads, within a transaction of its own, each object a frame binds again by its reference, found from its
singleton through the keyed entries that own it, as its path names them: a store whose objects are read through its
builders, one in memory. A store kept elsewhere (mbse-dynamodb's) is read only through its interpretation, `txn.exec`,
whose frames carry what their clauses name, and no clause of mbse-schemas 0.38 names a property without the value it
must hold: reading a view's properties that way waits on one (`variables`, mbse-basis
[CAP-142: expressions evaluated in queries](mbse:mbse-basis/docs/capabilities/CAP-142.md)).

What a frame of a view carries is its journal (mbse-schemas 0.38, [CAP-318: support for decoupled code](mbse:mbse-basis/docs/capabilities/README.md#CAP-318)), a
`Changes.Transaction`, written by hand as a witness, as mbse-schemas allows: its symbols the frame's, `x` and `y`, by
their references, then one of the journal's own, `o0`, `o1`, ..., for each other object whose properties it carries, in
the order met (a linked object's label, a provenance record, its session and identity); each entry it includes
inserted, its holder by its symbol, each other link by its symbol, else by its reference, with every property it
holds; then each object's properties, each set to its value. `properties` and `entries` read one back.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mbse.Schemas.Framework import Paths, Plain, References
from mbse.Schemas.Framework import Schemas as S

__all__ = ["KINDS", "SYMBOLS", "LABELS", "SUMMARIES", "CHIP_SCALARS", "template", "templates", "label_property",
           "summary_property", "chip_properties", "witness", "properties", "entries"]

KINDS = ("label", "chip", "detail", "adjacency")
SYMBOLS = {"label": ("x",), "chip": ("x",), "detail": ("x",), "adjacency": ("x", "y")}
LABELS = ("label", "name", "title")  # [CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md): the label is the first of these
SUMMARIES = ("summary", "description")  # [CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md): the summary is the first of these
CHIP_SCALARS = 3  # [CAP-006: chip view](mbse:mbse-basis/docs/capabilities/CAP-006.md): the other scalar properties a chip includes


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
    """A chip's properties ([CAP-006: chip view](mbse:mbse-basis/docs/capabilities/CAP-006.md)): the label's and the summary's, then the first `CHIP_SCALARS` other scalar
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


def _found(store: Any, reference: Any) -> Any | None:
    """Within the transaction open, the object `reference` designates: from its path's singleton, through each entry
    of the owner's adjacency the step names whose keys are the step's, to what it links besides the owner; None where
    the store holds none, or the path is a schema object's or steps through an adjacency with no name."""
    path = Plain.ToPlain(store)(reference.as_schema(), reference)["path"]
    try:
        found = store.singleton(path["singleton"])
    except LookupError:  # a schema object's path, from the root module ("."), or no singleton the store holds
        return None
    step = path["next"]
    while found is not None and "entry" in step:
        step = step["entry"]
        found, step = _owned(found, step["i"], step["properties"]), step["next"]
    return found


def _owned(owner: Any, name: str, keys: Mapping[str, Any]) -> Any | None:
    """What `owner` owns through its adjacency `name` by the entry whose keys are `keys`; None where none."""
    adjacency = owner.as_schema().adjacencies.get(name)
    if adjacency is None:
        return None
    (link,) = [link for link in adjacency.relation.entry.links if link != adjacency.me]
    for entry in getattr(owner, name):
        if all(getattr(entry, key).get() == value for key, value in keys.items()):
            return getattr(entry, link)
    return None


class _Witness:
    """What one frame witnesses, written as its journal ([CAP-318: support for decoupled code](mbse:mbse-basis/docs/capabilities/README.md#CAP-318), a `Changes.Transaction`): its
    symbols, the frame's own, by their references, then one of the journal's own for each other object whose
    properties it carries (`o0`, `o1`, ... in the order met); each entry inserted, once, its holder by its symbol, each
    other link by its symbol, else by its reference, with every property it holds; then each object's properties,
    once, each set to its value."""

    def __init__(self, store: Any, binds: Mapping[str, Any]) -> None:
        self.store = store
        self.symbols: dict[str, Any] = {}
        self._named: dict[str, str] = {}  # each symbol, by its object's reference's key
        self._others = 0
        self._entries: list[tuple[Any, str, dict[str, Any], dict[str, Any]]] = []
        self._entered: set[str] = set()  # each entry witnessed, by its reference's key
        self._assigned: set[str] = set()  # each object assigned, by its reference's key
        self._sets: list[dict[str, Any]] = []
        for name, reference in binds.items():
            self._name(name, reference)

    def _plain(self, reference: Any) -> Any:
        return Plain.ToPlain(self.store)(reference.as_schema(), reference)

    def _name(self, name: str, reference: Any, schema: Any = None) -> str:
        plain = self._plain(reference)
        symbol: dict[str, Any] = {"reference": plain}
        if schema is not None:
            try:
                implied = References.implied(self.store, plain["path"])
            except LookupError:
                implied = None
            if implied is not schema:  # where its path does not imply it, as mbse-schemas writes a symbol
                symbol["schema"] = Plain.ToPlain(self.store)(self.store.registered("References.OfSchema"),
                                                             self.store.References.OfSchema(lambda r: r.path(
                                                                 Paths.of(schema))))
        self.symbols[name] = symbol
        self._named.setdefault(json.dumps(plain, sort_keys=True), name)
        return name

    def symbol(self, obj: Any) -> str | None:
        """The symbol that binds `obj`, one of the journal's own where none does; None where it has no reference."""
        reference = _reference(self.store, obj)
        if reference is None:
            return None
        found = self._named.get(json.dumps(self._plain(reference), sort_keys=True))
        if found is not None:
            return found
        name = f"o{self._others}"
        while name in self.symbols:  # one the frame binds itself
            self._others += 1
            name = f"o{self._others}"
        self._others += 1
        return self._name(name, reference, obj.as_schema())

    def assign(self, obj: Any, kind: str) -> None:
        reference = _reference(self.store, obj)
        names = _properties(obj, kind)
        if reference is None or not names:
            return
        key = json.dumps(self._plain(reference), sort_keys=True)
        if key in self._assigned:
            return
        self._assigned.add(key)
        holder, schema = self.symbol(obj), obj.as_schema()
        self._sets += [{"property": {"set": {"holder": holder, "name": name, "value": Plain.ToPlain(self.store)(
            schema.properties[name].schema, getattr(obj, name).get())}}} for name in names]

    def enter(self, holder: Any, name: str, entry: Any) -> bool:
        """Witnesses `entry`, held by `holder`'s adjacency `name`, unless it links a counted object; whether it is
        witnessed."""
        try:
            reference = References.of(self.store, entry)
        except LookupError:
            return False
        key = json.dumps(self._plain(reference), sort_keys=True)
        if key not in self._entered:
            self._entered.add(key)
            adjacency = holder.as_schema().adjacencies[name]
            relation = adjacency.relation.entry
            links = {link: getattr(entry, link) for link in relation.links if link != adjacency.me}
            values = {prop: Plain.ToPlain(self.store)(relation.properties[prop].schema, getattr(entry, prop).get())
                      for prop in relation.properties if getattr(entry, prop).get() is not None}
            self._entries.append((holder, name, links, values))
        return True

    def journal(self) -> Any:
        """The journal: its symbols, each entry inserted, then each property set."""
        inserts = []
        for holder, name, links, values in self._entries:
            body: dict[str, Any] = {"holder": {"symbol": self.symbol(holder)}, "adjacency": name, "links": {
                link: self._link(obj) for link, obj in links.items()}}
            if values:
                body["properties"] = values
            inserts.append({"entry": {"insert": body}})
        plain = {"symbols": self.symbols, "changes": [*inserts, *self._sets]}
        return Plain.FromPlain(self.store)(self.store.registered("Changes.Transaction"), plain)

    def _link(self, obj: Any) -> Any:
        """What an entry names a linked object by, a `Changes.OfLink`: its symbol, where one binds it; else its
        reference."""
        reference = References.of(self.store, obj)
        plain = self._plain(reference)
        found = self._named.get(json.dumps(plain, sort_keys=True))
        return {"symbol": found} if found is not None else {"reference": plain}


def _history(store: Any, reference: Any) -> list[tuple[str, Mapping[str, Any]]]:
    """The provenance of the object `reference` designates ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md)): for `created` and `modified`, each frame binding
    `t`, the transaction record that created (or last wrote) it, `s`, its session, and `i`, the session's identity.
    Read from the records' side, since an object's adjacencies to them are anonymous, by a map over every record:
    slow for a long history until [CAP-178: an object's provenance read through its own named adjacencies](mbse:mbse-basis/docs/capabilities/CAP-178.md). None where the store has no
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


def _witness_history(seen: "_Witness", obj: Any, history: list[tuple[str, Mapping[str, Any]]]) -> None:
    """Witnesses `obj`'s provenance ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md)), `history`, read before the transaction open: each record, its
    session and identity, with what they hold, read again within it, and the entries linking them: `CreatedBy` and
    `ModifiedBy` (from the record), `InSession`, `Who`."""
    for relation, frame in history:
        record, session, identity = (_found(seen.store, frame[symbol]) for symbol in ("t", "s", "i"))
        if record is None or session is None or identity is None:
            continue
        for entry in getattr(record, relation):
            if entry.object is obj:
                seen.enter(record, relation, entry)
        for entry in record.session:
            seen.enter(record, "session", entry)
        for entry in session.who:
            seen.enter(session, "who", entry)
        seen.assign(record, "detail")
        seen.assign(session, "detail")
        seen.assign(identity, "detail")


def _linked(obj: Any, entry: Any, adjacency: Any) -> list[Any]:
    """What `entry`, held by `obj`'s `adjacency`, links besides `obj`."""
    return [getattr(entry, link) for link in adjacency.relation.entry.links if link != adjacency.me]


def witness(store: Any, kind: str, frame: Mapping[str, Any]) -> Any | None:
    """The `References.OfFrame` of a frame a transaction gave back, its journal (`_Witness`): each object it binds by
    its reference, and the properties and entries `kind` includes, read within a transaction of its own; None where it binds a
    counted object, which has no reference, or an object the store no longer holds."""
    try:
        binds = {name: frame[name] for name in frame}
    except LookupError:  # a counted object: the frame refuses it
        return None
    witnessed = {"detail": "x", "adjacency": "y"}.get(kind)
    history = [] if witnessed is None else _history(store, binds[witnessed])  # a transaction of its own, first
    with store.transaction():
        objects = {name: _found(store, reference) for name, reference in binds.items()}
        if any(obj is None for obj in objects.values()):
            return None
        seen = _Witness(store, binds)
        x = objects["x"]
        if kind in ("label", "chip", "detail"):
            seen.assign(x, kind)
        if kind == "detail":
            _witness_history(seen, x, history)
            for name, adjacency in x.as_schema().adjacencies.items():
                for entry in getattr(x, name):
                    if seen.enter(x, name, entry):
                        for other in _linked(x, entry, adjacency):
                            seen.assign(other, "label")
        if kind == "adjacency":
            y = objects["y"]
            for name, adjacency in x.as_schema().adjacencies.items():
                for entry in getattr(x, name):
                    if any(other is y for other in _linked(x, entry, adjacency)):
                        seen.enter(x, name, entry)
            seen.assign(y, "chip")
            _witness_history(seen, y, history)
        journal = seen.journal()
        return store.References.OfFrame(lambda f: f.journal(journal))


def properties(frame: Mapping[str, Any], symbol: str = "x") -> dict[str, Any]:
    """The properties a view's frame, a `References.OfFrame` as plain data, carries of the object `symbol` binds, one of
    the journal's own among them: each property its journal sets, its value as plain data, in the order set."""
    found: dict[str, Any] = {}
    for change in (frame.get("journal") or {}).get("changes") or []:
        body = change.get("property", {}).get("set")
        if body is not None and body["holder"] == symbol:
            found[body["name"]] = body["value"]
    return found


def entries(frame: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The relation entries a view's frame, a `References.OfFrame` as plain data, carries: each entry its journal
    inserts, as plain data, its `holder`, `adjacency`, `links` and `properties`, in order."""
    return [change["entry"]["insert"] for change in (frame.get("journal") or {}).get("changes") or []
            if "insert" in change.get("entry", {})]
