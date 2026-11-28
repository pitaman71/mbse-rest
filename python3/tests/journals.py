"""What the tests read inside a view's frame, a `References.OfFrame` as plain data, as mbse-schemas writes it: its
journal's property sets and entry inserts. The tests that look inside frames change with `References.OfFrame`; nothing
else does."""

from __future__ import annotations

from typing import Any


def properties(frame: dict[str, Any], symbol: str = "x") -> dict[str, Any]:
    """Each property the frame's journal sets of the object `symbol` binds, its value, in the order set."""
    return {body["name"]: body["value"] for change in frame["journal"].get("changes", [])
            for body in [change.get("property", {}).get("set")] if body is not None and body["holder"] == symbol}


def entries(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """Each entry the frame's journal inserts, in order."""
    return [change["entry"]["insert"] for change in frame["journal"].get("changes", []) if "insert" in change.get("entry", {})]
