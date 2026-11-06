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

# When the nearest station does not currently report temperature, a
# temperature-reporting station is preferred instead only if it is at
# most this much farther away (km, absolute, added to the nearest
# station's distance). This keeps a summit station whose 2 m sensors
# are offline (e.g. UEB) from shadowing a slightly farther full station.
TEMP_PREFERENCE_EXTRA_KM = 10.0


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


def select_nearest_station(
    point: LatLon,
    station_coords: dict[str, LatLon],
    observations: dict[str, StationObservation],
) -> StationChoice | None:
    """Pick the SwissMetNet station to use for a forecast point.

    Candidates are stations present both in the station list and in the
    latest actual-values data, sorted by haversine distance. The
    nearest wins, with one refinement: a station currently reporting
    temperature (``tre200s0``) is preferred — if the nearest station
    lacks temperature but a temperature-reporting station exists within
    ``TEMP_PREFERENCE_EXTRA_KM`` beyond the nearest distance, the
    nearest such station is chosen instead. If no station in that
    radius reports temperature, the nearest station is still accepted
    and ``has_temperature`` is False (callers surface this in
    diagnostics rather than failing).
    """
    ranked: list[tuple[float, str, bool]] = []
    for code, obs in observations.items():
        coords = station_coords.get(code)
        if coords is None:
            continue
        ranked.append(
            (haversine_km(point, coords), code, obs.get("tre200s0") is not None)
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    nearest_distance, nearest_code, nearest_has_temp = ranked[0]
    if nearest_has_temp:
        return StationChoice(nearest_code, nearest_distance, True)
    for distance, code, has_temp in ranked[1:]:
        if has_temp and distance <= nearest_distance + TEMP_PREFERENCE_EXTRA_KM:
            return StationChoice(code, distance, True)
    return StationChoice(nearest_code, nearest_distance, False)
