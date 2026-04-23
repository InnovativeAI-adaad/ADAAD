# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.regression_standard


def _ensure_sse_starlette_stub() -> None:
    if "sse_starlette.sse" in sys.modules:
        return
    sse_module = types.ModuleType("sse_starlette.sse")

    class _EventSourceResponse:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401, ANN002, ANN003
            self.args = args
            self.kwargs = kwargs

    sse_module.EventSourceResponse = _EventSourceResponse
    sys.modules["sse_starlette.sse"] = sse_module
    package = types.ModuleType("sse_starlette")
    package.sse = sse_module
    sys.modules["sse_starlette"] = package


class _FakeResponse:
    def __init__(self, *, status_code: int, chunks: list[bytes] | None = None, body: bytes = b"") -> None:
        self.status_code = status_code
        self._chunks = chunks or []
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aread(self) -> bytes:
        return self._body

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse, capture: dict | None = None, **kwargs) -> None:
        self._response = response
        self._capture = capture if capture is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method: str, url: str, **kwargs):
        self._capture["method"] = method
        self._capture["url"] = url
        self._capture["json"] = kwargs.get("json", {})
        return self._response

    async def aclose(self) -> None:
        return None


def test_dork_stream_rejects_invalid_messages_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_sse_starlette_stub()
    from app.api.streams import router as streams_router

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = FastAPI()
    app.include_router(streams_router)

    with TestClient(app) as client:
        response = client.post(
            "/api/dork/stream",
            json={"model": "claude-sonnet-4-6", "messages": {"role": "user", "content": "bad"}},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "messages_must_be_list"


def test_dork_stream_maps_upstream_non_2xx_to_gateway_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_sse_starlette_stub()
    from app.api.streams import router as streams_router

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = FastAPI()
    app.include_router(streams_router)

    upstream_response = _FakeResponse(status_code=429, body=b'{"error":"rate_limited"}')
    monkeypatch.setattr(
        "app.api.streams.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(upstream_response, **kwargs),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/dork/stream",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 502
    detail = response.json()["detail"]["error"]
    assert detail["type"] == "upstream_error"
    assert detail["upstream_status"] == 429
    assert "rate_limited" in detail["message"]


def test_dork_stream_clamps_max_tokens_before_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_sse_starlette_stub()
    from app.api.streams import router as streams_router

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = FastAPI()
    app.include_router(streams_router)
    capture: dict = {}
    upstream_response = _FakeResponse(status_code=200, chunks=[b"data: ok\n\n"])
    monkeypatch.setattr(
        "app.api.streams.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(upstream_response, capture=capture, **kwargs),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/dork/stream",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 999999,
            },
        )

    assert response.status_code == 200
    assert capture["json"]["max_tokens"] == 4096
