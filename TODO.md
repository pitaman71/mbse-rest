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
4. **The demo's identity and session** (CAP-015). The service's identity is configured (`MBSE_REST_USER`), and the
   session is whatever the client names in the `x-mbse-session` header, trusted: both stand in for a validated
   token, which the service will unpack and check, writing the session and identity it gives.
5. **Reading a snapshot is recorded** (mbse-schemas 0.26.0): a restart records the snapshot's reading as a new
   transaction, linking each object's `CreatedBy` to it beside its first. Reported to mbse-schemas;
   `test_a_restart_replays_the_same_records` is an expected failure until it is fixed.
6. **An object's provenance is found by a map over every transaction record** (`Views._history`): fine for a demo,
   slow for a long history. An index of records by object, or a lookup from the object's side, would replace it.
