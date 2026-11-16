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

The service's store is a `Builders.Store` over a store below it, a database's in production (mbse-dynamodb's), one in
memory by default: it loads what it is asked for, writes each transaction through, and persists by the store below's
journal alone, so that no snapshot is taken or read. Its endpoints, each in `Service.py`'s module docstring, are those a
client needs to be a store below: an object's document by path (`POST /documents`), a transaction committed or refused
(`POST /transactions`), the change feed read by position (`GET /changes`), and the schemas as the install transactions
that made them (`GET /schemas`, `POST /schemas`); and the logical views ([FEA-003: no-code logical views](https://github.com/pitaman71/mbse-basis/blob/main/docs/features/FEA-003.md)). The contract
is what mbse-basis' features and capabilities say, as built; the [golden corpus](conformance/README.md) holds real
requests and responses for clients to develop against.

It depends on [mbse-schemas](https://github.com/pitaman71/mbse-schemas) as a checkout beside this repository, and on
[mbse-demo-apps](https://github.com/pitaman71/mbse-demo-apps)' WorkTracker and
[mbse-journals](https://github.com/pitaman71/mbse-journals)' suite JRN for its tests, pinned in `siblings.json`.

## Running the service

```sh
cd python3 && uv sync --all-extras
uv run python -m mbse.Services.Rest      # the WorkTracker demo at http://127.0.0.1:8000, persisted in memory
MBSE_REST_ORIGINS=http://localhost:5173 MBSE_REST_PORT=8080 uv run python -m mbse.Services.Rest
```

It serves any MBSE app: `MBSE_REST_APP` names the app's package (its `Schemas.install`, or `Schemas.INSTALLS`, then
its `Seed.seed`, run where the store below is new), `MBSE_REST_STORE` the store below (`memory`, or `module:attribute`,
`mbse.Persistence.DynamoDB.Store:Store` for mbse-dynamodb's, configured by its own `MBSE_DYNAMODB_*`),
`MBSE_REST_ORIGINS` the UI's origins for CORS. Every variable is in `Service.from_environment`; `Service.app(installs,
below, seed)` serves an app from code. `MBSE_REST_PLUGIN` and `MBSE_REST_SNAPSHOT_EVERY` are retired, and refused.

## Using the client

The service as a store below (`Remote`), mbse-schemas' public store-below interface (`Stores.Below`,
[CAP-306: a public store-below interface](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/README.md#CAP-306)), and an app's store over it, a plain `Builders.Store` given the service's schemas
(`Store`):

```typescript
import { Remote, Store } from "@mbse/rest/Services/Rest/Store";

const remote = new Remote("http://localhost:8000");
const store = Store(remote);       // a Builders.Store over it: the service's schemas, from the installs that made them
store.transaction(install);        // its own schemas, run by the service first, as any store below runs them
remote.poll();                     // what others committed since, given to the store
```

```python
from mbse.Services.Rest.Store import Remote, Store

remote = Remote("http://localhost:8000")
store = Store(remote)              # Builders.Store(remote), given the service's schemas
remote.poll()
```

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

Both run mbse-schemas' suite BLW and mbse-journals' suite JRN from the sibling checkouts, unchanged but for the store
below, which is the client of a service over a store in memory: Python's in this process, TypeScript's against the
Python service, which its tests start (`python3/tests/serve.py`). mbse-dynamodb's tests run the service over its store.

---

<!-- nav -->
[The golden corpus →](conformance/README.md)
