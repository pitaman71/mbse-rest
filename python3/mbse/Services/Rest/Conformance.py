"""The golden corpus (`conformance/` at the repository's root): real requests and responses over the WorkTracker seed.

    uv run python -m mbse.Services.Rest.Conformance          # writes conformance/
    uv run python -m mbse.Services.Rest.Conformance --check  # fails where conformance/ differs from what it would write

Each case is sent to a fresh stub server (`Service.work_tracker`), so that no case depends on another. The server's
tests check that it still gives every response; the client's tests read every response, and check that the client
builds every request alike. `conformance/cases.json` lists the cases: each one's `method`, `path`, `request` (a file,
or null), `status`, `content_type` and `response` (a file). A `.json` file is compared as JSON; an `.ndjson` file, a
stream of frames, byte for byte.
"""

from __future__ import annotations

import datetime
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from mbse.Schemas.Framework import Plain, References

from . import Service

__all__ = ["ROOT", "CASES", "Case", "generate", "write", "check"]

ROOT = Path(__file__).resolve().parents[4] / "conformance"  # python3/mbse/Services/Rest -> the repository's root


def _find(store: Any, directory: str, adjacency: str, id_: str) -> Any:
    """A WorkTracker element by its ID, through its schema's directory."""
    return getattr(store.singleton(directory), adjacency)({"id": id_})


def _map(store: Any, symbols: Callable[[Any], dict[str, Any]], spec: Callable[[Any], list[Any]] | None = None) -> Any:
    """A filled template, as the client builds one: one map whose symbols are given, and, an adjacency's, its spec."""
    given = symbols(store)
    return Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols(given).spec(spec(store)) if spec else p.symbols(given)]))])))


def _edit(store: Any, reference: Callable[[Any], Any], values: dict[str, Any]) -> Any:
    """An edit (CAP-014), as the client builds one: the detail view's template, `x` given the object's reference, then
    an update writing each property given its value (None clears it)."""
    x = reference(store)
    return Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.map(
        lambda m: m.symbols([lambda p: p.symbols({"x": x})]).then([lambda w: w.update(lambda u: u.apply([
            lambda p: p.symbols({"x": x}).spec([lambda _, n=name, v=value: getattr(_.x, n)(v)
                                                 for name, value in values.items()])]))]))])))


def _propose(store: Any, reference: Callable[[Any], Any], adjacency: str, link: str, schema: str,
             values: dict[str, Any], entry: dict[str, Any] | None = None) -> Any:
    """A new object proposed through an adjacency (CAP-018), as the client builds it: an upsert whose symbols are `x`,
    the inbound object, and `n`, the new one, and whose spec writes `x`'s entry linking `n`, and `n`'s properties."""
    x = reference(store)
    return Plain.ToPlain(store).Transaction(store.Mutations.OfTransaction(lambda t: t.mutations([lambda mu: mu.upsert(
        lambda u: u.exists([lambda p: p.symbols({"x": x, "n": store.registered(schema)}).spec([
            lambda _: getattr(_.x, adjacency)([lambda e: _entry(getattr(e, link)(_.n), entry or {})]),
            *[lambda _, name=name, value=value: getattr(_.n, name)(value) for name, value in values.items()],
        ])]))])))


def _entry(built: Any, entry: dict[str, Any]) -> Any:
    for name, value in entry.items():
        built = getattr(built, name)(value)
    return built


class Case:
    """One request and the response it gets; `view`, where given, says what the request is made of (its kind, what
    each symbol is given, and an adjacency's name), so that a client can build it again without knowing the case."""

    def __init__(self, name: str, method: str, path: str, request: Callable[[Any], Any] | None = None,
                 view: dict[str, Any] | None = None) -> None:
        self.name, self.method, self.path, self.request, self.view = name, method, path, request, view


def _ref(directory: str, adjacency: str, id_: str) -> Callable[[Any], Any]:
    return lambda store: References.of(store, _find(store, directory, adjacency, id_))


CASES = [
    Case("schemas", "GET", "/schemas"),
    Case("schema-inspector", "GET", "/schemas/work.Project"),
    Case("schema-unknown", "GET", "/schemas/work.Nothing"),
    Case("templates", "GET", "/views"),
    Case("label-capabilities", "POST", "/views/label",
         lambda store: _map(store, lambda s: {"x": s.work.Capability})),
    Case("label-directory", "POST", "/views/label",
         lambda store: _map(store, lambda s: {"x": s.work.ProjectDirectory})),
    Case("chip-tasks", "POST", "/views/chip", lambda store: _map(store, lambda s: {"x": s.work.Task})),
    Case("chip-comments", "POST", "/views/chip", lambda store: _map(store, lambda s: {"x": s.work.Comment})),
    Case("detail-feature", "POST", "/views/detail",
         lambda store: _map(store, lambda s: {"x": _ref("work.Features", "features", "FEA-002")(s)})),
    Case("detail-goal", "POST", "/views/detail",
         lambda store: _map(store, lambda s: {"x": _ref("work.Goals", "goals", "GOL-001")(s)})),
    Case("adjacency-goal-capabilities", "POST", "/views/adjacency",
         lambda store: _map(store, lambda s: {"x": _ref("work.Goals", "goals", "GOL-001")(s), "y": s.work.Capability},
                            lambda s: [lambda _: _.x.capabilities([_.y])])),
    Case("adjacency-feature-capabilities", "POST", "/views/adjacency",
         lambda store: _map(store, lambda s: {"x": _ref("work.Features", "features", "FEA-002")(s),
                                              "y": s.work.Capability},
                            lambda s: [lambda _: _.x.capabilities([_.y])])),
    Case("adjacency-comment-about", "POST", "/views/adjacency",
         lambda store: _map(store, lambda s: {"x": _ref("work.Comments", "comments", "CMT-001")(s),
                                              "y": s.work.Result},
                            lambda s: [lambda _: _.x.about([_.y])])),
    Case("edit-task-title", "POST", "/views/detail",
         lambda store: _edit(store, _ref("work.Tasks", "tasks", "TSK-001"),
                             {"title": "Install the **schemas**", "description": "Define them in a *module-scope* `install`."})),
    Case("edit-task-clear", "POST", "/views/detail",
         lambda store: _edit(store, _ref("work.Tasks", "tasks", "TSK-002"), {"description": None})),
    Case("propose-thread", "POST", "/views/detail",
         lambda store: _propose(store, _ref("work.Features", "features", "FEA-002"), "comments", "comment",
                                "work.Comment", {"text": "Who reviews the **views**?"})),
    Case("propose-reply", "POST", "/views/detail",
         lambda store: _propose(store, _ref("work.Comments", "comments", "CMT-001"), "replies", "reply",
                                "work.Comment", {"text": "Closing this.", "resolves_thread": True})),
    Case("view-unknown-kind", "POST", "/views/summary",
         lambda store: _map(store, lambda s: {"x": s.work.Task})),
    Case("view-unassigned-symbol", "POST", "/views/label",
         lambda store: Service.Service().templates()["label"]),
]


FRAMEWORK = ("Schemas", "Paths", "Mutations", "References", "Parametrics", "Provenance")


def _app_schemas(store: Any) -> list[str]:
    """The app's reference object schemas, in the store's order: those mbse-react's browsers show (CAP-009 to
    CAP-011), the directories included."""
    return [name for name in store.names() if name.split(".")[0] not in FRAMEWORK
            and getattr(store.registered(name), "ref", None) is True]


def _linked(store: Any, schema: str) -> list[tuple[str, list[str]]]:
    """Each named adjacency of `schema`, with the schemas whose objects its entries may link: those declaring an
    adjacency to its relation through another link, as mbse-react's inspector asks CAP-008 for them."""
    declared = [(name, adjacency) for name in _app_schemas(store)
                for adjacency in [*store.registered(name).adjacencies.values(), *store.registered(name).anonymous]]
    found = []
    for adjacency_name, adjacency in store.registered(schema).adjacencies.items():
        relation = adjacency.relation.name
        linked = list(dict.fromkeys(owner for owner, other in declared
                                    if other.relation.name == relation and other.me != adjacency.me))
        found.append((adjacency_name, linked))
    return found


def _key(plain: Any) -> str:
    """A case name's part for an object, from its reference: its last key's values, or a singleton's name."""
    step, key = plain["path"], plain["path"]["singleton"]
    while "entry" in step["next"]:
        step = step["next"]["entry"]
        key = "-".join(str(value) for value in step["properties"].values())
    return key.replace("/", "-")  # a file name's part


def _given(store: Any, given: dict[str, Any]) -> Callable[[Any], dict[str, Any]]:
    """Symbols as `view` describes them, given in the store a case runs in: a schema by name, or a reference."""
    def symbols(s: Any) -> dict[str, Any]:
        return {symbol: s.registered(value["schema"]) if "schema" in value
                else Plain.FromPlain(s)(s.References.OfObject.as_schema(), value["reference"])
                for symbol, value in given.items()}
    return symbols


def _ui_cases() -> list[Case]:
    """A case for every view mbse-react asks of the WorkTracker seed: each app schema's chips (CAP-006) and entries
    (CAP-007 over its extent, the relation browser's), each object's detail (CAP-007), and each object's adjacencies,
    one case per schema their entries may link (CAP-008). All reads, so they may share one server."""
    store = _server().state.service.store
    reference = store.References.OfObject.as_schema()
    cases = []
    for schema in _app_schemas(store):
        for kind, prefix in (("chip", "ui-chip"), ("detail", "ui-entries")):
            view = {"kind": kind, "given": {"x": {"schema": schema}}}
            cases.append(Case(f"{prefix}-{schema}", "POST", f"/views/{kind}",
                              lambda s, v=view: _map(s, _given(s, v["given"])), view))
    for schema in _app_schemas(store):
        for obj in store.extent(schema):
            try:
                plain = Plain.ToPlain(store)(reference, References.of(store, obj))
            except LookupError:  # a counted object: no reference, left out (FEA-003)
                continue
            key = _key(plain)
            view = {"kind": "detail", "given": {"x": {"reference": plain}}}
            cases.append(Case(f"ui-detail-{key}", "POST", "/views/detail",
                              lambda s, v=view: _map(s, _given(s, v["given"])), view))
            for adjacency, linked in _linked(store, schema):
                for y in linked:
                    view = {"kind": "adjacency", "given": {"x": {"reference": plain}, "y": {"schema": y}},
                            "adjacency": adjacency}
                    cases.append(Case(f"ui-adjacency-{key}-{adjacency}-{y}", "POST", "/views/adjacency",
                                      lambda s, v=view: _map(s, _given(s, v["given"]), lambda _s, a=v["adjacency"]: [
                                          lambda _: getattr(_.x, a)([_.y])]), view))
    return cases


def _dump(plain: Any) -> str:
    return json.dumps(plain, indent=1, ensure_ascii=False) + "\n"


def _server() -> Any:
    """A fresh stub server whose writes are stamped reproducibly (CAP-015): a fixed clock, and uids by count."""
    count = iter(range(1, 1_000_000))
    return Service.work_tracker(clock=lambda: datetime.datetime(2026, 10, 26, 14, 30, 5, tzinfo=datetime.timezone.utc),
                                uids=lambda: f"corpus-{next(count)}")


def generate() -> dict[str, str]:
    """Every file of the corpus, by its name: each case's request and response, and the index."""
    files: dict[str, str] = {}
    index = []
    shared = _server()
    for case in [*CASES, *_ui_cases()]:
        api = shared if case.view is not None else _server()  # the UI's cases only read
        client = TestClient(api)
        body = case.request(api.state.service.store) if case.request else None
        response = client.request(case.method, case.path, json=body) if body is not None else \
            client.request(case.method, case.path)
        content_type = response.headers["content-type"].split(";")[0]
        stream = content_type == Service.NDJSON
        entry = {"name": case.name, "method": case.method, "path": case.path,
                 "request": f"{case.name}.request.json" if body is not None else None,
                 "status": response.status_code, "content_type": content_type,
                 "response": f"{case.name}.response.{'ndjson' if stream else 'json'}"}
        if case.view is not None:
            entry["view"] = case.view
        index.append(entry)
        if body is not None:
            files[entry["request"]] = _dump(body)
        files[entry["response"]] = response.text if stream else _dump(response.json())
    files["cases.json"] = _dump(index)
    return files


def write(root: Path = ROOT) -> None:
    """Writes the corpus to `root`, removing any case file it no longer has."""
    files = generate()
    root.mkdir(parents=True, exist_ok=True)
    for old in root.glob("*.json*"):
        if old.name not in files:
            old.unlink()
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")


def check(root: Path = ROOT) -> list[str]:
    """The corpus's files that differ from what `generate` gives, or are missing; [] when it is current."""
    problems = []
    for name, text in generate().items():
        path = root / name
        if not path.exists():
            problems.append(f"{name}: missing")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"{name}: differs")
    return problems


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        found = check()
        print("\n".join(found) or "conformance/ is current")
        sys.exit(1 if found else 0)
    write()
    print(f"wrote {ROOT}")
