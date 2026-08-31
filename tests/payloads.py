"""Minimal, synthetic Econt response shapes; all personal data is omitted."""
from __future__ import annotations

ACTIVE_CODE = "1055215517881"
DELIVERED_CODE = "1055215517880"


def event(timestamp: int | str, detail: str, kind: str = "office") -> dict:
    return {"time": timestamp, "destinationDetailsEn": detail, "destinationType": kind}


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    return {
        "shipmentNumber": code,
        "shortDeliveryStatus": "Delivered",
        "shortDeliveryStatusEn": "Delivered",
        "deliveryTime": 1784203767167,
        # Epoch milliseconds, same scale as sendTime/deliveryTime — not an ISO string.
        "expectedDeliveryDate": 1784275200000,
        "weight": 0,
        "trackingEvents": [
            event(1784100000000, "Accepted at office"),
            event(1784200000000, "Delivered", "client"),
        ],
    }


def active_sample(code: str = ACTIVE_CODE) -> dict:
    return {
        "shipmentNumber": code,
        "shortDeliveryStatus": "В обработка",
        "shortDeliveryStatusEn": "In processing",
        "deliveryTime": None,
        # Epoch milliseconds, same scale as sendTime/deliveryTime — not an ISO string.
        "expectedDeliveryDate": 1784275200000,
        "weight": 0,
        "trackingEvents": [event(1784100000000, "Accepted at office")],
    }
