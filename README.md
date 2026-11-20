<!-- nav -->
[The golden corpus →](conformance/README.md)

# mbse-rest

A store served over REST: any mbse-schemas store exposed through an encapsulated REST interface, whose client is itself
a store that another stacks on, as on a store in memory; and, over it, a transactional API whose queries and responses
are mutation expressions and `References.OfFrame` streams, so that a schema-driven UI can browse and edit any MBSE
app's data with no app-specific service code.

It consolidates and verifies the entire interface in one repository: the server side in Python
(`python3/mbse/Services/Rest`, `mbse.Services.Rest`) and the client side in TypeScript
(`typescript5/mbse/Services/Rest/Store.ts` and `Client.ts`, `@mbse/rest`), the store client in Python too
(`mbse.Services.Rest.Store`). What it serves is specified in mbse-basis'
capabilities: [CAP-002: named schema list](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-004.md) and [CAP-012: logical view endpoints](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-012.md), over the stack under [FEA-006: persistence](https://github.com/pitaman71/mbse-basis/blob/main/docs/features/FEA-006.md), as
[CAP-290: a service's store stacked, with no snapshot](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/README.md#CAP-290) and [the stacked stores proposal](https://github.com/pitaman71/mbse-basis/blob/main/proposals/STACKED-STORES.md) state.

The service serves a store, a database's in production (mbse-dynamodb's), one in memory by default, as the layer below
a cache layer in another process ([the stacked stores proposal, a cache layer and the layer below](https://github.com/pitaman71/mbse-basis/blob/main/proposals/STACKED-STORES.md#a-cache-layer-and-the-layer-below),
its third stage; [CAP-308: stacking by mutation transactions, in one round trip](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/README.md#CAP-308)): it persists by what that store keeps alone, so that no snapshot is
taken or read. Its endpoints, each in `Service.py`'s module docstring, are the store's transaction, held open across a
client's requests, and its `exec`; the change feed; the install transactions it was given; and the logical views
([FEA-003: no-code logical views](https://github.com/pitaman71/mbse-basis/blob/main/docs/features/FEA-003.md)). A client's transaction is a request sequence:

| Request | What it does | Answer |
|---|---|---|
| `POST /transactions` | opens a transaction of the store for the client's, once no other is open | `{"transaction": id, "feed", "head"}` |
| `POST /transactions/{id}/exec` | `txn.exec` within it: `{"expression", "remainder", "frames", "write"}`, the expression as `Plain.ToPlain(store).Transaction` writes it, the subterm the remainder starts at, the input frames, each a `References.OfFrame` | the stream of frames, one `References.OfItem` a line (NDJSON), as mbse-schemas writes it, the last `{"end": {}}` |
| `POST /transactions/{id}/commit` | commits it, the layers below the store first | `{"head", "journal", "after"}`: what the store's follow gave of it, a `Changes.Journal` |
| `DELETE /transactions/{id}` | drops it, nothing written | `{}` |
| `GET /changes?feed=f&after=id&wait=s` | the change feed: each committed transaction as mbse-schemas' `follow` gives it, a one-transaction `Changes.Journal`, read after a position, a transaction's `id`, with [mbse-journals](https://github.com/pitaman71/mbse-journals) | `{"feed", "head", "journal"}` |
| `GET /schemas` | the install transactions the service was given | a list of transactions' expressions |

One client's transaction is open at a time: another's waits for it, up to 30 seconds, else is refused (503), and one
left idle (`MBSE_REST_LEASE`, 60 seconds) is dropped. A frame crosses as mbse-schemas writes it, with its scope, its
remainder, its errors and its journal; what has no reference, a counted object, crosses refused: the frame comes over
with that symbol left out and an error annotated, which the transaction raises at its end. The contract is what
mbse-basis' features and capabilities say, as built; the [golden corpus](conformance/README.md) holds real requests and
responses of the logical views for clients to develop against.

It depends on [mbse-schemas](https://github.com/pitaman71/mbse-schemas) and, the service,
[mbse-journals](https://github.com/pitaman71/mbse-journals), as checkouts beside this repository, and on
[mbse-demo-apps](https://github.com/pitaman71/mbse-demo-apps)' WorkTracker for its tests, pinned in `siblings.json`.

## Running the service

```sh
cd python3 && uv sync --all-extras
uv run python -m mbse.Services.Rest      # the WorkTracker demo at http://127.0.0.1:8000, persisted in memory
MBSE_REST_ORIGINS=http://localhost:5173 MBSE_REST_PORT=8080 uv run python -m mbse.Services.Rest
```

It serves any MBSE app: `MBSE_REST_APP` names the app's package (its `Schemas.install`, or `Schemas.INSTALLS`, then
its `Seed.seed`, run where the store is new), `MBSE_REST_STORE` the store served (`memory`, or `module:attribute`,
`mbse.Persistence.DynamoDB.Store:Store` for mbse-dynamodb's, configured by its own `MBSE_DYNAMODB_*`),
`MBSE_REST_ORIGINS` the UI's origins for CORS, `MBSE_REST_LEASE` how long an idle client's transaction is kept. Every
variable is in `Service.from_environment`; `Service.app(installs, store, seed)` serves an app from code.
`MBSE_REST_PLUGIN` and `MBSE_REST_SNAPSHOT_EVERY` are retired, and refused.

## Using the client

The service as a layer below (`Remote`), a store holding the schemas alone whose transaction is the service's, and an
app's store over it, a cache layer (`Store`), given the installs the service was given, and what others commit by the
change feed, in a follow mode chosen as it is made: `CATCH_UP`, the default, reads the feed to its head before each
transaction; `POLLED` on `poll()` alone, reading what it holds a poll behind.

```typescript
import { POLLED, Remote, Store } from "@mbse/rest/Services/Rest/Store";

const store = Store("http://localhost:8000");   // a cache layer over the service, caught up before each transaction
store.transaction(install);                     // its own schemas: the service's store first, then the client, then it
const frames = store.transaction(query);        // its frames come from the service, in one transaction of its
const remote = new Remote("http://localhost:8000");
const polled = Store(remote, POLLED);           // what others commit, on remote.poll() alone
```

```python
from mbse.Services.Rest.Store import POLLED, Remote, Store

store = Store("http://localhost:8000")
with store.transaction() as txn:           # one transaction of the service's, held open across each exec
    for item in txn.exec(Frame(), query, True):
        ...
polled = Store(Remote("http://localhost:8000"), follow=POLLED)
```

A cache layer reads what it holds alone: an object it made, or a follow gave it; every other read is a transaction's
frames, which come from the service ([the completeness rule](https://github.com/pitaman71/mbse-basis/blob/main/proposals/STACKED-STORES.md#a-cache-layer-and-the-layer-below)).
mbse-schemas' store interface is synchronous, and so is the client: in Node, each request waits on a worker thread
that fetches; in a browser, it is a synchronous `XMLHttpRequest`, best made from a worker. The logical views:

```typescript
import { Client, newStore, Views } from "@mbse/rest/Services/Rest/Client";

const client = new Client("http://localhost:8000");
const store = newStore();
await client.loadSchemas(store);
for (const frame of await client.label(store, store.registered("work.Task"))) console.log(Views.label(store, frame));
```

Its calls, options, typed errors and aborts are in [FEA-003: no-code logical views](https://github.com/pitaman71/mbse-basis/blob/main/docs/features/FEA-003.md#the-client), the client.

## Testing

```sh
cd python3 && uv sync --all-extras && uv run pytest
(cd ../mbse-schemas/typescript5 && npm ci --omit=dev)   # once: mbse-schemas' own dependency, which the client imports
cd typescript5 && npm install && npm run typecheck && npm test
```

Both run mbse-schemas' suite BLW from the sibling checkout, with mbse-rest in its stack: Python's with its cache layer
over the client of a service, in this process, that serves the suite's layer below; TypeScript's with its layer below a
cache layer over the client of a service of its own, against the Python service, which its tests start
(`python3/tests/serve.py`). Each case runs as mbse-schemas wrote it, but for the few lines `tests/test_below.py` and
`tests/store.test.ts` list, each saying why. Suite EXE is not run over REST: its cases read the store through builders
within the transaction, which a client holding no data cannot. What a follow gives is held to mbse-schemas' own suites (BLW, and CHG-14): a journal is
not kept in a store, so mbse-journals' suite is not run over one. mbse-dynamodb's tests run the service over its store.

---

<!-- nav -->
[The golden corpus →](conformance/README.md)
