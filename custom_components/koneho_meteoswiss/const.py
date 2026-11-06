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

# Metadata used for automatic nearest-station selection:
# - OGD local-forecasting point metadata: one row per forecast point;
#   postal-code points have point_id = PLZ * 100 and carry WGS84 lat/lon.
# - SwissMetNet station list: one row per station with the code in the
#   "Abr." column and WGS84 "Latitude"/"Longitude" columns. The French
#   file is used because it was verified live on 2026-11-06 to return
#   exactly those columns; the file is language-specific only in its
#   headers/free-text columns, the codes and coordinates are identical.
META_POINTS_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.ogd-local-forecasting/"
    "ogd-local-forecasting_meta_point.csv"
)
STATION_LIST_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.messnetz-automatisch/"
    "ch.meteoschweiz.messnetz-automatisch_fr.csv"
)

CONF_NAME = "name"
CONF_POSTCODE = "postcode"
CONF_STATION = "station"
CONF_POLLEN_STATION = "pollen_station"
CONF_WARNINGS_NUMBER = "warnings_number"
CONF_UPDATE_INTERVAL = "update_interval"

# Pollen data (v0.3.0), both public and keyless:
# - Station metadata (name, canton, WGS84 coordinates, localised
#   station-type names) as a latin-1 CSV on data.geo.admin.ch.
# - Per-plant current values as a stations-table JSON product on the
#   MeteoSwiss website, one file per plant and language.
POLLEN_META_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.ogd-pollen/"
    "ogd-pollen_meta_stations.csv"
)
POLLEN_DATA_URL = (
    "https://www.meteoschweiz.admin.ch/product/output/measured-values/"
    "stationsTable/messwerte-pollen-{plant}-1h/"
    "stationsTable.messwerte-pollen-{plant}-1h.{lang}.json"
)

# Number of per-rank warning sensor pairs (type + level). Mirrors the
# old hass-swissweather "weather warnings number" setting: rank 1 is
# the most severe active warning. 0 disables the rank sensors.
DEFAULT_WARNINGS_NUMBER = 1
MIN_WARNINGS_NUMBER = 0
MAX_WARNINGS_NUMBER = 5


def warnings_number(entry_data: object) -> int:
    """Resolve the stored per-rank warning sensor count for an entry.

    Missing or unparsable values fall back to the default (1, matching
    the behaviour of showing the most severe warning); parsable values
    are clamped into the configurable range. Pure helper, HA-free.
    """
    raw = None
    if isinstance(entry_data, dict):
        raw = entry_data.get(CONF_WARNINGS_NUMBER)
    try:
        number = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WARNINGS_NUMBER
    return max(MIN_WARNINGS_NUMBER, min(MAX_WARNINGS_NUMBER, number))

# Update interval (v0.2.2): configurable per entry in minutes via the
# config/reconfigure flow. The default preserves the pre-0.2.2 fixed
# 15-minute cadence, so existing entries (which have no stored value)
# behave exactly as before.
DEFAULT_UPDATE_INTERVAL_MINUTES = 15
MIN_UPDATE_INTERVAL_MINUTES = 1
MAX_UPDATE_INTERVAL_MINUTES = 180

UPDATE_INTERVAL = timedelta(minutes=DEFAULT_UPDATE_INTERVAL_MINUTES)
TIMEZONE = "Europe/Zurich"

USER_AGENT = "Home Assistant koneho_meteoswiss/0.3.0"


def update_interval_minutes(entry_data: object) -> int:
    """Resolve the stored update interval (minutes) for a config entry.

    Missing or unparsable values fall back to the default; parsable
    values are clamped into the configurable range. Pure helper so the
    coordinator's cadence can be unit-tested without Home Assistant.
    """
    raw = None
    if isinstance(entry_data, dict):
        raw = entry_data.get(CONF_UPDATE_INTERVAL)
    try:
        minutes = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_UPDATE_INTERVAL_MINUTES
    return max(MIN_UPDATE_INTERVAL_MINUTES, min(MAX_UPDATE_INTERVAL_MINUTES, minutes))


def resolve_update_interval(entry_data: object) -> timedelta:
    """The coordinator update interval implied by stored entry data."""
    return timedelta(minutes=update_interval_minutes(entry_data))

# MeteoSwiss warning type codes (warnType in plzDetail warnings).
# Best-effort table: the numbering follows the hazard categories of the
# Swiss natural-hazards warning system (wind, thunderstorm, rain, snow,
# black ice, heat, frost, avalanches, earthquake, forest fire, flood,
# lake wind). Type 10 = forest fire was verified against live data
# (FOEN forest-fire warning for Pfäffikon SZ, 2026-11-06); the other
# entries follow the same published category order but have not each
# been observed in a live payload. Unknown codes render as "Type <n>".
WARN_TYPE_NAMES: dict[int, str] = {
    1: "Wind",
    2: "Thunderstorm",
    3: "Rain",
    4: "Snow",
    5: "Slippery roads",
    6: "Heat",
    7: "Frost",
    8: "Avalanches",
    9: "Earthquake",
    10: "Forest fire",
    11: "Flood",
    12: "Lake wind",
}


def warning_type_name(code: object) -> str:
    """Human name for a warnType code, 'Type <n>' when unknown."""
    try:
        numeric = int(code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"Type {code}"
    return WARN_TYPE_NAMES.get(numeric, f"Type {numeric}")


# MeteoSwiss warning levels (warnLevel 0-5) with the hazard names used
# by the Swiss warning system. Level 2 is where cantonal measures
# typically start (the level of the live forest-fire warnings seen for
# Pfäffikon SZ in Nov 2026).
WARN_LEVEL_NAMES: dict[int, str] = {
    0: "No danger",
    1: "No or minimal hazard",
    2: "Moderate hazard",
    3: "Significant hazard",
    4: "Severe hazard",
    5: "Very severe hazard",
}


def warning_level_name(level: object) -> str | None:
    """Hazard name for a warnLevel value, None when unusable."""
    try:
        numeric = int(level)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return WARN_LEVEL_NAMES.get(numeric, f"Level {numeric}")


def warning_level_color(level: object) -> str:
    """Icon colour for a warnLevel: gray <= 1, amber at 2, red above."""
    try:
        numeric = int(level)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "gray"
    if numeric <= 1:
        return "gray"
    if numeric == 2:
        return "amber"
    return "red"


# Languages MeteoSwiss publishes its content in. Home Assistant hands
# out tags like "de", "de-CH" or "pt-BR"; the app API localises its
# warning/forecast texts and the pollen products exist per language.
SUPPORTED_LANGUAGES = ("de", "fr", "it", "en")
DEFAULT_LANGUAGE = "en"


def normalize_language(language: object) -> str:
    """Map an HA language tag onto a MeteoSwiss language.

    "de-CH" -> "de", "fr_CA" -> "fr"; anything not served by
    MeteoSwiss (and missing/empty input) falls back to English.
    """
    if not language or not isinstance(language, str):
        return DEFAULT_LANGUAGE
    base = language.replace("_", "-").split("-")[0].strip().lower()
    if base in SUPPORTED_LANGUAGES:
        return base
    return DEFAULT_LANGUAGE

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
