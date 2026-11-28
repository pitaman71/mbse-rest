/** The logical view kinds (mbse-basis [FEA-003: no-code logical views](mbse:mbse-basis/docs/features/FEA-003.md)), the client's side: each kind's template filled, and what a
 * frame of each kind carries read back ([CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md) to [CAP-008: adjacency as a list of chips](mbse:mbse-basis/docs/capabilities/CAP-008.md)). The server's side is `python3/mbse/Services/Rest/Views.py`;
 * [FEA-003: no-code logical views](mbse:mbse-basis/docs/features/FEA-003.md#view-kinds) is the prose, and the golden corpus in `conformance/` checks that both agree. */

import { JSON as J, Plain, References } from "@mbse/schemas/Framework";

export const KINDS = ["label", "chip", "detail", "adjacency"] as const;
export type Kind = (typeof KINDS)[number];
/** Each kind's symbols: `x` is the object viewed; in `adjacency`, `y` is what `x` links. */
export const SYMBOLS: Readonly<Record<Kind, readonly string[]>> = {
  label: ["x"], chip: ["x"], detail: ["x"], adjacency: ["x", "y"],
};
export const LABELS = ["label", "name", "title"] as const; // [CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md): the label is the first of these
export const SUMMARIES = ["summary", "description"] as const; // [CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md): the summary is the first of these
export const CHIP_SCALARS = 3; // [CAP-006: chip view](mbse:mbse-basis/docs/capabilities/CAP-006.md): the other scalar properties a chip includes

/** A kind's template, its symbols given ([CAP-004: logical view templates](mbse:mbse-basis/docs/capabilities/CAP-004.md), [CAP-012: logical view endpoints](mbse:mbse-basis/docs/capabilities/CAP-012.md)): each one a schema (`store.registered("work.Task")`), which
 * ranges over every extant object of it, or a `References.OfObject` value, which binds the one object it designates.
 * For `adjacency`, `adjacency` names the adjacency of `x`'s schema whose entries link `y`, written in the spec,
 * `_.x.<adjacency>([_.y])`. Gives the transaction's expression, the request's body. */
export function request(store: any, kind: Kind, given: Readonly<Record<string, unknown>>, adjacency?: string):
    Plain.PlainMap {
  const names = SYMBOLS[kind];
  const missing = names.filter((name) => given[name] === undefined);
  const extra = Object.keys(given).filter((name) => !names.includes(name));
  if (missing.length > 0 || extra.length > 0) {
    throw new TypeError(`the ${kind} view gives each of ${names.join(", ")} exactly one of a schema or a reference`);
  }
  if ((kind === "adjacency") !== (adjacency !== undefined)) {
    throw new TypeError("an adjacency, and only an adjacency view, names the adjacency of x it follows");
  }
  const symbols = Object.fromEntries(names.map((name) => [name, given[name]]));
  const transaction = store.Mutations.OfTransaction((t: any) => t.mutations([(mu: any) => mu.map((m: any) =>
    m.symbols([(p: any) => adjacency === undefined ? p.symbols(symbols)
      : p.symbols(symbols).spec([(_: any) => _.x[adjacency]([_.y])])]))]));
  return Plain.ToPlain(store).Transaction(transaction);
}

/** What a client says of its interactive session in a write ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md)): its locale and device, where known. The
 * session's id and identity are the service's to stamp. */
export interface Session {
  readonly locale?: string | undefined;
  readonly device?: string | undefined;
}

/** The transaction's `session`, from what is known of it; none where nothing is. */
function inSession(t: any, session: Session | undefined): any {
  if (session === undefined || (session.locale === undefined && session.device === undefined)) return t;
  return t.session((s: any) => {
    let built = s;
    if (session.locale !== undefined) built = built.locale(session.locale);
    if (session.device !== undefined) built = built.device(session.device);
    return built;
  });
}

/** An edit of one object's properties ([CAP-014: properties as markdown](mbse:mbse-basis/docs/capabilities/CAP-014.md)): the detail view's template, `x` given the object's reference, then an
 * update that writes each property given its value (`null` clears it). Posted to the detail view, it gives the object's
 * detail as the edit left it, once committed. Gives the transaction's expression, the request's body. */
export function edit(store: any, reference: unknown, values: Readonly<Record<string, unknown>>, session?: Session):
    Plain.PlainMap {
  const names = Object.keys(values);
  if (names.length === 0) throw new TypeError("an edit writes at least one property");
  const transaction = store.Mutations.OfTransaction((t: any) => inSession(t, session).mutations([(mu: any) => mu.map((m: any) => m
    .symbols([(p: any) => p.symbols({ x: reference })])
    .then([(w: any) => w.update((u: any) => u.apply([(p: any) => p
      .symbols({ x: reference })
      .spec(names.map((name) => (_: any) => _.x[name](values[name])))]))]))]));
  return Plain.ToPlain(store).Transaction(transaction);
}

/** A new object proposed through an adjacency ([CAP-018: adjacency inspector](mbse:mbse-basis/docs/capabilities/CAP-018.md)): `x`, the inbound object's reference, gains an entry in its
 * `adjacency`, whose other link, `link`, holds a new object of `schema` (the store's schema object), with `values` its
 * properties and `entry` the entry's. Posted to the detail view, it gives `x`'s detail with the new entry, once the
 * service has committed it; an owned object is placed in its directory, its key given there. Gives the transaction's
 * expression, the request's body. */
export function propose(store: any, x: unknown, adjacency: string, link: string, schema: unknown,
    values: Readonly<Record<string, unknown>>, entry: Readonly<Record<string, unknown>> = {}, session?: Session):
    Plain.PlainMap {
  const transaction = store.Mutations.OfTransaction((t: any) => inSession(t, session).mutations([(mu: any) => mu.upsert((u: any) => u
    .exists([(p: any) => p
      .symbols({ x, n: schema })
      .spec([
        (_: any) => _.x[adjacency]([(e: any) => Object.entries(entry)
          .reduce((built: any, [name, value]) => built[name](value), e[link](_.n))]),
        ...Object.entries(values).map(([name, value]) => (_: any) => _.n[name](value)),
      ])]))]));
  return Plain.ToPlain(store).Transaction(transaction);
}

/** A relation entry a view's frame carries: one its journal inserts. */
export interface Entry {
  /** The symbol that binds its holder, the object whose adjacency holds it. */
  readonly holder: string;
  /** The holder's adjacency that holds it, by name. */
  readonly adjacency: string;
  /** Its relation's registered name (`relationName`). */
  readonly relation: string;
  /** Its links, each its name and the `References.OfObject` it links, the holder's own among them. */
  readonly links: ReadonlyMap<string, unknown>;
  /** Its properties, each its value. */
  readonly properties: ReadonlyMap<string, unknown>;
  /** What tells it apart from any other entry: its relation, links and properties, as JSON. */
  readonly key: string;
}

/** A frame of a view's response, a `References.OfFrame` read back: its journal ([CAP-318: support for decoupled code](mbse:mbse-basis/docs/capabilities/README.md#CAP-318), mbse-schemas
 * 0.38), a `Changes.Transaction` whose symbols are the frame's bindings, then the journal's own for the other objects
 * whose properties it carries (`o0`, `o1`, ...), and whose changes set those properties and insert its entries. */
export interface Frame {
  /** The `References.OfFrame` value, in the store that read it. */
  readonly value: any;
  /** Each symbol's `References.OfObject`, the journal's own among them. */
  readonly binds: ReadonlyMap<string, unknown>;
  /** The properties the journal sets, by the key of the object it sets them of (`keyOf`), each its value, in the order
   * set. */
  readonly properties: ReadonlyMap<string, ReadonlyMap<string, unknown>>;
  /** Each entry the journal inserts, in order. */
  readonly entries: readonly Entry[];
}

/** The value object a member or an element holds, as its visitor; null where it holds none (a visitor of nothing has
 * no schema). */
function object(member: any): any {
  let found: any = null;
  member.as_object((o: any) => { found = o; return o; });
  return present(found) ? found : null;
}

const present = (visitor: any): boolean =>
  visitor !== null && visitor !== undefined && visitor.as_schema() !== null && visitor.as_schema() !== undefined;

/** The elements of the container a member holds, each with its index, in order; none where it holds none. */
function elements(member: any): [unknown, any][] {
  let found: [unknown, any][] = [];
  member.as_value((a: any) => a.as_container((c: any) => {
    if (present(c)) c.as_entries((entries: Iterator<[unknown, any]>) => { found = [...{ [Symbol.iterator]: () => entries }]; });
    return c;
  }));
  return found;
}

/** The union value an element holds, as its visitor. */
function union(element: any): any {
  let found: any = null;
  element.as_union((u: any) => { found = u; return u; });
  return found;
}

/** The value a payload holds, a member's or an element's: a scalar, else the visitor of the value. */
function payload(member: any): unknown {
  let found: unknown = null;
  const read = (a: any): any => {
    a.as_scalar((v: any) => { if (v.get() !== null && v.get() !== undefined) found = v.get(); return v; });
    for (const select of ["as_object", "as_union", "as_intersection", "as_container"]) {
      a[select]((v: any) => { if (found === null && present(v)) found = v; return v; });
    }
    return a;
  };
  if (typeof member.as_value === "function") member.as_value(read); else read(member);
  return found;
}

/** One line of a view's response read back: decoded as a `References.OfFrame` value of the store's, by mbse-schemas'
 * `JSON`, which needs the schemas of the objects whose values and entries it carries; its journal read through the
 * visitors as `Frame` gives it. */
export function read(store: any, line: string): Frame {
  const value: any = J.FromJSON(store)(store.registered("References.OfFrame"), line);
  const journal = object(value.journal);
  const symbols = new Map(journal === null ? [] : elements(journal.symbols)
    .map(([name, symbol]) => [name as string, object(symbol)] as [string, any]));
  const binds = new Map([...symbols].map(([name, symbol]) => [name, object(symbol.reference)] as [string, unknown]));
  const schemaOf = (symbol: any): any => { // its `schema` where the symbol gives one, else the one its path implies
    const given = object(symbol.schema);
    const path = (reference: any): unknown => (Plain.ToPlain(store)(reference.as_schema(), reference) as Map<string, any>)
      .get("path");
    return given !== null ? store.held(path(given)) : References.implied(store, path(object(symbol.reference)));
  };
  const properties = new Map<string, Map<string, unknown>>();
  const entries: Entry[] = [];
  for (const [, element] of journal === null ? [] : elements(journal.changes)) {
    const change = union(element);
    const set = present(change.property) ? change.property.set : null;
    if (present(set)) {
      const key = keyOf(store, binds.get(set.holder.get()));
      const held = properties.get(key) ?? new Map<string, unknown>();
      held.set(set.name.get(), payload(set.value));
      properties.set(key, held);
    }
    const insert = present(change.entry) ? change.entry.insert : null;
    if (!present(insert)) continue;
    const holder = insert.holder.symbol.get() as string;
    const adjacency = insert.adjacency.get() as string;
    const declared = schemaOf(symbols.get(holder)).adjacencies.get(adjacency);
    const relation = store.name_of(declared.relation) as string;
    const linksGiven = new Map(elements(insert.links).map(([link, given]) => [link as string, union(given)] as [string, any]));
    const links = new Map<string, unknown>();
    for (const link of declared.relation.entry.links.keys() as Iterable<string>) { // in the relation's order
      const linked = linksGiven.get(link);
      if (link === declared.me) links.set(link, binds.get(holder));
      else if (linked !== undefined) {
        const symbol = linked.symbol.get();
        links.set(link, symbol !== null && symbol !== undefined ? binds.get(symbol) : linked.reference); // a branch: its visitor
      }
    }
    const given = new Map(elements(insert.properties).map(([name, v]) => [name as string, payload(v)] as [string, unknown]));
    const key = J.dumps([relation, ...[...links].map(([link, reference]) => [link, keyOf(store, reference)]),
      [...given]] as any);
    entries.push({ holder, adjacency, relation, links, properties: given, key });
  }
  return { value, binds, properties, entries };
}

/** What tells a reference apart, so that two compare: its JSON. */
export function keyOf(store: any, reference: any): string {
  return J.dumps(Plain.ToPlain(store)(reference.as_schema(), reference));
}

/** The properties `frame` carries of the object `symbol` binds; empty where it carries none. */
export function properties(store: any, frame: Frame, symbol = "x"): ReadonlyMap<string, unknown> {
  return assignedTo(store, frame, frame.binds.get(symbol));
}

/** The properties `frame` carries of the object `reference` designates; empty where it carries none. */
function assignedTo(store: any, frame: Frame, reference: unknown): ReadonlyMap<string, unknown> {
  if (reference === undefined || reference === null) return new Map();
  return frame.properties.get(keyOf(store, reference)) ?? new Map();
}

type Step = Map<string, any>;

/** A path's steps, from its root: each `entry` step's properties, and the root's singleton. */
function steps(store: any, reference: any): { singleton: string; keys: Map<string, unknown>[] } {
  const path = (Plain.ToPlain(store)(reference.as_schema(), reference) as Step).get("path") as Step;
  const keys: Map<string, unknown>[] = [];
  for (let next = path.get("next") as Step | undefined; next !== undefined; next = (next.get("entry") as Step | undefined)?.get("next")) {
    const entry = next.get("entry") as Step | undefined;
    if (entry === undefined) break;
    keys.push(entry.get("properties") as Map<string, unknown>);
  }
  return { singleton: path.get("singleton") as string, keys };
}

/** The last key of an object's path: its owning entry's key values, or, a singleton, its name. */
export function lastKey(store: any, reference: unknown): string {
  const { singleton, keys } = steps(store, reference);
  const last = keys[keys.length - 1];
  return last === undefined ? singleton : [...last.values()].map(String).join(" ");
}

const first = (held: ReadonlyMap<string, unknown>, names: readonly string[]): string | null => {
  const name = names.find((n) => held.get(n) !== undefined && held.get(n) !== null);
  return name === undefined ? null : String(held.get(name));
};

/** [CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md): an object's label, the first of `LABELS` the frame assigns it; else its schema's name, where the caller
 * knows it, and its path's last key. */
export function label(store: any, frame: Frame, symbol = "x", schemaName?: string): string {
  const reference = frame.binds.get(symbol);
  return labelOf(store, frame, reference, schemaName);
}

function labelOf(store: any, frame: Frame, reference: unknown, schemaName?: string): string {
  const held = first(assignedTo(store, frame, reference), LABELS);
  if (held !== null) return held;
  const key = lastKey(store, reference);
  return schemaName === undefined ? key : `${schemaName} ${key}`;
}

/** [CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md): an object's summary, the first of `SUMMARIES` the frame assigns it; else empty. */
export function summary(store: any, frame: Frame, symbol = "x"): string {
  return first(properties(store, frame, symbol), SUMMARIES) ?? "";
}

/** [CAP-006: chip view](mbse:mbse-basis/docs/capabilities/CAP-006.md): a chip's other properties, those the frame assigns besides its label's and its summary's. */
export function chip(store: any, frame: Frame, symbol = "x"): ReadonlyMap<string, unknown> {
  const held = properties(store, frame, symbol);
  const skip: (string | undefined)[] = [LABELS.find((n) => held.has(n)), SUMMARIES.find((n) => held.has(n))];
  return new Map([...held].filter(([name]) => !skip.includes(name)));
}

/** A relation entry's relation, by its schema's registered name. */
export function relationName(_store: any, entry: Entry): string {
  return entry.relation;
}

/** [CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md), an entry's label: its relation's name and its linked objects' labels, as the frame gives them. */
export function entryLabel(store: any, frame: Frame, entry: Entry): string {
  return `${entry.relation}: ${[...entry.links.values()].map((link) => labelOf(store, frame, link)).join(", ")}`;
}

/** An entry's properties, each its value. */
export function entryProperties(entry: Entry): ReadonlyMap<string, unknown> {
  return entry.properties;
}

/** An entry's links, each its name and the `References.OfObject` it links. */
export function entryLinks(entry: Entry): ReadonlyMap<string, unknown> {
  return entry.links;
}

/** One transaction in an object's provenance ([CAP-015: transaction provenance](mbse:mbse-basis/docs/capabilities/CAP-015.md)), as a frame carries it. */
export interface Written {
  /** When the transaction executed, UTC ISO 8601 text. */
  readonly when: string;
  /** Its session's identity, by name. */
  readonly who: string;
  readonly locale?: string;
  readonly device?: string;
}

/** [CAP-020: provenance display](mbse:mbse-basis/docs/capabilities/CAP-020.md): an object's provenance as `frame` carries it (the detail view's `x`, an adjacency view's `y`): the
 * transaction that created it and the one that last wrote it after, where the frame has them. */
export function provenance(store: any, frame: Frame, reference: unknown):
    { readonly created?: Written; readonly modified?: Written } {
  const entries = frame.entries;
  const linking = (relation: string, link: string, target: unknown) => {
    if (target === undefined || target === null) return undefined;
    const key = keyOf(store, target);
    return entries.find((e) => e.relation === relation && e.links.has(link) && keyOf(store, e.links.get(link)) === key);
  };
  const written = (relation: string): Written | undefined => {
    const record = linking(relation, "object", reference)?.links.get("transaction");
    if (record === undefined) return undefined;
    const session = linking("Provenance.InSession", "transaction", record)?.links.get("session");
    const identity = linking("Provenance.Who", "session", session)?.links.get("identity");
    const held = assignedTo(store, frame, session);
    const text = (name: string): string | undefined => {
      const value = held.get(name);
      return typeof value === "string" ? value : undefined;
    };
    return {
      when: String(assignedTo(store, frame, record).get("when") ?? ""),
      who: identity === undefined ? "unknown" : lastKey(store, identity),
      ...(text("locale") === undefined ? {} : { locale: text("locale")! }),
      ...(text("device") === undefined ? {} : { device: text("device")! }),
    };
  };
  const created = written("Provenance.CreatedBy");
  const modified = written("Provenance.ModifiedBy");
  return { ...(created === undefined ? {} : { created }), ...(modified === undefined ? {} : { modified }) };
}
