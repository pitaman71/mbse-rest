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
| `adjacency` | `x`, `y` | `x` a reference, `y` a schema; and the spec `_.x.<adjacency>([_.y])`, which names the adjacency |

The client builds the filled template with mbse-schemas' builders, `Views.request(store, kind, given, adjacency?)`,
never by editing JSON: for example, the capabilities of a goal,

```typescript
Views.request(store, "adjacency", { x: goalReference, y: store.registered("work.Capability") }, "capabilities");
```

The `adjacency` template carries no spec: an adjacency is a member of `x`'s schema, which the template does not know
until `x` is given. Building that request in a client is blocked for now (Gaps, 2).

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

- **Label and summary.** The label's property is the first of `label`, `name` and `title` the object holds; the
  summary's, the first of `summary` and `description`. The values are the properties' own, so `assigns` names them as
  the schema does (`title`, not `label`). The client reads them back: `Views.label`, `Views.summary`, `Views.chip`.
- **Fallbacks** (client side, from what the frame carries). An object's label, where it holds none: its schema's
  name, where the caller knows it (it gave the symbol that schema), and its path's last key, the owning entry's key
  values, or, a singleton, the singleton's name: `work.Comment CMT-001`, `work.ProjectDirectory work.Projects`. An
  entry's label: its relation's name and its linked objects' labels in its links' order,
  `work.Plans: Demoable index site, No-code index view` (`Views.entryLabel`). A summary, where none is held, is empty.
- **Counted objects** have no reference: a frame that binds one is left out of the stream, and an entry that links one
  out of `entries` (FEA-003).
- A view's transaction may write (CAP-013's flow): whatever it writes is committed, and journaled, before its frames
  are filled.

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
  same protocol, and should pass the same tests (`python3/tests/test_service.py`, the persistence cases) with its
  plugin in place of `Memory`.

## The golden corpus

`conformance/cases.json` lists each case: `name`, `method`, `path`, `request` (a file, or null), `status`,
`content_type` and `response` (a file). Each case is sent to a fresh stub server over the WorkTracker seed
(mbse-demo-apps). `uv run python -m mbse.Services.Rest.Conformance` writes it; `--check` reports what differs.

- The server's tests require the corpus to be current: a change to a response is a change to the corpus, committed
  with it, and reviewed as a change to the contract.
- The client's tests serve the corpus through a fetch of their own: the client must build every request byte for byte
  (in mbse-schemas' JSON) and read every frame back byte for byte. mbse-react can develop against the corpus with
  the same fetch, before a server runs.

## Running it

```sh
cd python3 && uv sync && uv run pytest              # the server, its views, persistence, and the corpus current
uv run python -m mbse.Services.Rest.Conformance     # regenerate conformance/
cd typescript5 && npm install && npm run typecheck && npm test
```

The stub server is `Service.work_tracker()`, a FastAPI application; serve it with any ASGI server, for example
`uv run --with uvicorn uvicorn --factory mbse.Services.Rest.Service:work_tracker`.

## Gaps in mbse-schemas

Reported, not worked around (AGENTS.md):

1. **One schema object cannot be written as a document.** `Plain.ToPlain(store).OfObject(meta, schema)` refuses a
   schema object: Python raises `AttributeError` (`_ObjectData` has no `as_schema`); given the schema's builder
   instead, `ValueError: a 'Schemas.OfObject' is owned through an adjacency with no name`; TypeScript raises
   `TypeError: root.as_schema is not a function`. Only the whole store's schemas are written, as the snapshot's first
   transaction. CAP-003 answers 501 until it can.
2. **A spec cannot be recorded over a reference the store does not hold.** A client's store holds the app's schemas
   but none of its data, so `.symbols({x: reference, y: Capability}).spec([_ => _.x.capabilities([_.y])])` is refused
   when recorded, `LookupError: symbol 'x' is given a reference that designates nothing the store holds`
   (mbse-schemas' References proposal, as settled in building Decided, 8). That is CAP-008's own example, built where a UI builds it.
   The server reads and runs the same expression, since it holds the data. The client's adjacency requests are
   `todo` tests until mbse-schemas records such a spec against the schema the reference's path implies, or takes the
   schema with the reference.
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
5. **`adjacency`'s template has no spec.** The client adds `_.x.<adjacency>([_.y])` with `x` given (CAP-008 names the
   adjacency in the spec, but a template without arguments cannot know `x`'s schema).
6. **Relation entries (CAP-005, CAP-006 given a `References.OfEntry`)** have no template of their own: a pattern's
   symbol binds an object, never an entry. Entries arrive in `detail` and `adjacency` frames, with their properties,
   and the client labels them (`Views.entryLabel`).
7. **"Declares" read as "holds"** for the label and summary properties (CAP-005): the first of the convention's
   properties the object holds, so that the client, which receives only what is held, picks the same one; a declared
   property the object lacks falls back as an undeclared one does.
8. **Label fallbacks** as in View kinds: the schema's name only where the caller knows it (a frame does not carry an
   object's schema), the last key of the object's path, and `relation: label, label` for an entry.
9. **Chip**: "the first three other scalar properties" counts those the object holds, in the schema's order.
10. **Detail** includes every named adjacency (anonymous ones are not members), entries in the schema's adjacency order
    and each adjacency's own, and the `label` view of each linked object, so that the inspector can show each entry
    without a second request (FEA-003, "sensibly nested").
11. **Adjacency** witnesses every entry of `x`'s named adjacencies that links `y`, rather than reading the adjacency's
    name from the request's spec; for the WorkTracker the two agree.
12. **NDJSON** for the stream, its status decided before the first frame (the server computes the frames, then
    writes them).
13. **Writes through view endpoints** are accepted and journaled (CAP-013's flow), detected by an `upsert` or `update`
    term in the expression.
14. **The plugin gives data, the service replays it** (`load` returns the snapshot and the journal), so that a plugin
    is storage only; first start runs the installs, then snapshots (Gaps, 3); a snapshot every 100 journaled
    transactions.
15. **One transaction at a time**: the service holds one lock over its store (transactions on one store do not nest).
16. **The corpus** as above, one case per file pair, `.json` compared as JSON and `.ndjson` byte for byte.
17. **Tests**: Node's test runner through `tsx` for TypeScript (`npm test`), since `@mbse/schemas` is TypeScript
    source; `httpx2` for FastAPI's test client, which deprecates `httpx`.
18. **Pins**: mbse-schemas at 39bc8d8 as instructed, though development ran against its checkout five commits later
    (5599d11, which makes `References.OfObject` a value object; the wire is unchanged); mbse-demo-apps at 917beb0.
