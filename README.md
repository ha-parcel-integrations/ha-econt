# Econt Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-econt.svg)](https://github.com/ha-parcel-integrations/ha-econt/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Econt](https://www.econt.com/) parcels in Bulgaria. No account is needed: add each numeric shipment number yourself.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Econt parcels by tracking code — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), the carrier's own status text, the expected delivery window and a tracking deep-link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the expected delivery windows
- `econt.track_parcel` / `econt.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.12 or newer
- An Econt parcel and its tracking code (from the shipping
  confirmation email or the missed-delivery card) — no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-econt` as an **Integration**.
3. Install **Econt** and restart Home Assistant.

### Manual

Copy `custom_components/econt` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Econt**. There is nothing to fill in: the hub is created immediately (Econt tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`econt.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking code is on your shipping confirmation email or the missed-delivery card.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

Polling isn't one of these settings: the integration polls on a dynamic,
status-driven schedule (quiet overnight window, faster when a parcel is out
for delivery, stopped entirely once nothing is left to track) with nothing to
configure. See [CLAUDE.md](CLAUDE.md) for the details.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Econt → ⋮ → Delete**. Nothing is stored on Econt's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.econt_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.econt_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.econt_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.econt_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.econt_last_successful_update` | Diagnostic: when Econt was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `delivered` | Delivered |
| `unknown` | Not yet scanned, or a status we have not mapped yet |

The carrier's own human-readable text is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Econt device):

| Event | When |
|---|---|
| `econt_parcel_registered` | A new parcel appears in the active list |
| `econt_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `econt_parcel_delivered` | A parcel is delivered |
| `econt_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `econt.track_parcel` | `tracking_code` | Start tracking a parcel |
| `econt.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.econt: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Econt has not scanned it yet (their API answers `not_found` until the first scan), or the code is wrong. It will pick up automatically once scanned.
- **A status logs "Unrecognised Econt status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-econt/issues/new) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as the Econt consumer website. It is not affiliated with, endorsed by, or supported by Econt.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
