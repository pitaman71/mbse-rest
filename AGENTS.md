# Guide for AI agents

The named schema list, schema inspector, logical view templates and one endpoint per logical view kind (mbse-basis [CAP-002: named schema list](../mbse-basis/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](../mbse-basis/docs/capabilities/CAP-004.md) and [CAP-012: logical view endpoints](../mbse-basis/docs/capabilities/CAP-012.md)). The whole interface, verified in one repository: the server in Python, `python3/mbse/Services/Rest` (`mbse.Services.Rest`), and the client in TypeScript, `typescript5/mbse/Services/Rest/Client.ts` (`@mbse/rest`).

## Invariants

- **Use mbse-schemas as it stands.** A gap found is reported to the user, not worked around here.
- **Siblings are checkouts beside this repository**, pinned by commit in `siblings.json`. Other agents may be working
  in them: never edit a sibling from here.
- **What this repository builds is specified in mbse-basis' features and capabilities**
  ([`mbse-basis/docs/features/`](../mbse-basis/docs/features), [`mbse-basis/docs/capabilities/`](../mbse-basis/docs/capabilities)), by ID, cited as mbse-basis'
  [`docs/README.md`](../mbse-basis/docs/README.md) says.
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

## Working agreement (M0, for every agent on mbse-rest, mbse-dynamodb, mbse-react and mbse-demo-apps)

- Work on a branch in each repository you change (M0's is `m0-contract`). Commit and push after every step whose
  tests pass (`git push -u origin <branch>`, or `python3 ../mbse-basis/scripts/polyrepo.py push` where it supports
  every sibling). Never commit to `main`. When done, open one pull request per repository with `gh pr create`,
  listing the decisions for review.
- Where a capability is silent, decide and record it as mbse-basis' [`docs/README.md`](../mbse-basis/docs/README.md#detail-files) says (Detail files), and keep going.
- Stop and report (do not work around) for: a gap or bug in mbse-schemas; an outward-facing action beyond pushing
  branches and opening pull requests in these repositories; anything destructive (force-push, deleting branches or
  files outside your work, rewriting history); a contradiction in a capability that changes what gets built.
- Never edit a sibling from another repository's work; never edit mbse-schemas, nor mbse-basis
  beyond what its [`docs/README.md`](../mbse-basis/docs/README.md#detail-files) allows (Detail files).
- Never write to `~/.claude/projects/*/memory/` or any hidden memory: what is worth keeping goes in the repository.
- Conventions: Python with uv (`uv sync`, `uv run pytest`), never pip; package capitalization as mbse-schemas has it
  (`mbse.Services.Rest`); "property", never "field", and "schema", never "type", for schema-governed things. Models
  as data are written in the builders' fluent syntax, never wire format, never helpers that wrap builder syntax.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, and every pull request's
  description with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
