"""Tests for Econt's conservative canonical parcel mapping."""
from custom_components.econt.const import CAPABILITIES, ParcelStatus
from custom_components.econt.parcels import build_history, normalize_parcel

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    active_sample,
    delivered_sample,
    event,
)


def test_delivered_parcel_uses_delivery_time_as_authoritative_signal():
    parcel = normalize_parcel(delivered_sample(), include_history=True)
    assert parcel["barcode"] == DELIVERED_CODE
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-07-16T12:09:27.167000+00:00"
    assert parcel["planned_from"] is None
    assert parcel["history"][-1]["raw_status"] == "Delivered"


def test_unknown_current_status_has_sofia_all_day_eta_and_one_warning(caplog):
    parcel = normalize_parcel(active_sample())
    assert parcel["status"] is ParcelStatus.UNKNOWN
    assert parcel["planned_from"] == "2026-07-17T00:00:00+03:00"
    assert parcel["planned_to"] == "2026-07-17T23:59:59.999999+03:00"
    normalize_parcel(active_sample())
    assert caplog.text.count("In processing") == 1


def test_history_is_chronological_and_capped():
    events = [
        event(1784200000000 + index, str(index), "in_transit") for index in range(25, 0, -1)
    ]
    history = build_history(events)
    assert len(history) == 20
    assert history[0]["raw_status"] == "6"


def test_history_status_attempts_mapping_and_warns_once_when_unmapped(caplog):
    events = [
        event(1784200000000, "Sofia depot", "unmapped_leg"),
        event(1784200000001, "Sofia depot", "unmapped_leg"),
    ]
    history = build_history(events)
    assert all(item["status"] is None for item in history)
    assert caplog.text.count("unmapped_leg") == 1


def test_history_status_maps_known_destination_type():
    history = build_history([event(1784200000000, "Handed to client", "client")])
    assert history[0]["status"] is ParcelStatus.DELIVERED


def test_parcel_status_maps_in_transit_hub_event():
    raw = delivered_sample()
    raw["shortDeliveryStatusEn"] = "Arrival-Departure from HUB"
    raw["shortDeliveryStatus"] = "Постъпила за обработка в Логистичен център"
    raw["deliveryTime"] = None
    parcel = normalize_parcel(raw)
    assert parcel["status"] is ParcelStatus.IN_TRANSIT
    assert parcel["delivered"] is False


def test_parcel_status_maps_in_delivery_office():
    raw = delivered_sample()
    raw["shortDeliveryStatusEn"] = "In delivery office"
    raw["shortDeliveryStatus"] = "In delivery office"
    raw["deliveryTime"] = None
    parcel = normalize_parcel(raw)
    assert parcel["status"] is ParcelStatus.IN_TRANSIT
    assert parcel["delivered"] is False


def test_parcel_status_maps_cyrillic_canceled_before_dispatch():
    raw = delivered_sample()
    raw["shortDeliveryStatusEn"] = "Анулирана преди изпращане"
    raw["shortDeliveryStatus"] = "Анулирана преди изпращане"
    raw["deliveryTime"] = None
    parcel = normalize_parcel(raw)
    assert parcel["status"] is ParcelStatus.PROBLEM
    assert parcel["delivered"] is False


def test_parcel_status_maps_awaiting_delivery_to_econt():
    raw = delivered_sample()
    raw["shortDeliveryStatusEn"] = "Awaiting delivery to Econt"
    raw["shortDeliveryStatus"] = "Очаква предаване към Еконт"
    raw["deliveryTime"] = None
    parcel = normalize_parcel(raw)
    assert parcel["status"] is ParcelStatus.REGISTERED
    assert parcel["delivered"] is False


def test_history_status_maps_routing_leg_events():
    history = build_history(
        [
            event(1784200000000, "Kyustendil Moric Levi", "office"),
            event(1784200000001, "Dupnitsa - Kyustendil - Sofia", "courier_direction"),
            event(1784200000002, "Sofia NLC Orion", "office"),
        ]
    )
    assert [item["status"] for item in history] == [ParcelStatus.IN_TRANSIT] * 3


def test_history_status_maps_delivery_courier_event():
    history = build_history([event(1784200000000, "With courier", "in_delivery_courier")])
    assert history[0]["status"] is ParcelStatus.OUT_FOR_DELIVERY


def test_history_status_maps_return_and_failure_events():
    history = build_history(
        [
            event(1784200000000, "Returning to sender", "return"),
            event(1784200000001, "Returned to sender", "returned_to_sender"),
            event(1784200000002, "Destroyed", "destroy"),
            event(1784200000003, "Delivery failed", "failed_delivery"),
        ]
    )
    assert [item["status"] for item in history] == [
        ParcelStatus.RETURNING,
        ParcelStatus.RETURNING,
        ParcelStatus.PROBLEM,
        ParcelStatus.PROBLEM,
    ]


def test_history_status_leaves_pickup_office_unmapped():
    history = build_history([event(1784200000000, "At pickup office", "in_pickup_office")])
    assert history[0]["status"] is None


def test_history_status_leaves_instruction_unmapped(caplog):
    history = build_history([event(1784200000000, "Customer instruction", "instruction")])
    assert history[0]["status"] is None
    assert "instruction" in caplog.text


def test_optional_and_unconfirmed_fields_are_not_advertised():
    parcel = normalize_parcel({"shipmentNumber": ACTIVE_CODE, "weight": 0})
    assert parcel["weight"] is None
    assert parcel["dimensions"] is None
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None
    assert CAPABILITIES == frozenset({"delivery_window", "url", "history", "weight"})


def test_weight_is_passed_through_once_populated():
    parcel = normalize_parcel({"shipmentNumber": ACTIVE_CODE, "weight": 2.5})
    assert parcel["weight"] == 2.5
