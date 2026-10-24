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


class Case:
    """One request and the response it gets."""

    def __init__(self, name: str, method: str, path: str, request: Callable[[Any], Any] | None = None) -> None:
        self.name, self.method, self.path, self.request = name, method, path, request


def _ref(directory: str, adjacency: str, id_: str) -> Callable[[Any], Any]:
    return lambda store: References.of(store, _find(store, directory, adjacency, id_))


CASES = [
    Case("schemas", "GET", "/schemas"),
    Case("schema-inspector", "GET", "/schemas/work.Project"),
    Case("schema-unknown", "GET", "/schemas/work.Nothing"),
    Case("snapshot-schemas", "GET", "/snapshot/schemas"),
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
    Case("view-unknown-kind", "POST", "/views/summary",
         lambda store: _map(store, lambda s: {"x": s.work.Task})),
    Case("view-unassigned-symbol", "POST", "/views/label",
         lambda store: Service.Service().templates()["label"]),
]


def _dump(plain: Any) -> str:
    return json.dumps(plain, indent=1, ensure_ascii=False) + "\n"


def generate() -> dict[str, str]:
    """Every file of the corpus, by its name: each case's request and response, and the index."""
    files: dict[str, str] = {}
    index = []
    for case in CASES:
        api = Service.work_tracker()
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
