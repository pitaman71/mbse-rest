"""Serves, for the TypeScript client's tests (`typescript5/tests/store.test.ts`), a service per path prefix,
`/stores/<name>/...`, each over a store in memory of its own, made empty when first asked for, as `Service.app()` makes
one; or, at `/library/...`, one serving the tests' library (`library.py`), seeded. It prints the port it listens on,
then serves until it is stopped.

    uv run python tests/serve.py
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))  # library.py, beside it

from library import install, seed  # noqa: E402

from mbse.Services.Rest import Service  # noqa: E402


class Stores:
    """An ASGI application that gives each request to the service its path's prefix names, made when first asked."""

    def __init__(self) -> None:
        self.services: dict[str, Any] = {}

    def service(self, prefix: str, name: str) -> Any:
        key = f"{prefix}/{name}"
        if key not in self.services:
            self.services[key] = Service.app([install], seed=seed) if prefix == "library" else Service.app()
        return self.services[key]

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        _, prefix, name, *rest = scope["path"].split("/", 3)
        path = "/" + (rest[0] if rest else "")
        await self.service(prefix, name)(dict(scope, path=path, raw_path=path.encode(), root_path=""), receive, send)


def main() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    print(port, flush=True)
    uvicorn.run(Stores(), host="127.0.0.1", port=port, lifespan="off", log_level="warning")


if __name__ == "__main__":
    main()
