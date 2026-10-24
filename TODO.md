# Tech debt

1. **CAP-003 answers 501.** mbse-schemas cannot write one schema object as a document
   (`docs/CONTRACT.md`, Gaps in mbse-schemas, 1). When it can, `GET /schemas/{name}` serves the schema's definition,
   unnamed schemas defined inline and named ones referenced (VISUALIZATION.md, CAP-003), and its corpus case changes
   from 501.
2. **Installs are not journaled** (Gaps, 3; accepted for now): first start runs the app's installs and snapshots
   after them. When an install can be built as an expression without running it, journal it like any transaction.
3. **Undo by replay.** A transaction that writes commits before it is journaled, since transactions on one store do
   not nest; where it is then refused or its journal fails, the service reads the whole store back from the plugin
   (`docs/CONTRACT.md`, Refusals and failures). Correct, but costly for a large store: when mbse-schemas can hold a
   transaction open while the service journals it (or roll one back), journal before commit instead.
