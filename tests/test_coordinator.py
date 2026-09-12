"""Tests for Econt's one-request-per-refresh coordinator behaviour."""
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.econt.api import EcontApiError
from custom_components.econt.const import (
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DOMAIN,
    ParcelStatus,
)
from custom_components.econt.coordinator import EcontCoordinator

from .payloads import ACTIVE_CODE, DELIVERED_CODE, active_sample, delivered_sample


def _entry(codes: list[str]) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={CONF_PARCELS: [{CONF_TRACKING_CODE: code} for code in codes], "delivered_filter_type": "parcels", "delivered_filter_amount": 100})


async def test_one_batch_splits_active_delivered_and_matches_codes(hass):
    entry = _entry([DELIVERED_CODE, ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcels.return_value = {ACTIVE_CODE: active_sample(), DELIVERED_CODE: delivered_sample()}
    coordinator = EcontCoordinator(hass, client, entry)
    active = await coordinator._async_update_data()
    client.async_get_parcels.assert_awaited_once_with([DELIVERED_CODE, ACTIVE_CODE])
    assert active[0]["barcode"] == ACTIVE_CODE
    assert coordinator.delivered[0]["status"] is ParcelStatus.DELIVERED


async def test_delivered_code_skipped_from_fetch(hass):
    """A delivered code stops being fetched from the next cycle on."""
    entry = _entry([DELIVERED_CODE, ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcels.return_value = {
        ACTIVE_CODE: active_sample(),
        DELIVERED_CODE: delivered_sample(),
    }
    coordinator = EcontCoordinator(hass, client, entry)

    await coordinator._async_update_data()
    assert coordinator.delivered_codes == {DELIVERED_CODE}

    client.async_get_parcels.reset_mock()
    client.async_get_parcels.return_value = {ACTIVE_CODE: active_sample()}
    data = await coordinator._async_update_data()

    # Only the still-active code is fetched — the delivered one is skipped.
    client.async_get_parcels.assert_awaited_once_with([ACTIVE_CODE])
    assert any(p["barcode"] == DELIVERED_CODE for p in coordinator.delivered)
    assert data[0]["barcode"] == ACTIVE_CODE


async def test_delivered_code_forgotten_when_untracked(hass):
    """Untracking a delivered code drops it from the skip set too."""
    entry = _entry([DELIVERED_CODE])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcels.return_value = {DELIVERED_CODE: delivered_sample()}
    coordinator = EcontCoordinator(hass, client, entry)

    await coordinator._async_update_data()
    assert coordinator.delivered_codes == {DELIVERED_CODE}

    hass.config_entries.async_update_entry(entry, options={CONF_PARCELS: []})
    await coordinator._async_update_data()
    assert coordinator.delivered_codes == set()


async def test_not_found_yields_pending_placeholder(hass):
    entry = _entry([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcels.return_value = {ACTIVE_CODE: None}
    data = await EcontCoordinator(hass, client, entry)._async_update_data()
    assert data[0]["barcode"] == ACTIVE_CODE
    assert data[0]["status"] is ParcelStatus.UNKNOWN


async def test_batch_failure_uses_cache_or_fails_when_empty(hass):
    entry = _entry([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcels.side_effect = EcontApiError("HTTP 500")
    coordinator = EcontCoordinator(hass, client, entry)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    coordinator._raw_cache[ACTIVE_CODE] = active_sample()
    assert (await coordinator._async_update_data())[0]["barcode"] == ACTIVE_CODE


async def test_rate_limit_propagates_retry_after(hass):
    entry = _entry([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcels.side_effect = EcontApiError("HTTP 429", status_code=429, retry_after=120)
    with pytest.raises(UpdateFailed) as error:
        await EcontCoordinator(hass, client, entry)._async_update_data()
    assert error.value.retry_after == 120
