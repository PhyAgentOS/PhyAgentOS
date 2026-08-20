"""Asynchronous client for the Forge Gateway 1.0 Agent API."""

from __future__ import annotations

from typing import Any

import httpx


class ForgeGatewayError(RuntimeError):
    """A Gateway transport or contract operation failed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ForgeGatewayClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=max(0.1, float(timeout_s)),
            transport=transport,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def capabilities(self) -> dict[str, Any]:
        return await self._get("/agent/runtime/capabilities")

    async def runtime_status(self) -> dict[str, Any]:
        return await self._get("/agent/runtime/status")

    async def runtime_context(self) -> dict[str, Any]:
        return await self._get("/agent/runtime/context")

    async def reset_runtime(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._post("/agent/runtime/reset", {"inputs": inputs or {}})

    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/agent/sessions", payload)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await self._get(f"/agent/sessions/{session_id}")

    async def cancel_session(
        self, session_id: str, reason: str = "paos_requested"
    ) -> dict[str, Any]:
        return await self._post(
            f"/agent/sessions/{session_id}/cancel", {"reason": reason}
        )

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise ForgeGatewayError(f"Forge Gateway GET {path} failed: {exc}") from exc
        return self._decode(response, path)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise ForgeGatewayError(f"Forge Gateway POST {path} failed: {exc}") from exc
        return self._decode(response, path)

    @staticmethod
    def _decode(response: httpx.Response, path: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ForgeGatewayError(
                f"Forge Gateway {path} returned non-JSON response: HTTP {response.status_code}",
                status_code=response.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise ForgeGatewayError(
                f"Forge Gateway {path} returned invalid payload",
                status_code=response.status_code,
            )
        if response.status_code >= 400 or data.get("ok") is False:
            message = data.get("msg") or data.get("message") or response.text
            raise ForgeGatewayError(
                f"Forge Gateway {path} rejected request: {message}",
                status_code=response.status_code,
            )
        return data
