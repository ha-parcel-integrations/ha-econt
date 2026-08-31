"""Additional Econt error and nullable-field regression cases."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.econt.api import EcontApiClient, EcontApiError
from custom_components.econt.parcels import (
    build_history,
    format_dimensions,
    map_event_status,
    parse_iso,
    to_iso_timestamp,
    tracking_url,
)


def _session(status, body, headers=None):
    response = AsyncMock(status=status, headers=headers or {})
    response.json = AsyncMock(return_value=body)
    context = MagicMock(__aenter__=AsyncMock(return_value=response), __aexit__=AsyncMock(return_value=False))
    return MagicMock(post=MagicMock(return_value=context))


async def test_api_empty_input_and_http_error_paths():
    assert await EcontApiClient(MagicMock()).async_get_parcels([]) == {}
    with pytest.raises(EcontApiError) as error:
        await EcontApiClient(_session(429, {}, {"Retry-After": "invalid"})).async_get_parcels(["1"])
    assert error.value.status_code == 429 and error.value.retry_after is None
    with pytest.raises(EcontApiError):
        await EcontApiClient(_session(500, {})).async_get_parcels(["1"])


@pytest.mark.parametrize("body", [[], {"shipmentStatuses": ["bad"]}, {"shipmentStatuses": [{"status": "bad"}]}, {"shipmentStatuses": [{"status": {}}]}])
async def test_api_rejects_untrusted_element_shapes(body):
    with pytest.raises(EcontApiError):
        await EcontApiClient(_session(200, body)).async_get_parcels(["1"])


def test_nullable_and_malformed_helpers_never_raise():
    assert map_event_status(None) is None
    assert parse_iso("broken") is None
    assert to_iso_timestamp(None) is None
    assert to_iso_timestamp(10**30) is None
    assert format_dimensions(1, None, 3) is None
    assert tracking_url(None) is None
    assert build_history(["bad", {"time": None}, {"time": "broken", "destinationType": "instruction"}]) == [{"timestamp": "broken", "status": None, "raw_status": "instruction"}]
