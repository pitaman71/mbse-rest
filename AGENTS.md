# Guide for AI agents

The named schema list, schema inspector, logical view templates and one endpoint per logical view kind (mbse-basis [CAP-002: named schema list](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-004.md) and [CAP-012: logical view endpoints](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-012.md)). The whole interface, verified in one repository: the server in Python, `python3/mbse/Services/Rest` (`mbse.Services.Rest`), and the client in TypeScript, `typescript5/mbse/Services/Rest/Client.ts` (`@mbse/rest`).

## Read before any work

Agents must read these mbse-basis documents before doing any work:

- [The mbse basis](https://github.com/pitaman71/mbse-basis/blob/main/docs/README.md)
- [Principles](https://github.com/pitaman71/mbse-basis/blob/main/docs/PRINCIPLES.md)
- [Features](https://github.com/pitaman71/mbse-basis/blob/main/docs/features/README.md)
- [Capabilities](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/README.md)

These may be read selectively, on demand: [Vocabulary](https://github.com/pitaman71/mbse-basis/blob/main/docs/VOCABULARY.md) and
[Qualities](https://github.com/pitaman71/mbse-basis/blob/main/docs/QUALITIES.md).

Never write to `~/.claude/projects/*/memory/` or any hidden memory: what is worth keeping goes in the repository.

Resolve a link written `mbse:<repo>/<path>`, as skills and source comments write a link into another mbse
repository, to the first of these that exists: in a polyrepo checkout, `<repo root>/../<repo>/<path>`, where `<repo
root>` is this repository's root; for a link into the installed package's own repository, `<path>` without its
language directory (`python3/` or `typescript5/`), under the installed package's root (Python: the `site-packages`
directory that holds `mbse/`; npm: the package's directory), where the package ships that file; otherwise
`https://github.com/pitaman71/<repo>/blob/main/<path>`.

## This repository

- `Views.py` and `Views.ts` are the contract's two halves. A change to what the server answers regenerates
  [the golden corpus](conformance/README.md), committed with it, and is reviewed as a change to the contract:
  mbse-react and mbse-dynamodb build against it.

## Commands

```sh
python3 ../mbse-basis/scripts/polyrepo.py pin   # the siblings beside this repository, pinned in siblings.json
cd python3 && uv sync && uv run pytest          # Python: use uv, never pip
uv run python -m mbse.Services.Rest.Conformance  # the golden corpus, committed with the change

(cd ../mbse-schemas/typescript5 && npm ci --omit=dev)          # once: mbse-schemas' own dependency, which the client imports
cd typescript5 && npm install && npm run typecheck && npm test # Node's test runner through tsx
```
