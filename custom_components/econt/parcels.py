"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

Two things here are carrier-specific:
:data:`_STATUS_MAP` and :func:`normalize_parcel`. Everything else — the
timestamp parsing, the history builder, the sort contract, the delivered
filter, the one-shot warning for unmapped statuses — is suite-wide machinery
and should be left alone.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-econt/issues/new"
    "?template=unrecognised_status.yml"
)

# The keys are whatever the API reports; the values must come from the
# canonical enum — never invent a new one. Prefer mapping too little over
# mapping wrongly: an unmapped value surfaces as ``unknown`` plus a one-shot
# warning that asks the user to report it, which is how the map grows.
#
# Two distinct, unrelated vocabularies from the same API — kept as separate
# dicts so a value from one can never accidentally match a key meant for the
# other. ``_STATUS_MAP`` keys on the parcel's overall ``shortDeliveryStatusEn``
# (usually English; the Cyrillic key below is a confirmed translation gap for
# that one value, not a general fallback pattern). ``_EVENT_STATUS_MAP`` keys
# on a single history event's ``destinationType`` — a routing-leg code, not
# necessarily equal to the parcel's overall status at that point in time.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "Delivered": ParcelStatus.DELIVERED,
    "Arrival-Departure from HUB": ParcelStatus.IN_TRANSIT,
    "Анулирана преди изпращане": ParcelStatus.PROBLEM,  # "Canceled before dispatch"
    "Awaiting delivery to Econt": ParcelStatus.REGISTERED,
    # Live-confirmed shortDeliveryStatusEn value (not the docs' "In delivery
    # courier's office" wording). Same routing leg as the event-level
    # "in_delivery_office" below, so mapped the same way.
    "In delivery office": ParcelStatus.IN_TRANSIT,
}
_EVENT_STATUS_MAP: dict[str, ParcelStatus] = {
    "client": ParcelStatus.DELIVERED,
    "prepared": ParcelStatus.REGISTERED,
    "canceled": ParcelStatus.PROBLEM,
    # Routing legs — office scans and inter-office handoffs, confirmed by a
    # live in-transit sample whose events alternated "office" and
    # "courier_direction" while the parcel's own status stayed HUB transit.
    "office": ParcelStatus.IN_TRANSIT,
    "courier_direction": ParcelStatus.IN_TRANSIT,
    "courier": ParcelStatus.IN_TRANSIT,
    "in_delivery_office": ParcelStatus.IN_TRANSIT,
    "arrival_departure_from_hub": ParcelStatus.IN_TRANSIT,
    "in_delivery_courier": ParcelStatus.OUT_FOR_DELIVERY,
    # Return/failure codes — named unambiguously in the API's own docs
    # (destinationType's full vocabulary at ee.econt.com/services/Shipments/;
    # "return"/"destroy" are literally the only two failure values the same
    # docs give for lastProcessedInstruction, alongside "forward").
    "return": ParcelStatus.RETURNING,
    "is_returning_to_sender": ParcelStatus.RETURNING,
    "returned_to_sender": ParcelStatus.RETURNING,
    "destroy": ParcelStatus.PROBLEM,
    "failed_delivery": ParcelStatus.PROBLEM,
    # Deliberately unmapped — the docs list these values but not what they
    # mean, and a wrong guess is worse than one more "unknown":
    # "instruction" (delivery instruction vs. hold vs. redirect?),
    # "first_try"/"second_try" (failed attempt that could still resolve
    # several ways), "redirect" (redirect to where?), "in_pickup_courier"
    # (mirrors "in_pickup_office" below — sender-side pickup, not
    # necessarily in-transit).
    #
    # "in_pickup_office" was briefly mapped to at_pickup_point on name alone;
    # the full vocabulary above shows it paired with "in_pickup_courier" the
    # same way "in_delivery_office"/"in_delivery_courier" are paired — i.e.
    # it more likely describes the *sender*-side pickup leg, not a receiver
    # pickup point. Reverted until a real payload settles it.
}
_SOFIA = ZoneInfo("Europe/Sofia")

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Econt status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a carrier status code to a canonical :class:`ParcelStatus`.

    ``None`` (a not-yet-scanned parcel) reports ``unknown`` silently; an
    unrecognised code reports ``unknown`` with a one-shot warning.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return ParcelStatus.UNKNOWN


def map_event_status(code: str | None) -> ParcelStatus | None:
    """Map a history entry's ``destinationType`` to a canonical status, or ``None``.

    Unmapped codes keep ``status: null`` on the history entry (rather than
    ``unknown``, so a consumer can tell "no mapping" from "mapped to unknown")
    and warn once, reusing the parcel-status one-shot set.
    """
    if not code:
        return None
    mapped = _EVENT_STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def format_dimensions(
    length: float | None, width: float | None, height: float | None
) -> dict[str, Any] | None:
    """Return the canonical ``dimensions`` dict, or ``None`` when incomplete.

    Units contract: **centimetres**, with ``text`` pre-formatted as
    ``"L x W x H cm"`` (integer values, lowercase ``x``) so dashboards can show
    a dimension without doing their own formatting. Convert before calling if
    the carrier reports millimetres or inches.
    """
    if length is None or width is None or height is None:
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{round(length)} x {round(width)} x {round(height)} cm",
    }


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from the carrier's event list.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. ``raw_status`` is the carrier's own text, or
    its event code when the API has no human-readable text. Sorted oldest →
    newest and capped to the most recent ``max_events``.

    """
    parseable: list[tuple[datetime, dict]] = []
    unparseable: list[dict] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        timestamp = to_iso_timestamp(event.get("time"))
        if not timestamp:
            continue
        entry = {
            "timestamp": timestamp,
            "status": map_event_status(event.get("destinationType")),
            "raw_status": (
                event.get("destinationDetailsEn")
                or event.get("destinationDetails")
                or event.get("destinationType")
            ),
        }
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in parseable] + unparseable
    return ordered[-max_events:]


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def _moment(value: Any, zone: tzinfo) -> tuple[datetime, bool, str] | None:
    """Return ``(aware datetime, date_only, text)`` for a carrier time, or ``None``.

    A naive time or a bare date gets ``zone``; an aware time keeps its offset
    and, when it came in as a string, its own spelling.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        moment = datetime.combine(value, time.min, tzinfo=zone)
        return moment, True, moment.isoformat()
    elif isinstance(value, str) and value:
        try:
            if len(value) == 10:
                moment = datetime.combine(
                    date.fromisoformat(value), time.min, tzinfo=zone
                )
                return moment, True, moment.isoformat()
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo:
            return parsed, False, value
    else:
        return None
    moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)
    return moment, False, moment.isoformat()


def _end_of_day(moment: datetime, zone: tzinfo) -> datetime:
    local = moment.astimezone(zone)
    return datetime.combine(local.date(), time(23, 59, 59), tzinfo=zone)


def planned_window(
    start: Any, end: Any, *, zone: tzinfo
) -> tuple[str | None, str | None]:
    """Return ``(planned_from, planned_to)`` in the canonical window shape.

    ``start`` and ``end`` are ISO strings, dates or datetimes, or ``None``; an
    epoch number must be converted first (see ``to_iso_timestamp``). A window
    keeps both ends. One moment with a time ends at ``23:59:59`` the same local
    day; a date covers ``00:00:00`` to ``23:59:59``; two dates run from the
    first day's start to the last day's end. Equal values are one moment,
    reversed values are swapped, and ``planned_to`` is never set without
    ``planned_from``. ``zone`` is the carrier's own zone: it dates naive times
    and bare dates and decides which day a moment ends on, so a ``Z`` moment
    still ends on the carrier's local day. When nothing is left of that day
    after the moment, there is no ``planned_to``.
    """
    first = _moment(start, zone)
    last = _moment(end, zone)
    if first is None:
        first, last = last, None
    if first is None:
        return None, None

    def closing(moment: tuple[datetime, bool, str]) -> datetime:
        return _end_of_day(moment[0], zone) if moment[1] else moment[0]

    if last is not None and closing(last) < first[0]:
        first, last = last, first
    if last is not None and closing(last) == first[0]:
        last = None

    if last is None:
        end_of_day = _end_of_day(first[0], zone)
        return first[2], end_of_day.isoformat() if end_of_day > first[0] else None
    return first[2], closing(last).isoformat() if last[1] else last[2]


_NO_WINDOW_STATUSES = frozenset(
    {ParcelStatus.AT_PICKUP_POINT, ParcelStatus.RETURNING, ParcelStatus.DELIVERED}
)


def planned_for_status(
    status: ParcelStatus, planned_from: str | None, planned_to: str | None
) -> tuple[str | None, str | None]:
    """Empty the delivery window once the parcel is at its destination or done."""
    if status in _NO_WINDOW_STATUSES:
        return None, None
    return planned_from, planned_to


def is_pickup(
    route_flag: bool | None,
    status: ParcelStatus,
    event_statuses: Iterable[ParcelStatus | None] = (),
) -> bool:
    """Whether the delivery route ends at a pickup point.

    The carrier's own route flag wins; otherwise the parcel having reached
    ``AT_PICKUP_POINT`` at any point counts, so the value survives collection.
    """
    if route_flag:
        return True
    return status is ParcelStatus.AT_PICKUP_POINT or any(
        event is ParcelStatus.AT_PICKUP_POINT for event in event_statuses
    )


def _office_delivery(raw: dict) -> bool | None:
    """Whether the payload's delivery type is an office/locker rather than a door."""
    kind = raw.get("deliveryType")
    if not isinstance(kind, str) or not kind.strip():
        return None
    return kind.strip().lower() != "door"


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are
    the contract**: every carrier in the suite returns exactly these, in this
    order, and the aggregator and cross-carrier dashboards depend on it. Set a
    key to ``None`` when the carrier does not expose it — never omit it.

    Rules worth keeping when you rewrite the body:

    * ``status`` is canonical, ``raw_status`` is the carrier's own text.
    * A delivered parcel has ``delivered_at`` set and ``planned_from`` /
      ``planned_to`` cleared — the ETA is meaningless once it has arrived.
    * ``planned_to`` is ``None`` for a point estimate; only fill it when the
      carrier genuinely reports a *window*.
    * ``weight`` is kilograms, ``dimensions`` centimetres (see
      :func:`format_dimensions`).
    * ``history`` is ``None`` when the option is off — the key still exists.
    """
    tracking_code = raw.get("shipmentNumber")
    raw_weight = raw.get("weight")
    # 0 is a placeholder for "not weighed", not a real weight — every live
    # sample seen so far reports it that way. Any positive value is passed
    # through as-is; the API documents kilograms.
    weight = (
        raw_weight if isinstance(raw_weight, (int, float)) and raw_weight > 0 else None
    )
    raw_status = raw.get("shortDeliveryStatusEn") or raw.get("shortDeliveryStatus")
    status = map_parcel_status(raw_status)
    if raw.get("deliveryTime") is not None and status is not ParcelStatus.RETURNING:
        status = ParcelStatus.DELIVERED
    delivered = status is ParcelStatus.DELIVERED
    planned_from = planned_to = None
    expected_date = raw.get("expectedDeliveryDate")
    if expected_date:
        # expectedDeliveryDate is epoch milliseconds, same as sendTime/deliveryTime
        # — not an ISO date string. Only the date component is meaningful.
        expected_dt = parse_iso(to_iso_timestamp(expected_date))
        if expected_dt is not None:
            planned_from, planned_to = planned_window(
                expected_dt.astimezone(_SOFIA).date(), None, zone=_SOFIA
            )
    planned_from, planned_to = planned_for_status(status, planned_from, planned_to)
    pickup = is_pickup(
        _office_delivery(raw),
        status,
        (
            map_event_status(event.get("destinationType"))
            for event in raw.get("trackingEvents") or []
            if isinstance(event, dict)
        ),
    )

    return {
        "carrier": "Econt",
        "barcode": tracking_code,
        "sender": None,
        "receiver": None,
        "contents": None,
        "status": status,
        "raw_status": raw_status,
        "delivered": delivered,
        "delivered_at": to_iso_timestamp(raw.get("deliveryTime"))
        if delivered
        else None,
        "planned_from": planned_from,
        "planned_to": planned_to,
        "pickup": pickup,
        "pickup_point": None,
        "url": tracking_url(tracking_code),
        "weight": weight,
        "dimensions": None,
        "history": build_history(raw.get("trackingEvents"))
        if include_history
        else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
