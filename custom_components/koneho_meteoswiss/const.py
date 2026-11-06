"""Constants for the MeteoSwiss (Koneho) integration.

Clean-room implementation, written from scratch in 2026 against the live
behaviour of the public MeteoSwiss endpoints. Not derived from any other
Home Assistant integration or client library.

Data sources (all public, no API key):
- MeteoSwiss app backend ``v2/plzDetail`` (primary, richest payload) with
  ``v2/forecast`` as fallback. Both unpredictably answer with JSON *or*
  XML (Content-Type ``application/xhtml+xml``); the client sniffs the
  payload and parses both forms into one logical model.
- Official SwissMetNet actual-values CSV files (VQHA80 / VQHA98) from
  data.geo.admin.ch for station observations.

Attribution required by the data terms: "Source: MeteoSwiss".
"""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "koneho_meteoswiss"
ATTRIBUTION = "Source: MeteoSwiss"

APP_API_BASE = "https://app-prod-ws.meteoswiss-app.ch/v2"
PLZ_DETAIL_URL = APP_API_BASE + "/plzDetail?plz={plz}00"
FORECAST_URL = (
    APP_API_BASE
    + "/forecast?plz={plz}00&graph_startLowResolution=true&warning=true"
)

STATION_CSV_VQHA80_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-aktuell/VQHA80.csv"
)
STATION_CSV_VQHA98_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-aktuell/VQHA98.csv"
)

CONF_NAME = "name"
CONF_POSTCODE = "postcode"
CONF_STATION = "station"

UPDATE_INTERVAL = timedelta(minutes=15)
TIMEZONE = "Europe/Zurich"

USER_AGENT = "Home Assistant koneho_meteoswiss/0.1.0"

# Metadata for every column of the SwissMetNet actual-values CSV files.
# Key: raw column code as it appears in the CSV header.
# Value: (human name, unit, HA sensor device class, HA state class)
# Device/state classes are plain strings here so this module (and the
# client/models) stays importable without Home Assistant, e.g. in tests.
# sensor.py maps the strings onto the real HA enums.
STATION_COLUMNS: dict[str, tuple[str, str | None, str | None, str | None]] = {
    "tre200s0": ("Temperature", "°C", "temperature", "measurement"),
    "rre150z0": ("Precipitation (10 min)", "mm", "precipitation", "measurement"),
    "sre000z0": ("Sunshine duration (10 min)", "min", "duration", "measurement"),
    "gre000z0": ("Global radiation", "W/m²", "irradiance", "measurement"),
    "ure200s0": ("Humidity", "%", "humidity", "measurement"),
    "tde200s0": ("Dew point", "°C", "dew_point", "measurement"),
    "dkl010z0": ("Wind direction", "°", None, "measurement"),
    "fu3010z0": ("Wind speed", "km/h", "wind_speed", "measurement"),
    "fu3010z1": ("Wind gust speed", "km/h", "wind_gust_speed", "measurement"),
    "prestas0": ("Station pressure", "hPa", "pressure", "measurement"),
    "pp0qffs0": ("Pressure reduced to sea level (QFF)", "hPa", "pressure", "measurement"),
    "pp0qnhs0": ("Pressure reduced to sea level (QNH)", "hPa", "pressure", "measurement"),
    "ppz850s0": ("850 hPa geopotential height pressure", "hPa", "pressure", "measurement"),
    "ppz700s0": ("700 hPa geopotential height pressure", "hPa", "pressure", "measurement"),
    "dv1towz0": ("Tower wind direction", "°", None, "measurement"),
    "fu3towz0": ("Tower wind speed", "km/h", "wind_speed", "measurement"),
    "fu3towz1": ("Tower wind gust speed", "km/h", "wind_gust_speed", "measurement"),
    "ta1tows0": ("Tower temperature", "°C", "temperature", "measurement"),
    "uretows0": ("Tower humidity", "%", "humidity", "measurement"),
    "tdetows0": ("Tower dew point", "°C", "dew_point", "measurement"),
}
