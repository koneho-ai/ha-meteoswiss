"""SwissMetNet station metadata and nearest-station selection.

No Home Assistant imports; unit-testable offline.

Coordinate sources (both public CSVs on data.geo.admin.ch, verified
live on 2026-11-06):

- OGD local-forecasting point metadata (``META_POINTS_URL``): rows for
  every forecast point. Postal-code points have ``point_id = PLZ * 100``
  and columns ``point_coordinates_wgs84_lat`` / ``..._lon``.
- SwissMetNet station list (``STATION_LIST_URL``, the
  ``ch.meteoschweiz.messnetz-automatisch_fr.csv`` file): rows with the
  station code in ``Abr.`` and ``Latitude`` / ``Longitude`` columns.
  This file is the station-metadata source chosen for v0.2.0.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

from .models import StationObservation

LatLon = tuple[float, float]

# Richer stations are preferred only within this many kilometres
# beyond the nearest station's distance. The window was originally
# introduced for temperature availability and now also covers the core
# measurement set below. Keeping the window bounded prevents a distant
# full station from displacing a much closer partial station.
TEMP_PREFERENCE_EXTRA_KM = 10.0

# Measurements that make a station broadly useful for current weather
# conditions. Pressure may be either station pressure or QNH.
CORE_REQUIRED_COLUMNS = ("tre200s0", "ure200s0", "fu3010z0")
CORE_PRESSURE_COLUMNS = ("prestas0", "pp0qnhs0")


def station_has_core_measurements(obs: StationObservation) -> bool:
    """Whether an observation reports temperature, humidity, wind and pressure."""
    return all(obs.get(column) is not None for column in CORE_REQUIRED_COLUMNS) and any(
        obs.get(column) is not None for column in CORE_PRESSURE_COLUMNS
    )


def _float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


def parse_meta_points(text: str) -> dict[str, LatLon]:
    """Parse the OGD point metadata CSV: point_id -> (lat, lon)."""
    points: dict[str, LatLon] = {}
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        point_id = (row.get("point_id") or "").strip()
        lat = _float(row.get("point_coordinates_wgs84_lat"))
        lon = _float(row.get("point_coordinates_wgs84_lon"))
        if point_id and lat is not None and lon is not None:
            points[point_id] = (lat, lon)
    return points


def parse_station_list(text: str) -> dict[str, LatLon]:
    """Parse the SwissMetNet station list CSV: code -> (lat, lon)."""
    stations: dict[str, LatLon] = {}
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        code = (row.get("Abr.") or "").strip().upper()
        lat = _float(row.get("Latitude"))
        lon = _float(row.get("Longitude"))
        if code and lat is not None and lon is not None:
            stations[code] = (lat, lon)
    return stations


def parse_station_directory(text: str) -> dict[str, str]:
    """Parse the SwissMetNet station list CSV: code -> station name.

    The name comes from the list's ``Station`` column (e.g. "Zürich /
    Fluntern" for SMA). Rows without a usable name fall back to the
    code itself so every station remains selectable.
    """
    directory: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        code = (row.get("Abr.") or "").strip().upper()
        if not code:
            continue
        name = (row.get("Station") or "").strip()
        directory[code] = name or code
    return directory


# Label of the first (automatic) option in the config-flow station
# picker; its value is the empty string, matching how "no station
# configured" is stored in the entry data.
AUTOMATIC_STATION_LABEL = "Automatic (nearest station)"


def build_station_options(directory: dict[str, str]) -> list[tuple[str, str]]:
    """(value, label) options for the config-flow station picker.

    The first option is the automatic choice (empty value); the rest
    are every station as ``"Name (CODE)"``, sorted by station name
    (case-insensitive, code as tie-breaker). Values are the plain
    station codes, exactly as stored in the entry data.
    """
    options: list[tuple[str, str]] = [("", AUTOMATIC_STATION_LABEL)]
    for code, name in sorted(
        directory.items(), key=lambda item: (item[1].lower(), item[0])
    ):
        options.append((code, f"{name} ({code})"))
    return options


def haversine_km(a: LatLon, b: LatLon) -> float:
    """Great-circle distance between two (lat, lon) points, in km."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


@dataclass
class StationChoice:
    """Result of automatic nearest-station selection."""

    code: str
    distance_km: float
    has_temperature: bool
    has_core_measurements: bool = False


def select_nearest_station(
    point: LatLon,
    station_coords: dict[str, LatLon],
    observations: dict[str, StationObservation],
) -> StationChoice | None:
    """Pick the SwissMetNet station to use for a forecast point.

    Candidates are stations present both in the station list and in the
    latest actual-values data. The nearest station defines a preference
    window extending ``TEMP_PREFERENCE_EXTRA_KM`` beyond its distance.
    Within that window, ranking is:

    1. stations reporting the core set (temperature, humidity, wind,
       and station pressure or QNH);
    2. stations reporting temperature (the pre-existing preference, so
       a summit station with its 2 m temperature sensor offline does
       not shadow a slightly farther measuring station);
    3. distance.

    A richer station outside the window does not displace a nearer
    station. If no preferred station is in the window, the nearest is
    accepted and its capability flags tell callers what it reports.
    """
    ranked: list[tuple[float, str, bool, bool]] = []
    for code, obs in observations.items():
        coords = station_coords.get(code)
        if coords is None:
            continue
        ranked.append(
            (
                haversine_km(point, coords),
                code,
                obs.get("tre200s0") is not None,
                station_has_core_measurements(obs),
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    nearest_distance = ranked[0][0]
    in_window = [
        item
        for item in ranked
        if item[0] <= nearest_distance + TEMP_PREFERENCE_EXTRA_KM
    ]
    distance, code, has_temperature, has_core = min(
        in_window,
        key=lambda item: (not item[3], not item[2], item[0], item[1]),
    )
    return StationChoice(code, distance, has_temperature, has_core)
