# Guide for AI agents

The named schema list, schema inspector, logical view templates and one endpoint per logical view kind (VISUALIZATION.md, CAP-002 to CAP-004 and CAP-012). The whole interface, verified in one repository: the server in Python, `python3/mbse/Services/Rest` (`mbse.Services.Rest`), and the client in TypeScript, `typescript5/mbse/Services/Rest/Client.ts` (`@mbse/rest`).

## Invariants

- **Use mbse-schemas as it stands.** A gap found is reported to the user, not worked around here.
- **Siblings are checkouts beside this repository**, pinned by commit in `siblings.json`. Other agents may be working
  in them: never edit a sibling from here.
- **What this repository builds is specified in the workspace's `VISUALIZATION.md`**, by feature and capability ID;
  cite those IDs rather than restate them.
- **Tests run with pytest** from `python3/`: `uv sync && uv run pytest`. Use uv, never pip.
- **Type-check the client** from `typescript5/`: `npm install && npm run typecheck`.
