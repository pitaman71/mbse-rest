/** mbse-rest's client, the service as a layer below (`Store.ts`'s `Remote`), its transaction the service's, held open
 * across its requests, and a cache layer over it (`Store`), given what others commit by the change feed in either
 * follow mode, against the Python service (mbse-basis CAP-290, CAP-308, the stacked stores proposal's third stage): it
 * runs `python3/tests/serve.py`, a service per path prefix, each over a store in memory of its own.
 *
 * mbse-schemas' suite BLW runs here from its sibling checkout's TypeScript notebook, each case as mbse-schemas wrote it,
 * with mbse-rest at the bottom of its stack: the suite's layer below, `lower`, is a cache layer over mbse-rest's client
 * of a service of its own, so that every transaction the suite runs reaches the service; the suite's
 * `const lower = seeded(new B.Store());` alone is changed. What a follow gives, a one-transaction journal, is held to
 * mbse-schemas' own suites (BLW, and CHG-14): a journal is not kept in a store. */

import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { createInterface } from "node:readline";
import { after, before, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Builders, Changes, JSON as J, Plain, Transactions } from "@mbse/schemas/Framework";
import { LookupError, ValueError } from "@mbse/schemas/Framework/Errors";
import { Gone, ServiceError, TransportError, Unavailable } from "../mbse/Services/Rest/Client.js";
import { CATCH_UP, nodeTransport, POLLED, Remote, Store, transportFor, xhrTransport, type Reply, type Transport }
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

/** A sibling's notebook as one module, its relative imports made absolute, each cell preceded by its case ID, the
 * cells of the cases `skip` names left out, and `replace`'s replacements made, each found exactly as often as it says. */
function generated(sibling: string, notebook: string, name: string,
    replace: [string, string, number][], skip: string[] = []): string {
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
    if (skip.includes(current)) continue;
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

/** BLW's setup, its layer below a cache layer over mbse-rest's client of a service of its own, which an install given to
 * the cache layer reaches through `exec` (mbse-schemas 0.35.0, BLW-15); BLW-11's count of what is forwarded, the cache
 * layer's alone; and BLW-12's frame binding a counted object, which crosses from the service refused, its symbol left
 * out. */
const OVER_REST: [string, string, number][] = [
  ["const lower = seeded(new B.Store());", "const lower = seeded((globalThis as any).__servedOverRest());", 1],
  // BLW-11 counts what the cache layer forwards: the layer below, a cache layer too, forwards to the service besides
  ["    sent.push(rest.subterm);", "    if (this.store === cache) sent.push(rest.subterm);", 1],
  // BLW-12: a frame binding a counted object crosses from the service with that symbol left out, annotated with why
  [`    raises(LookupError, () => noted.get("n"), "symbol 'n' of the frame: a counted 'crm.Note' has no reference");`,
    `    assert(!noted.has("n") && noted.errors[0].message.startsWith("symbol 'n' of the frame: a counted 'crm.Note' has no reference"));`, 1],
];

describe("mbse-schemas' BLW, over REST", () => {
  test("BLW: each case as mbse-schemas wrote it, mbse-rest at the bottom of the stack", async () => {
    (globalThis as any).__servedOverRest = () => Store(nodeTransport(fresh()));
    await run(generated("mbse-schemas", "36_Below.ipynb", "BLW.ts", OVER_REST));
    assert.equal((globalThis as any).__case, "BLW-15");
  });
});

const { Frame } = Transactions;
let counter = 0;

/** The books on the shelf, by name, sorted, read within a transaction of a store that holds them all. */
function names(store: any): string[] {
  return store.transaction(() => [...store.singleton("lib.TheShelf").books].map((e: any) => e.book.name.get()).sort());
}

/** A map of each book named `name`. */
function named(name: string): (t: any) => any {
  return (t: any) => t.uid(`named/${counter++}`).mutations([(mu: any) => mu.map((m: any) => m.symbols([(p: any) => p
    .symbols({ b: t.lib.Book }).spec([(_: any) => _.b.name(name)])]))]);
}

/** A transaction: the book `id` is named `name`. */
function renamed(id: string, name: string): (t: any) => any {
  return (t: any) => t.uid(`renamed/${counter++}`).mutations([(mu: any) => mu.map((m: any) => m.symbols([(p: any) => p
    .symbols({ s: t.lib.Shelf, b: t.lib.Book }).spec([(_: any) => _.s.books({ [id]: (e: any) => e.book(_.b) })])])
    .then([(w: any) => w.update((u: any) => u.apply([(p: any) => p.symbols({ b: t.lib.Book })
      .spec([(_: any) => _.b.name(name)])]))]))]);
}

/** A transaction: a book `id` on the shelf, named `name`. */
function added(id: string, name: string): (t: any) => any {
  return (t: any) => t.uid(`added/${id}`).mutations([(mu: any) => mu.upsert((u: any) => u.exists([(p: any) => p
    .symbols({ s: t.lib.Shelf, b: t.lib.Book }).spec([(_: any) => _.s.books({ [id]: (e: any) => e.book(_.b) }),
      (_: any) => _.b.name(name)])]))]);
}

/** The name of the book `id`, read within a transaction of `store`, a cache layer that holds it. */
function nameOf(store: any, id: string): string {
  return store.transaction(() => store.singleton("lib.TheShelf").books({ id }).name.get());
}

/** The frames of a stream, its completion markers left out. */
function frames(stream: any): any[] {
  const given: any[] = [];
  let failure: { error: unknown } | null = null;
  stream.subscribe({ next: (item: any) => given.push(item), error: (error: unknown) => { failure = { error }; } });
  if (failure !== null) throw (failure as { error: unknown }).error;
  return given.filter((item) => item instanceof Frame);
}

/** A transport to the service at `url`, and the requests made through it, each its method and its path. */
function requests(url: string): [Transport, [string, string][]] {
  const sent = nodeTransport(url);
  const made: [string, string][] = [];
  return [(method, path, body) => {
    made.push([method, path.split("?")[0]!]);
    return sent(method, path, body);
  }, made];
}

/** The service's change feed, from its first transaction. */
function feed(url: string): Map<string, unknown>[] {
  const transport = nodeTransport(url);
  const name = (J.loads(transport("GET", "/changes").body) as Map<string, unknown>).get("feed") as string;
  return (J.loads(transport("GET", `/changes?feed=${name}`).body) as Map<string, any>).get("journal");
}

describe("the client", () => {
  test("made, it holds the service's schemas and nothing else; a transaction's frames come from the service", () => {
    const [transport, made] = requests(fresh("library"));
    const client: any = Store(transport);
    assert.ok(client._below instanceof Remote && client instanceof Builders.Store);
    assert.ok(["lib.Shelf", "lib.Book", "lib.OnShelf"].every((n) => [...client.names()].includes(n)));
    assert.ok(["lib.Shelf", "lib.Book"].every((n) => [...client._below.names()].includes(n))); // the client's too
    assert.deepEqual(made.slice(0, 2), [["GET", "/changes"], ["GET", "/schemas"]]);
    assert.deepEqual(made.slice(2).map(([method]) => method), ["GET", "POST", "POST", "POST"]);
    assert.deepEqual(names(client), []); // it holds none of the books: nothing is loaded
    assert.equal(client.transaction(named("SICP")).length, 1);
  });

  test("a transaction spans several exec calls, in one transaction of the service", () => {
    const url = fresh("library");
    const [transport, made] = requests(url);
    const remote: any = new Remote(transport);
    const install = (J.loads(nodeTransport(url)("GET", "/schemas").body) as Plain.PlainData[])[0]!;
    remote.transaction(Plain.FromPlain(remote).Transaction(install));
    const built = (spec: (t: any) => any): any => remote.Mutations.OfTransaction((t: any) => spec(new Proxy(t, {
      get: (target, name) => (typeof name === "string" && !(name in target) ? remote[name] : target[name]) })));
    const add = built(added("BK-3", "HtDP"));
    const rename = built(renamed("BK-3", "How to Design Programs"));
    const find = built(named("How to Design Programs"));
    const before = feed(url).length;
    made.length = 0;
    remote.transaction((txn: any = null) => {
      const [first] = frames(txn.exec(new Frame(), add, true));
      const [halted] = frames(txn.exec(new Frame(), rename, false));
      assert.equal(halted.remainder.subterm, "$.mutations[0].map.then[0].update"); // read-only: halted where it writes
      assert.equal(halted.remainder.transaction, rename); // a position in the expression it was given
      const [resumed] = frames(txn.exec(halted, halted.remainder, true));
      const [found] = frames(txn.exec(new Frame(), find, true));
      assert.ok(first.journal !== null && resumed.journal !== null && found.journal === null);
      assert.equal(feed(url).length, before); // nothing committed yet
    });
    assert.deepEqual(made.map(([method]) => method), ["POST", "POST", "POST", "POST", "POST", "POST"]);
    assert.ok(made[0]![1] === "/transactions" && made[5]![1].endsWith("/commit"));
    assert.equal(feed(url).length, before + 1);
  });

  test("a refusal below aborts both", () => {
    const url = fresh("library");
    const client: any = Store(url);
    const before = feed(url).length;
    const doubled = (t: any) => t.uid("doubled/1").mutations([(mu: any) => mu.map((m: any) => m.symbols([(p: any) => p
      .symbols({ s: t.lib.Shelf, b: t.lib.Book }).spec([(_: any) => _.s.books({ "BK-1": (e: any) => e.book(_.b) })])])
      .then([(w: any) => w.update((u: any) => u.apply([(p: any) => p.symbols({ s: t.lib.Shelf, b: t.lib.Book })
        .spec([(_: any) => _.s.books({ "BK-9": (e: any) => e.book(_.b) })])]))]))]);
    assert.throws(() => client.transaction(doubled),
      (e: Error) => e instanceof LookupError && /has more than one owner/.test(e.message));
    assert.throws(() => client.transaction((txn: any = null) => {
      frames(txn.exec(new Frame(), added("BK-3", "Dropped"), true));
      throw new Error("stop"); // the cache layer's transaction throws: the service's is dropped
    }), /stop/);
    assert.equal(feed(url).length, before);
    assert.equal(client.transaction(named("Dropped")).length, 0);
    assert.equal(client.transaction(added("BK-3", "After")).length, 1); // the service goes on
  });

  test("the follow mode catches up before each transaction by default", () => {
    const url = fresh("library");
    const here: any = Store(url);
    const there: any = Store(url);
    here.transaction(added("BK-3", "HtDP")); // made through it: it holds all of it
    assert.equal(nameOf(here, "BK-3"), "HtDP");
    there.transaction(renamed("BK-3", "How to Design Programs"));
    assert.equal(nameOf(here, "BK-3"), "How to Design Programs"); // caught up as its transaction began
  });

  test("the follow mode polled reads a poll behind", () => {
    const url = fresh("library");
    const remote = new Remote(url);
    const here: any = Store(remote, POLLED);
    const there: any = Store(url, CATCH_UP);
    here.transaction(added("BK-3", "HtDP"));
    there.transaction(renamed("BK-3", "How to Design Programs"));
    assert.equal(nameOf(here, "BK-3"), "HtDP"); // a poll behind
    assert.ok(remote.poll() >= 1);
    assert.equal(remote.poll(), 0);
    assert.equal(nameOf(here, "BK-3"), "How to Design Programs");
    assert.throws(() => Store(remote, "sometimes"), ValueError);
  });

  test("its followers are given each transaction once, in the service's order", () => {
    const url = fresh("library");
    const remote = new Remote(url);
    const here: any = Store(remote, POLLED);
    const there: any = Store(url);
    here.transaction(added("BK-3", "A"));
    const seen: string[] = [];
    Changes.observe(here, (journal: unknown) => seen.push(J.dumps(Plain.ToPlain(here)(
      here.registered("Changes.Journal"), journal) as Plain.PlainData)));
    there.transaction(renamed("BK-3", "B")); // another's: read from the feed as it polls
    remote.poll();
    here.transaction(renamed("BK-3", "C")); // its own: at its commit; read from the feed after it, it changes nothing
    there.transaction(renamed("BK-3", "D")); // another's, not yet read
    remote.poll();
    assert.deepEqual(seen.map((s) => ["B", "C", "D"].map((n) => s.includes(`"${n}"`))),
      [[true, false, false], [false, true, false], [false, false, true]]);
    assert.equal(nameOf(here, "BK-3"), "D");
  });

  test("its own transaction is committed as the service committed it, its record among it", () => {
    const url = fresh("work");
    const client: any = Store(url, POLLED);
    const seen: unknown[] = [];
    Changes.observe(client, (journal: unknown) => seen.push(journal));
    client.transaction((t: any) => t.uid(`edited/${counter++}`).mutations([(mu: any) => mu.map((m: any) => m.symbols([
      (p: any) => p.symbols({ d: t.work.CommentDirectory, c: t.work.Comment }).spec([
        (_: any) => _.d.comments({ "CMT-001": (e: any) => e.comment(_.c) })])]).then([(w: any) => w.update(
      (u: any) => u.apply([(p: any) => p.symbols({ c: t.work.Comment }).spec([(_: any) => _.c.text("Edited.")])]))]))]));
    assert.equal(seen.length, 1); // one transaction, given once
    const [given] = Plain.ToPlain(client)(client.registered("Changes.Journal"), seen[0]) as Map<string, unknown>[];
    const last = feed(url).at(-1)!;
    assert.equal(given!.get("id"), last.get("id"));
    assert.ok(J.dumps(given as Plain.PlainData).includes("Provenance.Transactions")); // its record, taken in
  });

  test("an install a client runs reaches the service and the client", () => {
    const url = fresh();
    const first: any = Store(url);
    const install = (J.loads(nodeTransport(fresh("library"))("GET", "/schemas").body) as Plain.PlainData[])[0]!;
    first.transaction(Plain.FromPlain(first).Transaction(install));
    first.transaction(Plain.FromPlain(first).Transaction(install)); // again: it writes nothing
    assert.ok([...first._below.names()].includes("lib.Book"));
    assert.equal((J.loads(nodeTransport(url)("GET", "/schemas").body) as unknown[]).length, 0); // not served
    first.transaction(added("BK-1", "SICP"));
    const second: any = Store(url);
    assert.ok(![...second.names()].includes("lib.Book")); // given no installs: it holds no schemas of the service's
    second.transaction(Plain.FromPlain(second).Transaction(install));
    assert.equal(second.transaction(named("SICP")).length, 1);
  });

  test("each refusal kind and status, as an error", () => {
    const replies: Reply[] = [{ status: 200, body: "{\"feed\": \"f\", \"head\": null, \"journal\": []}" },
      { status: 200, body: "{\"transaction\": \"t1\"}" }, { status: 400, body: "{\"error\": \"TypeError: read-only\"}" },
      { status: 200, body: "{}" }, { status: 200, body: "{\"transaction\": \"t2\"}" },
      { status: 400, body: "{\"error\": \"LookupError: no such path\"}" }, { status: 200, body: "{}" },
      { status: 200, body: "{\"transaction\": \"t3\"}" }, { status: 400, body: "{\"error\": \"malformed\"}" },
      { status: 200, body: "{}" }, { status: 200, body: "{\"transaction\": \"t4\"}" },
      { status: 503, body: "{\"error\": \"the database is unreachable\"}" }, { status: 503, body: "{}" },
      { status: 410, body: "{\"error\": \"restarted\"}" }, { status: 500, body: "not json" },
      { status: 200, body: "{\"transaction\": \"t5\"}" }, { status: 200, body: "{\"frame\": {\"binds\": {}}}\n" },
      { status: 200, body: "{}" }];
    const remote: any = new Remote(() => replies.shift()!);
    const expression = remote.Mutations.OfTransaction((t: any) => t.mutations([]));
    assert.throws(() => remote.transaction(expression), (e: Error) => e instanceof TypeError && e.message === "read-only");
    assert.throws(() => remote.transaction(expression),
      (e: Error) => e instanceof LookupError && e.message === "no such path");
    assert.throws(() => remote.transaction(expression), (e: ServiceError) => e.status === 400 && e.error === "malformed");
    assert.throws(() => remote.transaction(expression), Unavailable); // its abort, refused too, left to the service
    assert.throws(() => remote.poll(), Gone);
    assert.throws(() => remote.transaction(expression), (e: ServiceError) => e.status === 500 && e.error === "not json");
    assert.throws(() => remote.transaction((txn: any = null) => frames(txn.exec(new Frame(), expression, true))),
      (e: ServiceError) => e instanceof Unavailable && /before its completion marker/.test(e.error));
    assert.equal(replies.length, 0);
  });

  test("a transaction ended refuses its exec", () => {
    const remote: any = new Remote(fresh("library"));
    let kept: any = null;
    remote.transaction((txn: any = null) => { kept = txn; });
    assert.throws(() => frames(kept.exec(new Frame(), remote.Mutations.OfTransaction((t: any) => t.mutations([])), true)),
      /has ended/);
  });

  test("transports: time the process is stopped, as a machine asleep, is not counted against a request", () => {
    // A request held open by the service (a read of the change feed waiting 2.5 s for a commit), while this process is
    // stopped 3 s, as a laptop asleep stops it: on waking, the request has waited longer than its timeout by the clock,
    // but less while the process ran, and is answered, not aborted.
    const url = fresh();
    const transport = nodeTransport(url, { timeout: 2_000 });
    const name = (J.loads(transport("GET", "/changes").body) as Map<string, unknown>).get("feed") as string;
    spawn("sh", ["-c", `sleep 0.3; kill -STOP ${process.pid}; sleep 3; kill -CONT ${process.pid}`],
      { stdio: "ignore" }).unref();
    const started = Date.now();
    const reply = transport("GET", `/changes?feed=${encodeURIComponent(name)}&wait=2.5`);
    assert.ok(Date.now() - started >= 3_000); // stopped meanwhile: longer than its timeout, by the clock
    assert.equal(reply.status, 200);
    const hurried = nodeTransport(url, { timeout: 1_000 }); // running all along: aborted at its timeout
    assert.throws(() => hurried("GET", `/changes?feed=${encodeURIComponent(name)}&wait=5`),
      (e: Error) => e instanceof TransportError && /aborted due to timeout/.test(e.message));
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
      assert.deepEqual(transport("POST", "/transactions", "{}"), { status: 200, body: "[]" });
      assert.deepEqual(sent, [["open", "POST", "http://s/transactions", false], ["header", "x-mbse-session", "tab-1"],
        ["header", "content-type", "application/json"], ["send", "{}"]]);
      assert.throws(() => xhrTransport("http://s")("POST", "/transactions", "fail"), TransportError);
    } finally {
      delete (globalThis as any).XMLHttpRequest;
    }
  });
});
