# mbse-rest

REST endpoints for any mbse-schemas store: a transactional API whose queries and responses are mutation expressions and
`References.OfFrame` streams, so that a schema-driven UI can browse and edit any MBSE app's data with no app-specific
service code.

It consolidates and verifies the entire interface in one repository: the server side in Python
(`python3/mbse/Services/Rest`, `mbse.Services.Rest`) and the client side in TypeScript
([`typescript5/mbse/Services/Rest/Client.ts`](typescript5/mbse/Services/Rest/Client.ts), `@mbse/rest`). What it serves is specified in mbse-basis'
capabilities: [CAP-002: named schema list](../mbse-basis/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](../mbse-basis/docs/capabilities/CAP-004.md) and [CAP-012: logical view endpoints](../mbse-basis/docs/capabilities/CAP-012.md), over the stack under [FEA-006: persistence](../mbse-basis/docs/features/FEA-006.md).

The contract, its endpoints, view kinds and persistence plugin, is [docs/CONTRACT.md](docs/CONTRACT.md); the
[golden corpus](conformance/README.md) holds real requests and responses for clients to develop against.

It depends on [mbse-schemas](https://github.com/pitaman71/mbse-schemas) as a checkout beside this repository, and on
[mbse-demo-apps](https://github.com/pitaman71/mbse-demo-apps)' WorkTracker for its tests and corpus, pinned in
[siblings.json](siblings.json).

## Running the service

```sh
cd python3 && uv sync --all-extras
uv run python -m mbse.Services.Rest      # the WorkTracker demo at http://127.0.0.1:8000, persisted in memory
MBSE_REST_ORIGINS=http://localhost:5173 MBSE_REST_PORT=8080 uv run python -m mbse.Services.Rest
```

It serves any MBSE app: `MBSE_REST_APP` names the app's package (its `Schemas.install`, then its `Seed.seed`),
`MBSE_REST_PLUGIN` its persistence plugin (`memory`, or `module:attribute`), `MBSE_REST_ORIGINS` the UI's origins for
CORS. Every variable, and `Service.app` for serving an app from code, is in
[docs/CONTRACT.md](docs/CONTRACT.md#the-service-for-any-mbse-app-m1).

## Using the client

```typescript
import { Client, newStore, Views } from "@mbse/rest/Services/Rest/Client";

const client = new Client("http://localhost:8000");
const store = newStore();
await client.loadSchemas(store);
for (const frame of await client.label(store, store.registered("work.Task"))) console.log(Views.label(store, frame));
```

Its calls, options, typed errors and aborts are in [docs/CONTRACT.md](docs/CONTRACT.md#the-client-m1).

## Testing

```sh
cd python3 && uv sync --all-extras && uv run pytest
(cd ../mbse-schemas/typescript5 && npm ci --omit=dev)   # once: mbse-schemas' own dependency, which the client imports
cd typescript5 && npm install && npm run typecheck && npm test
```
