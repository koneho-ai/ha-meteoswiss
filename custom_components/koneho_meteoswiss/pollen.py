"""Pollen data model: stations, per-plant values, load levels.

No Home Assistant imports; unit-testable offline.

Data sources (both public, keyless, verified live 2026-11-06):

- Station metadata: the OGD pollen CSV on data.geo.admin.ch
  (``POLLEN_META_URL``) — one row per pollen station with code, name,
  canton, station height, WGS84 coordinates and localised station
  type names (``station_type_de`` / ``_fr`` / ``_it`` / ``_en``).
  The network is sparse by design (15 stations for Switzerland).
- Current values: one stations-table JSON product per plant on the
  MeteoSwiss website (``POLLEN_DATA_URL``), localised by language
  suffix. Each product lists every station's current concentration
  (``current.value``, a string) and measurement time
  (``current.date``, epoch milliseconds).

Load classes follow the official MeteoSwiss classification of
allergenic pollen (Belastungsklassen der allergenen Pollenarten):
per-plant thresholds in pollen/m³ separating Low / Medium / Strong;
anything above the Strong threshold is Very Strong, a measured 0 is
None (no pollen), and an unmeasured plant stays unknown.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from .const import DEFAULT_LANGUAGE, normalize_language
from .models import to_datetime
from .stations import LatLon, haversine_km

# (plant key, product file stem, display name) in product order. The
# plant key is the stable identifier used in entity unique ids; the
# product stem is the German name used in the measured-values URLs.
POLLEN_PLANTS: tuple[tuple[str, str, str], ...] = (
    ("birch", "birke", "Birch"),
    ("grasses", "graeser", "Grasses"),
    ("alder", "erle", "Alder"),
    ("hazel", "hasel", "Hazel"),
    ("beech", "buche", "Beech"),
    ("ash", "esche", "Ash"),
    ("oak", "eiche", "Oak"),
)
POLLEN_PLANT_KEYS: tuple[str, ...] = tuple(key for key, _, _ in POLLEN_PLANTS)
POLLEN_PLANT_PRODUCTS: dict[str, str] = {key: stem for key, stem, _ in POLLEN_PLANTS}
POLLEN_PLANT_NAMES: dict[str, str] = {key: name for key, _, name in POLLEN_PLANTS}

# Official load-class thresholds (low, medium, strong) in pollen/m³.
POLLEN_THRESHOLDS: dict[str, tuple[int, int, int]] = {
    "birch": (10, 70, 300),
    "grasses": (20, 50, 150),
    "alder": (10, 70, 250),
    "hazel": (10, 70, 250),
    "beech": (50, 130, 400),
    "ash": (10, 100, 350),
    "oak": (50, 130, 400),
}
DEFAULT_POLLEN_THRESHOLDS = (10, 70, 250)

POLLEN_LEVELS: tuple[str, ...] = ("None", "Low", "Medium", "Strong", "Very Strong")


def pollen_level(value: float | None, plant_key: str) -> str | None:
    """Load level for a concentration, None when there is no value."""
    if value is None:
        return None
    if value <= 0:
        return "None"
    low, medium, strong = POLLEN_THRESHOLDS.get(
        plant_key, DEFAULT_POLLEN_THRESHOLDS
    )
    if value <= low:
        return "Low"
    if value <= medium:
        return "Medium"
    if value <= strong:
        return "Strong"
    return "Very Strong"


def pollen_level_color(level: str | None) -> str:
    """Icon colour for a pollen load level."""
    if level == "Medium":
        return "amber"
    if level in ("Strong", "Very Strong"):
        return "red"
    return "gray"


@dataclass
class PollenStation:
    """One row of the pollen station metadata CSV."""

    code: str
    name: str
    canton: str | None = None
    station_type: str | None = None
    height_masl: float | None = None
    coordinates: LatLon | None = None


def _float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


def parse_pollen_stations(
    text: str, language: str | None = None
) -> dict[str, PollenStation]:
    """Parse the pollen metadata CSV: station code -> PollenStation.

    ``language`` selects which localised ``station_type_*`` column is
    exposed; it is normalised the same way as everywhere else.
    """
    lang = normalize_language(language) if language else DEFAULT_LANGUAGE
    stations: dict[str, PollenStation] = {}
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        code = (row.get("station_abbr") or "").strip().upper()
        name = (row.get("station_name") or "").strip()
        if not code or not name:
            continue
        lat = _float(row.get("station_coordinates_wgs84_lat"))
        lon = _float(row.get("station_coordinates_wgs84_lon"))
        stations[code] = PollenStation(
            code=code,
            name=name,
            canton=(row.get("station_canton") or "").strip() or None,
            station_type=(row.get(f"station_type_{lang}") or "").strip() or None,
            height_masl=_float(row.get("station_height_masl")),
            coordinates=(lat, lon) if lat is not None and lon is not None else None,
        )
    return stations


def parse_pollen_product(
    payload: object,
) -> dict[str, tuple[float | None, datetime | None]]:
    """Parse one per-plant stations-table product.

    Returns station code -> (concentration in pollen/m³, measured
    at). Stations with an unparsable block are skipped; a value that
    does not parse becomes None but keeps its timestamp.
    """
    result: dict[str, tuple[float | None, datetime | None]] = {}
    if not isinstance(payload, dict):
        return result
    stations = payload.get("stations")
    if not isinstance(stations, list):
        return result
    for station in stations:
        if not isinstance(station, dict):
            continue
        code = str(station.get("id") or "").strip().upper()
        current = station.get("current")
        if not code or not isinstance(current, dict):
            continue
        raw_value = current.get("value")
        try:
            value = float(raw_value) if raw_value not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        result[code] = (value, to_datetime(current.get("date")))
    return result


@dataclass
class PollenData:
    """Current pollen values for one station."""

    station_code: str
    station_name: str | None = None
    measured_at: datetime | None = None
    values: dict[str, float | None] = field(default_factory=dict)

    def value(self, plant_key: str) -> float | None:
        return self.values.get(plant_key)

    def level(self, plant_key: str) -> str | None:
        return pollen_level(self.values.get(plant_key), plant_key)


def select_nearest_pollen_station(
    point: LatLon, stations: dict[str, PollenStation]
) -> tuple[str, float] | None:
    """Nearest pollen station to a point: (code, distance km)."""
    best: tuple[str, float] | None = None
    for code, station in stations.items():
        if station.coordinates is None:
            continue
        distance = haversine_km(point, station.coordinates)
        if best is None or (distance, code) < (best[1], best[0]):
            best = (code, distance)
    return best


# Label of the first (automatic) option in the config-flow pollen
# station picker; its value is the empty string, matching how "no
# pollen station configured" would be stored — except automatic is
# the default and always resolves to a real station at runtime.
AUTOMATIC_POLLEN_STATION_LABEL = "Automatic (nearest pollen station)"


def build_pollen_station_options(
    stations: dict[str, PollenStation],
    home: LatLon | None = None,
) -> list[tuple[str, str]]:
    """(value, label) options for the config-flow pollen picker.

    Mirrors :func:`stations.build_station_options`: the automatic
    choice comes first (empty value), then every station as
    ``"Name (CODE)"`` sorted by name; when the HA home coordinates
    are known, each station with coordinates gets a
    ``" – N km away"`` suffix with its distance from home.
    """
    options: list[tuple[str, str]] = [("", AUTOMATIC_POLLEN_STATION_LABEL)]
    for code, station in sorted(
        stations.items(), key=lambda item: (item[1].name.lower(), item[0])
    ):
        label = f"{station.name} ({code})"
        if home is not None and station.coordinates is not None:
            label += f" – {haversine_km(home, station.coordinates):.0f} km away"
        options.append((code, label))
    return options
