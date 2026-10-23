# mbse-rest

REST endpoints for any mbse-schemas store: a transactional API whose queries and responses are mutation expressions and `References.OfFrame` streams, so that a schema-driven UI can browse and edit any MBSE app's data with no app-specific service code.

The named schema list, schema inspector, logical view templates and one endpoint per logical view kind (VISUALIZATION.md, CAP-002 to CAP-004 and CAP-012).

It depends on [mbse-schemas](https://github.com/pitaman71/mbse-schemas) as a checkout beside this repository, pinned in
[siblings.json](siblings.json).

```sh
cd python3 && uv sync && uv run pytest
```
