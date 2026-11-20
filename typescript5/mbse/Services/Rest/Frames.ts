/** A frame stream across HTTP: frames and completion markers as mbse-schemas writes them, `References.OfFrame` and
 * `References.OfItem` as plain data, written and read by the client as Python's `mbse.Services.Rest.Frames` writes and
 * reads them for the service and its client (mbse-basis
 * [the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md#a-cache-layer-and-the-layer-below), its third stage).
 *
 * A frame stream has no wire format of its own (mbse-basis
 * [PRI-018: no model needs code to read or write](mbse:mbse-basis/docs/PRINCIPLES.md#PRI-018)): each item is
 * `References.of(store, item)`, wrapped as a `References.OfItem`, written by `Plain.ToPlain(store)`, one JSON document a
 * line, `{"frame": ...}` or `{"end": ...}`; the stream's last item is the completion marker of the whole stream,
 * `{"end": {}}`, the plain form of `{"end": null}`. An input frame is a `References.OfFrame` as plain data.
 *
 * Reading one back gives a `Transactions.Frame` of the reading store's: each symbol's object by its reference, a schema
 * object as the schema object the store holds; what it assigns, by symbol; its errors, each error as its kind names it
 * (`ValueError`, `TypeError`, `LookupError`, else `Error`); its scope; its remainder, a position in the expression the
 * reader gave; and its journal, a one-transaction `Changes.Journal`. What cannot cross is refused, not lost: a symbol
 * binding a schema object the store does not hold is left out, and the frame annotated with why (`LookupError`). */

import { Errors, JSON as J, Plain, References, Transactions } from "@mbse/schemas/Framework";
import { LookupError, ValueError } from "@mbse/schemas/Framework/Errors";

const { Frame, FrameError, Remainder } = Transactions;
type Frame = InstanceType<typeof Frame>;
type Item = Transactions.Item;
type PlainMap = Map<string, unknown>;

/** The errors a frame's error annotation is read back as, by the name of its kind; any other kind is an `Error`. */
export const ERRORS: Readonly<Record<string, new (message: string) => Error>> = { ValueError, TypeError, LookupError };

/** The last item of a stream: the completion marker of the whole stream, `{"end": null}`, as mbse-schemas writes it. */
export const END = '{"end": {}}';

const STEP = /^(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\[("(?:[^"\\]|\\.)*")\])/;

/** The position a subterm names, `$.mutations[0].map.then[0].update`, as a `Transactions.Remainder` holds it; refused
 * (`ValueError`) where it is no subterm. */
export function at(subterm: string): (string | number)[] {
  if (!subterm.startsWith("$")) throw new ValueError(`not a subterm: ${JSON.stringify(subterm)}`);
  const steps: (string | number)[] = [];
  let rest = subterm.slice(1);
  while (rest.length > 0) {
    const match = STEP.exec(rest);
    if (match === null) throw new ValueError(`not a subterm: ${JSON.stringify(subterm)}`);
    steps.push(match[1] ?? (match[2] !== undefined ? Number(match[2]) : JSON.parse(match[3]!) as string));
    rest = rest.slice(match[0].length);
  }
  if (Errors.path(...steps) !== subterm) throw new ValueError(`not a subterm: ${JSON.stringify(subterm)}`);
  return steps;
}

/** The error an annotation of `kind` stands for, thrown where the transaction ends. */
export function errorOf(kind: string, message: string): Error {
  return new (ERRORS[kind] ?? Error)(message);
}

/** An input frame as plain data, a `References.OfFrame` of `store`'s, refused where it binds what has no reference. */
export function frame(store: any, given: Map<string, unknown>): Plain.PlainData {
  return Plain.ToPlain(store)(store.registered("References.OfFrame"), References.of(store, given));
}

function object(store: any, plain: unknown): unknown {
  const path = plain instanceof Map ? plain.get("path") : undefined;
  if (path instanceof Map && path.get("singleton") === ".") return store.held(path);
  return Plain.FromPlain(store)(store.registered("References.OfObject"), plain as Plain.PlainData);
}

function value(store: any, plain: unknown): unknown {
  const holder = Plain.FromPlain(store)(store.registered("References.OfValue"), new Map([["value", plain]]) as any);
  return store.member(holder, "value");
}

function journal(store: any, plain: unknown): unknown {
  return Plain.FromPlain(store)(store.registered("Changes.Journal"), [plain] as Plain.PlainData);
}

function list(plain: PlainMap, name: string): unknown[] {
  const found = plain.get(name) ?? [];
  if (!Array.isArray(found)) throw new ValueError(`a frame's ${name} is a list`);
  return found;
}

/** A `References.OfFrame`, as plain data, as a frame of `store`'s: its bindings, errors, scope, what it assigns, its
 * journal and, where `transaction` is the expression it was executed over, its remainder in it. */
export function readFrame(store: any, plain: unknown, transaction: unknown = null): Frame {
  if (!(plain instanceof Map) || !((plain.get("binds") ?? new Map()) instanceof Map)) {
    throw new ValueError("a frame is a References.OfFrame, a JSON object: its binds an object, its assigns and its "
      + "errors lists");
  }
  const errors = list(plain, "errors").map((given) => {
    const e = given as PlainMap;
    const kind = (e.get("kind") ?? "Error") as string;
    const message = (e.get("message") ?? "") as string;
    return new FrameError((e.get("subterm") ?? "$") as string, kind, message, errorOf(kind, message));
  });
  const bound: [string, unknown][] = [];
  const paths: [string, string][] = [];
  for (const [name, reference] of (plain.get("binds") ?? new Map()) as PlainMap) {
    const found = object(store, reference);
    if (found === null || found === undefined) {
      const message = `symbol '${name}' of the frame: a schema object the layer it goes to does not hold`;
      errors.push(new FrameError((plain.get("remainder") ?? "$") as string, "LookupError", message,
        new LookupError(message)));
      continue;
    }
    bound.push([name, found]);
    paths.push([name, J.dumps(reference as Plain.PlainData)]);
  }
  const assigns = new Map<string, Map<string, unknown>>();
  for (const witnessed of list(plain, "assigns") as PlainMap[]) {
    const key = J.dumps(witnessed.get("object") as Plain.PlainData);
    const values = [...((witnessed.get("properties") ?? new Map()) as PlainMap)]
      .map(([name, given]) => [name, value(store, given)] as [string, unknown]);
    for (const [name, path] of paths) {
      if (path !== key) continue;
      const held = assigns.get(name) ?? new Map<string, unknown>();
      for (const [property, given] of values) held.set(property, given);
      assigns.set(name, held);
    }
  }
  const remainder = plain.get("remainder");
  return new Frame(bound, errors, assigns,
    typeof remainder !== "string" || transaction === null ? null : new Remainder(transaction, at(remainder)),
    (plain.get("scope") ?? null) as string | null,
    plain.get("journal") === undefined || plain.get("journal") === null ? null : journal(store, plain.get("journal")));
}

/** An item of a frame stream, a `References.OfItem` as plain data, as `txn.exec` gives it in a process: a frame
 * (`readFrame`), or the completion marker `{"end": scope}`, with its `journal` where it carries one. */
export function readItem(store: any, plain: unknown, transaction: unknown): Item {
  const refused = (): ValueError =>
    new ValueError('an item of a frame stream is a References.OfItem: {"frame": ...} or {"end": ...}');
  if (!(plain instanceof Map) || plain.size !== 1) throw refused();
  if (plain.has("frame")) return readFrame(store, plain.get("frame"), transaction);
  const end = plain.get("end");
  if (!(end instanceof Map)) throw refused();
  const marker = new Map<string, unknown>([["end", end.get("scope") ?? null]]);
  if (end.get("journal") !== undefined && end.get("journal") !== null) {
    marker.set("journal", journal(store, end.get("journal")));
  }
  return marker as Item;
}
