"""Tests for Econt's batched shipment-status client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.econt.api import EcontApiClient, EcontApiError

from .payloads import ACTIVE_CODE, DELIVERED_CODE, active_sample, delivered_sample


def _session(status: int, body: object) -> MagicMock:
    response = AsyncMock(status=status, headers={})
    response.json = AsyncMock(
        side_effect=json.JSONDecodeError("x", str(body), 0) if isinstance(body, str) else None,
        return_value=None if isinstance(body, str) else body,
    )
    ctx = MagicMock(__aenter__=AsyncMock(return_value=response), __aexit__=AsyncMock(return_value=False))
    session = MagicMock(post=MagicMock(return_value=ctx))
    return session


async def test_get_parcels_matches_reverse_order_by_shipment_number():
    session = _session(200, {"shipmentStatuses": [{"status": active_sample()}, {"status": delivered_sample()}]})
    result = await EcontApiClient(session).async_get_parcels([DELIVERED_CODE, ACTIVE_CODE])
    assert result[DELIVERED_CODE]["shipmentNumber"] == DELIVERED_CODE
    assert result[ACTIVE_CODE]["shipmentNumber"] == ACTIVE_CODE
    assert session.post.call_args.kwargs["json"] == {"shipmentNumbers": [DELIVERED_CODE, ACTIVE_CODE]}


async def test_get_parcels_not_found_is_none():
    result = await EcontApiClient(_session(200, {"shipmentStatuses": [{"status": None, "error": {"message": "not found"}}]})).async_get_parcels([ACTIVE_CODE])
    assert result == {ACTIVE_CODE: None}


@pytest.mark.parametrize("status, body", [(517, {}), (200, "not json"), (200, {"shipmentStatuses": [{}]})])
async def test_get_parcels_rejects_invalid_or_malformed_response(status, body):
    with pytest.raises(EcontApiError):
        await EcontApiClient(_session(status, body)).async_get_parcels([ACTIVE_CODE])


async def test_get_parcels_rejects_duplicate_response_number():
    body = {"shipmentStatuses": [{"status": delivered_sample()}, {"status": delivered_sample()}]}
    with pytest.raises(EcontApiError, match="duplicate"):
        await EcontApiClient(_session(200, body)).async_get_parcels([DELIVERED_CODE])


async def test_get_parcels_propagates_network_error():
    session = MagicMock(post=MagicMock(side_effect=aiohttp.ClientError("boom")))
    with pytest.raises(aiohttp.ClientError):
        await EcontApiClient(session).async_get_parcels([ACTIVE_CODE])
