# MeteoSwiss (Koneho) — Home Assistant integration

A Home Assistant custom integration for Swiss weather data from
MeteoSwiss: place forecasts by postcode, plus live SwissMetNet station
observations.

**Clean-room implementation.** This integration was written from scratch
in November 2026 against the observed behaviour of the public
MeteoSwiss endpoints. It is not a fork of, and shares no code with, any
existing MeteoSwiss integration or client library.

**Source: MeteoSwiss** (attribution as required by the data terms).

## Why it exists

The MeteoSwiss app API (`app-prod-ws.meteoswiss-app.ch`) answers its
forecast endpoints with JSON *or* XML (`application/xhtml+xml`),
unpredictably per postcode and cache state, and the Accept header does
not control it. Clients that assume JSON break when a postcode flips to
XML — as happened broadly in October 2026. This integration's client
sniffs every payload and parses **both** formats into one data model,
so a format flip upstream is a non-event.

## Data sources

| Source | Use |
| --- | --- |
| `v2/plzDetail?plz={PLZ}00` (app API) | Primary place payload: current weather, 8-day forecast, full 8-day hourly graph (temperature min/mean/max, wind + gusts incl. q10/q90 bands, 3-hourly icons and precipitation probability, 1h/10min precipitation incl. min/max, sunshine, sunrise/sunset), warnings, klimaGraph climate normals |
| `v2/forecast?plz={PLZ}00&graph_startLowResolution=true&warning=true` (app API) | Fallback place payload if plzDetail fails |
| `data.geo.admin.ch/.../VQHA80.csv` + `VQHA98.csv` | Official SwissMetNet actual values (10-minute station observations, `-` = missing) |

No API key. Polling interval: 15 minutes.

## Installation

### Manual

Copy `custom_components/koneho_meteoswiss/` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

### HACS (custom repository)

In HACS → Integrations → ⋮ → Custom repositories, add
`https://github.com/koneho-ai/ha-meteoswiss` as an *Integration*, then
install "MeteoSwiss (Koneho)" and restart Home Assistant.

## Configuration

Settings → Devices & Services → Add Integration → **MeteoSwiss (Koneho)**:

- **Place name** (optional) — defaults to `MeteoSwiss <postcode>`.
- **Postcode** — 4-digit Swiss PLZ (e.g. `8048` for Zürich Altstetten,
  `8808` for Pfäffikon SZ). Validated with a live fetch during setup.
- **SwissMetNet station code** (optional) — 3-letter code such as
  `UEB` (Uetliberg), `SMA` (Zürich Fluntern) or `KLO` (Zürich Kloten).
  When set, station observation sensors are created as well.

One config entry = one postcode (+ optional station). Add the
integration again for more places.

## Entities created

Per place:

- **Weather entity** — current temperature and condition (MeteoSwiss
  symbol code mapped to HA conditions; night variants 100+ handled,
  101 = clear-night), `async_get_forecasts` daily (8 days: high/low,
  precipitation, max precipitation probability, max wind/gust,
  sunrise/sunset) and hourly (192 h: temperature mean/min/max,
  precipitation, precipitation probability, wind, gusts, direction,
  3-hourly condition). Extra attributes carry the *complete* payload:
  every graph series, all forecast-day fields, warnings overview and
  the klimaGraph.
- **Sunshine today** (h; minutes and the full 1h series in attributes)
- **Precipitation today** (mm; today's min/max sums and the 1h + 10 min
  series incl. min/max variants in attributes)
- **Max precipitation probability today** (%)
- **Max wind today** (km/h; today's gust max and all wind/gust/
  direction series incl. q10/q90 bands in attributes)
- **Sunrise** / **Sunset** (timestamp; full 8-day series in attributes)
- **Current icon code** (diagnostic; raw MeteoSwiss symbol + V2 code,
  3-hourly icon series in attributes)
- **Climate normals** (diagnostic; state = this month's temperature
  normal, attributes = full klimaGraph: monthly abs/norm/deviation
  for temperature, precipitation and sunshine)
- **Forecast graph data** (diagnostic; state = graph start, attributes
  = every graph series exactly as delivered)
- **Warnings** binary sensor (on = a warning is active; attributes =
  full warning records incl. text, level, type, validity, links, and
  the warnings overview)

Per station (when a station code is configured), one sensor per CSV
column present for that station — up to: temperature, precipitation
(10 min), sunshine duration (10 min), global radiation, humidity, dew
point, wind direction, wind speed, wind gust, station pressure, QFF,
QNH, 850/700 hPa pressures, and the tower instruments (wind direction,
wind speed, gust, temperature, humidity, dew point). Columns reporting
`-` show as unavailable values rather than breaking the station.

## Icon → condition mapping

Based on the MeteoSwiss weather-symbol set (day codes 1–35, night =
day + 100), as documented e.g. in the Meteomatics "General Weather
State" symbol table: 1 clear, 2–3 partly cloudy, 4 cloudy, 5 rain,
6 rain/snow, 7 snow, 8 rain shower, 9 snow shower, 10 rain/snow
shower, 11–12 fog, 13 freezing rain (→ rainy), 14 thunderstorm,
15 drizzle (→ rainy), 16 sandstorm (→ windy). Unmapped codes yield no
condition but remain visible on the icon-code sensor.

## Development

The parsing core (`client.py`, `models.py`, `icons.py`) has no Home
Assistant dependency and is covered by offline pytest tests using live
fixtures captured on 2026-11-06:

```bash
python -m pytest tests/
```

## License / attribution

Weather data: **Source: MeteoSwiss**. Symbol graphics are MeteoSwiss
property and are not redistributed; only the symbol numbers are used.
