"""Tests for Econt's numeric tracking-code options flow."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.econt.config_flow import (
    normalize_tracking_code,
    valid_tracking_code,
)
from custom_components.econt.const import CONF_PARCELS, CONF_TRACKING_CODE, DOMAIN


def test_numeric_code_validation_is_trimmed_but_not_reformatted():
    assert normalize_tracking_code(" 1055215517880 ") == "1055215517880"
    assert valid_tracking_code("1055215517880")
    assert not valid_tracking_code("")
    assert not valid_tracking_code("10552-15517880")
    assert not valid_tracking_code("econt")


async def test_user_flow_creates_one_code_based_hub(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "create_entry"
    assert result["options"][CONF_PARCELS] == []


async def test_options_rejects_non_numeric_and_deduplicates_numeric_codes(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={CONF_PARCELS: []})
    entry.add_to_hass(hass)
    start = await hass.config_entries.options.async_init(entry.entry_id)
    form = await hass.config_entries.options.async_configure(start["flow_id"], {"next_step_id": "parcels"})
    invalid = await hass.config_entries.options.async_configure(form["flow_id"], {"tracking_codes": ["ABC"]})
    assert invalid["errors"]["base"] == "invalid_tracking_code"

    start = await hass.config_entries.options.async_init(entry.entry_id)
    form = await hass.config_entries.options.async_configure(start["flow_id"], {"next_step_id": "parcels"})
    result = await hass.config_entries.options.async_configure(form["flow_id"], {"tracking_codes": [" 1055215517880 ", "1055215517880"]})
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: "1055215517880"}]
