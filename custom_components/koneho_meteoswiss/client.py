"""Async client for the MeteoSwiss app API and SwissMetNet CSV files.

Written from scratch (clean room). Only depends on aiohttp and the
standard library, never on Home Assistant, so it is unit-testable.

Key behaviours, all observed live against the production endpoints:

- ``v2/plzDetail`` and ``v2/forecast`` answer with JSON *or* XML
  (``application/xhtml+xml``), unpredictably per postcode/cache state;
  the Accept header has no reliable effect. :func:`parse_payload`
  therefore sniffs the body and parses either form into the same
  logical dict.
- In the XML form, lists are encoded as a wrapper element whose
  children repeat the wrapper's own tag (e.g. ``<graph>`` series and
  ``<regionForecast>``), scalars are element text, and times are
  ISO-8601 strings instead of epoch milliseconds.
- The SwissMetNet CSVs are ``;``-separated, latin-1 encoded, and use
  ``-`` for missing values.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import (
    FORECAST_URL,
    META_POINTS_URL,
    PLZ_DETAIL_URL,
    STATION_CSV_VQHA80_URL,
    STATION_CSV_VQHA98_URL,
    STATION_LIST_URL,
    USER_AGENT,
)
from .models import MeteoData, PlaceForecast, StationObservation
from .stations import (
    LatLon,
    parse_meta_points,
    parse_station_list,
    select_nearest_station,
)

_LOGGER = logging.getLogger(__name__)

# Module-level cache for the two metadata files used by automatic
# station selection (point coordinates + station coordinates). Both
# files are ~0.1-0.8 MB and change rarely; 24 h TTL is ample.
_METADATA_TTL_SECONDS = 24 * 3600
_metadata_cache: dict[str, tuple[float, Any]] = {}


def _metadata_cache_get(key: str) -> Any | None:
    entry = _metadata_cache.get(key)
    if entry is None:
        return None
    stored_at, value = entry
    if time.monotonic() - stored_at > _METADATA_TTL_SECONDS:
        _metadata_cache.pop(key, None)
        return None
    return value


def _metadata_cache_set(key: str, value: Any) -> None:
    _metadata_cache[key] = (time.monotonic(), value)


class MeteoSwissApiError(Exception):
    """Raised when MeteoSwiss data cannot be fetched or parsed."""


def _coerce(text: str | None) -> object:
    """Coerce XML element text to int/float/bool where it round-trips."""
    if text is None:
        return None
    value = text.strip()
    if value == "":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def xml_element_to_value(element: ET.Element) -> object:
    """Recursively convert an XML element to plain Python data.

    Rules derived from the observed payload shape:
    - No children -> coerced text.
    - All children share the element's own tag -> list of child values
      (this is how the API encodes arrays, e.g. graph series and the
      ``regionForecast`` wrapper).
    - Otherwise -> dict grouping children by tag; a tag that occurs
      multiple times becomes a list.
    """
    children = list(element)
    if not children:
        return _coerce(element.text)
    if all(child.tag == element.tag for child in children):
        return [xml_element_to_value(child) for child in children]
    result: dict[str, object] = {}
    for child in children:
        value = xml_element_to_value(child)
        if child.tag in result:
            existing = result[child.tag]
            if isinstance(existing, list):
                existing.append(value)
            else:
                result[child.tag] = [existing, value]
        else:
            result[child.tag] = value
    return result


def parse_payload(body: bytes | str) -> dict:
    """Parse a JSON or XML app-API body into a plain dict.

    Sniffs the first non-whitespace byte; the Content-Type header is
    deliberately not trusted.
    """
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body
    stripped = text.lstrip()
    if not stripped:
        raise MeteoSwissApiError("Empty response body")
    if stripped.startswith("<"):
        try:
            root = ET.fromstring(stripped)
        except ET.ParseError as err:
            raise MeteoSwissApiError(f"Invalid XML payload: {err}") from err
        value = xml_element_to_value(root)
        if not isinstance(value, dict):
            raise MeteoSwissApiError("Unexpected XML payload shape")
        return value
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as err:
        raise MeteoSwissApiError(f"Invalid JSON payload: {err}") from err
    if not isinstance(data, dict):
        raise MeteoSwissApiError("Unexpected JSON payload shape")
    return data


def parse_station_csv(text: str, source: str) -> dict[str, StationObservation]:
    """Parse one SwissMetNet actual-values CSV into observations by code."""
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    stations: dict[str, StationObservation] = {}
    for row in reader:
        code = (row.get("Station/Location") or "").strip()
        if not code:
            continue
        measured_at = None
        raw_date = (row.get("Date") or "").strip()
        if raw_date:
            try:
                measured_at = datetime.strptime(raw_date, "%Y%m%d%H%M").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                measured_at = None
        values: dict[str, float | None] = {}
        for column, raw in row.items():
            if column in ("Station/Location", "Date") or raw is None:
                continue
            raw = raw.strip()
            if raw in ("", "-"):
                values[column] = None
            else:
                try:
                    values[column] = float(raw)
                except ValueError:
                    values[column] = None
        stations[code] = StationObservation(
            code=code, measured_at=measured_at, values=values, source=source
        )
    return stations


def merge_station_data(
    primary: dict[str, StationObservation],
    extra: dict[str, StationObservation],
) -> dict[str, StationObservation]:
    """Merge VQHA98 observations into VQHA80 ones without overwriting."""
    merged = dict(primary)
    for code, obs in extra.items():
        if code not in merged:
            merged[code] = obs
        else:
            existing = merged[code]
            for column, value in obs.values.items():
                if existing.values.get(column) is None and value is not None:
                    existing.values[column] = value
    return merged


class MeteoSwissClient:
    """Client for one postcode (+ optional SwissMetNet station)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        postcode: str,
        station: str | None = None,
    ) -> None:
        self._session = session
        self.postcode = str(postcode).strip()
        self.station = station.strip().upper() if station else None

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT}

    async def _get_text(self, url: str) -> str:
        try:
            async with self._session.get(
                url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                body = await response.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MeteoSwissApiError(f"Request to {url} failed: {err}") from err
        return body.decode("utf-8", errors="replace")

    async def async_fetch_place(self) -> PlaceForecast:
        """Fetch the place payload: plzDetail first, forecast as fallback."""
        detail_url = PLZ_DETAIL_URL.format(plz=self.postcode)
        try:
            payload = parse_payload(await self._get_text(detail_url))
            place = PlaceForecast.from_payload(payload, self.postcode, "plzDetail")
            if not place.days and not place.graph.series:
                raise MeteoSwissApiError("plzDetail payload had no forecast data")
            return place
        except MeteoSwissApiError as err:
            _LOGGER.debug("plzDetail failed for %s (%s); trying forecast", self.postcode, err)
        forecast_url = FORECAST_URL.format(plz=self.postcode)
        payload = parse_payload(await self._get_text(forecast_url))
        place = PlaceForecast.from_payload(payload, self.postcode, "forecast")
        if not place.days and not place.graph.series:
            raise MeteoSwissApiError(
                f"No forecast data for postcode {self.postcode} on either endpoint"
            )
        return place

    async def async_fetch_stations(self) -> dict[str, StationObservation]:
        """Fetch and merge both SwissMetNet actual-values CSV files."""
        text80 = await self._get_text(STATION_CSV_VQHA80_URL)
        stations = parse_station_csv(text80, "VQHA80")
        try:
            text98 = await self._get_text(STATION_CSV_VQHA98_URL)
            stations = merge_station_data(stations, parse_station_csv(text98, "VQHA98"))
        except MeteoSwissApiError as err:
            _LOGGER.debug("VQHA98 fetch failed (%s); continuing with VQHA80 only", err)
        return stations

    async def async_fetch_point_coordinates(self) -> LatLon | None:
        """WGS84 coordinates of this entry's postcode point (cached)."""
        points = _metadata_cache_get("meta_points")
        if points is None:
            text = await self._get_text(META_POINTS_URL)
            # The file is latin-1 in practice (place names); _get_text
            # decoded as UTF-8 with replacement, which only affects
            # non-ASCII names — coordinates and ids are pure ASCII.
            points = parse_meta_points(text)
            _metadata_cache_set("meta_points", points)
        return points.get(f"{int(self.postcode) * 100}")

    async def async_fetch_station_coordinates(self) -> dict[str, LatLon]:
        """WGS84 coordinates of all SwissMetNet stations (cached)."""
        coords = _metadata_cache_get("station_list")
        if coords is None:
            text = await self._get_text(STATION_LIST_URL)
            coords = parse_station_list(text)
            _metadata_cache_set("station_list", coords)
        return coords

    async def async_get_data(self) -> MeteoData:
        """Fetch place payload plus station data.

        A manually configured station always wins. Without one, the
        nearest SwissMetNet station is selected automatically (see
        :func:`stations.select_nearest_station`); if the metadata
        needed for selection cannot be fetched, the update still
        succeeds with forecast data only.
        """
        place = await self.async_fetch_place()
        if self.station:
            stations = await self.async_fetch_stations()
            station_obs = stations.get(self.station)
            if station_obs is None:
                _LOGGER.warning(
                    "Station %s not present in SwissMetNet CSV data", self.station
                )
            return MeteoData(place=place, station=station_obs)

        stations = await self.async_fetch_stations()
        try:
            point = await self.async_fetch_point_coordinates()
            station_coords = await self.async_fetch_station_coordinates()
        except MeteoSwissApiError as err:
            _LOGGER.warning(
                "Automatic station selection unavailable for %s: %s",
                self.postcode,
                err,
            )
            return MeteoData(place=place, station=None)
        if point is None:
            _LOGGER.warning(
                "No OGD point coordinates for postcode %s; no station selected",
                self.postcode,
            )
            return MeteoData(place=place, station=None)
        choice = select_nearest_station(point, station_coords, stations)
        if choice is None:
            _LOGGER.warning(
                "No SwissMetNet station with coordinates for postcode %s",
                self.postcode,
            )
            return MeteoData(place=place, station=None)
        _LOGGER.debug(
            "Auto-selected station %s for %s (%.1f km, temperature=%s)",
            choice.code,
            self.postcode,
            choice.distance_km,
            choice.has_temperature,
        )
        return MeteoData(
            place=place,
            station=stations.get(choice.code),
            station_auto_selected=True,
            station_distance_km=round(choice.distance_km, 1),
            station_has_temperature=choice.has_temperature,
        )
