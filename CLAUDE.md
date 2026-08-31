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

## Options and reloads

For code-based carriers, the options flow starts with exactly `Pakketten` and
`Instellingen`. `Pakketten` is one editable multi-code list; `Instellingen` is
a flat form. Changes apply without a restart. Two models, **do not mix them**:
- **Account-less carriers** (the default) apply changes live: an update listener
  calls `async_request_refresh()`, so added/removed parcel sensors appear
  immediately (this is also the resume path after polling has fully
  suspended — see "Dynamic polling" below).
- **Account-based carriers** call `async_schedule_reload` on submit and register
  **no** update listener. Combining a listener with a reload-on-update flow is
  deprecated, an error in HA 2026.12+.

## Dynamic polling

There is no user-facing polling interval — this is a deliberate suite-wide
choice, not a gap. `coordinator.py` recomputes `update_interval` at the end of
every refresh:

- **Quiet window:** no polling 00:00–06:00 local time, except two daily
  anchors (~00:00 and ~06:00) for overnight / end-of-day catch-up.
- **Tiers while polling:** *hot* (15 min) when a tracked, not-yet-delivered
  parcel is `out_for_delivery` within an hour of its `planned_from` (or has no
  `planned_from` at all); *mid* (45 min) for anything else still in flight —
  `problem`/`returning` included, deliberately not hot. Account-based carriers
  never fully stop even with nothing hot or in transit: the mid-tier poll is
  also how a new shipment gets discovered.
- **Full stop (account-less carriers only):** `update_interval = None` when
  nothing is tracked or every tracked parcel is delivered. Resumes the moment
  a parcel is added back, via the options-flow refresh above.
- **Stagger:** a small, stable per-install offset (hash of the config entry
  id) is added to every computed interval so installs don't all hit an anchor
  or tier boundary at the same second.
- **429 backoff:** a 429 anywhere in a poll raises `UpdateFailed` with
  `retry_after` — the carrier's own `Retry-After` header if present, otherwise
  an exponential backoff tracked per-coordinator. `api.py`'s
  `…ApiError.status_code` / `.retry_after` carry this from the HTTP layer.

A carrier that genuinely throttles or soft-bans traffic harder than the 429
backoff handles is a documented, local divergence from this in that one
repo's own `CLAUDE.md` — not a generator flag.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`, account-less only) | no |

`parcels.py` is deliberately free of I/O and HA objects so the per-carrier part
stays unit-testable without Home Assistant. Config: `ConfigEntry.runtime_data`
(typed, no `hass.data`), `PARALLEL_UPDATES = 0`, coordinator takes
`config_entry=entry`. `aiohttp.ClientError` is caught **per parcel** in the gather
loop (one bad parcel doesn't fail the poll) but **not** around the whole update
(the coordinator wraps that). Entities: `has_entity_name` + `translation_key`,
`icons.json`, translated units, `_attr_attribution`, `_unrecorded_attributes` on
anything with a parcel list or `raw`. Over-redact diagnostics — they get pasted
into public issues.

## Running tests

```
python -m pytest tests/ --cov=custom_components.econt
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in your own private research notes, never in
this repo.
