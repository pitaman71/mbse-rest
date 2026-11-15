/** mbse-rest's client: a store served over REST, which a `Builders.Store` stacks on as on any store below it
 * (mbse-basis [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290), as
 * [the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md) states). Python's `mbse.Services.Rest.Store`
 * is the same client.
 *
 * `new Store(transport)` is an mbse-schemas store (`Builders.Store`) whose store below is the service at the other end
 * of `transport` (`nodeTransport(base)` in Node, `xhrTransport(base)` in a browser, or the URL, which chooses one). Made,
 * it holds the service's schemas, executing the install transactions that made them (`GET /schemas`); a store above it
 * is made over it, `new Builders.Store(new Store(...))`, as over a store in memory:
 *
 * - `document(path)` gives the object at `path` as a one-transaction document, null where neither it nor the service
 *   holds one: an object it does not hold is loaded from the service (`POST /documents`), on demand.
 * - `transaction(...)` interprets a transaction with mbse-schemas' own interpreter, and sends its changes, as plain
 *   data, to the service before it commits (`POST /transactions`): the service commits them first, and its refusal
 *   refuses the transaction, thrown as the error the service's store raised (`ValueError`, `TypeError` or
 *   `LookupError`). An install, a transaction that writes schemas, is sent to the service first as it was given
 *   (`POST /schemas`), so that the service's store, and the store below it, hold the schemas too.
 * - `Changes.observe(store, observer)` gives `observer` each transaction the service's store committed, in the order
 *   it committed them, from the service's change feed (`GET /changes`): its own among them, each given once, and
 *   others', read before each of its transactions, after each, and on `poll()`. Each is applied to the objects it
 *   holds first.
 *
 * mbse-schemas' store interface is synchronous: a store above reads an object's document, and sends a transaction's
 * changes, within a call that returns them. So is a transport: in Node, it waits on a worker thread that fetches
 * (`Atomics.wait`); in a browser, it is a synchronous `XMLHttpRequest`, which blocks the page while the service
 * answers, and is better made from a worker. */

import { Builders, JSON as J, Plain } from "@mbse/schemas/Framework";
import { LookupError, ValueError } from "@mbse/schemas/Framework/Errors";
import { ServiceError, TransportError } from "./Client.js";

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

/** The members of a transaction's expression its record is made from (mbse-schemas' `Provenance`), carried below. */
export const PROVENANCE = ["uid", "when", "session", "where"] as const;

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

/** A `Builders.Store` given a store below, which carries to it, with each transaction's changes, the `uid`, `when`,
 * `session` and `where` its expression gives, so that a store below with `Provenance` installed records the same
 * transaction, found by its `uid`, rather than one of its own. */
export class Stacked extends Builders.Store {
  _carried(plain: unknown): unknown {
    const expression = this._proposals?.expression ?? null;
    if (expression === null) return plain; // an imperative scope: no expression, nothing to carry
    const whole = Plain.ToPlain(this as any).Transaction(expression) as Map<string, unknown>;
    const carried = new Map<string, unknown>();
    for (const name of PROVENANCE) if (whole.has(name)) carried.set(name, whole.get(name));
    for (const [name, value] of plain as Map<string, unknown>) carried.set(name, value);
    return carried;
  }

  override _send(plain: unknown): void {
    super._send(this._carried(plain));
  }
}

/** A store over the service that `transport` reaches, or the service at the URL `transport` (`transportFor`). */
export class Store extends Stacked {
  readonly _transport: Transport;
  /** How deep in executing the service's installs: those are not sent back. */
  _installing = 0;
  /** The change feed's name, and the last change it was given. */
  _feed: string;
  _seq: number;

  constructor(transport: Transport | string) {
    super();
    this._transport = typeof transport === "string" ? transportFor(transport) : transport;
    this._below = { document: (path: unknown) => this._call("POST", "/documents", path) }; // its own objects load from
    const head = this._call("GET", "/changes") as Map<string, unknown>; //                    the service, on demand
    this._feed = head.get("feed") as string;
    this._seq = Number(head.get("head"));
    this._installing += 1;
    try {
      for (const plain of this._call("GET", "/schemas") as unknown[]) {
        super.transaction(Plain.FromPlain(this as any).Transaction(plain as Plain.PlainData));
      }
    } finally {
      this._installing -= 1;
    }
  }

  /** The service's answer to a request, read from JSON; a refusal thrown: a transaction's as the error its store
   * raised, any other as a `ServiceError` (`Gone` for 410, `Unavailable` for 503). */
  _call(method: string, path: string, body?: unknown): unknown {
    const reply = this._transport(method, path, body === undefined ? undefined : J.dumps(body as Plain.PlainData));
    if (reply.status === 200) return J.loads(reply.body);
    const refusal = ServiceError.of(reply.status, reply.body);
    if (reply.status === 400) {
      const at = refusal.error.indexOf(": ");
      const Refusal = at > 0 ? REFUSALS[refusal.error.slice(0, at)] : undefined;
      if (Refusal !== undefined) throw new Refusal(refusal.error.slice(at + 2));
    }
    throw refusal;
  }

  /** Gives the objects this store holds, and its followers, each transaction the service's store committed since it was
   * last given one, in the order it committed them; how many. Within a transaction of this store's, none. */
  poll(): number {
    if (this._proposals !== null || this._loading > 0 || this._applying > 0) return 0;
    let count = 0;
    for (;;) {
      const query = `after=${this._seq}&feed=${encodeURIComponent(this._feed)}`;
      const read = this._call("GET", `/changes?${query}`) as Map<string, any>;
      for (const change of read.get("changes") as Map<string, unknown>[]) {
        this._seq = Number(change.get("position"));
        count += 1;
        this._deliver(change.get("effect"));
      }
      if (this._seq >= Number(read.get("head"))) return count;
    }
  }

  /** A transaction the service's store committed: applied to the objects present, as a store above applies the store
   * below's (CAP-285), and its followers given the whole of it, as committed. */
  _deliver(plain: unknown): void {
    const observers = this._observers;
    this._observers = [];
    try {
      this._apply(plain);
    } finally {
      this._observers = observers;
    }
    if (observers.length > 0) {
      const effect = Plain.FromPlain(this as any).Transaction(plain as Plain.PlainData);
      for (const observer of [...observers]) observer(effect);
    }
  }

  /** A transaction (`Builders.Store.transaction`), interpreted once the store has read the service's changes, and
   * committed by the service first; its followers are given it from the service's change feed, in order, read once it
   * ends. */
  override transaction(spec?: unknown): any {
    if (this._loading > 0 || this._applying > 0 || this._proposals !== null) return super.transaction(spec);
    this.poll();
    const done = super.transaction(spec);
    this.poll();
    return done;
  }

  /** Sends a transaction's schemas, where it writes any, then its changes, to the service; its followers are not given
   * it here, but from the service's change feed, in the order the service committed it. */
  override _settled(proposals: any): void {
    const writesSchemas = this._held > proposals.existing || proposals.deferred.size > 0;
    if (writesSchemas && this._installing === 0 && this._applying === 0 && proposals.expression !== null) {
      this._call("POST", "/schemas", Plain.ToPlain(this as any).Transaction(proposals.expression));
    }
    super._settled(proposals);
    this._changes = null;
  }

  /** A transaction's changes, sent to the service, which commits them first (CAP-285). */
  override _send(plain: unknown): void {
    this._call("POST", "/transactions", this._carried(plain));
  }
}
