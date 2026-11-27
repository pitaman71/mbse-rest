/** The logical view kinds (mbse-basis [FEA-003: no-code logical views](mbse:mbse-basis/docs/features/FEA-003.md)), the client's side: each kind's template filled, and what a
 * frame of each kind carries read back ([CAP-005: label and summary view](mbse:mbse-basis/docs/capabilities/CAP-005.md) to [CAP-008: adjacency as a list of chips](mbse:mbse-basis/docs/capabilities/CAP-008.md)). The server's side is `python3/mbse/Services/Rest/Views.py`;
 * [FEA-003: no-code logical views](mbse:mbse-basis/docs/features/FEA-003.md#view-kinds) is the prose, and the golden corpus in `conformance/` checks that both agree. */

import { JSON as J, Paths, Plain, References } from "@mbse/schemas/Framework";

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

type PlainMap = Map<string, any>;

/** Each name, as a relation's path from the root module gives it, joined by dots: its registered name. */
function pathName(path: Step | undefined): string {
  const names: string[] = [];
  for (let next = path?.get("next") as Step | undefined; next?.get("entry") !== undefined;
    next = (next.get("entry") as Step).get("next") as Step | undefined) {
    names.push(String(((next.get("entry") as Step).get("properties") as Step).get("name")));
  }
  return names.join(".");
}

/** The schema of the object a journal's symbol binds: its `schema` where the symbol gives one, else the one its
 * reference's path implies. */
function schemaOf(store: any, symbol: PlainMap): any {
  const given = symbol.get("schema") as PlainMap | undefined;
  if (given !== undefined) return store.held(given.get("path"));
  return References.implied(store, (symbol.get("reference") as PlainMap).get("path"));
}

/** One line of a view's response read back: decoded as a `References.OfFrame` of the store's, which needs only the
 * framework's schemas, and the schemas of the objects whose entries it carries; its journal read as `Frame` gives it. */
export function read(store: any, line: string): Frame {
  const value: any = J.FromJSON(store)(store.References.OfFrame.as_schema(), line);
  const journal = ((J.loads(line) as PlainMap).get("journal") ?? new Map()) as PlainMap;
  const symbols = (journal.get("symbols") ?? new Map()) as Map<string, PlainMap>;
  const OfObject = store.registered("References.OfObject");
  const binds = new Map([...symbols].map(([name, symbol]) =>
    [name, Plain.FromPlain(store)(OfObject, symbol.get("reference"))] as [string, unknown]));
  const properties = new Map<string, Map<string, unknown>>();
  const entries: Entry[] = [];
  for (const change of (journal.get("changes") ?? []) as PlainMap[]) {
    const set = (change.get("property") as PlainMap | undefined)?.get("set") as PlainMap | undefined;
    if (set !== undefined) {
      const key = keyOf(store, binds.get(set.get("holder")));
      const held = properties.get(key) ?? new Map<string, unknown>();
      held.set(set.get("name"), set.get("value"));
      properties.set(key, held);
    }
    const insert = (change.get("entry") as PlainMap | undefined)?.get("insert") as PlainMap | undefined;
    if (insert === undefined) continue;
    const holder = (insert.get("holder") as PlainMap).get("symbol") as string;
    const adjacency = insert.get("adjacency") as string;
    const declared = schemaOf(store, symbols.get(holder)!).adjacencies.get(adjacency);
    const path: any = Paths.of(declared.relation);
    const relation = pathName(Plain.ToPlain(store)(path.as_schema(), path) as Step);
    const linksGiven = (insert.get("links") ?? new Map()) as Map<string, PlainMap>;
    const links = new Map<string, unknown>();
    for (const link of declared.relation.entry.links.keys() as Iterable<string>) { // in the relation's order
      const linked = linksGiven.get(link);
      if (link === declared.me) links.set(link, binds.get(holder));
      else if (linked !== undefined) {
        links.set(link, linked.has("symbol") ? binds.get(linked.get("symbol")) : Plain.FromPlain(store)(OfObject,
          linked.get("reference")));
      }
    }
    const given = new Map([...((insert.get("properties") ?? new Map()) as PlainMap)]);
    const key = J.dumps(new Map<string, unknown>([["relation", relation], ["links", new Map([...links].sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0).map(([link, reference]) => [link, J.loads(keyOf(store, reference))]))],
      ["properties", given]]) as any);
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
