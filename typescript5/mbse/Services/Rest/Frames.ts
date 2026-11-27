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
 * Each frame is its journal (mbse-schemas 0.38, mbse-basis
 * [CAP-318: support for decoupled code](mbse:mbse-basis/docs/capabilities/README.md#CAP-318)): `{"frame": {"journal", "scope",
 * "remainder", "errors", "terminal"}}`, its journal a `Changes.Transaction` whose `symbols` are the frame's bindings, an
 * object by its `References.OfObject`, a schema object by its `References.OfSchema`, and whose `changes` are the state
 * its path's clauses referenced or changed. A completion marker is `{"end": {"scope"}}`, and carries nothing else. A
 * frame written before a frame was its journal, with `binds` or `assigns`, is refused where it is read.
 *
 * Reading one back gives a `Transactions.Frame` of the reading store's: each symbol's object by its reference (a
 * `References.OfObject` of that store, a schema object's a `References.OfSchema`), read from its journal; its errors,
 * each error as its kind names it (`ValueError`, `TypeError`, `LookupError`, else `Error`); its scope; its remainder, a
 * position in the expression the reader gave; its journal, a `Changes.Transaction` of the reading store's; and whether
 * it is terminal, a routing mark passed through to the layer that commits. What cannot cross is refused, not lost: a
 * frame binding a counted object, which has no reference, comes over with that symbol left out of its journal, and
 * annotated with why (`LookupError`), as mbse-schemas writes it. */

import { Errors, Plain, References, Transactions } from "@mbse/schemas/Framework";
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

/** An input frame as plain data, a `References.OfFrame` of `store`'s: its journal, its bindings each by its reference,
 * and whether it is terminal; a symbol binding what has no reference left out, and annotated. */
export function frame(store: any, given: Map<string, unknown>): Plain.PlainData {
  return Plain.ToPlain(store)(store.registered("References.OfFrame"), References.of(store, given));
}

function list(plain: PlainMap, name: string): unknown[] {
  const found = plain.get(name) ?? [];
  if (!Array.isArray(found)) throw new ValueError(`a frame's ${name} is a list`);
  return found;
}

/** A frame's parts before it was its journal (mbse-schemas 0.38). */
const OLD = ["binds", "assigns", "entries", "variables"];

/** A `References.OfFrame`, as plain data, as a frame of `store`'s: its bindings, read from its journal's symbols, each a
 * reference, data, a schema object's a `References.OfSchema`, which the layer it goes to resolves; its errors, scope,
 * journal and whether it is terminal; and, where `transaction` is the expression it was executed over, its remainder
 * in it. An input frame, `given` to `txn.exec`, carries no journal, as a layer above gives one in a process. One
 * written before a frame was its journal, with `binds` or `assigns`, is refused (`ValueError`). */
export function readFrame(store: any, plain: unknown, transaction: unknown = null, given = false): Frame {
  if (!(plain instanceof Map)) {
    throw new ValueError("a frame is a References.OfFrame, a JSON object: its journal a Changes.Transaction, its "
      + "errors a list");
  }
  const old = OLD.filter((name) => plain.has(name));
  if (old.length > 0) {
    throw new ValueError("a frame is a References.OfFrame, its journal a Changes.Transaction (mbse-schemas 0.38): "
      + `its ${old.join(", ")} are gone`);
  }
  const journalPlain = plain.get("journal") ?? new Map();
  if (!(journalPlain instanceof Map) || !((journalPlain.get("symbols") ?? new Map()) instanceof Map)) {
    throw new ValueError("a frame's journal is a Changes.Transaction, a JSON object: its symbols an object");
  }
  const errors = list(plain, "errors").map((e0) => {
    const e = e0 as PlainMap;
    const kind = (e.get("kind") ?? "Error") as string;
    const message = (e.get("message") ?? "") as string;
    return new FrameError((e.get("subterm") ?? "$") as string, kind, message, errorOf(kind, message));
  });
  const journal = Plain.FromPlain(store)(store.registered("Changes.Transaction"), journalPlain as Plain.PlainData);
  const reference = store.registered("References.OfObject");
  const bound = [...((journalPlain.get("symbols") ?? new Map()) as PlainMap)].map(([name, symbol]) =>
    [name, Plain.FromPlain(store)(reference, ((symbol ?? new Map()) as PlainMap).get("reference") as Plain.PlainData)] as
      [string, unknown]);
  const remainder = plain.get("remainder");
  return new Frame(bound, errors,
    typeof remainder !== "string" || transaction === null ? null : new Remainder(transaction, at(remainder)),
    (plain.get("scope") ?? null) as string | null, given ? null : journal, plain.get("terminal") === true);
}

/** An item of a frame stream, a `References.OfItem` as plain data, as `txn.exec` gives it in a process: a frame
 * (`readFrame`), or the completion marker `{"end": scope}`, which carries nothing else. */
export function readItem(store: any, plain: unknown, transaction: unknown): Item {
  const refused = (): ValueError =>
    new ValueError('an item of a frame stream is a References.OfItem: {"frame": ...} or {"end": ...}');
  if (!(plain instanceof Map) || plain.size !== 1) throw refused();
  if (plain.has("frame")) return readFrame(store, plain.get("frame"), transaction);
  const end = plain.get("end");
  if (!(end instanceof Map)) throw refused();
  return new Map<string, unknown>([["end", end.get("scope") ?? null]]) as Item;
}
