# Tech debt

1. **CAP-003 answers 501.** mbse-schemas cannot write one schema object as a document
   ([`docs/CONTRACT.md`](docs/CONTRACT.md), Gaps in mbse-schemas, 1). When it can, `GET /schemas/{name}` serves the schema's definition,
   unnamed schemas defined inline and named ones referenced (mbse-basis [CAP-003: schema inspector](../mbse-basis/docs/capabilities/CAP-003.md)), and its corpus case changes
   from 501.
2. **Installs are not journaled** (Gaps, 3; accepted for now): first start runs the app's installs and snapshots
   after them. When an install can be built as an expression without running it, journal it like any transaction.
3. **Undo by replay.** A transaction that writes commits before it is journaled, since transactions on one store do
   not nest; where it is then refused or its journal fails, the service reads the whole store back from the plugin
   ([`docs/CONTRACT.md`](docs/CONTRACT.md), Refusals and failures). Correct, but costly for a large store: when mbse-schemas can hold a
   transaction open while the service journals it (or roll one back), journal before commit instead.
4. **The demo's identity and session** ([CAP-015: transaction provenance](../mbse-basis/docs/capabilities/CAP-015.md)). The service's identity is configured (`MBSE_REST_USER`), and the
   session is whatever the client names in the `x-mbse-session` header, trusted: both stand in for a validated
   token, which the service will unpack and check, writing the session and identity it gives.
5. **An object's provenance is found by a map over every transaction record** (`Views._history`): fine for a demo,
   slow for a long history. An index of records by object, or a lookup from the object's side, would replace it.
