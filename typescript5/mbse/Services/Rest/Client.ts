/** The client side of mbse-rest: translates a mutation query into well-formed REST calls, and reads the frame stream
 * back for the UI (VISUALIZATION.md, FEA-006, CAP-013). The calls are `docs/CONTRACT.md`'s. */

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

/** A response the service refused: its status and its error, `{"error": message}`. */
export class ServiceError extends Error {
  constructor(readonly status: number, readonly body: string) {
    let message = body;
    try {
      message = (globalThis.JSON.parse(body) as { error?: string }).error ?? body;
    } catch {
      // not JSON: the body as it is
    }
    super(`${status}: ${message}`);
    this.name = "ServiceError";
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/** The calls, against a service at `base` (`http://localhost:8000`), through `fetch` (a test gives its own). */
export class Client {
  constructor(readonly base: string, private readonly fetch: Fetch = globalThis.fetch.bind(globalThis)) {}

  private async call(method: string, path: string, body?: Plain.PlainData): Promise<Response> {
    const init: RequestInit = { method, headers: { accept: `application/json, ${NDJSON}` } };
    if (body !== undefined) {
      init.headers = { ...init.headers, "content-type": "application/json" };
      init.body = J.dumps(body);
    }
    const response = await this.fetch(`${this.base}${path}`, init);
    if (!response.ok) throw new ServiceError(response.status, await response.text());
    return response;
  }

  /** CAP-003: one schema in full. Refused (501) until mbse-schemas writes one schema object as a document. */
  async schema(name: string): Promise<Plain.PlainData> {
    return J.loads(await (await this.call("GET", `/schemas/${encodeURIComponent(name)}`)).text());
  }

  /** CAP-002, while CAP-003 is blocked: reads the service's schema snapshot into `store`, which then holds every
   * named schema, so that it can give a template's symbol a schema and read any value a frame assigns. Gives the names
   * of every named schema it holds (`schemaNames`). */
  async loadSchemas(store: any): Promise<string[]> {
    const text = await (await this.call("GET", "/schemas")).text();
    Plain.FromPlain(store).Snapshot([J.loads(text)]);
    return schemaNames(store);
  }

  /** CAP-004: each kind's template, a transaction's expression, by kind. */
  async templates(): Promise<Map<string, Plain.PlainData>> {
    return J.loads(await (await this.call("GET", "/views")).text()) as Map<string, Plain.PlainData>;
  }

  /** CAP-012: the frames `transaction` gives, filled as `kind` defines, each read back as it arrives. */
  async *stream(store: any, kind: Views.Kind, transaction: Plain.PlainData): AsyncGenerator<Views.Frame> {
    const response = await this.call("POST", `/views/${kind}`, transaction);
    const decoder = new TextDecoder();
    let pending = "";
    const reader = response.body?.getReader();
    while (reader !== undefined) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) if (line !== "") yield Views.read(store, line);
      if (done) break;
    }
    if (pending !== "") yield Views.read(store, pending);
  }

  /** CAP-012: every frame `transaction` gives, filled as `kind` defines. */
  async view(store: any, kind: Views.Kind, transaction: Plain.PlainData): Promise<Views.Frame[]> {
    const frames: Views.Frame[] = [];
    for await (const frame of this.stream(store, kind, transaction)) frames.push(frame);
    return frames;
  }
}
