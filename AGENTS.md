# Guide for AI agents

A store served over REST, whose client is a store another stacks on (mbse-basis [CAP-290: a service's store stacked, with no snapshot](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/README.md#CAP-290)), and the named schema list, schema inspector, logical view templates and one endpoint per logical view kind ([CAP-002: named schema list](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-004.md) and [CAP-012: logical view endpoints](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/CAP-012.md)). The whole interface, verified in one repository: the server in Python, `python3/mbse/Services/Rest` (`mbse.Services.Rest`), and the client in TypeScript, `typescript5/mbse/Services/Rest/Store.ts` and `Client.ts` (`@mbse/rest`), the store client in Python too (`Store.py`).

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

- `Service.py` is the service, which serves a store's transaction, held open across a client's requests, and its
  `exec`, its stream each a `References.OfItem` value, written and read by mbse-schemas' own `JSON` (PRI-018,
  PRI-024: no format of mbse-rest's own; a frame's value read through the visitors, `Store.frame_of`);
  `Store.py` and `Store.ts` the client, `Remote`, the service as a layer below (a `Builders.Store` holding the schemas
  alone, whose transaction is the service's), and `Store`, a cache layer over it, in a follow mode, the same in both
  languages: a change to one is made to the other. Both use mbse-schemas' public interface alone: no private name of
  it, nor a subclass overriding one (mbse-basis [CAP-306: a public store-below interface](https://github.com/pitaman71/mbse-basis/blob/main/docs/capabilities/README.md#CAP-306)). Their deliberate differences: the
  transport, synchronous in both since the store interface is, Python's through the standard library, TypeScript's
  waiting on a worker thread in Node or a synchronous `XMLHttpRequest` in a browser; `exec`'s stream, a list's
  iterator in Python, an observable in TypeScript, as mbse-schemas' are; and the errors for a status, Python's
  `Store.ServiceError`, `Gone` and `Unavailable`, TypeScript's `Client.ts`'s, which the view calls share.
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
