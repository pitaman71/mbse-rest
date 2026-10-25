"""Serves the REST service with uvicorn, as the environment configures it (`Service.from_environment`):

    uv run python -m mbse.Services.Rest

- `MBSE_REST_HOST` and `MBSE_REST_PORT`: where it listens (`127.0.0.1`, `8000`);
- `MBSE_REST_APP`, `MBSE_REST_SEED`, `MBSE_REST_PLUGIN`, `MBSE_REST_SNAPSHOT_EVERY` and `MBSE_REST_ORIGINS`: what it
  serves, as `Service.from_environment` reads them.
"""

from __future__ import annotations

import os

import uvicorn

from .Service import from_environment


def main() -> None:
    uvicorn.run(from_environment(), host=os.environ.get("MBSE_REST_HOST", "127.0.0.1"),
                port=int(os.environ.get("MBSE_REST_PORT", "8000")))


if __name__ == "__main__":
    main()
