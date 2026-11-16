/** mbse-rest's client: the service as a store below, which a `Builders.Store` stacks on as on any store below it
 * (mbse-basis [CAP-290: a service's store stacked, with no snapshot](mbse:mbse-basis/docs/capabilities/README.md#CAP-290), as
 * [the stacked stores proposal](mbse:mbse-basis/proposals/STACKED-STORES.md) states), written against mbse-schemas'
 * public store-below interface alone, `Stores.Below`
 * ([CAP-306: a public store-below interface](mbse:mbse-basis/docs/capabilities/README.md#CAP-306)). Python's
 * `mbse.Services.Rest.Store` is the same client.
 *
 * `new Remote(transport)` is the service at the other end of `transport` (`nodeTransport(base)` in Node,
 * `xhrTransport(base)` in a browser, or the URL, which chooses one), as a store below (`Stores.Below`):
 *
 * - `document(path)` gives the object at `path` as a one-transaction document, null where the service holds none
 *   (`POST /documents`): what a store over it loads, on demand.
 * - `commit(plain)` sends a transaction's changes, as plain data, to the service (`POST /transactions`), which commits
 *   them first; its refusal is thrown as the error the service's store raised (`ValueError`, `TypeError` or
 *   `LookupError`). It gives back the transaction as the service's store committed it, its record (`Provenance`)
 *   among it, which a store over it takes into its own transaction, as it takes what any store below gives back.
 * - `install(plain)` sends an install, a transaction that writes schemas, to the service (`POST /schemas`), which runs
 *   it in its store and the store below that; one of the installs the service gave it, run again over it, is not sent
 *   back.
 * - `follow(follower)` gives `follower` each transaction the service's store committed, as plain data, once each, in
 *   the order it committed them, read from its change feed (`GET /changes`) on `poll()` and after each commit, its own
 *   among them.
 * - `records` is true: the service's lowest store records each transaction, so that a store over it records none.
 *
 * `Store(transport)`, or `Store(remote)`, is a plain `Builders.Store` over it, given the service's schemas: it runs
 * each of the install transactions that made them (`GET /schemas`). An app reads and writes it as any store, and gives
 * it its own installs, which reach the service. `remote.poll()` reads the change feed, so that what others committed
 * reaches it; a program that reads others' writes before it writes polls first.
 *
 * mbse-schemas' store interface is synchronous: a store above reads an object's document, and sends a transaction's
 * changes, within a call that returns them. So is a transport: in Node, it waits on a worker thread that fetches
 * (`Atomics.wait`); in a browser, it is a synchronous `XMLHttpRequest`, which blocks the page while the service
 * answers, and is better made from a worker. */

import { Builders, JSON as J, type Stores } from "@mbse/schemas/Framework";
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

/** The service that `transport` reaches, or the service at the URL `transport` (`transportFor`), as a store below
 * (`Stores.Below`). */
export class Remote implements Stores.Below {
  /** The service records each transaction (`Provenance`), in its lowest store: a store over it records none. */
  readonly records = true;
  /** The install transactions that made the service's schemas, in order. */
  installs: unknown[];
  readonly _transport: Transport;
  readonly _followers: ((plain: unknown) => void)[] = [];
  /** The change feed's name, and the last change its followers were given. */
  _feed: string;
  _seq: number;
  /** How deep in running the service's own installs over it (`Store`): those are not sent back. */
  _served = 0;

  constructor(transport: Transport | string) {
    this._transport = typeof transport === "string" ? transportFor(transport) : transport;
    const head = this._call("GET", "/changes") as Map<string, unknown>;
    this._feed = head.get("feed") as string;
    this._seq = Number(head.get("head"));
    this.installs = this._call("GET", "/schemas") as unknown[];
  }

  /** The service's answer to a request, read from JSON; a refusal thrown: a transaction's as the error its store
   * raised, any other as a `ServiceError` (`Gone` for 410, `Unavailable` for 503). */
  _call(method: string, path: string, body?: unknown): unknown {
    const reply = this._transport(method, path, body === undefined ? undefined : J.dumps(body as any));
    if (reply.status === 200) return J.loads(reply.body);
    const refusal = ServiceError.of(reply.status, reply.body);
    if (reply.status === 400) {
      const at = refusal.error.indexOf(": ");
      const Refusal = at > 0 ? REFUSALS[refusal.error.slice(0, at)] : undefined;
      if (Refusal !== undefined) throw new Refusal(refusal.error.slice(at + 2));
    }
    throw refusal;
  }

  /** The document of the object at `path`, null where the service holds none. */
  document(path: unknown): unknown {
    return this._call("POST", "/documents", path);
  }

  /** Commits a transaction's changes in the service, refused as its store refuses them; gives back the transaction as
   * its store committed it, its record among it, null where it changed nothing. The change feed is read after it, its
   * own among what it gives the followers; a failure to read it is left to the next `poll()`, since the transaction
   * has committed. */
  commit(plain: unknown): unknown {
    const committed = (this._call("POST", "/transactions", plain) as Map<string, unknown>).get("effect") ?? null;
    try {
      this.poll();
    } catch (error) {
      if (!(error instanceof ServiceError || error instanceof TransportError)) throw error;
    }
    return committed;
  }

  /** Runs an install in the service, its store and the store below that, refused as they refuse it; one of the
   * service's own installs, run over it as `Store` runs them, is not sent back. */
  install(plain: unknown): void {
    if (this._served === 0) this.installs = this._call("POST", "/schemas", plain) as unknown[];
  }

  /** Gives `follower` each transaction the service's store commits from now, once each, in its order, as the change
   * feed gives them; gives back a function that ends it. */
  follow(follower: (plain: unknown) => void): () => void {
    this._followers.push(follower);
    return () => {
      const at = this._followers.indexOf(follower);
      if (at >= 0) this._followers.splice(at, 1);
    };
  }

  /** Gives the followers each transaction the service's store committed since they were last given one, in the order
   * it committed them; how many. */
  poll(): number {
    let count = 0;
    for (;;) {
      const query = `after=${this._seq}&feed=${encodeURIComponent(this._feed)}`;
      const read = this._call("GET", `/changes?${query}`) as Map<string, any>;
      for (const change of read.get("changes") as Map<string, unknown>[]) {
        this._seq = Number(change.get("position"));
        count += 1;
        for (const follower of [...this._followers]) follower(change.get("effect"));
      }
      if (this._seq >= Number(read.get("head"))) return count;
    }
  }
}

/** A store over the service that `transport` reaches, the service at the URL `transport`, or `remote`: a plain
 * `Builders.Store` over it, given the service's schemas by running each install that made them. */
export function Store(transport: Transport | string | Remote): any {
  const remote = transport instanceof Remote ? transport : new Remote(transport);
  const store: any = new Builders.Store(remote);
  remote._served += 1;
  try {
    for (const plain of remote.installs) store.install(plain);
  } finally {
    remote._served -= 1;
  }
  return store;
}
