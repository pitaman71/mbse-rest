/** mbse-rest's client: the service as a layer below, which a `Builders.Store` stacks on as on any layer below it, a
 * cache layer (mbse-basis [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290),
 * [CAP-308: stacking by mutation transactions, in one round trip](mbse:mbse-basis/docs/capabilities/README.md#CAP-308), as
 * [the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md#a-cache-layer-and-the-layer-below), its third stage, states),
 * written against mbse-schemas' public interface alone
 * ([CAP-306: a public store-below interface](mbse:mbse-basis/docs/capabilities/README.md#CAP-306)). Python's
 * `mbse.Services.Rest.Store` is the same client.
 *
 * `new Remote(transport)` is the service at the other end of `transport` (`nodeTransport(base)` in Node,
 * `xhrTransport(base)` in a browser, or the URL, which chooses one): a store, a `Builders.Store` holding the schemas
 * alone, whose transaction is one of the service's store, held open by the service for as long as its own:
 *
 * - `transaction((txn = null) => ...)` opens one (`POST /transactions`); its `exec(frame, remainder, allowWrite)` is a
 *   request (`POST /transactions/{id}/exec`) carrying the expression, the subterm the remainder starts at and the input
 *   frames, answered with the stream of frames, each read back as a frame of this store's (`Frames.ts`), its remainder
 *   a position in the expression given; the scope's end commits it (`POST /transactions/{id}/commit`), a refusal
 *   thrown as the error the service's store raised (`ValueError`, `TypeError` or `LookupError`), or, where it throws,
 *   drops it (`DELETE /transactions/{id}`). What the service's follow gave of it as it committed is given to this
 *   store's followers within the commit, so that a cache layer over it takes it into its own transaction; where the
 *   change feed was read to just before it, the feed's position moves past it, else the feed gives it again, in its
 *   place among others', where applying it again changes nothing.
 * - An install, an expression binding a symbol of a meta-schema, is run in this store too, within its own transaction,
 *   which commits after the service's, so that it holds the schemas of the stores above it.
 * - `follow(follower)` gives `follower` each transaction the service's store committed, as a `Changes.Journal` of that
 *   one transaction, as plain data, once each, in the order it committed them, read from its change feed
 *   (`GET /changes`) after the last it was given, by its id, on `poll()`.
 *
 * `Store(transport, follow = CATCH_UP)` is a cache layer over it, a `Builders.Store` given it as its layer below,
 * holding the schemas of the installs the service was given (`GET /schemas`), each run in it, and so through it. What
 * others commit reaches it by the follow, in a mode chosen where it is made (mbse-basis
 * [QUA-017: distributed or local, decided at runtime](mbse:mbse-basis/docs/QUALITIES.md#QUA-017)): `CATCH_UP`, the
 * default, reads the change feed to its head before each transaction, so that the cache layer reads what it holds as of
 * then; `POLLED` reads it when the program calls `poll()`, and reads what it holds a poll behind.
 *
 * mbse-schemas' store interface is synchronous: a cache layer's transaction executes below within a call that returns
 * the frames. So is a transport: in Node, it waits on a worker thread that fetches (`Atomics.wait`); in a browser, it
 * is a synchronous `XMLHttpRequest`, which blocks the page while the service answers, and is better made from a
 * worker. */

import { Builders, JSON as J, Plain, Transactions } from "@mbse/schemas/Framework";
import { LookupError, ValueError } from "@mbse/schemas/Framework/Errors";
import { Gone, ServiceError, TransportError, Unavailable } from "./Client.js";
import * as Frames from "./Frames.js";

const { Frame, Observable, Remainder } = Transactions;
type Frame = InstanceType<typeof Frame>;
type Item = Transactions.Item;

/** The follow mode that reads the change feed to its head before each transaction of the cache layer: the default. */
export const CATCH_UP = "catch-up";

/** The follow mode that reads the change feed on `poll()` alone, the cache layer reading what it holds a poll behind. */
export const POLLED = "polled";

/** What a transport gives back: the response's status and its body, as text. */
export interface Reply {
  readonly status: number;
  readonly body: string;
}

/** How a store reaches the service: `transport(method, path, body)` gives the response. `path` starts with `/` and
 * holds its query; `body` is JSON, or undefined. Synchronous, as the store interface is. */
export type Transport = (method: string, path: string, body?: string) => Reply;

export interface TransportOptions {
  /** Headers sent with each request besides `content-type`: the session's, `x-mbse-session`, for one. */
  readonly headers?: Readonly<Record<string, string>>;
  /** How long a request may take, in milliseconds: 60 seconds by default. */
  readonly timeout?: number;
}

/** Each kind of refusal the service reports, by the name its error message begins with, and the error thrown for it. */
export const REFUSALS: Readonly<Record<string, new (message: string) => Error>> = { ValueError, TypeError, LookupError };

/** The worker a Node transport fetches in, its caller waiting on `Atomics.wait` until it has the response. */
const WORKER = `
const { parentPort } = require("node:worker_threads");
parentPort.on("message", async ({ signal, port, method, url, body, headers, timeout }) => {
  let reply;
  try {
    const response = await fetch(url, { method, body, headers, signal: AbortSignal.timeout(timeout) });
    reply = { status: response.status, body: await response.text() };
  } catch (error) {
    reply = { error: String(error && error.message ? error.message : error) };
  }
  port.postMessage(reply);
  port.close();
  Atomics.store(signal, 0, 1);
  Atomics.notify(signal, 0);
});
`;

function headersOf(options: TransportOptions, body: string | undefined): Record<string, string> {
  return { ...options.headers, ...(body === undefined ? {} : { "content-type": "application/json" }) };
}

/** A transport to the service at `base` (`http://localhost:8000`), in Node: each request is fetched in a worker thread,
 * which this one waits on. */
export function nodeTransport(base: string, options: TransportOptions = {}): Transport {
  const threads = (globalThis as any).process?.getBuiltinModule?.("node:worker_threads");
  if (threads === undefined) throw new TransportError("nodeTransport: not in Node 22 or later, which has worker threads");
  const root = base.replace(/\/+$/, "");
  const timeout = options.timeout ?? 60_000;
  let worker: any = null;
  return (method, path, body) => {
    if (worker === null) {
      worker = new threads.Worker(WORKER, { eval: true });
      worker.unref(); // a store held does not keep the process alive
    }
    const signal = new Int32Array(new SharedArrayBuffer(4));
    const { port1, port2 } = new threads.MessageChannel();
    worker.postMessage({ signal, port: port2, method, url: root + path, body, headers: headersOf(options, body),
      timeout }, [port2]);
    Atomics.wait(signal, 0, 0, timeout + 5_000);
    const received = threads.receiveMessageOnPort(port1);
    port1.close();
    if (received === undefined) throw new TransportError(`${method} ${path}: no response in ${timeout} ms`);
    const reply = received.message as Reply & { error?: string };
    if (reply.error !== undefined) throw new TransportError(`${method} ${path}: ${reply.error}`);
    return { status: reply.status, body: reply.body };
  };
}

/** A transport to the service at `base`, in a browser: a synchronous `XMLHttpRequest`, best made from a worker. */
export function xhrTransport(base: string, options: TransportOptions = {}): Transport {
  const root = base.replace(/\/+$/, "");
  return (method, path, body) => {
    const request = new XMLHttpRequest();
    request.open(method, root + path, false);
    for (const [name, value] of Object.entries(headersOf(options, body))) request.setRequestHeader(name, value);
    try {
      request.send(body ?? null);
    } catch (error) {
      throw new TransportError(`${method} ${path}: ${error instanceof Error ? error.message : String(error)}`,
        { cause: error });
    }
    return { status: request.status, body: request.responseText };
  };
}

/** The transport to `base` for where it runs: a synchronous `XMLHttpRequest` where there is one, else Node's. */
export function transportFor(base: string, options: TransportOptions = {}): Transport {
  return typeof (globalThis as any).XMLHttpRequest === "function" ? xhrTransport(base, options)
    : nodeTransport(base, options);
}

/** The service a `Remote` reaches: its transport, the change feed's name, the position its followers were given last,
 * and its followers. */
class Connection {
  readonly followers = new Map<object, (plain: unknown) => void>();
  polling = false;
  readonly feed: string;
  head: string | null;

  constructor(readonly transport: Transport) {
    const head = this.call("GET", "/changes") as Map<string, unknown>;
    this.feed = head.get("feed") as string;
    this.head = (head.get("head") ?? null) as string | null;
  }

  /** The service's answer to a request, as text; a refusal thrown: a transaction's as the error its store raised, any
   * other as a `ServiceError` (`Gone` for 410, `Unavailable` for 503). */
  send(method: string, path: string, body?: unknown): string {
    const reply = this.transport(method, path, body === undefined ? undefined : J.dumps(body as any));
    if (reply.status === 200) return reply.body;
    const refusal = ServiceError.of(reply.status, reply.body);
    if (reply.status === 400) {
      const at = refusal.error.indexOf(": ");
      const Refusal = at > 0 ? REFUSALS[refusal.error.slice(0, at)] : undefined;
      if (Refusal !== undefined) throw new Refusal(refusal.error.slice(at + 2));
    }
    throw refusal;
  }

  call(method: string, path: string, body?: unknown): unknown {
    return J.loads(this.send(method, path, body));
  }

  give(journal: unknown): void {
    for (const follower of [...this.followers.values()]) follower(journal);
  }

  /** Gives the followers each transaction the service's store committed since they were last given one, in the order it
   * committed them, each a one-transaction journal, read from the change feed after the last's id, to its head; how
   * many. A read while it reads, as a follower's own transaction reads, reads nothing. */
  poll(): number {
    if (this.polling) return 0;
    this.polling = true;
    try {
      let count = 0;
      for (;;) {
        const after = this.head === null ? "" : `&after=${encodeURIComponent(this.head)}`;
        const read = this.call("GET", `/changes?feed=${encodeURIComponent(this.feed)}${after}`) as Map<string, any>;
        const journal = read.get("journal") as Map<string, unknown>[];
        for (const transaction of journal) {
          this.head = transaction.get("id") as string;
          count += 1;
          this.give([transaction]);
        }
        if (journal.length === 0 || this.head === read.get("head")) return count;
      }
    } finally {
      this.polling = false;
    }
  }
}

/** Whether a symbol, as an expression's wire form writes it, is of a meta-schema: its objects are schema objects, the
 * schema one the store was made holding in the module `Schemas`. */
function meta(remote: any, plain: unknown): boolean {
  const schema = plain instanceof Map ? plain.get("schema") : undefined;
  for (const reference of Array.isArray(schema) ? schema : [schema]) {
    const path = reference instanceof Map ? reference.get("path") : undefined;
    const held = path instanceof Map && path.get("singleton") === "." ? remote.held(path) : null;
    if (held !== null && held !== undefined && remote.framework(held) && remote.name_of(held).startsWith("Schemas.")) {
      return true;
    }
  }
  return false;
}

/** Whether an expression, as the wire carries it, is an install: an upsert or an update of it binds a symbol of a
 * meta-schema, as a cache layer finds one. */
function installs(remote: any, plain: unknown): boolean {
  if (plain instanceof Map) {
    for (const [verb, patterns] of [["upsert", "exists"], ["update", "apply"]] as const) {
      const body = plain.get(verb);
      if (body instanceof Map && ((body.get(patterns) ?? []) as unknown[]).some((pattern) => pattern instanceof Map
        && [...((pattern.get("symbols") ?? new Map()) as Map<string, unknown>).values()].some((s) => meta(remote, s)))) {
        return true;
      }
    }
    return [...plain.values()].some((value) => installs(remote, value));
  }
  return Array.isArray(plain) && plain.some((value) => installs(remote, value));
}

/** A transaction of the service's store, open for one of this store's: what a cache layer over the store is given by
 * `transaction(...)`. It lives as long as its scope. */
export class Transaction {
  ended = false;

  constructor(readonly _remote: Remote, readonly id: string, readonly _local: any) {}

  /** Executes the suffix of a transaction's expression over input frames within the service's transaction, as
   * `Transactions.Transaction.exec` does in a process: `frame`, a frame or a stream of them; `remainder`, a
   * `Transactions.Remainder` or a whole transaction's expression, of this store's. Gives the stream the service gave, an
   * observable, its request made as it is subscribed to, each item read as this store's, a frame's remainder a position
   * in the same expression; an error of no one frame, the observable's error, as the service's store raised it. */
  exec(frame: unknown, remainder: unknown, allowWrite: boolean): Transactions.Observable<Item> {
    return new Observable<Item>((observer) => {
      let items: Item[];
      try {
        items = this.items(frame, remainder, allowWrite);
      } catch (error) {
        observer.error!(error);
        return;
      }
      for (const item of items) {
        observer.next!(item);
        if (observer.closed) return;
      }
      observer.complete!();
    });
  }

  items(frame: unknown, remainder: unknown, allowWrite: boolean): Item[] {
    if (this.ended) throw new ValueError("a transaction's exec runs within it: this one has ended (store.transaction)");
    const remote = this._remote;
    const expression = remainder instanceof Remainder ? remainder.transaction : remainder;
    const plain = Plain.ToPlain(remote).Transaction(expression);
    const inputs = frame instanceof Map ? [frame] : [...frame as Iterable<Map<string, unknown>>];
    if ((!(remainder instanceof Remainder) || remainder.at.length <= 3) && installs(remote, plain)) {
      const made: Frame[] = [];
      let failure: { error: unknown } | null = null;
      this._local.exec(inputs, expression, allowWrite).subscribe({
        next: (item: Item) => { if (item instanceof Frame) made.push(item); },
        error: (error: unknown) => { failure = { error }; },
      });
      if (failure !== null) throw (failure as { error: unknown }).error;
      const failed = made.find((each) => each.errors.length > 0);
      if (failed !== undefined && failed.errors[0]!.error !== null) throw failed.errors[0]!.error;
    }
    const body = new Map<string, unknown>([["expression", plain],
      ["frames", inputs.map((given) => Frames.frame(remote, given))], ["write", allowWrite]]);
    if (remainder instanceof Remainder) body.set("remainder", remainder.subterm);
    const text = remote._rest.send("POST", `/transactions/${encodeURIComponent(this.id)}/exec`, body);
    const lines = text.split("\n").filter((line) => line.trim() !== "");
    if (lines.length === 0 || J.dumps(J.loads(lines[lines.length - 1]!) as any) !== Frames.END) {
      throw new Unavailable(503, J.dumps(new Map([["error",
        "the service's stream ended before its completion marker: nothing it gave is whole"]])));
    }
    return lines.slice(0, -1).map((line) => Frames.readItem(remote, J.loads(line), expression));
  }
}

/** The service that `transport` reaches, or the service at the URL `transport` (`transportFor`), as a layer below: a
 * store holding the schemas alone, whose transaction is the service's. */
export class Remote extends Builders.Store {
  _rest: Connection;

  constructor(transport: Transport | string) {
    super();
    this._rest = new Connection(typeof transport === "string" ? transportFor(transport) : transport);
  }

  /** Given a function that declares no parameter, the scope of a transaction of the service's store: it is given the
   * transaction (`Transaction`), committed where it returns, dropped where it throws; this store's own transaction,
   * which runs the installs it is given, commits after it. Given a transaction's expression, it executed over one empty
   * frame, writing, within one, its frames given back; the first error annotated on one thrown. */
  override transaction(spec: unknown): any {
    if (typeof spec === "function" && spec.length === 0) return this.opened(spec as (txn: unknown) => unknown);
    return this.opened((txn: any = null) => {
      const frames: Frame[] = [];
      let failure: { error: unknown } | null = null;
      (txn as Transaction).exec(new Frame(), spec, true).subscribe({
        next: (item) => { if (item instanceof Frame) frames.push(item); },
        error: (error) => { failure = { error }; },
      });
      if (failure !== null) throw (failure as { error: unknown }).error;
      const failed = frames.find((frame) => frame.errors.length > 0);
      if (failed !== undefined) throw failed.errors[0]!.error ?? new Error(failed.errors[0]!.message);
      return frames;
    });
  }

  opened<T>(body: (txn: unknown) => T): T {
    return super.transaction((local: any = null) => {
      const opened = this._rest.call("POST", "/transactions") as Map<string, unknown>;
      const txn = new Transaction(this, opened.get("transaction") as string, local);
      let result: T;
      try {
        result = body(txn);
      } catch (error) {
        txn.ended = true;
        try {
          this._rest.call("DELETE", `/transactions/${encodeURIComponent(txn.id)}`);
        } catch (refused) {
          if (!(refused instanceof ServiceError || refused instanceof TransportError)) throw refused;
        }
        throw error;
      }
      txn.ended = true;
      const committed = this._rest.call("POST", `/transactions/${encodeURIComponent(txn.id)}/commit`) as
        Map<string, unknown>;
      const journal = committed.get("journal") as Map<string, unknown>[];
      if (journal.length > 0) {
        this._rest.give(journal);
        // read to just before it: the feed holds nothing else to it
        if ((committed.get("after") ?? null) === this._rest.head) this._rest.head = journal.at(-1)!.get("id") as string;
      }
      return result;
    });
  }

  /** Gives `follower` each transaction the service's store commits from now, once each, in its order, as a
   * one-transaction journal, as plain data, read from the change feed; gives back a function that ends it. */
  override follow(follower: (plain: unknown) => void): () => void {
    const token = {}; // this following, though the same follower follow twice
    this._rest.followers.set(token, follower);
    return () => { this._rest.followers.delete(token); };
  }

  /** Gives the followers each transaction the service's store committed since they were last given one, to the change
   * feed's head; how many. */
  poll(): number {
    return this._rest.poll();
  }

  /** The change feed's position its followers were given last: a transaction's id, null for none. */
  position(): string | null {
    return this._rest.head;
  }
}

/** A cache layer over the service (`Store`), which reads the change feed to its head before each transaction, in the
 * follow mode `CATCH_UP`. */
class Cached extends Builders.Store {
  constructor(readonly _restRemote: Remote, readonly _restMode: string) {
    super(_restRemote);
  }

  override transaction(spec: unknown): any {
    if (this._restMode === CATCH_UP) this._restRemote.poll();
    return super.transaction(spec);
  }
}

/** A cache layer over the service that `transport` reaches, the service at the URL `transport`, or `remote`: a
 * `Builders.Store` over it, given the service's schemas by running each install it was given, which reaches it through
 * the layer below, as any install does. `follow` is the mode in which what others commit reaches it: `CATCH_UP`, before
 * each transaction, or `POLLED`, on `poll()`. */
export function Store(transport: Transport | string | Remote, follow: string = CATCH_UP): any {
  if (follow !== CATCH_UP && follow !== POLLED) {
    throw new ValueError(`a follow mode is '${CATCH_UP}' or '${POLLED}', not ${JSON.stringify(follow)}`);
  }
  const remote = transport instanceof Remote ? transport : new Remote(transport);
  const store: any = new Cached(remote, follow);
  for (const plain of remote._rest.call("GET", "/schemas") as Plain.PlainData[]) {
    store.transaction(Plain.FromPlain(store).Transaction(plain));
  }
  return store;
}

export { Gone, LookupError };
