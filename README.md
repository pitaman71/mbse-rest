# mbse-rest

REST endpoints for any mbse-schemas store: a transactional API whose queries and responses are mutation expressions and
`References.OfFrame` streams, so that a schema-driven UI can browse and edit any MBSE app's data with no app-specific
service code.

It consolidates and verifies the entire interface in one repository: the server side in Python
(`python3/mbse/Services/Rest`, `mbse.Services.Rest`) and the client side in TypeScript
(`typescript5/mbse/Services/Rest/Client.ts`, `@mbse/rest`). What it serves is specified in the workspace's
`VISUALIZATION.md`: CAP-002 to CAP-004 and CAP-012, over the stack under FEA-006.

It depends on [mbse-schemas](https://github.com/pitaman71/mbse-schemas) as a checkout beside this repository, pinned in
[siblings.json](siblings.json).

```sh
cd python3 && uv sync && uv run pytest
cd typescript5 && npm install && npm run typecheck
```
