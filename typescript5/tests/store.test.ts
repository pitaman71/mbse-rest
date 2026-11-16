/** mbse-rest's client, the service as a store below (`Store.ts`'s `Remote`, mbse-schemas' `Stores.Below`) and a plain
 * `Builders.Store` over it (`Store`), against the Python service (mbse-basis CAP-290, CAP-306): it runs
 * `python3/tests/serve.py`, a service per path prefix, each over a store in memory of its own.
 *
 * mbse-schemas' suite BLW and mbse-journals' suite JRN run here from their sibling checkouts' TypeScript notebooks, each
 * case as its repository wrote it, the store below each store the suites make mbse-rest's client of a service of its
 * own: BLW's `const below: any = new B.Store();` alone is changed, and in JRN each `new Builders.Store()`, as
 * mbse-dynamodb runs them over its store. */

import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { createInterface } from "node:readline";
import { after, before, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Builders, Changes, JSON as J, Plain, Stores } from "@mbse/schemas/Framework";
import { LookupError, ValueError } from "@mbse/schemas/Framework/Errors";
import { Gone, ServiceError, TransportError, Unavailable } from "../mbse/Services/Rest/Client.js";
import { nodeTransport, Remote, Store, transportFor, xhrTransport, type Reply, type Transport }
  from "../mbse/Services/Rest/Store.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../../..");  // beside this repository's checkout: its siblings (siblings.json)
const BUILD = resolve(HERE, ".build");

let server: ChildProcess;
let base = "";
let stores = 0;

/** The URL of a service of its own, over a store in memory, empty; or the seeded library's. */
function fresh(prefix = "stores"): string {
  stores += 1;
  return `${base}/${prefix}/${stores}`;
}

before(async () => {
  server = spawn("uv", ["run", "--quiet", "python", "tests/serve.py"], { cwd: resolve(HERE, "../../python3"),
    stdio: ["ignore", "pipe", "inherit"] });
  const [line] = await new Promise<string[]>((done, fail) => {
    server.once("exit", (code) => fail(new Error(`serve.py exited: ${code}`)));
    createInterface({ input: server.stdout! }).once("line", (text) => done([text]));
  });
  base = `http://127.0.0.1:${line!.trim()}`;
  for (let i = 0; i < 200; i++) {  // until it answers
    try {
      if ((await fetch(`${base}/stores/probe/changes`)).ok) return;
    } catch {
      // not yet listening
    }
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error("serve.py did not answer");
});

after(() => {
  server?.kill();
});

/** A cell's case ID, from the markdown cell before it. */
const CASE = /<a id="([A-Z]+-\d+)"><\/a>/;

/** A sibling's notebook as one module, its relative imports made absolute, each cell preceded by its case ID, and
 * `replace`'s replacements made, each found exactly as often as it says. */
function generated(sibling: string, notebook: string, name: string,
    replace: [string, string, number][]): string {
  const folder = resolve(ROOT, sibling, "typescript5", "tests");
  const cells = (JSON.parse(readFileSync(resolve(folder, notebook), "utf8")) as { cells: any[] }).cells;
  let current = "setup";
  const parts: string[] = [];
  for (const cell of cells) {
    const source = Array.isArray(cell.source) ? cell.source.join("") : cell.source;
    if (cell.cell_type === "markdown") {
      current = CASE.exec(source)?.[1] ?? current;
      continue;
    }
    const absolute = source.replace(/(from\s+)(["'])(\.\.?\/[^"']*)\2/g, (_m: string, lead: string, q: string,
      spec: string) => `${lead}${q}${pathToFileURL(resolve(folder, spec)).href}${q}`);
    parts.push(`(globalThis as any).__case = ${JSON.stringify(current)};`, absolute);
  }
  let module = parts.join("\n") + "\nexport {};\n";
  for (const [from, to, times] of replace) {
    assert.equal(module.split(from).length - 1, times, `${notebook}: ${from}`);
    module = module.split(from).join(to);
  }
  mkdirSync(BUILD, { recursive: true });
  const target = resolve(BUILD, name);
  writeFileSync(target, module);
  return target;
}

/** Runs a generated module; a failure names the case it failed in. */
async function run(module: string): Promise<void> {
  try {
    await import(pathToFileURL(module).href);
  } catch (error) {
    throw new Error(`${(globalThis as any).__case}: ${error instanceof Error ? error.stack : String(error)}`);
  }
}

/** `new Builders.Store()`, made over mbse-rest's client of a service of its own: a test's stand-in, which adds
 * nothing. An install the suite runs in it is run by the service first, as any store below runs the installs of the
 * store over it (`Stores.Below.install`, CAP-306). */
class Stacked extends Builders.Store {
  constructor(below: any = null) {
    super(below ?? new Remote(nodeTransport(fresh())));
  }
}

describe("mbse-schemas' BLW, over REST", () => {
  test("BLW-01..19: the client as the store below, each case as mbse-schemas wrote it", async () => {
    (globalThis as any).__servedOverRest = () => Store(nodeTransport(fresh()));
    await run(generated("mbse-schemas", "36_Below.ipynb", "BLW.ts",
      [["const below: any = new B.Store();", "const below: any = (globalThis as any).__servedOverRest();", 1]]));
    assert.equal((globalThis as any).__case, "BLW-19");
  });
});

describe("mbse-journals' JRN, over REST", () => {
  test("JRN-01..08: each journal kept over REST, each case as mbse-journals wrote it", async () => {
    (globalThis as any).__Stacked = Stacked;
    const before = stores;
    await run(generated("mbse-journals", "03_Journals.ipynb", "JRN.ts",
      [["new Builders.Store()", "new (globalThis as any).__Stacked()", 1]]));
    assert.equal((globalThis as any).__case, "JRN-08");
    assert.ok(stores - before >= 6); // the model, the journals, the replica, again, here and there
  });
});

/** The book on the library's shelf whose key is `id`. */
function book(store: any, id: string): any {
  return [...store.singleton("lib.TheShelf").books].find((e: any) => e.id.get() === id).book;
}

function names(store: any): string[] {
  return [...store.singleton("lib.TheShelf").books].map((e: any) => e.book.name.get()).sort();
}

function rename(store: any, id: string, name: string): void {
  store.transaction(() => store.lib.Book(book(store, id), (b: any) => b.name(name)));
}

/** The library's install, as the service gives it: the client takes it from the service. */
function libraryInstall(): Plain.PlainData {
  const reply = nodeTransport(fresh("library"))("GET", "/schemas");
  return (J.loads(reply.body) as Plain.PlainData[])[0]!;
}

describe("the client", () => {
  test("made, it holds the service's schemas, loads nothing, then loads what is read", () => {
    const url = fresh("library");
    const sent = nodeTransport(url);
    const read: string[] = [];
    const remote = new Remote((method, path, body) => {
      if (path === "/documents") read.push(body!);
      return sent(method, path, body);
    });
    const client: any = Store(remote);
    assert.ok(Stores.isBelow(remote) && client.constructor === Builders.Store);
    assert.ok(["lib.Shelf", "lib.Book", "lib.OnShelf"].every((n) => [...client.names()].includes(n)));
    assert.equal(read.length, 0);
    assert.deepEqual(names(client), ["LISP 1.5", "SICP"]);
    assert.equal(read.length, 3); // the shelf, then each book read
    assert.equal((J.loads(sent("GET", "/schemas").body) as unknown[]).length, 1); // its installs, not sent back
  });

  test("a store above stacks over it: loads on demand, writes through, given others' writes in order, once", () => {
    const url = fresh("library");
    const here: any = Store(url);
    const remote = new Remote(url);
    const there: any = Store(remote);
    const above: any = new Builders.Store(there);
    const install = libraryInstall();
    above.transaction(Plain.FromPlain(above).Transaction(install));
    const effects: unknown[] = [];
    Changes.observe(above, (effect) => effects.push(effect));
    assert.deepEqual(names(above), ["LISP 1.5", "SICP"]);
    rename(here, "BK-1", "Structure");
    rename(here, "BK-2", "Lisp");
    assert.deepEqual(names(above), ["LISP 1.5", "SICP"]); // not yet read from the feed
    assert.equal(remote.poll(), 2);
    assert.equal(remote.poll(), 0);
    assert.deepEqual([names(above), effects.length], [["Lisp", "Structure"], 2]);
    rename(above, "BK-1", "SICP"); // written through: committed by the service first
    assert.deepEqual(names(here), ["Lisp", "Structure"]); // not yet read
    rename(here, "BK-2", "LISP"); // its own commit reads the change feed after it: the other's first
    assert.deepEqual(names(here), ["LISP", "SICP"]);
  });

  test("its followers are given each transaction once, in the service's order", () => {
    // its own at its commit, as the service committed it; others' read from the change feed, in the service's order,
    // what they changed of the objects it holds: polled before its own, before it, else read after its own commits;
    // its own, read from the change feed again, changes nothing, and its followers are told nothing more
    const url = fresh("library");
    const remote = new Remote(url);
    const here: any = Store(remote);
    const there: any = Store(url);
    assert.deepEqual(names(here), ["LISP 1.5", "SICP"]); // each book held
    const seen: string[] = [];
    Changes.observe(here, (effect) => seen.push(J.dumps(Plain.ToPlain(here).Transaction(effect))));
    rename(there, "BK-1", "A"); // another's, before its own: read from the feed as it polls
    remote.poll();
    rename(here, "BK-2", "B"); // its own: at its commit; read from the feed after it, it changes nothing
    rename(there, "BK-1", "C"); // another's, not yet read
    rename(here, "BK-2", "D"); // its own, then the other's, read after it
    remote.poll();
    assert.deepEqual(seen.map((s) => ["A", "B", "C", "D"].map((n) => s.includes(`"${n}"`))),
      [[true, false, false, false], [false, true, false, false], [false, false, false, true],
        [false, false, true, false]]);
    assert.deepEqual(names(here), ["C", "D"]);
  });

  test("its own transaction is committed as the service committed it, its record among it", () => {
    const url = fresh("work");
    const remote = new Remote(url);
    const client: any = Store(remote);
    const transport = nodeTransport(url);
    const head = Number((J.loads(transport("GET", "/changes").body) as Map<string, unknown>).get("head"));
    const seen: string[] = [];
    Changes.observe(client, (effect) => seen.push(J.dumps(Plain.ToPlain(client).Transaction(effect))));
    const comment = client.singleton("work.Comments").comments({ id: "CMT-001" });
    client.transaction(() => client.work.Comment(comment, (c: any) => c.text("Edited.")));
    remote.poll();
    assert.equal(seen.length, 1); // one transaction, given once
    const read = J.loads(transport("GET", `/changes?after=${head}`).body) as Map<string, any>;
    const changes = read.get("changes") as Map<string, unknown>[];
    assert.equal(changes.length, 1);
    assert.ok(seen[0]!.includes("Provenance")); // the service's record of it among it
    assert.equal(seen[0], J.dumps(changes[0]!.get("effect") as Plain.PlainData));
  });

  test("a refusal of the service's is thrown as the error its store raised, and writes nothing", () => {
    const remote = new Remote(fresh("library"));
    const client: any = Store(remote);
    const path = { singleton: "lib.TheShelf", next: { entry: { i: "books", o: "shelf", properties: { id: "BK-1" },
      next: { target: {} } } } };
    const nope = J.loads(JSON.stringify({ mutations: [{ upsert: { exists: [{ symbols: { x: { reference: { path } } },
      spec: [{ x: [{ as_property: { name: "nope", mutations: [{ set: { value: 1 } }] } }] }] }] } }] }));
    assert.throws(() => remote.commit(nope),
      (e: Error) => e instanceof ValueError && /has no property 'nope'/.test(e.message));
    assert.deepEqual(names(client), ["LISP 1.5", "SICP"]);
  });

  test("an install a client runs is sent to the service, and served to the next", () => {
    const url = fresh();
    const first: any = Store(url);
    const install = libraryInstall();
    first.transaction(Plain.FromPlain(first).Transaction(install));
    first.transaction(Plain.FromPlain(first).Transaction(install)); // again: it writes nothing, served once
    const second: any = Store(url);
    assert.ok([...second.names()].includes("lib.Book"));
    assert.equal((J.loads(nodeTransport(url)("GET", "/schemas").body) as unknown[]).length, 1);
  });

  test("each refusal kind and status, as an error", () => {
    const replies: Reply[] = [{ status: 200, body: "{\"feed\": \"f\", \"head\": 0, \"changes\": []}" },
      { status: 200, body: "[]" }, { status: 400, body: "{\"error\": \"TypeError: read-only\"}" },
      { status: 400, body: "{\"error\": \"LookupError: no such path\"}" }, { status: 400, body: "{\"error\": \"malformed\"}" },
      { status: 503, body: "{\"error\": \"the database is unreachable\"}" }, { status: 410, body: "{\"error\": \"restarted\"}" },
      { status: 500, body: "not json" }];
    const client = new Remote(() => replies.shift()!);
    assert.throws(() => client.commit(null), (e: Error) => e instanceof TypeError && e.message === "read-only");
    assert.throws(() => client.commit(null), (e: Error) => e instanceof LookupError && e.message === "no such path");
    assert.throws(() => client.commit(null), (e: ServiceError) => e.status === 400 && e.error === "malformed");
    assert.throws(() => client.commit(null), Unavailable);
    assert.throws(() => client.poll(), Gone);
    assert.throws(() => client.document(null), (e: ServiceError) => e.status === 500 && e.error === "not json");
  });

  test("transports: an unreachable service, and a browser's synchronous XMLHttpRequest", () => {
    assert.throws(() => nodeTransport("http://127.0.0.1:9", { timeout: 2_000 })("GET", "/changes"), TransportError);
    const sent: unknown[] = [];
    class FakeRequest {
      status = 200;
      responseText = "[]";
      open(...args: unknown[]): void { sent.push(["open", ...args]); }
      setRequestHeader(...args: unknown[]): void { sent.push(["header", ...args]); }
      send(body: unknown): void {
        if (body === "fail") throw new Error("network down");
        sent.push(["send", body]);
      }
    }
    (globalThis as any).XMLHttpRequest = FakeRequest;
    try {
      const transport: Transport = transportFor("http://s/", { headers: { "x-mbse-session": "tab-1" } });
      assert.deepEqual(transport("POST", "/documents", "{}"), { status: 200, body: "[]" });
      assert.deepEqual(sent, [["open", "POST", "http://s/documents", false], ["header", "x-mbse-session", "tab-1"],
        ["header", "content-type", "application/json"], ["send", "{}"]]);
      assert.throws(() => xhrTransport("http://s")("POST", "/transactions", "fail"), TransportError);
    } finally {
      delete (globalThis as any).XMLHttpRequest;
    }
  });
});
