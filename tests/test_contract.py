"""The parcel contract's checks, run over every normalised sample."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.econt.const import ParcelStatus
from custom_components.econt.parcels import (
    is_pickup,
    normalize_parcel,
    parse_iso,
    planned_for_status,
    planned_window,
)

from .payloads import active_sample, delivered_sample, event

SOFIA = ZoneInfo("Europe/Sofia")

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "contents",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def _in_transit() -> dict:
    sample = active_sample()
    sample["shortDeliveryStatusEn"] = "Arrival-Departure from HUB"
    return sample


def _delivery_time_only() -> dict:
    sample = _in_transit()
    sample["deliveryTime"] = 1784203767167
    return sample


def _with_events() -> dict:
    sample = _in_transit()
    sample["trackingEvents"] = [event(1784100000000, "Returned", "returned_to_sender")]
    return sample


SAMPLES = {
    "delivered": delivered_sample,
    "active": active_sample,
    "in_transit": _in_transit,
    "delivery_time_only": _delivery_time_only,
    "with_events": _with_events,
    "bare": lambda: {"shipmentNumber": "1055000000001"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param](), include_history=True)


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_a_delivery_time_folds_into_the_status():
    parcel = normalize_parcel(_delivery_time_only())
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-07-16T12:09:27.167000+00:00"
    assert parcel["planned_from"] is None


def test_a_delivery_time_never_overrides_returning(monkeypatch):
    monkeypatch.setitem(
        normalize_parcel.__globals__["_STATUS_MAP"], "Back", ParcelStatus.RETURNING
    )
    sample = _delivery_time_only()
    sample["shortDeliveryStatusEn"] = "Back"
    parcel = normalize_parcel(sample)
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None
    assert parcel["planned_from"] is None


def test_an_expected_date_covers_the_whole_sofia_day():
    parcel = normalize_parcel(_in_transit())
    start = datetime.fromisoformat(parcel["planned_from"])
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert start.date() == end.date()
    assert start.utcoffset() == end.utcoffset() == SOFIA.utcoffset(start)


def test_a_moment_ends_at_the_end_of_that_day():
    start, end = planned_window("2099-04-29T13:00:00Z", None, zone=SOFIA)
    assert start == "2099-04-29T13:00:00Z"
    assert end == "2099-04-29T23:59:59+03:00"


def test_a_date_covers_the_whole_day():
    assert planned_window(date(2099, 4, 29), None, zone=SOFIA) == (
        "2099-04-29T00:00:00+03:00",
        "2099-04-29T23:59:59+03:00",
    )


def test_planned_for_status_keeps_the_window_while_in_transit():
    window = ("2099-04-29T00:00:00+03:00", "2099-04-29T23:59:59+03:00")
    assert planned_for_status(ParcelStatus.IN_TRANSIT, *window) == window
    assert planned_for_status(ParcelStatus.RETURNING, *window) == (None, None)


def test_econt_pickup_follows_the_delivery_type():
    parcel = normalize_parcel(_with_events(), include_history=True)
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None
    office = normalize_parcel({**_with_events(), "deliveryType": "office"})
    assert office["pickup"] is True
    assert office["pickup_point"] is None
    door = normalize_parcel({**_with_events(), "deliveryType": "door"})
    assert door["pickup"] is False
    assert parcel["status"] is ParcelStatus.IN_TRANSIT


def test_planned_window_edge_cases():
    day = date(2099, 4, 29)
    assert planned_window(None, None, zone=SOFIA) == (None, None)
    assert planned_window("garbage", "2099-04-29", zone=SOFIA)[0] == (
        "2099-04-29T00:00:00+03:00"
    )
    assert planned_window(datetime(2099, 4, 29, 8, 0), None, zone=SOFIA) == (
        "2099-04-29T08:00:00+03:00",
        "2099-04-29T23:59:59+03:00",
    )
    assert planned_window(day, date(2099, 4, 30), zone=SOFIA) == (
        "2099-04-29T00:00:00+03:00",
        "2099-04-30T23:59:59+03:00",
    )
    assert planned_window("2099-04-30", "2099-04-29", zone=SOFIA) == (
        "2099-04-29T00:00:00+03:00",
        "2099-04-30T23:59:59+03:00",
    )
    assert planned_window(
        "2099-04-29T10:00:00+03:00", "2099-04-29T10:00:00+03:00", zone=SOFIA
    ) == ("2099-04-29T10:00:00+03:00", "2099-04-29T23:59:59+03:00")
    assert planned_window("2099-04-29T23:59:59", None, zone=SOFIA) == (
        "2099-04-29T23:59:59+03:00",
        None,
    )
    assert planned_window(5, None, zone=SOFIA) == (None, None)


def test_is_pickup_helper():
    assert is_pickup(True, ParcelStatus.IN_TRANSIT) is True
    assert is_pickup(None, ParcelStatus.AT_PICKUP_POINT) is True
    assert is_pickup(None, ParcelStatus.DELIVERED, [ParcelStatus.AT_PICKUP_POINT])
    assert is_pickup(None, ParcelStatus.DELIVERED, [None]) is False
