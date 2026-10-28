# Guide for AI agents

The named schema list, schema inspector, logical view templates and one endpoint per logical view kind (mbse-basis [CAP-002: named schema list](../mbse-basis/docs/capabilities/CAP-002.md) to [CAP-004: logical view templates](../mbse-basis/docs/capabilities/CAP-004.md) and [CAP-012: logical view endpoints](../mbse-basis/docs/capabilities/CAP-012.md)). The whole interface, verified in one repository: the server in Python, `python3/mbse/Services/Rest` (`mbse.Services.Rest`), and the client in TypeScript, `typescript5/mbse/Services/Rest/Client.ts` (`@mbse/rest`).

## Invariants

- **Use mbse-schemas as it stands.** A gap found is reported to the user, not worked around here.
- **Siblings are checkouts beside this repository**, pinned by commit in `siblings.json`. Other agents may be working
  in them: never edit a sibling from here.
- **What this repository builds is specified in mbse-basis' features and capabilities**
  ([`mbse-basis/docs/features/`](../mbse-basis/docs/features), [`mbse-basis/docs/capabilities/`](../mbse-basis/docs/capabilities)), by ID; cite those IDs, each introduced
  by bridge language (mbse-basis [`docs/README.md`](../mbse-basis/docs/README.md), Rules for writing items, "Bridge, don't duplicate").
- **Tests run with pytest** from `python3/`: `uv sync && uv run pytest`. Use uv, never pip.
- **Type-check and test the client** from `typescript5/`: `npm install && npm run typecheck && npm test`.
- **The contract is [`docs/CONTRACT.md`](docs/CONTRACT.md)**, with `Views.py` and `Views.ts` its two halves. A change to what the server
  answers regenerates the golden corpus (`uv run python -m mbse.Services.Rest.Conformance`), committed with it, and is
  reviewed as a change to the contract: mbse-react and mbse-dynamodb build against it.

## Working agreement (M0, for every agent on mbse-rest, mbse-dynamodb, mbse-react and mbse-demo-apps)

- Work on a branch in each repository you change (M0's is `m0-contract`). Commit and push after every step whose
  tests pass (`git push -u origin <branch>`, or `python3 ../mbse-basis/scripts/polyrepo.py push` where it supports
  every sibling). Never commit to `main`. When done, open one pull request per repository with `gh pr create`,
  listing the decisions for review.
- Where the capabilities are silent, take the simplest default consistent with them and with mbse-schemas, record it in
  mbse-rest's [`docs/CONTRACT.md`](docs/CONTRACT.md) under "Decided by the agent, for review", and keep going.
- Stop and report (do not work around) for: a gap or bug in mbse-schemas; an outward-facing action beyond pushing
  branches and opening pull requests in these repositories; anything destructive (force-push, deleting branches or
  files outside your work, rewriting history); a contradiction in a capability that changes what gets built.
- Never edit a sibling from another repository's work; never edit mbse-schemas or mbse-basis from here.
- Never write to `~/.claude/projects/*/memory/` or any hidden memory: what is worth keeping goes in the repository.
- Conventions: Python with uv (`uv sync`, `uv run pytest`), never pip; package capitalization as mbse-schemas has it
  (`mbse.Services.Rest`); "property", never "field", and "schema", never "type", for schema-governed things. Models
  as data are written in the builders' fluent syntax, never wire format, never helpers that wrap builder syntax.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, and every pull request's
  description with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
