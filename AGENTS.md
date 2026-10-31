# Guide for AI agents

The named schema list, schema inspector, logical view templates and one endpoint per logical view kind (mbse-basis [CAP-002: named schema list](../mbse-basis/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](../mbse-basis/docs/capabilities/CAP-004.md) and [CAP-012: logical view endpoints](../mbse-basis/docs/capabilities/CAP-012.md)). The whole interface, verified in one repository: the server in Python, `python3/mbse/Services/Rest` (`mbse.Services.Rest`), and the client in TypeScript, `typescript5/mbse/Services/Rest/Client.ts` (`@mbse/rest`).

## Invariants

The conventions every mbse repository shares are stated once in mbse-basis; this file cites them and keeps
only what differs here.

- **Vocabulary**: [VOC-007: property](../mbse-basis/docs/VOCABULARY.md#VOC-007) and [VOC-026: schema](../mbse-basis/docs/VOCABULARY.md#VOC-026) for schema-governed things, qualified with whose it is where
  it meets a language's own term ([the vocabulary](../mbse-basis/docs/VOCABULARY.md), its introduction).
- **Models as data** are written in the builders' fluent syntax ([PRI-019: fluent builder syntax](../mbse-basis/docs/PRINCIPLES.md#PRI-019)); packages are laid out and
  capitalized alike ([PRI-030: one package layout](../mbse-basis/docs/PRINCIPLES.md#PRI-030)).
- **Documents**: navigation lines, the README opening with why, and what this file holds ([Rules for every document](../mbse-basis/docs/README.md#rules-for-every-document)).
- **Work**: [PRI-029: parallel work in polyrepo workspaces](../mbse-basis/docs/PRINCIPLES.md#PRI-029), so a sibling is changed only through a workspace that edits it, never from this
  checkout; [PRI-031: the version is the contract](../mbse-basis/docs/PRINCIPLES.md#PRI-031); [PRI-032: a sibling's gap is reported, not worked around](../mbse-basis/docs/PRINCIPLES.md#PRI-032) (mbse-schemas used as it stands); and [PRI-033: work lands by branch and pull request](../mbse-basis/docs/PRINCIPLES.md#PRI-033).
- **What this repository builds is specified in mbse-basis' features and capabilities**, cited by ID; where one is
  silent, decide and record it as the basis says ([Detail files](../mbse-basis/docs/README.md#detail-files)).
- **Siblings are checkouts beside this repository**, pinned by version and commit in `siblings.json`
  (`python3 ../mbse-basis/scripts/polyrepo.py pin`).
- **Tests run with pytest** from `python3/`: `uv sync && uv run pytest`. Use uv, never pip.
- **Type-check and test the client** from `typescript5/`: `npm install && npm run typecheck && npm test`, Node's test
  runner through `tsx`, since `@mbse/schemas` is TypeScript source. Its tests import mbse-schemas' TypeScript source,
  whose own dependency (`yaml`) must be installed in the sibling's checkout: `(cd ../mbse-schemas/typescript5 && npm ci
  --omit=dev)`. The server's tests use `httpx2` for FastAPI's test client, which deprecates `httpx`; no server runs in
  them: the entry point is tested by what it hands uvicorn, every endpoint through FastAPI's test client.
- **The contract is what mbse-basis' [FEA-003: no-code logical views](../mbse-basis/docs/features/FEA-003.md) and its capabilities say, as built**
  (each detail file's As built section), with `Views.py` and `Views.ts` its two halves. A change to what the server
  answers regenerates the golden corpus (`uv run python -m mbse.Services.Rest.Conformance`), committed with it, and is
  reviewed as a change to the contract: mbse-react and mbse-dynamodb build against it.
- Never write to `~/.claude/projects/*/memory/` or any hidden memory: what is worth keeping goes in the repository.
