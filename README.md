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
| `ogd-local-forecasting_meta_point.csv` + `ch.meteoschweiz.messnetz-automatisch_fr.csv` | Point and station coordinates for automatic nearest-station selection (cached 24 h) |
| `ch.meteoschweiz.ogd-pollen` station metadata CSV (data.geo.admin.ch) + per-plant `messwerte-pollen-{plant}-1h` stations-table products | Pollen stations (15, incl. coordinates) and current per-plant concentrations (cached 1 h) |

No API key. Polling interval: 15 minutes (pollen is fetched at most
hourly via the client-side cache).

The client sends an `Accept-Language` header derived from the Home
Assistant language (normalised to de/fr/it/en, `de-CH` → `de`,
fallback English), so warning and forecast texts come back localised;
the same language selects the pollen product files.

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
- **SwissMetNet station** — a dropdown of all stations by name
  (e.g. "Uetliberg (UEB)", "Zürich / Fluntern (SMA)"), headed by
  **Automatic**: the nearest station is selected automatically
  (haversine distance from the postcode point to the stations in the
  current SwissMetNet data. Within 10 km beyond the nearest station's
  distance, a station reporting the core set — temperature, humidity,
  wind, and station pressure or QNH — is preferred; failing that, a
  temperature-reporting station is preferred). A manually picked
  station always wins. If the station list cannot be fetched during
  setup, the field falls back to a free-text 3-letter code.
- **Pollen station** — same dropdown pattern as the weather station,
  over the ~15 pollen stations; **Automatic** (default) picks the
  nearest pollen station to the postcode point. The network is sparse
  by design, so "nearest" can be tens of kilometres away.
- **Warning sensor pairs** — 0–5 (default 1). For each rank up to N, a
  pair of sensors exposes the Nth most severe *active* warning (see
  Entities). 0 disables the rank sensors.
- **Update interval** — minutes between data updates (1–180,
  default 15).

One config entry = one postcode (+ optional station). Add the
integration again for more places. Existing entries can be changed
(name, postcode, station, update interval) via **Reconfigure** on the
integration — setting the station back to Automatic re-enables
automatic selection. If a manually picked station stops appearing in
the SwissMetNet data for several consecutive updates, a Repairs issue
is raised (and cleared automatically when it reports again).

## Entities created

Per place:

- **Weather entity** — current temperature and condition (MeteoSwiss
  symbol code mapped to HA conditions; night variants 100+ handled,
  101 = clear-night). Current humidity, pressure (QNH, falling back
  to station pressure), dew point, wind speed/gust and wind bearing
  are taken from the station observation (manual or auto-selected),
  since the place payload only carries icon + temperature.
  `async_get_forecasts` daily (8 days: high/low,
  precipitation, max precipitation probability, max wind/gust,
  sunrise/sunset) and hourly (from the current hour to the end of the
  192 h window: temperature mean/min/max,
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
- **Wind speed** / **Wind gust** (forecast value for the current hour;
  full hourly series incl. q10/q90 bands in attributes)
- **Wind direction** (forecast value for the current 3-hour block;
  full 3-hourly series in attributes)
- **Sunrise** / **Sunset** (timestamp; full 8-day series in attributes)
- **Current icon code** (diagnostic; raw MeteoSwiss symbol + V2 code,
  3-hourly icon series in attributes)
- **Climate normals** (diagnostic; state = this month's temperature
  normal, attributes = full klimaGraph: monthly abs/norm/deviation
  for temperature, precipitation and sunshine)
- **Forecast graph data** (diagnostic; state = graph start, attributes
  = every graph series exactly as delivered, plus the effective
  station code, whether it was auto-selected, and its distance)
- **Warnings** sensor — human-readable state: `None`, or
  `Level <n>: <type>` for the highest active warning (e.g.
  `Level 2: Forest fire`). Attributes carry the warning count, the
  full records, all warning texts joined (`warnings_text`), the type
  codes and names, the max level and the validity start — this is
  where the warning *text* lives. Only warnings still in force count:
  the API keeps recently ended warnings in the payload, and records
  whose `validTo` has passed are filtered out of the summary, the
  rank sensors and the binary sensor (the raw payload records remain
  on the forecast-graph sensor).
- **Warning <n> type** / **Warning <n> level** sensors — per-rank
  pairs (count configurable, default 1 pair). Rank 1 is the most
  severe active warning. The type sensor's state is the warning type
  name, with attributes `level` (hazard name), `level_numeric`,
  `text`, `html_text`, `valid_from`, `valid_to`, `links`, `outlook`
  and `icon_color` (gray ≤ level 1, amber at 2, red above). The level
  sensor's state is the hazard name (`No danger`, `No or minimal
  hazard`, `Moderate hazard`, `Significant hazard`, `Severe hazard`,
  `Very severe hazard`) with `numeric` and `icon_color` attributes.
- **Warnings active** binary sensor (on = an unexpired warning is
  active; attributes = full warning records incl. text, level, type,
  validity, links, and the warnings overview)

Per station (configured manually, or the auto-selected nearest
station), sensors are created only for CSV columns that have a value
in that station's current row — up to: temperature, precipitation
(10 min), sunshine duration (10 min), global radiation, humidity, dew
point, wind direction, wind speed, wind gust, station pressure, QFF,
QNH, 850/700 hPa pressures, and the tower instruments (wind direction,
wind speed, gust, temperature, humidity, dew point). Columns whose
current value is `-` do not create sensors; on upgrade, stale station
sensor registry entries for columns without current data are removed
automatically.

## Pollen

When pollen data is available for the entry's pollen station (see
Configuration), each place also gets:

- **Pollen <plant>** — current concentration in pollen/m³ for each of
  the seven allergenic plants: birch, grasses, alder, hazel, beech,
  ash and oak (measurement, no device class — HA has no pollen device
  class).
- **Pollen <plant> level** — the official MeteoSwiss load class for
  that plant: `None` (0 pollen/m³), `Low`, `Medium`, `Strong` or
  `Very Strong`, from the per-plant thresholds (low/medium/strong in
  pollen/m³: birch 10/70/300, grasses 20/50/150, alder 10/70/250,
  hazel 10/70/250, beech 50/130/400, ash 10/100/350, oak 50/130/400).
  Attributes carry the raw concentration and an `icon_color`
  (gray / amber for Medium / red for Strong and above).
- **Pollen measurement** — timestamp of the station's latest pollen
  measurement.

Pollen is fetched from the public OGD metadata CSV and the per-plant
stations-table products on the MeteoSwiss website, cached for one
hour inside the client. A failed pollen fetch never fails the weather
update — the pollen sensors simply go unavailable for that cycle.

## Precipitation alignment note

The hourly graph carries three precipitation series whose relationship
was investigated against live payloads on 2026-11-06 (postcodes 8808
and 8048, plus the captured fixture):

- `precipitation1h` starts exactly at the graph's
  `startLowResolution` timestamp (its offset from the window start
  equals `startLowResolution − start` in hours: 20 h and 22 h in the
  samples, with 172/170 values against 192 temperature hours). In
  every observed payload that anchor coincides with aligning the
  series to the **end** of the window, which is what the integration
  does.
- `precipitation10m` values behave as an hourly mean/rate, not as
  10-minute depths: chunk *sums* overshoot the day's precipitation by
  ~6×, while chunk *means* land close to `precipitation1h` (the
  leftover partial chunk past `startLowResolution` matched
  `precipitation1h[0]` exactly in the live sample). However, the
  totals do not reconcile exactly with either `precipitation1h` or
  the daily `precipitation` sums across the whole window (the daily
  list appears to come from a different model run), so no 10-minute
  reconstruction is shipped: the hourly forecast keeps using the
  end-aligned `precipitation1h`, whose anchoring is validated, and
  the raw 10-minute series remains available verbatim in the
  precipitation sensor attributes.

## Icon → condition mapping

Based on MeteoSwiss's published weather-symbol table: day symbols
1–42 and night symbols 101–142, each mapped to the HA condition for
that symbol's situation in the table (e.g. 5 "very cloudy" → cloudy,
14 "very cloudy, light rain" → rainy, 20 "very overcast with rain" →
pouring). Night symbols mirror the day symbols except 101
(clear-night) and 126 (cloudy). Codes outside the published table
yield no condition but remain visible on the icon-code sensor.

## Changelog

- **0.3.0** — Pollen: per-plant concentration + load-level sensors
  and a measurement timestamp for the nearest (or a configured)
  pollen station, from the public OGD/stations-table products,
  cached hourly. Warnings: expired warnings (`validTo` passed) are
  filtered out of the summary/rank/binary sensors, active warnings
  are sorted by level, and configurable per-rank type+level sensor
  pairs were added (default 1 pair). Localisation: the client sends
  `Accept-Language` from the HA language (de/fr/it/en), which also
  selects the pollen product language. Hourly forecast now starts at
  the current hour (past hours dropped) and the model carries
  per-hour sunshine minutes (not forwarded to HA — the Forecast
  dictionary has no sunshine key in HA 2026.11; sunshine stays on the
  Sunshine today sensor and the model data). Current condition
  prefers the V2 icon; the API's 32767 "no data" sentinel is treated
  as missing for current temperature/icons. A failed station-CSV
  fetch no longer fails the whole update (forecast still updates,
  station is empty for that cycle). Station pickers show
  "– N km away" distance labels when the HA home location is known.
  CI: hassfest, HACS and pytest workflows added. See the
  precipitation alignment note above for the (unchanged, validated)
  hourly precipitation anchoring.

- **0.2.2** — Condition mapping replaced with MeteoSwiss's published
  symbol table (day codes 1–42, night codes 101–142; previously only
  ~22 codes were mapped and several differed, e.g. 5 is now cloudy,
  14 rainy, 20 pouring). Update interval is configurable per entry
  (1–180 minutes, default 15). The station field in the config and
  reconfigure flows is now a dropdown of station names ("Name
  (CODE)") with Automatic first, falling back to the free-text code
  field if the station list cannot be fetched. A Repairs issue is
  raised when a manually configured station is missing from the
  SwissMetNet data for 3 consecutive updates, and cleared when it
  reports again.

- **0.2.1** — Station sensors are created only for columns with a
  current value (and stale registry entries for missing columns are
  removed on setup); automatic station selection prefers a nearby
  station with the core temperature/humidity/wind/pressure set;
  climate normals expose this month's normal temperature; and the
  weather entity's station humidity is exposed through HA's
  `humidity` property. Also fixes `weather.get_forecasts`, which
  returned `unknown_error` because the entity implemented a method
  HA never calls — it now implements the `async_forecast_daily()` /
  `async_forecast_hourly()` dispatch methods HA actually uses, so
  forecast cards work again.

## Development

The parsing core (`client.py`, `models.py`, `icons.py`, `pollen.py`,
`stations.py`) has no Home Assistant dependency and is covered by
offline pytest tests using live fixtures captured on 2026-11-06:

```bash
python -m pytest tests/
```

## License / attribution

Weather data: **Source: MeteoSwiss**. Symbol graphics are MeteoSwiss
property and are not redistributed; only the symbol numbers are used.
