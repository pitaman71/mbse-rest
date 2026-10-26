# The REST contract (M0)

What mbse-rest serves, and what its client, mbse-react and mbse-dynamodb build against: VISUALIZATION.md's CAP-002,
CAP-003, CAP-004 and CAP-012, the view kinds of CAP-005 to CAP-008, and the persistence plugin of CAP-013. This page
fixes what VISUALIZATION.md leaves open; it cites the capabilities rather than restating them.

The code is the contract's other half, and the golden corpus (`conformance/`) checks that both sides keep it:

| Part | Python (server) | TypeScript (client) |
|---|---|---|
| Endpoints | `python3/mbse/Services/Rest/Service.py` | `typescript5/mbse/Services/Rest/Client.ts` |
| View kinds | `python3/mbse/Services/Rest/Views.py` (fills frames) | `typescript5/mbse/Services/Rest/Views.ts` (fills templates, reads frames) |
| Persistence | `python3/mbse/Services/Rest/Persistence.py` | none: persistence is the server's |
| Corpus | `python3/mbse/Services/Rest/Conformance.py` writes `conformance/` | `typescript5/tests/client.test.ts` reads it |

## Wire format

Every body that carries a schema-governed value is mbse-schemas' plain form as JSON, written and read by mbse-schemas
alone (`Plain`, `JSON`): a transaction is its expression (`Plain.ToPlain(store).Transaction`), a frame a
`References.OfFrame` value. Nothing here defines a format of its own beyond the envelopes below.

- A JSON body is `application/json`. A refusal is `{"error": "<message>"}` with a 4xx or 5xx status.
- A stream of frames is `application/x-ndjson`: one `References.OfFrame` a line, each line as
  `JSON.ToJSON(store)(References.OfFrame, frame)` writes it, each ending with `\n`. No frames is an empty body. The
  status is decided before the first frame is written: a refused transaction is a 400 with an error body, never a
  partial stream.

## Endpoints

| Method and path | For | Request | Response |
|---|---|---|---|
| `GET /schemas` | CAP-002 | none | the store's schema snapshot, while CAP-003 is blocked: the schemas transaction of `Plain.ToPlain(store).Snapshot()` |
| `GET /schemas/{name}` | CAP-003 | none | 501 until mbse-schemas writes one schema object (Gaps, 1); 404 for a name the store lacks |
| `GET /views` | CAP-004 | none | `{"label": T, "chip": T, "detail": T, "adjacency": T}`, each `T` a template, a transaction's expression |
| `POST /views/{kind}` | CAP-012 | a template of `kind`, its symbols given: a transaction's expression | the frames, NDJSON; 404 for an unknown kind, 400 for a transaction refused |

**Endpoints take no arguments** (CAP-012): no query parameters, and no path segment that binds anything. A view's
path names its endpoint, one per kind; the mutation expression in the request's body carries the query's bindings,
each symbol given a schema or a `References.OfObject`, and whatever the spec adds. `GET /schemas/{name}` keeps its
name for now, answering 501 (tech debt, TODO.md, 1).

A client reads `GET /schemas` into its own store first (`Client.loadSchemas`, which executes it with
`Plain.FromPlain(store).Snapshot`): its store then holds every named schema, the framework's and the app's, and the
list of their names is the store's own (`schemaNames(store)`). Giving a template's symbol a schema, and reading a value
of a value object schema, needs the app's schemas there; the frames themselves need only the framework's.

CAP-003's intended body, once mbse-schemas can write it: the schema as a document of one upsert, as the snapshot's
first transaction writes each schema (a schema with no name of its own defined where it is linked, `{"def": ...}`;
a named one referred to by path, `{"ref": {"path": ...}}`).

## Templates (CAP-004)

A template is one map whose one pattern declares the kind's symbols, each given neither a schema nor a reference:

```json
{"mutations": [{"map": {"symbols": [{"symbols": {"x": {}, "y": {}}}]}}]}
```

| Kind | Symbols | The client gives |
|---|---|---|
| `label` | `x` | `x` a schema (every object of it) or a `References.OfObject` (that one object) |
| `chip` | `x` | as `label` |
| `detail` | `x` | as `label`; usually a reference |
| `adjacency` | `x`, `y` | `x` a reference, `y` a schema; and adds to the pattern's spec `_.x.<adjacency>([_.y])`, naming the adjacency (CAP-004) |

The client builds the filled template with mbse-schemas' builders, `Views.request(store, kind, given, adjacency?)`,
never by editing JSON: for example, the capabilities of a goal,

```typescript
Views.request(store, "adjacency", { x: goalReference, y: store.registered("work.Capability") }, "capabilities");
```

A template carries no spec; the client may add to it (CAP-004), as the `adjacency` view does to name the adjacency
it follows, a member of `x`'s schema, in plain builder notation, as above.

## View kinds (CAP-005 to CAP-008)

The server executes the transaction and, for each frame the executor gives back, writes a `References.OfFrame`:
`binds`, each symbol's `References.OfObject`; `assigns`, a `References.OfProperties` for each object it witnesses,
once, in the order met; `entries`, a `References.OfEntry` for each entry it witnesses, once. `variables` is empty.

| Kind | `assigns` | `entries` |
|---|---|---|
| `label` (CAP-005) | `x`: its label's and its summary's properties | none |
| `chip` (CAP-006) | `x`: `label`'s, then the first three other scalar properties its schema declares that it holds | none |
| `detail` (CAP-007) | `x`: every property it holds; then each object its entries link: `label`'s | every entry of each of `x`'s named adjacencies, in the schema's order |
| `adjacency` (CAP-008) | `y`: `chip`'s | every entry of `x`'s named adjacencies that links `y` |

- **Label and summary** (CAP-005's convention). The label's property is the first of `label`, `name` and `title` that
  the object holds; the summary's, the first of `summary` and `description` that it holds. The values are the properties' own, so `assigns` names them as
  the schema does (`title`, not `label`). The client reads them back: `Views.label`, `Views.summary`, `Views.chip`.
- **Fallbacks** (client side, from what the frame carries). An object's label, where it holds none: its schema's
  name, where the caller knows it (it gave the symbol that schema), and its path's last key, the owning entry's key
  values, or, a singleton, the singleton's name: `work.Comment CMT-001`, `work.ProjectDirectory work.Projects`. An
  entry's label: its relation's name and its linked objects' labels in its links' order,
  `work.Plans: Demoable index site, No-code index view` (`Views.entryLabel`). A summary, where none is held, is empty.
- **Entry views** (CAP-005 and CAP-006 of a `References.OfEntry`) are requested as mutation expressions, as any view
  is, and come back in frames' `entries`, with the entry's properties; the client labels them (`Views.entryLabel`).
- **Counted objects** have no reference: a frame that binds one is left out of the stream, and an entry that links one
  out of `entries` (FEA-003).
- A view's transaction may write (CAP-013's flow): whatever it writes is committed, and journaled, before its frames
  are filled.

## Edits (CAP-014)

An edit writes an object's properties and gives back its detail: the detail view's template, `x` given the object's
`References.OfObject`, then an `update` whose spec writes each property given, a value of its property's schema, or
none to clear it, posted to `POST /views/detail`. The endpoint takes no new arguments: the expression carries the
edit, as it carries any view's bindings. The service commits and journals it (Persistence, below) before it fills the
frames, so the response is the object's detail as the edit left it; a refused edit is a 400 and writes nothing.

- **The client**: `Views.edit(store, reference, values)` builds it, and `client.edit(store, reference, values)` sends
  it and reads the detail back. An edit of no property is refused by the client, and one of a property the object's
  schema lacks by mbse-schemas' spec recorder, before anything is sent.
- **The corpus**: `edit-task-title` (markdown written into a task's title and description) and `edit-task-clear` (a
  description cleared), each on a fresh server, since they write.
- What a UI may edit, and how text is shown, is the UI's: CAP-014 reads every `Schemas.OfStr` as markdown and leaves
  ownership keys uneditable; the service does not validate what it is given.

## Provenance (CAP-015)

An app with a history lists its installs in `Schemas.INSTALLS` (`installs_of`): its schemas, `Provenance.install`
(mbse-schemas 0.26.0), and an install calling `Provenance.extend` for the schemas whose objects have a history; the
WorkTracker's are its comments.

- **The service stamps every transaction that writes** before executing and journaling it (`Service.stamp`): a `uid`
  where it has none, so that a replay finds the same record; `when`, from its clock, as UTC ISO 8601 text; and the
  session's `id` and `who`, the session the request names in the `x-mbse-session` header (else `<who>:default`) and
  the service's identity (`MBSE_REST_USER`, `demo` by default), keeping the client's `locale`, `device` and `where`.
  Its startup installs are given `when` from its clock too. The journal holds what was stamped.
- **The detail and adjacency views carry provenance**: for `x`'s detail, and for each `y` of an adjacency view, the
  records of the transactions that created it and last wrote it, each one's session and the session's identity
  (`assigns`), and the entries linking them, `Provenance.CreatedBy`, `ModifiedBy`, `InSession` and `Who`
  (`entries`). An identity has no properties: its name is its directory key, the last key of its reference's path.
- **The corpus** stamps reproducibly: a fixed clock and uids by count (`corpus-1`, ...).

## Proposals (CAP-018)

A proposal makes a new object through an existing one's adjacency: an `upsert` whose symbols are `x`, the inbound
object's `References.OfObject`, and `n`, given the new object's schema, and whose spec writes `x`'s entry in the
adjacency linking `n` through the relation's other link (with the entry's properties, where given) and `n`'s
properties, posted to `POST /views/detail`. The service commits and journals it; an owned object is placed in its
directory, its key given there (CMT-004 for the WorkTracker's next comment); the response is `x`'s detail with the new
entry.

- **The client**: `Views.propose(store, x, adjacency, link, schema, values, entry)` builds it, and
  `client.propose(...)` sends it.
- **The corpus**: `propose-thread` (a comment about a feature) and `propose-reply` (a reply resolving a thread).
- Editing an existing entry's properties with its linked object's, the rest of CAP-018, is not built yet.

## Persistence (CAP-013)

`Persistence.Plugin`, a Python protocol whose every argument and result is mbse-schemas' plain form, so that a plugin
never holds a proxy:

```python
class Plugin(Protocol):
    def load(self) -> tuple[list[PlainData] | None, list[PlainData]]: ...  # latest snapshot, journal after it
    def journal(self, transaction: PlainData) -> None: ...  # a committed transaction that writes, its expression
    def snapshot(self, snapshot: list[PlainData]) -> None: ...  # Plain.ToPlain(store).Snapshot(), two transactions
```

- **Startup.** `Persistence.replay(store, plugin)` reads the snapshot (`Plain.FromPlain(store).Snapshot`), then
  executes each journaled transaction in order. Where the plugin holds nothing, the service runs the app's installs
  (`Schemas.install`, then `Seed.seed`) and gives the plugin a snapshot of what they wrote: the database is
  initialized by schema.
- **Journal.** A transaction is journaled after it commits, in commit order, when its expression has an `upsert` or an
  `update` term; a refused transaction writes nothing and is never journaled.
- **Snapshots.** Every `snapshot_every` journaled transactions (100 by default); after one, `load` gives only what
  is journaled after it.
- `Persistence.Memory` is the reference implementation. `mbse.Persistence.DynamoDB` (mbse-dynamodb) implements the
  same protocol. Every plugin must pass `PersistenceCases.CASES`, each a function given a maker of a fresh plugin,
  which checks the service's use of it through the protocol alone (`load`, and a `Counting` wrapper for how often it
  journals and snapshots), never a plugin's own attributes; mbse-rest runs them with `Memory`
  (`python3/tests/test_service.py`), mbse-dynamodb with its own plugin.

## The golden corpus

`conformance/cases.json` lists each case: `name`, `method`, `path`, `request` (a file, or null), `status`,
`content_type` and `response` (a file). Each case is sent to a fresh stub server over the WorkTracker seed
(mbse-demo-apps). `uv run python -m mbse.Services.Rest.Conformance` writes it; `--check` reports what differs.

Beside the hand-written cases, the corpus holds a case for every view mbse-react asks of the seed (`ui-*`), generated
from the store so that the UI can develop against the corpus alone: each app reference object schema's chips
(`ui-chip-<schema>`, CAP-006) and entries (`ui-entries-<schema>`, CAP-007 with `x` given the schema, the relation
browser's), each object's detail (`ui-detail-<key>`, CAP-007), and each object's named adjacencies, one case for each
schema whose objects their entries may link (`ui-adjacency-<key>-<adjacency>-<schema>`, CAP-008). They only read, so
they share one server. Each carries `view`, what its request is made of: its `kind`, what each symbol is `given` (a
`schema` by name, or a `reference`, a `References.OfObject` in mbse-schemas' JSON), and, an adjacency view's, its
`adjacency`; the client's tests build each such request again from it, byte for byte.

- The server's tests require the corpus to be current: a change to a response is a change to the corpus, committed
  with it, and reviewed as a change to the contract.
- The client's tests serve the corpus through a fetch of their own: the client must build every request byte for byte
  (in mbse-schemas' JSON) and read every frame back byte for byte. mbse-react can develop against the corpus with
  the same fetch, before a server runs.

## Refusals and failures (M1)

Every refusal is `{"error": "<message>"}`, `application/json`; the message is for people, not to be parsed.

| Status | When |
|---|---|
| 400 | `POST /views/{kind}`: the body is not strict JSON (mbse-schemas' `JSON.loads`), or not a transaction's expression, or the executor refuses it; or a frame it gives does not bind each of the kind's symbols. It wrote nothing. |
| 404 | a path the service does not serve, a view kind it lacks, a schema name its store lacks |
| 405 | a method a path does not take |
| 500 | a fault of the service's own |
| 501 | `GET /schemas/{name}` (CAP-003), until Gaps, 1 is closed |
| 503 | the plugin failed: a transaction that wrote could not be journaled, and is undone, so that it may be sent again; or, after that, the store could not be read back from the plugin, and then every request answers 503 until the service restarts |

- **What the plugin has not journaled is undone.** Transactions on one store do not nest, so a transaction that
  writes commits in memory before the service can journal it or check its frames. Where it is then refused (a frame
  lacks a symbol) or its journal fails, the service reads the store back from the plugin (`Service.restore`): the
  snapshot, then the journal, as at startup. The store then holds exactly what the plugin holds.
- **A snapshot that fails** is logged and tried again after the next journaled transaction; the journal still holds
  every transaction, so nothing is lost and the request is answered as usual.
- **A plugin that fails at startup** (`load`, or the first snapshot) fails the start: `app()` raises.
- **One transaction at a time**: every endpoint holds the service's lock while it reads or writes the store; a view's
  frames are computed and written as JSON under it, then streamed (`StreamingResponse`, chunked) once the status is
  decided.

## The service for any MBSE app (M1)

```python
from mbse.Services.Rest import Service

api = Service.app(installs, plugin=None, snapshot_every=100, origins=())  # a FastAPI application
```

- `installs`: the app's installs, each a callback given a transaction (`store.transaction(install)`), its schemas'
  first, then, optionally, its seed's. `Service.installs_of("my.App", seed=True)` finds them by mbse-demo-apps'
  layout: `my.App.Schemas.install`, then `my.App.Seed.seed` where the package has one and `seed` is true.
- `plugin`: a `Persistence.Plugin`; `Persistence.Memory()` where None. `Service.plugin_of(name)` makes one by name:
  `memory`, or `module:attribute`, a class or function called with no arguments (its own configuration is its own).
- `origins`: the origins a browser may call the service from (CORS, `GET` and `POST`): none by default.
- `api.state.service` is the `Service`: its `store`, `plugin` and `installs`.
- `Service.work_tracker(plugin)` is the stub server over the WorkTracker, as before.

### Running it

```sh
cd python3 && uv run python -m mbse.Services.Rest   # serves with uvicorn, as the environment configures it
```

| Variable | Default | What |
|---|---|---|
| `MBSE_REST_APP` | `mbse.Demos.Apps.WorkTracker` | the app's package, its installs by `installs_of` |
| `MBSE_REST_SEED` | `1` | whether its `Seed.seed` runs at first start (`1`/`0`, `true`/`false`) |
| `MBSE_REST_PLUGIN` | `memory` | the persistence plugin, by `plugin_of`'s name, e.g. `mbse.Persistence.DynamoDB.Plugin:Plugin` |
| `MBSE_REST_SNAPSHOT_EVERY` | `100` | journaled transactions between snapshots |
| `MBSE_REST_ORIGINS` | none | the UI's origins, comma-separated, e.g. `http://localhost:5173` |
| `MBSE_REST_USER` | `demo` | the identity the service stamps on writes (CAP-015), standing in for a validated token |
| `MBSE_REST_HOST` | `127.0.0.1` | where it listens |
| `MBSE_REST_PORT` | `8000` | |

`Service.from_environment()` builds the same application, for any ASGI server:
`uv run uvicorn --factory mbse.Services.Rest.Service:from_environment`.

## The client (M1)

`typescript5/mbse/Services/Rest/Client.ts` (`@mbse/rest/Services/Rest/Client`), over mbse-schemas' TypeScript
implementation. A store (`newStore()`) reads the schemas once, then gives symbols schemas and reads frames back
(`Views`).

```typescript
import { Client, newStore, Views, TransactionRefused } from "@mbse/rest/Services/Rest/Client";

const client = new Client("http://localhost:8000");          // or "", the page's own origin; or { fetch, headers }
const store = newStore();
const names = await client.loadSchemas(store);                // CAP-002: every named schema, now in `store`
const tasks = await client.chip(store, store.registered("work.Task"));
for (const frame of tasks) console.log(Views.label(store, frame), [...Views.chip(store, frame)]);
const abort = new AbortController();
for await (const frame of client.stream(store, "detail", Views.request(store, "detail", { x: ref }),
  { signal: abort.signal })) { /* each frame as it arrives */ }
```

| Member | For |
|---|---|
| `new Client(base = "", options?)` | `base` without its trailing slash; `options` is `{fetch?, headers?}`, or a fetch (as in M0) |
| `loadSchemas(store, {signal}?)` | CAP-002: reads the schema snapshot into `store`; gives `schemaNames(store)` |
| `schema(name, {signal}?)` | CAP-003: rejects with `Unimplemented` (501) for now, `NotFound` for an unknown name |
| `templates({signal}?)` | CAP-004: a `Map` of each kind's template |
| `stream(store, kind, transaction, {signal}?)` | CAP-012: an async generator of `Views.Frame`, read as the response arrives |
| `view(store, kind, transaction, {signal}?)` | CAP-012: every frame, as an array |
| `viewOf(store, kind, given, {adjacency?, signal?})` | `view` of `Views.request(store, kind, given, adjacency)` |
| `label(store, x)`, `chip(store, x)`, `detail(store, x)`, `adjacency(store, x, adjacency, y)` | CAP-005 to CAP-008, `x` a schema or a `References.OfObject`, each with `{signal}?` last |
| `url(path)` | the URL a call is sent to |

Errors, each a `RestError` (an `Error`):

| Class | When |
|---|---|
| `ServiceError` | any refusal: `status`, `body`, and `error`, the body's message |
| `TransactionRefused`, `NotFound`, `Unimplemented`, `Unavailable` | `ServiceError`s of 400, 404, 501 and 503 (`ServiceError.of`) |
| `TransportError` | the service out of reach, or the response cut off: `cause` is the platform's error |
| `ResponseError` | a response accepted that is not what the contract gives (not JSON, not NDJSON, a line not a frame) |

An abort is not a `RestError`: the call rejects with the signal's reason, the platform's `AbortError`, so that a UI
tells it apart as it does any fetch's. Aborting, or leaving a `for await` over `stream` early, cancels the response.

## Running the tests

```sh
cd python3 && uv sync && uv run pytest              # the server, its views, persistence, and the corpus current
uv run python -m mbse.Services.Rest.Conformance     # regenerate conformance/
cd typescript5 && npm install && npm run typecheck && npm test
```

The client's tests import mbse-schemas' TypeScript source, whose own dependency (`yaml`) must be installed in the
sibling's checkout: `(cd ../mbse-schemas/typescript5 && npm ci --omit=dev)`.

## Gaps in mbse-schemas

Reported, not worked around (AGENTS.md):

1. **One schema object cannot be written as a document.** `Plain.ToPlain(store).OfObject(meta, schema)` refuses a
   schema object: Python raises `AttributeError` (`_ObjectData` has no `as_schema`); given the schema's builder
   instead, `ValueError: a 'Schemas.OfObject' is owned through an adjacency with no name`; TypeScript raises
   `TypeError: root.as_schema is not a function`. Only the whole store's schemas are written, as the snapshot's first
   transaction. CAP-003 answers 501 until it can.
2. **Resolved by mbse-schemas c835f83** ("References, Decided 8: a reference symbol's schema from its path, through
   the schemas"). A spec over a symbol given a reference was refused when the store did not hold the object
   (`LookupError: symbol 'x' is given a reference that designates nothing the store holds`), so a client's store,
   which holds the app's schemas but none of its data, could not build CAP-008's request. It now records in plain
   builder notation, `.symbols({x: reference, y: Capability}).spec([_ => _.x.capabilities([_.y])])`, and the client
   builds every adjacency request byte for byte against the corpus.
3. **An install cannot be built as an expression without running it.** `store.transaction(install)` gives `install`
   the store's schemas by name (`txn.Schemas`, `txn.work`) through a private wrapper; `store.Mutations.OfTransaction(
   install)` does not (`TypeError: no member of the entry takes <empty>`). So installs are not journaled: the service
   snapshots after them instead.

## Decided by the agent, for review

Where VISUALIZATION.md is silent, the simplest default consistent with it and with mbse-schemas:

1. **Paths and methods** as in Endpoints; `POST` for a view, since its body is a transaction's expression.
2. **CAP-002's names** are every named schema the client's store holds once it has read the snapshot, the
   framework's included, in the store's order; choosing which to show (CAP-009 excludes `Schemas.*` and the like) is
   the UI's.
3. **CAP-003** answers 501 with an error body until Gaps, 1 is closed; the path is fixed now.
4. **Templates**: kinds `label`, `chip`, `detail`, `adjacency`; symbols `x` (the object viewed) and `y` (what `x`
   links); each template one map of one pattern, its symbols unassigned (`{}`), which the executor refuses as such.
5. **Relation entries (CAP-005, CAP-006 given a `References.OfEntry`)** have no template of their own: a pattern's
   symbol binds an object, never an entry. Entries arrive in `detail` and `adjacency` frames, with their properties,
   and the client labels them (`Views.entryLabel`).
6. **Label fallbacks** as in View kinds: the schema's name only where the caller knows it (a frame does not carry an
   object's schema), the last key of the object's path, and `relation: label, label` for an entry.
7. **Chip**: "the first three other scalar properties" counts those the object holds, in the schema's order.
8. **Detail** includes every named adjacency (anonymous ones are not members), entries in the schema's adjacency order
   and each adjacency's own, and the `label` view of each linked object, so that the inspector can show each entry
   without a second request (FEA-003, "sensibly nested").
9. **Adjacency** witnesses every entry of `x`'s named adjacencies that links `y`, rather than reading the adjacency's
   name from the request's spec; for the WorkTracker the two agree.
10. **NDJSON** for the stream, its status decided before the first frame (the server computes the frames, then
    writes them).
11. **Writes through view endpoints** are accepted and journaled (CAP-013's flow), detected by an `upsert` or `update`
    term in the expression.
12. **The plugin gives data, the service replays it** (`load` returns the snapshot and the journal), so that a plugin
    is storage only; first start runs the installs, then snapshots (Gaps, 3); a snapshot every 100 journaled
    transactions.
13. **One transaction at a time**: the service holds one lock over its store (transactions on one store do not nest).
14. **The corpus** as above, one case per file pair, `.json` compared as JSON and `.ndjson` byte for byte.
15. **Tests**: Node's test runner through `tsx` for TypeScript (`npm test`), since `@mbse/schemas` is TypeScript
    source; `httpx2` for FastAPI's test client, which deprecates `httpx`.
16. **Pins**: mbse-schemas at c835f83, the checkout it is developed and tested against (an earlier note, pinned at
    39bc8d8 while developing at 5599d11, is moot); mbse-demo-apps at 7f030e8 (M1; 917beb0 in M0), the checkout M1
    is tested against.

Decided in M1 (none changes a request or a response the corpus holds):

17. **The factory** keeps M0's `app(installs, plugin, snapshot_every)`, adding `origins` by keyword, so that
    mbse-dynamodb's tests call it as before; an app's installs are found by mbse-demo-apps' layout
    (`Schemas.install`, optional `Seed.seed`), and a plugin by `memory` or `module:attribute`, made with no arguments.
18. **Configuration by environment variables**, `MBSE_REST_*`, as in Running it; the app defaults to the WorkTracker,
    the demo, and CORS to no origin at all, so that a browser can call the service only from origins it is given.
19. **Every refusal answers the contract's error body**, including FastAPI's own (an unknown path, 404; a method,
    405), and a body that is not strict JSON is a 400, not FastAPI's 422.
20. **A frame that does not bind the kind's symbols** is a 400 (it was a `KeyError` answered as one), checked before
    the transaction is journaled.
21. **Undo by replay**: what the plugin has not journaled is undone by reading the store back from it, since
    transactions do not nest and so cannot be held open while journaling. Where that fails, the service answers 503
    until it restarts, rather than serve a store that disagrees with its plugin.
22. **503 for a journal that fails** (the transaction undone, safe to send again), 500 for the service's own faults;
    a snapshot that fails does not fail the request.
23. **The client's errors** are classes, `RestError` and below, by status where the contract names one; an abort
    rejects with the signal's own reason, unwrapped.
24. **The client's conveniences** (`viewOf`, `label`, `chip`, `detail`, `adjacency`) build requests with
    `Views.request`, as before, so they send what the corpus holds byte for byte.
25. **No server runs in the tests**: the entry point is tested by what it hands uvicorn; every endpoint through
    FastAPI's test client.
26. **An edit is an `update` after the detail view's map** (CAP-014), posted to the detail view, rather than an
    endpoint of its own: its response is the detail the inspector shows next, and the view endpoints already accept
    and journal writes (11).
27. **A proposal is an `upsert` posted to the detail view** (CAP-018), its symbols `x` and `n`, as an edit is an
    `update` there (26): the response is the inbound object's detail with the new entry.
28. **The service stamps writes on what it receives** (CAP-015), the expression's plain form, so that the journal holds
    the stamped transaction; the session's id comes from a header while there is no token (TODO.md, 4).
