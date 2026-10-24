/** The client against the golden corpus (`conformance/`): it builds every request the server's corpus holds, and reads
 * every response back. A fetch of its own serves the corpus, so no server runs. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { JSON as J, Plain } from "@mbse/schemas/Framework";
import { Client, newStore, schemaNames, ServiceError, Views } from "../mbse/Services/Rest/Client.js";

const ROOT = new URL("../../conformance/", import.meta.url);
const read = (name: string): string => readFileSync(new URL(name, ROOT), "utf8");

interface Case {
  name: string; method: string; path: string; request: string | null; status: number; content_type: string;
  response: string;
}
const CASES = globalThis.JSON.parse(read("cases.json")) as Case[];
const byName = new Map(CASES.map((c) => [c.name, c]));
const canonical = (text: string): string => J.dumps(J.loads(text));

/** A fetch that serves the corpus: the case whose method, path and request body agree, else 599. */
async function corpus(input: string, init?: RequestInit): Promise<Response> {
  const path = new URL(input).pathname;
  const body = typeof init?.body === "string" ? canonical(init.body) : null;
  const found = CASES.find((c) => c.method === (init?.method ?? "GET") && c.path === path
    && (c.request === null ? body === null : body === canonical(read(c.request))));
  if (found === undefined) return new Response(`no case for ${path}`, { status: 599 });
  return new Response(read(found.response), { status: found.status, headers: { "content-type": found.content_type } });
}

const client = new Client("http://corpus", corpus);

async function storeWithSchemas(): Promise<any> {
  const store = newStore();
  await client.loadSchemas(store);
  return store;
}

/** A reference the corpus's frames carry, read into `store`. */
function reference(store: any, caseName: string, symbol = "x"): unknown {
  const line = read(byName.get(caseName)!.response).split("\n")[0]!;
  return Views.read(store, line).binds.get(symbol);
}

describe("the calls", () => {
  test("CAP-002: every named schema, read from the schema snapshot", async () => {
    const store = newStore();
    const names = await client.loadSchemas(store);
    assert.ok(names.includes("work.Project") && names.includes("References.OfFrame"));
    assert.deepEqual(schemaNames(store), names);
  });

  test("CAP-003: refused until mbse-schemas writes one schema object", async () => {
    await assert.rejects(client.schema("work.Project"), (e: ServiceError) => e.status === 501);
    await assert.rejects(client.schema("work.Nothing"), (e: ServiceError) => e.status === 404);
  });

  test("the schemas, read into the client's store", async () => {
    const store = await storeWithSchemas();
    assert.deepEqual([...store.registered("work.Plans").entry.properties.keys()],
      ["original", "forecast", "completed", "progress"]);
  });

  test("CAP-004: one template per kind, its symbols unassigned", async () => {
    const templates = await client.templates();
    assert.deepEqual([...templates.keys()], [...Views.KINDS]);
    for (const [kind, template] of templates) {
      const symbols = (template as any).get("mutations")[0].get("map").get("symbols")[0].get("symbols");
      assert.deepEqual([...symbols.keys()], Views.SYMBOLS[kind as Views.Kind]);
    }
  });

  test("errors: an unknown kind, a symbol given nothing", async () => {
    const store = await storeWithSchemas();
    const label = (await client.templates()).get("label")!;
    await assert.rejects(client.view(store, "label", label), (e: ServiceError) => e.status === 400);
    const tasks = Views.request(store, "chip", { x: store.registered("work.Task") });
    await assert.rejects(client.view(store, "summary" as Views.Kind, tasks), (e: ServiceError) => e.status === 404);
  });
});

describe("requests: the client builds each one the corpus holds", () => {
  const given: Record<string, [Views.Kind, (store: any) => Record<string, unknown>, string?]> = {
    "label-capabilities": ["label", (s) => ({ x: s.registered("work.Capability") })],
    "label-directory": ["label", (s) => ({ x: s.registered("work.ProjectDirectory") })],
    "chip-tasks": ["chip", (s) => ({ x: s.registered("work.Task") })],
    "chip-comments": ["chip", (s) => ({ x: s.registered("work.Comment") })],
    "detail-feature": ["detail", (s) => ({ x: reference(s, "detail-feature") })],
    "detail-goal": ["detail", (s) => ({ x: reference(s, "detail-goal") })],
  };
  for (const [name, [kind, symbols]] of Object.entries(given)) {
    test(name, async () => {
      const store = await storeWithSchemas();
      assert.equal(J.dumps(Views.request(store, kind, symbols(store))), canonical(read(`${name}.request.json`)));
    });
  }

  const adjacencies: Record<string, [string, string, string]> = {
    "adjacency-goal-capabilities": ["work.Capability", "capabilities", "adjacency-goal-capabilities"],
    "adjacency-feature-capabilities": ["work.Capability", "capabilities", "adjacency-feature-capabilities"],
    "adjacency-comment-about": ["work.Result", "about", "adjacency-comment-about"],
  };
  for (const [name, [y, adjacency, from]] of Object.entries(adjacencies)) {
    test(name, {
      todo: "mbse-schemas refuses a spec over a symbol given a reference that designates nothing the client's store "
        + "holds (docs/CONTRACT.md, Gaps in mbse-schemas)",
    }, async () => {
      const store = await storeWithSchemas();
      const plain = Views.request(store, "adjacency", { x: reference(store, from), y: store.registered(y) }, adjacency);
      assert.equal(J.dumps(plain), canonical(read(`${name}.request.json`)));
    });
  }
});

describe("responses: the client reads each stream the corpus holds", () => {
  const streams = CASES.filter((c) => c.content_type === "application/x-ndjson");

  test("every frame reads back byte for byte", async () => {
    const store = await storeWithSchemas();
    for (const c of streams) {
      for (const line of read(c.response).split("\n").filter((l) => l !== "")) {
        const frame = Views.read(store, line);
        assert.equal(J.dumps(Plain.ToPlain(store)(frame.value.as_schema(), frame.value)), line, c.name);
      }
    }
  });

  const frames = async (name: string): Promise<[any, Views.Frame[]]> => {
    const store = await storeWithSchemas();
    const c = byName.get(name)!;
    return [store, await client.view(store, c.path.split("/").pop() as Views.Kind, J.loads(read(c.request!)))];
  };

  test("CAP-005: labels and summaries by the naming convention", async () => {
    const [store, got] = await frames("label-capabilities");
    assert.deepEqual(got.map((f) => Views.label(store, f)),
      ["No-code index view", "Logical view as chip", "Logical view of object as detail"]);
    assert.equal(Views.summary(store, got[0]!), "The index site, from the schema alone.");
  });

  test("CAP-005: the fallbacks, a schema's name and the path's last key; an empty summary", async () => {
    const [store, comments] = await frames("chip-comments");
    assert.equal(Views.label(store, comments[0]!, "x", "work.Comment"), "work.Comment CMT-001");
    assert.equal(Views.label(store, comments[0]!), "CMT-001");
    assert.equal(Views.summary(store, comments[0]!), "");
    const [, directory] = await frames("label-directory");
    assert.equal(Views.label(store, directory[0]!, "x", "work.ProjectDirectory"), "work.ProjectDirectory work.Projects");
  });

  test("CAP-006: a chip's other scalar properties", async () => {
    const [store, comments] = await frames("chip-comments");
    assert.deepEqual([...Views.chip(store, comments[0]!)], [["text", "Should chips show adjacencies?"], ["resolved", false]]);
    const [, tasks] = await frames("chip-tasks");
    assert.deepEqual(tasks.map((f) => Views.label(store, f)), ["Install the schemas", "Seed the demo"]);
    assert.equal(Views.chip(store, tasks[0]!).size, 0);
  });

  test("CAP-007: a detail's properties, its entries and the labels of what they link", async () => {
    const [store, [goal]] = await frames("detail-goal");
    assert.deepEqual([...Views.properties(store, goal!)].map(([n]) => n), ["title", "description"]);
    assert.deepEqual(goal!.entries.map((e) => Views.entryLabel(store, goal!, e)), [
      "work.InGoals: Demoable index site, work.Goals",
      "work.HasGoal: Demoable index site, MVP",
      "work.Plans: Demoable index site, No-code index view",
      "work.Plans: Demoable index site, Logical view as chip",
    ]);
  });

  test("CAP-008: each linked object's entry properties and chip", async () => {
    const [store, got] = await frames("adjacency-goal-capabilities");
    assert.deepEqual(got.map((f) => Views.label(store, f, "y")), ["No-code index view", "Logical view as chip"]);
    assert.deepEqual([...Views.entryProperties(got[0]!.entries[0])],
      [["original", "2026-11-30"], ["forecast", "2026-12-07"], ["progress", 0.25]]);
  });
});
