# Working in this repository

Home Assistant custom integration for **Econt** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| change which optional field this carrier populates vs. always returns `None` | Update `const.py`'s `CAPABILITIES` in the same commit — it feeds the comparison table on the docs site, so a field that starts (or stops) coming back non-null and isn't reflected there is a wrong claim on the website, not just a stale comment. If this carrier has more than one backend (a country-specific transport, not just a config option) with genuinely different field support, `CAPABILITIES` should be a `CAPABILITIES_BY_VARIANT` dict instead — one frozenset per backend, so a field only some backends populate doesn't get silently intersected away or overclaimed for the rest |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Structure, options flow, dynamic polling and module layout are suite-wide**
and identical in every carrier — the authoritative spec is
[`ha-carrier-template/scaffold/CLAUDE.md`](https://github.com/ha-parcel-integrations/ha-carrier-template/blob/main/scaffold/CLAUDE.md).
This repo follows it exactly.

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).
- **If this carrier can reach `ParcelStatus.AT_PICKUP_POINT` from a real raw
  status/code**, it needs an `awaiting_pickup` sensor — see *Parcel contract*
  in `CONVENTIONS.md`. Say "pickup point", not "ServicePoint"/"parcel
  shop"/"locker", for the generic concept. `ha-dhl-nl`, `ha-dpd`, `ha-gls`,
  `ha-inpost` are reference implementations; `econt` here does not
  demonstrate it yet.

## Carrier-specific notes

**API mechanics live in `carrier-research/econt/api/` (private research repo)** —
endpoints, envelope and status vocabulary belong there, never in this repo.

Econt is code-based and unauthenticated. The coordinator makes one batch read
per refresh and retains cached data if that read fails. Numeric shipment
numbers are trimmed but never length-constrained; one malformed value must not
poison the complete batch.

**Two separate, unrelated status vocabularies, two separate maps — do not
merge them.** `_STATUS_MAP` maps the parcel's overall `shortDeliveryStatusEn`
(`"Delivered"`, `"Arrival-Departure from HUB"`, `"Awaiting delivery to
Econt"`, plus one confirmed Cyrillic value — see below). `_EVENT_STATUS_MAP`
maps a single history event's `destinationType` — a routing-leg code, not the
same vocabulary and not necessarily equal to the parcel's overall status at
that point in time (a live sample showed the last event as
`courier_direction` while the parcel's own status read `"Arrival-Departure
from HUB"`). Growing either map from a real payload is fine; do not let a
value from one leak into the other's dict just because both happen to come
from the same API. Unmapped values in both warn once and safely remain
`unknown` — that one-shot warning is how each map grows, and it now also
fires from history events (`build_history` calls `map_event_status` on every
event; it used to hardcode `status: null` and never call it at all).

The service's own docs (`ee.econt.com/services/Shipments/`, the model page,
not a real endpoint) give the full `destinationType` vocabulary: `client,
courier, courier_direction, office, first_try, second_try, instruction,
redirect, return, destroy, failed_delivery, in_pickup_courier,
in_pickup_office, in_delivery_courier, in_delivery_office,
arrival_departure_from_hub, is_returning_to_sender, returned_to_sender`. Every
value currently in `_EVENT_STATUS_MAP` is drawn from that list, but the docs
give no per-value description — only `"return"`/`"destroy"`/`"forward"` are
independently pinned down, as the only three values the same docs allow for
`lastProcessedInstruction`. `"instruction"`, `"first_try"`, `"second_try"`,
`"redirect"`, and `"in_pickup_courier"`/`"in_pickup_office"` stay unmapped —
a failed-attempt or redirect code could resolve several ways, and
`in_pickup_*`/`in_delivery_*` read as a sender-side/receiver-side pair, which
argues against `in_pickup_office` meaning a receiver pickup point (an
earlier, reverted guess — don't re-add it without a real payload).

The docs' `shortDeliveryStatusEn` list (`'Prepared in eEcont'`, `'Accepted in
Econt'`, `'In route'`, `'In courier'`, `'In pick up courier'`, `'Accepted in
office'`, `"In delivery courier's office"`, `'Arrived in office'`,
`'Arrival departure from hub'`, `'Delivered'`, `'Cancelled after sending'`,
`'Cancelled before sending'`, `'Is returning to sender'`, `'Returned to
sender'`) does **not** reliably match live casing/punctuation — a live
sample read `"Arrival-Departure from HUB"` (hyphen, different case) where the
docs say `'Arrival departure from hub'`, and `"Awaiting delivery to Econt"`
(confirmed live) isn't in the docs list at all. Don't add `_STATUS_MAP`
entries from this list's literal text — confirm the exact live string first,
same as every other entry in that map.

Event-level `out_for_delivery`/`returning`/`problem` mappings above are
history-only — they do not feed `_STATUS_MAP`, so they don't change the
parcel's overall `status` and don't by themselves trigger the suite's "needs
an `awaiting_pickup` sensor" rule. That rule only applies once a real
`shortDeliveryStatusEn` value is confirmed to mean pickup-ready.

`shortDeliveryStatusEn` is usually reliably English (`"Delivered"`,
`"Arrival-Departure from HUB"`) but confirmed to have at least one translation
gap: a canceled-before-dispatch shipment reported it back in Cyrillic
(`"Анулирана преди изпращане"`), which is why that literal string is a
`_STATUS_MAP` key rather than something derived generically — don't build a
general Cyrillic-fallback mechanism off one observed gap.

Date-only expected delivery data (`expectedDeliveryDate`, epoch milliseconds
like the other timestamp fields — not an ISO string, a real bug until this was
caught against a live payload) is published as a Europe/Sofia all-day window.
`weight` passes `raw.weight` through whenever it is a positive number — every
live sample so far reports `0`, a placeholder for "not weighed" rather than a
real value, so it still normalises to `None` in
practice. Sender/receiver and pickup point deliberately remain `None` until a
live payload establishes a safe canonical meaning. Diagnostics redact event
locations and client names.

## Running tests

```
python -m pytest tests/ --cov=custom_components.econt
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in your own private research notes, never in
this repo.
