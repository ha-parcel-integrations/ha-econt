"""Client for Econt's public, batched shipment-status service."""
from __future__ import annotations

from typing import Any

import aiohttp

from .const import TRACKING_API_URL


class EcontApiError(Exception):
    """Raised when Econt returns a transport or unrecognised API response."""

    def __init__(self, detail: str, *, status_code: int | None = None, retry_after: float | None = None) -> None:
        """Store the carrier response detail and optional retry metadata."""
        super().__init__(f"Econt API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


class EcontApiClient:
    """Read-only client for Econt shipment statuses."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with Home Assistant's shared session."""
        self._session = session

    async def async_get_parcels(self, codes: list[str]) -> dict[str, dict[str, Any] | None]:
        """Fetch codes in one request, matching results by shipment number."""
        if not codes:
            return {}
        async with self._session.post(TRACKING_API_URL, json={"shipmentNumbers": codes}) as response:
            if response.status == 429:
                try:
                    retry_after = float(response.headers.get("Retry-After", ""))
                except ValueError:
                    retry_after = None
                raise EcontApiError("HTTP 429", status_code=429, retry_after=retry_after)
            if response.status != 200:
                raise EcontApiError(f"HTTP {response.status}", status_code=response.status)
            try:
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise EcontApiError(f"unparseable body ({err})") from err

        statuses = payload.get("shipmentStatuses") if isinstance(payload, dict) else None
        if not isinstance(statuses, list):
            raise EcontApiError("unexpected response envelope")

        requested = set(codes)
        result: dict[str, dict[str, Any] | None] = {code: None for code in codes}
        seen: set[str] = set()
        for item in statuses:
            if not isinstance(item, dict):
                raise EcontApiError("shipment status is not an object")
            status, error = item.get("status"), item.get("error")
            if status is None:
                if error is None:
                    raise EcontApiError("empty shipment status element")
                unmatched = requested - seen
                if len(unmatched) != 1:
                    raise EcontApiError("ambiguous per-shipment error element")
                result[unmatched.pop()] = None
                continue
            if not isinstance(status, dict):
                raise EcontApiError("populated shipment status is not an object")
            shipment_number = status.get("shipmentNumber")
            if not isinstance(shipment_number, str) or shipment_number not in requested:
                raise EcontApiError("missing or unexpected shipmentNumber")
            if shipment_number in seen:
                raise EcontApiError("duplicate shipmentNumber")
            seen.add(shipment_number)
            result[shipment_number] = status
        return result
