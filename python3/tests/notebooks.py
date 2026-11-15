"""Suites of a sibling's test notebook, run here case by case: each code cell executed in order in one namespace, as
the notebook runs them, so that a case is run as its sibling wrote it."""

from __future__ import annotations

import contextlib
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]  # beside this repository's checkout: its siblings (siblings.json)
CASE = re.compile(r'<a id="([A-Z]+-\d+)"></a>')


def cells(sibling: str, notebook: str) -> list[tuple[str | None, str]]:
    """The notebook's code cells, each with the case ID of the markdown cell before it (None for its setup)."""
    nb = json.loads((ROOT / sibling / "python3" / "tests" / notebook).read_text())
    found, case = [], None
    for cell in nb["cells"]:
        source = "".join(cell["source"])
        if cell["cell_type"] == "markdown":
            match = CASE.search(source)
            case = match.group(1) if match else None
        else:
            found.append((case, source))
    return found


@contextlib.contextmanager
def raises(kind: type[BaseException], match: str | None = None) -> Any:
    """mbse-schemas' notebook helper (`tests/support.py`), as its notebooks import it."""
    with pytest.raises(kind, match=match):
        yield


def namespace() -> dict[str, Any]:
    support = types.ModuleType("support")
    support.raises = raises  # type: ignore[attr-defined]
    sys.modules.setdefault("support", support)
    return {"__name__": "__notebook__"}
