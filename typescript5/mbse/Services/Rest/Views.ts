/** The logical view kinds (VISUALIZATION.md, FEA-003), the client's side: each kind's template filled, and what a
 * frame of each kind carries read back (CAP-005 to CAP-008). The server's side is `python3/mbse/Services/Rest/Views.py`;
 * `docs/CONTRACT.md` is the prose, and the golden corpus in `conformance/` checks that both agree. */

import { JSON as J, Plain } from "@mbse/schemas/Framework";

export const KINDS = ["label", "chip", "detail", "adjacency"] as const;
export type Kind = (typeof KINDS)[number];
/** Each kind's symbols: `x` is the object viewed; in `adjacency`, `y` is what `x` links. */
export const SYMBOLS: Readonly<Record<Kind, readonly string[]>> = {
  label: ["x"], chip: ["x"], detail: ["x"], adjacency: ["x", "y"],
};
export const LABELS = ["label", "name", "title"] as const; // CAP-005: the label is the first of these
export const SUMMARIES = ["summary", "description"] as const; // CAP-005: the summary is the first of these
export const CHIP_SCALARS = 3; // CAP-006: the other scalar properties a chip includes

/** A kind's template, its symbols given (CAP-004, CAP-012): each one a schema (`store.registered("work.Task")`), which
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

/** What a client says of its interactive session in a write (CAP-015): its locale and device, where known. The
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

/** An edit of one object's properties (CAP-014): the detail view's template, `x` given the object's reference, then an
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

/** A new object proposed through an adjacency (CAP-018): `x`, the inbound object's reference, gains an entry in its
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

/** Property values a frame witnesses an object holds (`References.OfProperties`). */
export interface Assigned {
  /** The object's `References.OfObject`. */
  readonly object: unknown;
  /** Its properties, each its value, in the schema's order. */
  readonly properties: ReadonlyMap<string, unknown>;
}

/** A frame of a view's response, a `References.OfFrame` read back. */
export interface Frame {
  /** The `References.OfFrame` value, in the store that read it. */
  readonly value: any;
  /** Each symbol's `References.OfObject`. */
  readonly binds: ReadonlyMap<string, unknown>;
  readonly assigns: readonly Assigned[];
  /** Each entry witnessed, a `References.OfEntry`. */
  readonly entries: readonly unknown[];
}

const items = (container: any): [unknown, any][] => {
  let out: [unknown, any][] = [];
  container.as_value((v: any) => v.as_container((c: any) => c.as_entries((entries: Iterator<[unknown, any]>) => {
    out = [...{ [Symbol.iterator]: () => entries }];
  })));
  return out;
};

const valueOf = (any: any): unknown => {
  let out: unknown = null;
  any.as_scalar((s: any) => { out = s.get(); });
  return out;
};

const objectOf = (any: any): any => {
  let out: any = null;
  any.as_object((o: any) => { out = o; });
  return out;
};

/** One line of a view's response read back: decoded as a `References.OfFrame` of the store's, which needs only the
 * framework's schemas, and the schemas of any value object a property holds. */
export function read(store: any, line: string): Frame {
  const value: any = J.FromJSON(store)(store.References.OfFrame.as_schema(), line);
  const binds = new Map(items(value.binds).map(([name, any]) => [name as string, objectOf(any)]));
  const assigns = items(value.assigns).map(([, any]) => {
    const assigned = objectOf(any);
    return {
      object: objectOf(assigned.object),
      properties: new Map(items(assigned.properties).map(([name, v]) => [name as string, valueOf(v)])),
    };
  });
  const entries = items(value.entries).map(([, any]) => objectOf(any));
  return { value, binds, assigns, entries };
}

/** What tells a reference apart, so that two compare: its JSON. */
export function keyOf(store: any, reference: any): string {
  return J.dumps(Plain.ToPlain(store)(reference.as_schema(), reference));
}

/** The properties `frame` assigns to the object `symbol` binds; empty where it assigns none. */
export function properties(store: any, frame: Frame, symbol = "x"): ReadonlyMap<string, unknown> {
  return assignedTo(store, frame, frame.binds.get(symbol));
}

function assignedTo(store: any, frame: Frame, reference: unknown): ReadonlyMap<string, unknown> {
  if (reference === undefined || reference === null) return new Map();
  const key = keyOf(store, reference);
  return frame.assigns.find((a) => keyOf(store, a.object) === key)?.properties ?? new Map();
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

/** CAP-005: an object's label, the first of `LABELS` the frame assigns it; else its schema's name, where the caller
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

/** CAP-005: an object's summary, the first of `SUMMARIES` the frame assigns it; else empty. */
export function summary(store: any, frame: Frame, symbol = "x"): string {
  return first(properties(store, frame, symbol), SUMMARIES) ?? "";
}

/** CAP-006: a chip's other properties, those the frame assigns besides its label's and its summary's. */
export function chip(store: any, frame: Frame, symbol = "x"): ReadonlyMap<string, unknown> {
  const held = properties(store, frame, symbol);
  const skip: (string | undefined)[] = [LABELS.find((n) => held.has(n)), SUMMARIES.find((n) => held.has(n))];
  return new Map([...held].filter(([name]) => !skip.includes(name)));
}

/** A relation entry's relation, by its schema's name: its path's steps' names, joined by dots. */
export function relationName(store: any, entry: any): string {
  const plain = Plain.ToPlain(store)(entry.as_schema(), entry) as Step;
  const names: string[] = [];
  for (let next = (plain.get("relation") as Step).get("next") as Step | undefined; next?.get("entry") !== undefined;
    next = (next.get("entry") as Step).get("next") as Step | undefined) {
    names.push(String(((next.get("entry") as Step).get("properties") as Step).get("name")));
  }
  return names.join(".");
}

/** CAP-005, an entry's label: its relation's name and its linked objects' labels, as the frame gives them. */
export function entryLabel(store: any, frame: Frame, entry: any): string {
  const links = items(entry.links).map(([, any]) => objectOf(any));
  return `${relationName(store, entry)}: ${links.map((link) => labelOf(store, frame, link)).join(", ")}`;
}

/** An entry's properties, each its value. */
export function entryProperties(entry: any): ReadonlyMap<string, unknown> {
  return new Map(items(entry.properties).map(([name, v]) => [name as string, valueOf(v)]));
}

/** An entry's links, each its name and the `References.OfObject` it links. */
export function entryLinks(entry: any): ReadonlyMap<string, unknown> {
  return new Map(items(entry.links).map(([name, any]) => [String(name), objectOf(any)]));
}

/** One transaction in an object's provenance (CAP-015), as a frame carries it. */
export interface Written {
  /** When the transaction executed, UTC ISO 8601 text. */
  readonly when: string;
  /** Its session's identity, by name. */
  readonly who: string;
  readonly locale?: string;
  readonly device?: string;
}

/** CAP-020: an object's provenance as `frame` carries it (the detail view's `x`, an adjacency view's `y`): the
 * transaction that created it and the one that last wrote it after, where the frame has them. */
export function provenance(store: any, frame: Frame, reference: unknown):
    { readonly created?: Written; readonly modified?: Written } {
  const entries = frame.entries.map((entry) => ({ relation: relationName(store, entry), links: entryLinks(entry) }));
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
