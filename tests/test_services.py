"""Tests for Econt parcel registration services."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.econt.const import CONF_PARCELS, CONF_TRACKING_CODE, DOMAIN

from .payloads import ACTIVE_CODE, active_sample


async def _setup(hass, parcels: list[dict] | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={CONF_PARCELS: parcels or []})
    entry.add_to_hass(hass)
    with patch("custom_components.econt.api.EcontApiClient.async_get_parcels", new=AsyncMock(return_value={})):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_track_and_untrack_numeric_code(hass):
    entry = await _setup(hass)
    with patch("custom_components.econt.api.EcontApiClient.async_get_parcels", new=AsyncMock(return_value={ACTIVE_CODE: active_sample()})):
        await hass.services.async_call(DOMAIN, "track_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]
        await hass.services.async_call(DOMAIN, "untrack_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE}, blocking=True)
        await hass.async_block_till_done()
    assert entry.options[CONF_PARCELS] == []


async def test_track_rejects_non_numeric_code(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "track_parcel", {CONF_TRACKING_CODE: "Econt"}, blocking=True)


async def test_track_duplicate_is_noop(hass):
    entry = await _setup(hass)
    with patch("custom_components.econt.api.EcontApiClient.async_get_parcels", new=AsyncMock(return_value={ACTIVE_CODE: active_sample()})):
        for _ in range(2):
            await hass.services.async_call(DOMAIN, "track_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE}, blocking=True)
            await hass.async_block_till_done()
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]


async def test_untrack_unknown_code_is_noop(hass):
    entry = await _setup(hass, parcels=[{CONF_TRACKING_CODE: ACTIVE_CODE}])
    with patch("custom_components.econt.api.EcontApiClient.async_get_parcels", new=AsyncMock(return_value={ACTIVE_CODE: active_sample()})):
        await hass.services.async_call(DOMAIN, "untrack_parcel", {CONF_TRACKING_CODE: "000000000"}, blocking=True)
        await hass.async_block_till_done()
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]
