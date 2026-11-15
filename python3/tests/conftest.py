"""What the tests share: a transport that reaches a service in this process, through FastAPI's test client."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def transport(api: Any) -> Any:
    """`Store.Transport` to the service `api` serves, in this process: no network."""
    client = TestClient(api)

    def send(method: str, path: str, body: bytes | None) -> tuple[int, bytes]:
        response = client.request(method, path, content=body, headers={"content-type": "application/json"})
        return response.status_code, response.content

    return send
