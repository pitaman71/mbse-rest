# Tech debt

1. **CAP-003 answers 501.** mbse-schemas cannot write one schema object as a document
   (`docs/CONTRACT.md`, Gaps in mbse-schemas, 1). When it can, `GET /schemas/{name}` serves the schema's definition,
   unnamed schemas defined inline and named ones referenced (VISUALIZATION.md, CAP-003), and its corpus case changes
   from 501.
2. **Installs are not journaled** (Gaps, 3; accepted for now): first start runs the app's installs and snapshots
   after them. When an install can be built as an expression without running it, journal it like any transaction.
