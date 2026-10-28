/** The client side of mbse-rest: translates a mutation query into well-formed REST calls, and reads the frame stream
 * back for the UI (mbse-basis FEA-006, CAP-013: an in-memory store journaled to DynamoDB). The calls are `docs/CONTRACT.md`'s; its "The client" section
 * documents this module's API. */

import { Builders, JSON as J, Plain } from "@mbse/schemas/Framework";
import * as Views from "./Views.js";

export { Views };

/** The media type of a view's response: one `References.OfFrame` as JSON a line. */
export const NDJSON = "application/x-ndjson";

/** A store for the client: it holds the framework's schemas, and the app's once `Client.loadSchemas` reads them. */
export function newStore(): any {
  return new Builders.Store();
}

/** CAP-002: every named schema `store` holds, by name, in its order: the framework's, and the app's once
 * `Client.loadSchemas` has read them. */
export function schemaNames(store: any): string[] {
  return [...store.names()];
}

/** Every error the client raises, apart from an abort, which raises the abort signal's own reason (an `AbortError`). */
export class RestError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = new.target.name;
  }
}

/** A response the service refused: its status, its body, and the body's `error` (CONTRACT.md, Wire format). Each
 * status the contract names has a class of its own; `ServiceError.of` chooses it. */
export class ServiceError extends RestError {
  /** The refusal's message: the body's `error`, else the body as it is. */
  readonly error: string;

  constructor(readonly status: number, readonly body: string) {
    let error = body;
    try {
      const parsed = globalThis.JSON.parse(body) as { error?: unknown };
      if (typeof parsed?.error === "string") error = parsed.error;
    } catch {
      // not JSON: the body as it is
    }
    super(`${status}: ${error}`);
    this.error = error;
  }

  /** The error for a refusal of `status`: `TransactionRefused`, `NotFound`, `Unimplemented`, `Unavailable`, or
   * `ServiceError` itself. */
  static of(status: number, body: string): ServiceError {
    const Class = { 400: TransactionRefused, 404: NotFound, 501: Unimplemented, 503: Unavailable }[status];
    return new (Class ?? ServiceError)(status, body);
  }
}

/** 400: the request's transaction is malformed, or the executor refused it; it wrote nothing. */
export class TransactionRefused extends ServiceError {}
/** 404: no such path, view kind or schema. */
export class NotFound extends ServiceError {}
/** 501: not served yet; `GET /schemas/{name}` (CAP-003) until mbse-schemas writes one schema object. */
export class Unimplemented extends ServiceError {}
/** 503: the service's persistence failed; a transaction that wrote is undone, and may be sent again. */
export class Unavailable extends ServiceError {}

/** The service could not be reached, or its response not received in full: `cause` is what the platform raised. */
export class TransportError extends RestError {}

/** A response the service accepted that the client cannot read (not JSON, not a frame, not the media type the
 * contract gives): `cause` is what reading it raised. */
export class ResponseError extends RestError {}

/** The request header that names the client's session (CAP-015): the service stamps it on each write. */
export const SESSION_HEADER = "x-mbse-session";

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export interface ClientOptions {
  /** The fetch to call through: the platform's by default; a test, or the corpus, gives its own. */
  readonly fetch?: Fetch;
  /** Headers sent with every call, besides `accept` and `content-type`. */
  readonly headers?: Readonly<Record<string, string>>;
  /** The interactive session the calls are made in (CAP-015): its `id`, sent as the `x-mbse-session` header for the
   * service to stamp on each write, and its `locale` and `device`, written into each edit and proposal. */
  readonly session?: Views.Session & { readonly id: string };
}

export interface CallOptions {
  /** Aborts the call, and a stream as it is read: the call rejects with the signal's reason. */
  readonly signal?: AbortSignal;
}

export interface ViewOptions extends CallOptions {
  /** An `adjacency` view's adjacency of `x`, whose entries link `y` (CAP-004, CAP-008). */
  readonly adjacency?: string;
}

/** The calls, against a service at `base` (`http://localhost:8000`; `""`, the page's own origin). */
export class Client {
  /** The service's base URL, without a trailing slash. */
  readonly base: string;
  private readonly fetch: Fetch;
  private readonly headers: Readonly<Record<string, string>>;
  private readonly session: Views.Session | undefined;

  constructor(base = "", options: ClientOptions | Fetch = {}) {
    const given: ClientOptions = typeof options === "function" ? { fetch: options } : options;
    this.base = base.replace(/\/+$/, "");
    this.fetch = given.fetch ?? globalThis.fetch.bind(globalThis);
    this.headers = { ...(given.session === undefined ? {} : { [SESSION_HEADER]: given.session.id }), ...given.headers };
    this.session = given.session === undefined ? undefined
      : { locale: given.session.locale, device: given.session.device };
  }

  /** The URL of `path` at the service. */
  url(path: string): string {
    return `${this.base}${path}`;
  }

  private async call(method: string, path: string, body?: Plain.PlainData, signal?: AbortSignal): Promise<Response> {
    const headers: Record<string, string> = { ...this.headers, accept: `application/json, ${NDJSON}` };
    const init: RequestInit = { method, headers };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
      init.body = J.dumps(body);
    }
    if (signal !== undefined) init.signal = signal;
    let response: Response;
    try {
      signal?.throwIfAborted();
      response = await this.fetch(this.url(path), init);
    } catch (error) {
      throw aborted(signal, error) ?? new TransportError(`${method} ${path}: ${describe(error)}`, { cause: error });
    }
    if (!response.ok) throw ServiceError.of(response.status, await text(response, signal));
    return response;
  }

  private async json(path: string, options: CallOptions): Promise<Plain.PlainData> {
    const body = await text(await this.call("GET", path, undefined, options.signal), options.signal);
    try {
      return J.loads(body);
    } catch (error) {
      throw new ResponseError(`GET ${path}: ${describe(error)}`, { cause: error });
    }
  }

  /** CAP-003: one schema in full. Refused (`Unimplemented`, 501) until mbse-schemas writes one schema object as a
   * document; `NotFound` (404) for a name the service's store lacks. */
  async schema(name: string, options: CallOptions = {}): Promise<Plain.PlainData> {
    return this.json(`/schemas/${encodeURIComponent(name)}`, options);
  }

  /** CAP-002, while CAP-003 is blocked: reads the service's schema snapshot into `store`, which then holds every
   * named schema, so that it can give a template's symbol a schema and read any value a frame assigns. Gives the names
   * of every named schema it holds (`schemaNames`). */
  async loadSchemas(store: any, options: CallOptions = {}): Promise<string[]> {
    const schemas = await this.json("/schemas", options);
    try {
      Plain.FromPlain(store).Snapshot([schemas]);
    } catch (error) {
      throw new ResponseError(`GET /schemas: ${describe(error)}`, { cause: error });
    }
    return schemaNames(store);
  }

  /** CAP-004: each kind's template, a transaction's expression, by kind. */
  async templates(options: CallOptions = {}): Promise<Map<string, Plain.PlainData>> {
    const templates = await this.json("/views", options);
    if (!(templates instanceof Map)) throw new ResponseError("GET /views: not a mapping of each kind's template");
    return templates as Map<string, Plain.PlainData>;
  }

  /** CAP-012: the frames `transaction` gives, filled as `kind` defines, each read back as it arrives. Breaking out of
   * the loop, or aborting `options.signal`, cancels the response. */
  async *stream(store: any, kind: Views.Kind, transaction: Plain.PlainData, options: CallOptions = {}):
      AsyncGenerator<Views.Frame> {
    const { signal } = options;
    const path = `/views/${kind}`;
    const response = await this.call("POST", path, transaction, signal);
    const type = (response.headers.get("content-type") ?? "").split(";")[0]!.trim();
    if (type !== NDJSON) {
      await response.body?.cancel().catch(() => undefined);
      throw new ResponseError(`POST ${path}: expected ${NDJSON}, not ${type || "no media type"}`);
    }
    const reader = response.body?.getReader();
    if (reader === undefined) return; // no body: no frames
    const cancel = (): void => void reader.cancel(signal?.reason).catch(() => undefined);
    signal?.addEventListener("abort", cancel, { once: true });
    const decoder = new TextDecoder();
    const frame = (line: string): Views.Frame => {
      try {
        return Views.read(store, line);
      } catch (error) {
        throw new ResponseError(`POST ${path}: a line is not a frame: ${describe(error)}`, { cause: error });
      }
    };
    let pending = "";
    let done = false;
    try {
      while (!done) {
        signal?.throwIfAborted();
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          chunk = await reader.read();
        } catch (error) {
          throw aborted(signal, error) ?? new TransportError(`POST ${path}: ${describe(error)}`, { cause: error });
        }
        signal?.throwIfAborted(); // a read the abort ended
        done = chunk.done;
        pending += decoder.decode(chunk.value, { stream: !done });
        const lines = pending.split("\n");
        pending = lines.pop() ?? "";
        for (const line of lines) if (line !== "") yield frame(line);
      }
      if (pending !== "") yield frame(pending);
    } finally {
      signal?.removeEventListener("abort", cancel);
      if (!done) await reader.cancel().catch(() => undefined); // left early: the rest is not read
      reader.releaseLock();
    }
  }

  /** CAP-012: every frame `transaction` gives, filled as `kind` defines. */
  async view(store: any, kind: Views.Kind, transaction: Plain.PlainData, options: CallOptions = {}):
      Promise<Views.Frame[]> {
    const frames: Views.Frame[] = [];
    for await (const frame of this.stream(store, kind, transaction, options)) frames.push(frame);
    return frames;
  }

  /** CAP-012 over CAP-004's template: the `kind` view of what `given` gives each symbol, a schema or a
   * `References.OfObject` (`Views.request`); an `adjacency` view names its adjacency in `options`. */
  async viewOf(store: any, kind: Views.Kind, given: Readonly<Record<string, unknown>>, options: ViewOptions = {}):
      Promise<Views.Frame[]> {
    return this.view(store, kind, Views.request(store, kind, given, options.adjacency), options);
  }

  /** CAP-005: the label view of `x`, a schema (every object of it) or a `References.OfObject`. */
  label(store: any, x: unknown, options: CallOptions = {}): Promise<Views.Frame[]> {
    return this.viewOf(store, "label", { x }, options);
  }

  /** CAP-006: the chip view of `x`, as `label`. */
  chip(store: any, x: unknown, options: CallOptions = {}): Promise<Views.Frame[]> {
    return this.viewOf(store, "chip", { x }, options);
  }

  /** CAP-007: the detail view of `x`, usually a `References.OfObject`. */
  detail(store: any, x: unknown, options: CallOptions = {}): Promise<Views.Frame[]> {
    return this.viewOf(store, "detail", { x }, options);
  }

  /** CAP-008: the `y`, a schema, that `x`, a `References.OfObject`, links through its adjacency `adjacency`. */
  adjacency(store: any, x: unknown, adjacency: string, y: unknown, options: CallOptions = {}): Promise<Views.Frame[]> {
    return this.viewOf(store, "adjacency", { x, y }, { ...options, adjacency });
  }

  /** CAP-014: writes `values` to the properties of the object `x`, a `References.OfObject`, each a value of its
   * property's schema or `null` to clear it (`Views.edit`), and gives its detail view (CAP-007) once the service has
   * committed the edit; a refused edit raises, as any view's refusal does. */
  edit(store: any, x: unknown, values: Readonly<Record<string, unknown>>, options: CallOptions = {}):
      Promise<Views.Frame[]> {
    return this.view(store, "detail", Views.edit(store, x, values, this.session), options);
  }

  /** CAP-018: proposes a new object of `schema` through `x`'s `adjacency`, its other link `link` (`Views.propose`), and
   * gives `x`'s detail view (CAP-007) once the service has committed it. */
  propose(store: any, x: unknown, adjacency: string, link: string, schema: unknown,
      values: Readonly<Record<string, unknown>>, entry: Readonly<Record<string, unknown>> = {},
      options: CallOptions = {}): Promise<Views.Frame[]> {
    return this.view(store, "detail", Views.propose(store, x, adjacency, link, schema, values, entry, this.session),
      options);
  }
}

/** The signal's reason, where `error` is what its abort raised. */
function aborted(signal: AbortSignal | undefined, error: unknown): unknown {
  if (signal?.aborted) return signal.reason;
  return error instanceof Error && error.name === "AbortError" ? error : undefined;
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function text(response: Response, signal?: AbortSignal): Promise<string> {
  try {
    return await response.text();
  } catch (error) {
    throw aborted(signal, error) ?? new TransportError(`reading a response: ${describe(error)}`, { cause: error });
  }
}
