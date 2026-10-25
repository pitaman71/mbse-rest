/** The client's calls apart from the corpus's bodies: its base URL and headers, its typed errors, streams read in
 * pieces, aborted and left early, and the conveniences for each view kind. Every fetch here is the test's own. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { JSON as J } from "@mbse/schemas/Framework";
import {
  Client, NDJSON, NotFound, ResponseError, RestError, ServiceError, TransactionRefused, TransportError, Unavailable,
  Unimplemented, Views, newStore, type Fetch,
} from "../mbse/Services/Rest/Client.js";

const ROOT = new URL("../../conformance/", import.meta.url);
const read = (name: string): string => readFileSync(new URL(name, ROOT), "utf8");
const encoder = new TextEncoder();

interface Case { method: string; path: string; request: string | null; status: number; content_type: string;
  response: string }
const CASES = globalThis.JSON.parse(read("cases.json")) as Case[];
const canonical = (text: string): string => J.dumps(J.loads(text));

/** The corpus, served: the case whose method, path and body agree. */
const corpus: Fetch = async (input, init) => {
  const path = new URL(input).pathname;
  const body = typeof init?.body === "string" ? canonical(init.body) : null;
  const found = CASES.find((c) => c.method === (init?.method ?? "GET") && c.path === path
    && (c.request === null ? body === null : body === canonical(read(c.request))));
  if (found === undefined) return new Response(`no case for ${path}`, { status: 599 });
  return new Response(read(found.response), { status: found.status, headers: { "content-type": found.content_type } });
};

async function schemas(): Promise<any> {
  const store = newStore();
  await new Client("http://corpus", corpus).loadSchemas(store);
  return store;
}

/** A fetch answering every call with `status` and `body`, as `content-type`. */
const answering = (status: number, body: string, type = "application/json"): Fetch =>
  async () => new Response(body, { status, headers: { "content-type": type } });

/** A stream of `chunks`, given one by one as read; it stays open after them where `open`. */
function chunked(chunks: string[], open = false): { stream: ReadableStream<Uint8Array>; cancelled: () => boolean } {
  let cancelled = false;
  let next = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (next < chunks.length) controller.enqueue(encoder.encode(chunks[next++]!));
      else if (!open) controller.close();
      else return new Promise(() => undefined); // waits for ever: only a cancel ends it
    },
    cancel() { cancelled = true; },
  });
  return { stream, cancelled: () => cancelled };
}

const LINES = read("label-capabilities.response.ndjson").split("\n").filter((l) => l !== "");
const LABEL = J.loads(read("label-capabilities.request.json"));
const streaming = (stream: ReadableStream<Uint8Array>): Fetch =>
  async () => new Response(stream, { status: 200, headers: { "content-type": `${NDJSON}; charset=utf-8` } });

describe("the base URL and headers", () => {
  test("a trailing slash is dropped; the headers are sent with the contract's", async () => {
    const seen: [string, RequestInit | undefined][] = [];
    const client = new Client("http://service:8000/api//", {
      fetch: async (input, init) => { seen.push([input, init]); return answering(200, "{}")(input, init); },
      headers: { authorization: "Bearer t" },
    });
    assert.equal(client.base, "http://service:8000/api");
    await client.templates();
    await client.view(newStore(), "label", LABEL).catch(() => undefined);
    assert.deepEqual(seen.map(([url]) => url), ["http://service:8000/api/views", "http://service:8000/api/views/label"]);
    const [, post] = seen[1]!;
    assert.deepEqual(post?.headers, { authorization: "Bearer t", accept: `application/json, ${NDJSON}`,
      "content-type": "application/json" });
    assert.equal(post?.method, "POST");
  });

  test("an empty base: the page's own origin", () => {
    assert.equal(new Client().url("/views"), "/views");
    assert.equal(new Client("", corpus).url("/schemas"), "/schemas");
  });
});

describe("typed errors", () => {
  const cases: [number, Function][] = [[400, TransactionRefused], [404, NotFound], [501, Unimplemented],
    [503, Unavailable], [500, ServiceError], [405, ServiceError]];
  for (const [status, Class] of cases) {
    test(`${status}: ${Class.name}`, async () => {
      const client = new Client("http://s", answering(status, globalThis.JSON.stringify({ error: "why" })));
      await assert.rejects(client.templates(), (e: ServiceError) =>
        e instanceof Class && e instanceof ServiceError && e instanceof RestError && e.status === status
        && e.error === "why" && e.message === `${status}: why` && e.name === Class.name);
    });
  }

  test("a refusal whose body is not the contract's: the body as it is", async () => {
    const client = new Client("http://s", answering(502, "Bad Gateway", "text/plain"));
    await assert.rejects(client.loadSchemas(newStore()), (e: ServiceError) => e.error === "Bad Gateway");
  });

  test("the corpus's refusals", async () => {
    const client = new Client("http://corpus", corpus);
    await assert.rejects(client.schema("work.Project"), Unimplemented);
    await assert.rejects(client.schema("work.Nothing"), NotFound);
    const store = await schemas();
    await assert.rejects(client.view(store, "label", (await client.templates()).get("label")!), TransactionRefused);
  });

  test("a service out of reach: TransportError, its cause the platform's", async () => {
    const down = new TypeError("fetch failed");
    const client = new Client("http://s", async () => { throw down; });
    await assert.rejects(client.templates(), (e: TransportError) => e instanceof TransportError && e.cause === down);
  });

  test("a response that is not what the contract gives: ResponseError", async () => {
    await assert.rejects(new Client("http://s", answering(200, "{nope")).templates(), ResponseError);
    await assert.rejects(new Client("http://s", answering(200, "[]")).templates(), ResponseError);
    await assert.rejects(new Client("http://s", answering(200, "[]")).loadSchemas(newStore()), ResponseError);
    await assert.rejects(new Client("http://s", answering(200, "{}")).view(newStore(), "label", LABEL), ResponseError);
    const store = await schemas();
    await assert.rejects(new Client("http://s", answering(200, "{\"bogus\": 1}\n", NDJSON)).view(store, "label", LABEL),
      (e: ResponseError) => e instanceof ResponseError && /not a frame/.test(e.message));
  });
});

describe("streams", () => {
  test("lines split across chunks, and a last line without its newline", async () => {
    const store = await schemas();
    const text = LINES.join("\n");
    const pieces = [text.slice(0, 7), text.slice(7, LINES[0]!.length + 3), text.slice(LINES[0]!.length + 3)];
    const frames = await new Client("http://s", streaming(chunked(pieces).stream)).view(store, "label", LABEL);
    assert.deepEqual(frames.map((f) => Views.label(store, f)),
      ["No-code index view", "Logical view as chip", "Logical view of object as detail"]);
  });

  test("an empty body: no frames", async () => {
    assert.deepEqual(await new Client("http://s", answering(200, "", NDJSON)).view(newStore(), "label", LABEL), []);
  });

  test("left early, the response is cancelled", async () => {
    const store = await schemas();
    const body = chunked(LINES.map((l) => `${l}\n`), true);
    for await (const frame of new Client("http://s", streaming(body.stream)).stream(store, "label", LABEL)) {
      assert.equal(Views.label(store, frame), "No-code index view");
      break;
    }
    assert.ok(body.cancelled());
  });

  test("aborted as it is read: rejects with the signal's reason, the response cancelled", async () => {
    const store = await schemas();
    const body = chunked([`${LINES[0]}\n`], true); // one frame, then nothing more, for ever
    const abort = new AbortController();
    const got: string[] = [];
    const reading = (async () => {
      for await (const frame of new Client("http://s", streaming(body.stream)).stream(store, "label", LABEL,
        { signal: abort.signal })) {
        got.push(Views.label(store, frame));
        setTimeout(() => abort.abort(), 5);
      }
    })();
    await assert.rejects(reading, (e: Error) => e.name === "AbortError");
    assert.deepEqual(got, ["No-code index view"]);
    assert.ok(body.cancelled());
  });

  test("aborted before the call: the fetch is never called", async () => {
    let called = false;
    const client = new Client("http://s", async () => { called = true; return answering(200, "{}")("x"); });
    await assert.rejects(client.templates({ signal: AbortSignal.abort() }), (e: Error) => e.name === "AbortError");
    assert.equal(called, false);
  });

  test("an abort the fetch itself raises passes through", async () => {
    const abort = new AbortController();
    const client = new Client("http://s", (_, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal!.reason));
    }));
    const call = client.loadSchemas(newStore(), { signal: abort.signal });
    abort.abort();
    await assert.rejects(call, (e: Error) => e.name === "AbortError" && !(e instanceof RestError));
  });
});

describe("a call per view kind, as the corpus answers it", () => {
  const client = new Client("http://corpus", corpus);
  const reference = (store: any, file: string): unknown =>
    Views.read(store, read(file).split("\n")[0]!).binds.get("x");

  test("label and chip of a schema", async () => {
    const store = await schemas();
    assert.deepEqual((await client.label(store, store.registered("work.Capability"))).map((f) => Views.label(store, f)),
      ["No-code index view", "Logical view as chip", "Logical view of object as detail"]);
    assert.deepEqual((await client.chip(store, store.registered("work.Task"))).map((f) => Views.label(store, f)),
      ["Install the schemas", "Seed the demo"]);
  });

  test("detail and adjacency of a reference", async () => {
    const store = await schemas();
    const goal = reference(store, "detail-goal.response.ndjson");
    const [detail] = await client.detail(store, goal);
    assert.equal(Views.label(store, detail!), "Demoable index site");
    const capabilities = await client.adjacency(store, goal, "capabilities", store.registered("work.Capability"));
    assert.deepEqual(capabilities.map((f) => Views.label(store, f, "y")), ["No-code index view", "Logical view as chip"]);
    const same = await client.viewOf(store, "adjacency", { x: goal, y: store.registered("work.Capability") },
      { adjacency: "capabilities" });
    assert.equal(same.length, 2);
  });
});
