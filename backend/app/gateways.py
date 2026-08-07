from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class ObjectStoreGateway(Protocol):
    async def put(self, key: str, content: bytes, content_type: str) -> str: ...


class OutboundGateway(Protocol):
    async def send_group(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class FlightPlanRecoveryGateway(Protocol):
    async def request_plan_ids(
        self,
        *,
        airport_code: str,
        stand: str,
        window_start: Any,
        window_end: Any,
        flight_numbers: list[str],
        request_id: str,
    ) -> dict[str, Any]: ...


@dataclass
class HttpObjectStoreGateway:
    base_url: str
    token: str | None = None

    async def put(self, key: str, content: bytes, content_type: str) -> str:
        headers = {"Content-Type": content_type}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.put(f"{self.base_url.rstrip('/')}/{key}", content=content, headers=headers)
            response.raise_for_status()
        return key


@dataclass
class PreviewOnlyOutboundGateway:
    """The v1 boundary: build the exact payload but never send it externally."""

    async def send_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"sent": False, "mode": "preview", "payload": payload}


@dataclass
class PreviewOnlyFlightPlanRecoveryGateway:
    """Records a recovery request without pretending the current batch is a response."""

    async def request_plan_ids(
        self,
        *,
        airport_code: str,
        stand: str,
        window_start: Any,
        window_end: Any,
        flight_numbers: list[str],
        request_id: str,
    ) -> dict[str, Any]:
        return {
            "received": False,
            "mode": "preview",
            "plan_ids": [],
            "request_id": request_id,
        }
