<!-- nav -->
[← mbse-rest](../README.md)

# The golden corpus

Real requests and responses of mbse-rest's stub server over the WorkTracker seed (mbse-demo-apps), the contract
between the server and every client ([FEA-003: no-code logical views](../../mbse-basis/docs/features/FEA-003.md#the-golden-corpus), the golden corpus). `cases.json` lists
each case; the `ui-*` cases, generated for every view mbse-react asks of the seed, carry `view`, what their
request is made of. `<case>.request.json` is its body, and `<case>.response.json` or `.ndjson` what the server answers.

Generated, never edited by hand: from `python3/`, `uv run python -m mbse.Services.Rest.Conformance`. The server's tests
fail while it is out of date; the client's tests read it (`typescript5/tests/client.test.ts`).

---

<!-- nav -->
[← mbse-rest](../README.md)
