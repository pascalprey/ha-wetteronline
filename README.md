# WetterOnline for Home Assistant (unofficial)

An **unofficial** custom integration that reads the weather data from the public
location page of [wetteronline.de](https://www.wetteronline.de) and exposes it as
a `weather` entity plus a rich set of sensors in Home Assistant.

Unlike most existing WetterOnline integrations (which only embed the rain-radar
map), this one provides the **full** forecast dataset: current conditions, ~48 h
hourly and up to 14 days daily — including pressure, humidity, dew point,
apparent temperature, UV index, pollen and severe-weather warnings.

> [!WARNING]
> **Unofficial, no warranty.** This project is not affiliated with WetterOnline
> GmbH. It reads the publicly served web page (scraping). WetterOnline offers no
> free API and its content is copyright protected. Use this **privately only**,
> at a low polling frequency, and do not redistribute its data/images. A page
> redesign on WetterOnline's side can break parsing. For a legally clean, stable
> German source, consider **DWD** (Deutscher Wetterdienst, open data) or
> **Open-Meteo**.

## Features

- **`weather.<location>` entity** with current values and forecasts:
  - current: temperature, apparent temperature, dew point, humidity, pressure,
    wind/gusts/bearing, visibility, UV index, condition
  - **hourly** (~48 h) and **daily** (up to 14 days) with temperature, apparent
    temperature, humidity, pressure, wind/gusts, precipitation probability,
    precipitation amount (mm, daily) and UV index (daily)
- **Additional sensors** per location:
  - temperature, apparent temperature, dew point, humidity, pressure,
    wind/gusts/bearing, visibility, UV index, precipitation probability
  - water temperature (nearby lake/sea, if any), thunderstorm probability
  - sunrise/sunset, sunshine hours today, today's high/low, precipitation today
  - **pollen** (14 allergens, burden 0–3, 7-day forecast as an attribute)
  - **severe-weather warnings** (count + details as an attribute)
  - optional (disabled by default): solar elevation, pressure tendency, smog
    level, day length, moon phase, moonrise/moonset, precipitation type,
    significant weather, today's prose forecast text

## Data source & limits

The data comes from `https://www.wetteronline.de/wetter/<location>`, more
precisely from the embedded Angular state (`ng-state`) that mirrors the responses
of WetterOnline's backend API — a single GET returns everything. **Not
available:** there is no numeric cloud-cover percentage in the dataset (only the
condition/symbol and sunshine hours), and precipitation amount in mm is only
available daily, not hourly.

The prose forecast text is WetterOnline's copyrighted editorial content; the
corresponding sensor is therefore **disabled by default**.

## Installation

### HACS (recommended)

1. HACS → ⋮ → *Custom repositories* → add this repository as an *Integration*.
2. Install "WetterOnline", then restart Home Assistant.

### Manual

Copy `custom_components/wetteronline/` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

*Settings → Devices & Services → Add Integration → "WetterOnline"*, then type a
location (e.g. "Neustadt"). If the name is ambiguous, a picker lets you choose the
right place (region shown in brackets). Add multiple locations as separate
entries. The polling interval is adjustable via the entry's *Configure* button
(default 30 min, minimum 10 min).

## Development

The parser (`custom_components/wetteronline/api.py`) is intentionally free of
Home Assistant imports and can be tested offline against a saved HTML page (see
`tests/`).

## License

MIT — see [LICENSE](LICENSE).
