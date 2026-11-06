"""Normalised data model for MeteoSwiss payloads.

This module is deliberately free of Home Assistant imports so the whole
parsing/normalisation layer can be unit-tested with plain pytest.

The JSON and XML forms of the app API describe the same logical tree.
``client.parse_payload`` produces a plain ``dict`` for either form, and
the ``from_payload`` constructors here turn that dict into typed
dataclasses. Two representation differences are normalised here:

- Times: JSON carries epoch milliseconds (ints); XML carries ISO-8601
  strings. Both become timezone-aware ``datetime`` objects (UTC).
- The daily forecast list is called ``forecast`` in plzDetail and
  ``regionForecast`` in the forecast endpoint; both are accepted.

Nothing from the payload is dropped: :class:`PlaceForecast` keeps the
complete graph series dictionary, the full warnings list and the full
klimaGraph, and the HA platforms expose all of it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import ClassVar
from zoneinfo import ZoneInfo

from .const import (
    STATION_COLUMNS,
    warning_level_color,
    warning_level_name,
    warning_type_name,
)

LOCAL_TZ = ZoneInfo("Europe/Zurich")
UTC = timezone.utc

# The app API uses 32767 (Int16 max) as a "no data" sentinel in the
# currentWeather block (icon codes and temperature).
MISSING_VALUE_SENTINEL = 32767


def _num_or_none_sentinel(value: object) -> float | None:
    num = _num(value)
    return None if num is None or num == MISSING_VALUE_SENTINEL else num


def _int_or_none_sentinel(value: object) -> int | None:
    num = _int(value)
    return None if num is None or num == MISSING_VALUE_SENTINEL else num


def to_datetime(value: object) -> datetime | None:
    """Convert an epoch-ms number or ISO-8601 string to an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromtimestamp(int(text) / 1000, tz=UTC)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    num = _num(value)
    return int(num) if num is not None else None


@dataclass
class CurrentWeather:
    """Current conditions block of a place payload."""

    icon: int | None
    icon_v2: int | None
    temperature: float | None
    time: datetime | None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CurrentWeather":
        return cls(
            icon=_int_or_none_sentinel(data.get("icon")),
            icon_v2=_int_or_none_sentinel(data.get("iconV2")),
            temperature=_num_or_none_sentinel(data.get("temperature")),
            time=to_datetime(data.get("time")),
            raw=dict(data),
        )

    @property
    def condition_icon(self) -> int | None:
        """Icon code to derive the current condition from.

        The V2 icon set is preferred when present — it is the newer
        symbol set and carries the night variants — with the legacy
        icon as fallback when V2 is missing (or the sentinel).
        """
        return self.icon_v2 if self.icon_v2 is not None else self.icon


@dataclass
class DayForecast:
    """One day of the daily forecast list."""

    day: date
    icon_day: int | None
    icon_day_v2: int | None
    precipitation: float | None
    precipitation_min: float | None
    precipitation_max: float | None
    temperature_min: float | None
    temperature_max: float | None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "DayForecast":
        day_raw = data.get("dayDate")
        if isinstance(day_raw, datetime):
            day = day_raw.date()
        else:
            day = date.fromisoformat(str(day_raw)[:10])
        return cls(
            day=day,
            icon_day=_int(data.get("iconDay")),
            icon_day_v2=_int(data.get("iconDayV2")),
            precipitation=_num(data.get("precipitation")),
            precipitation_min=_num(data.get("precipitationMin")),
            precipitation_max=_num(data.get("precipitationMax")),
            temperature_min=_num(data.get("temperatureMin")),
            temperature_max=_num(data.get("temperatureMax")),
            raw=dict(data),
        )


@dataclass
class GraphData:
    """The full ``graph`` block: every series, unabridged.

    ``series`` maps each graph key (e.g. ``temperatureMean1h``) to its
    list of values, exactly as delivered. Typed accessors cover the
    series the HA platforms consume directly; everything else is still
    available through ``series`` and is exposed as entity attributes.
    """

    start: datetime | None
    start_low_resolution: datetime | None
    series: dict[str, list] = field(default_factory=dict)

    # Series resolutions, in hours per step.
    STEP_HOURS: ClassVar[dict[str, float]] = {
        "temperatureMean1h": 1,
        "temperatureMin1h": 1,
        "temperatureMax1h": 1,
        "windSpeed1h": 1,
        "windSpeed1hq10": 1,
        "windSpeed1hq90": 1,
        "gustSpeed1h": 1,
        "gustSpeed1hq10": 1,
        "gustSpeed1hq90": 1,
        "sunshine1h": 1,
        "precipitation1h": 1,
        "precipitationMin1h": 1,
        "precipitationMax1h": 1,
        "weatherIcon3h": 3,
        "weatherIcon3hV2": 3,
        "windSpeed3h": 3,
        "windDirection3h": 3,
        "precipitationProbability3h": 3,
        "precipitationMean1h": 1,  # forecast-endpoint naming
    }
    # 10-minute series: 121 values starting at ``start``.
    TEN_MIN_SERIES: ClassVar[tuple[str, ...]] = (
        "precipitation10m",
        "precipitationMin10m",
        "precipitationMax10m",
    )

    @classmethod
    def from_dict(cls, data: dict) -> "GraphData":
        series: dict[str, list] = {}
        for key, value in data.items():
            if key in ("start", "startLowResolution"):
                continue
            if isinstance(value, list):
                series[key] = list(value)
            else:
                series[key] = [value]
        return cls(
            start=to_datetime(data.get("start")),
            start_low_resolution=to_datetime(data.get("startLowResolution")),
            series=series,
        )

    def get(self, name: str) -> list:
        return self.series.get(name, [])

    def hourly_datetimes(self, count: int) -> list[datetime]:
        if self.start is None:
            return []
        return [self.start + timedelta(hours=i) for i in range(count)]

    def local_day_indices(self, day: date) -> range:
        """Hourly indices (into 1h series) whose local date equals ``day``."""
        if self.start is None:
            return range(0)
        first_local = self.start.astimezone(LOCAL_TZ)
        # First index whose local time is >= local midnight of `day`.
        start_of_day = datetime.combine(day, time.min, tzinfo=LOCAL_TZ)
        offset = (start_of_day - first_local).total_seconds() / 3600
        first = max(int(offset) if offset == int(offset) else int(offset) + 1, 0)
        return range(first, first + 24)

    def values_for_local_day(self, name: str, day: date) -> list:
        """Values of a series belonging to a local calendar day.

        1h series are indexed by hour; 3h series by 3-hour block; the
        10-minute series by 10-minute step. Returns [] for unknown
        series or series without a defined resolution.
        """
        values = self.get(name)
        if not values or self.start is None:
            return []
        if name in self.TEN_MIN_SERIES:
            step = timedelta(minutes=10)
        elif name in self.STEP_HOURS:
            step = timedelta(hours=self.STEP_HOURS[name])
        else:
            return []
        result = []
        for idx, value in enumerate(values):
            moment = self.start + step * idx
            if moment.astimezone(LOCAL_TZ).date() == day:
                result.append(value)
        return result

    def value_at(self, name: str, moment: datetime) -> object:
        """Value of a series valid at ``moment`` (index clamped).

        Works for the 1h and 3h series in ``STEP_HOURS`` and for the
        10-minute series. Returns None for unknown/empty series or
        when the graph start is unknown.
        """
        values = self.get(name)
        if not values or self.start is None:
            return None
        if name in self.TEN_MIN_SERIES:
            step = timedelta(minutes=10)
        elif name in self.STEP_HOURS:
            step = timedelta(hours=self.STEP_HOURS[name])
        else:
            return None
        index = int((moment - self.start) // step)
        index = max(0, min(index, len(values) - 1))
        return values[index]

    def sunrise(self, index: int = 0) -> datetime | None:
        values = self.get("sunrise")
        if index < len(values):
            return to_datetime(values[index])
        return None

    def sunset(self, index: int = 0) -> datetime | None:
        values = self.get("sunset")
        if index < len(values):
            return to_datetime(values[index])
        return None


@dataclass
class ClimateGraph:
    """The ``klimaGraph`` block: monthly climate normals vs. actuals.

    Each of precipitation/sunshine/temperature carries three parallel
    monthly lists: ``abs`` (measured), ``norm`` (1991-2020 normal) and
    ``abweichung`` (deviation), starting at ``start``.
    """

    plz: int | None
    start: datetime | None
    precipitation: dict = field(default_factory=dict)
    sunshine: dict = field(default_factory=dict)
    temperature: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ClimateGraph":
        return cls(
            plz=_int(data.get("plz")),
            start=to_datetime(data.get("start")),
            precipitation=dict(data.get("precipitationGraphValues") or {}),
            sunshine=dict(data.get("sunshineGraphValues") or {}),
            temperature=dict(data.get("temperatureGraphValues") or {}),
            raw=dict(data),
        )

    def current_month_norm_temperature(self, now: datetime) -> float | None:
        """Climate-normal temperature for the month containing ``now``.

        The fixture's ``temperatureGraphValues`` contains 24 monthly
        entries beginning in November 2024. Its ``norm`` list is the
        fixed climate-normal annual cycle, repeated after 12 entries
        (for example, November is 5.4 °C at indices 0 and 12); ``abs``
        is instead the rolling month's measured mean. We therefore use
        ``norm`` and select it by calendar month modulo 12. An absolute
        month offset would run off the end of the 24-entry list for
        current dates in late 2026 and incorrectly produce no state.
        """
        if self.start is None:
            return None
        values = self.temperature.get("norm") or []
        if not values:
            return None
        cycle_index = (now.month - self.start.month) % 12
        if cycle_index < len(values):
            return _num(values[cycle_index])
        return None


@dataclass
class PlaceForecast:
    """Complete payload for one postcode, from plzDetail or forecast."""

    plz: str
    current: CurrentWeather
    days: list[DayForecast]
    graph: GraphData
    warnings: list[dict] = field(default_factory=list)
    warnings_overview: list[dict] = field(default_factory=list)
    climate: ClimateGraph | None = None
    source_endpoint: str = "plzDetail"
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict, plz: str, source_endpoint: str) -> "PlaceForecast":
        days_raw = payload.get("forecast")
        if days_raw is None:
            days_raw = payload.get("regionForecast") or []
        if isinstance(days_raw, dict):
            days_raw = [days_raw]
        klima_raw = payload.get("klimaGraph")
        plz_value = payload.get("plz")
        if plz_value is None and klima_raw:
            plz_value = klima_raw.get("plz")
        return cls(
            plz=str(plz_value)[:4] if plz_value is not None else plz,
            current=CurrentWeather.from_dict(payload.get("currentWeather") or {}),
            days=[DayForecast.from_dict(d) for d in days_raw],
            graph=GraphData.from_dict(payload.get("graph") or {}),
            warnings=list(payload.get("warnings") or []),
            warnings_overview=list(payload.get("warningsOverview") or []),
            climate=ClimateGraph.from_dict(klima_raw) if klima_raw else None,
            source_endpoint=source_endpoint,
            raw=dict(payload),
        )

    # -- Warnings --------------------------------------------------------------

    def active_warnings(self, now: datetime | None = None) -> list[dict]:
        """Warnings in force at ``now``, most severe first.

        Full warning records whose ``validTo`` has passed are
        expired and excluded (the app API keeps recently ended
        warnings in the payload for a while). Overview entries carry
        no validity window, so they are used as-is when the payload
        has no full records. When full records exist they are the
        authority: if all of them expired, nothing is active even if
        the overview still lists the type.
        """
        if now is None:
            now = datetime.now(UTC)
        if self.warnings:
            pool = [
                warning
                for warning in self.warnings
                if (valid_to := to_datetime(warning.get("validTo"))) is None
                or valid_to >= now
            ]
        else:
            pool = list(self.warnings_overview)
        return sorted(
            pool, key=lambda w: _num(w.get("warnLevel")) or 0, reverse=True
        )

    def highest_warning(self, now: datetime | None = None) -> dict | None:
        """The active warning record with the highest warnLevel."""
        active = self.active_warnings(now)
        return active[0] if active else None

    def warning_at_rank(
        self, rank: int, now: datetime | None = None
    ) -> dict | None:
        """Active warning at 0-based ``rank`` (0 = most severe)."""
        active = self.active_warnings(now)
        if 0 <= rank < len(active):
            return warning_details(active[rank])
        return None

    def warnings_summary(self, now: datetime | None = None) -> dict:
        """Readable summary of the active warnings (for the sensor)."""
        active = self.active_warnings(now)
        highest = active[0] if active else None
        if highest is None:
            return {
                "state": "None",
                "count": 0,
                "max_level": None,
                "warn_types": [],
                "warn_type_names": [],
                "texts": [],
                "text_joined": "",
                "valid_from": None,
                "warnings": [],
            }
        level = _int(highest.get("warnLevel"))
        type_name = warning_type_name(highest.get("warnType"))
        state = f"Level {level}: {type_name}" if level is not None else type_name
        texts = [
            str(w["text"]).strip()
            for w in active
            if w.get("text") and str(w["text"]).strip()
        ]
        types = sorted(
            {
                t
                for t in (_int(w.get("warnType")) for w in active)
                if t is not None
            }
        )
        valid_from = to_datetime(highest.get("validFrom"))
        levels = [
            lvl
            for lvl in (_int(w.get("warnLevel")) for w in active)
            if lvl is not None
        ]
        return {
            "state": state[:255],
            "count": len(active),
            "max_level": max(levels) if levels else None,
            "warn_types": types,
            "warn_type_names": [warning_type_name(t) for t in types],
            "texts": texts,
            "text_joined": "\n\n".join(texts),
            "valid_from": valid_from.isoformat() if valid_from else None,
            "warnings": active,
        }

    # -- Aggregates used by the HA platforms ---------------------------------

    def sunshine_hours_for_day(self, day: date) -> float | None:
        """Total sunshine for a local day, in hours.

        The ``sunshine1h`` series carries minutes of sunshine per hour
        (0-60), consistent with the SwissMetNet ``sre000z0`` convention.
        """
        values = [
            v for v in self.graph.values_for_local_day("sunshine1h", day) if v is not None
        ]
        if not values:
            return None
        return round(sum(values) / 60.0, 2)

    def precipitation_for_day(self, day: date) -> dict[str, float | None]:
        """Precipitation sums (mm) for a local day incl. min/max variants."""
        result: dict[str, float | None] = {}
        for key, name in (
            ("precipitation", "precipitation1h"),
            ("precipitation_min", "precipitationMin1h"),
            ("precipitation_max", "precipitationMax1h"),
        ):
            values = [
                v for v in self.graph.values_for_local_day(name, day) if v is not None
            ]
            result[key] = round(sum(values), 2) if values else None
        # The fallback endpoint names its hourly precipitation series
        # precipitationMean1h instead of precipitation1h.
        if result["precipitation"] is None:
            values = [
                v
                for v in self.graph.values_for_local_day("precipitationMean1h", day)
                if v is not None
            ]
            if values:
                result["precipitation"] = round(sum(values), 2)
        return result

    def max_precipitation_probability_for_day(self, day: date) -> float | None:
        values = [
            v
            for v in self.graph.values_for_local_day("precipitationProbability3h", day)
            if v is not None
        ]
        return float(max(values)) if values else None

    def max_wind_for_day(self, day: date) -> dict[str, float | None]:
        wind = [v for v in self.graph.values_for_local_day("windSpeed1h", day) if v is not None]
        gust = [v for v in self.graph.values_for_local_day("gustSpeed1h", day) if v is not None]
        return {
            "wind_speed_max": float(max(wind)) if wind else None,
            "wind_gust_max": float(max(gust)) if gust else None,
        }

    def hourly_forecast(self, now: datetime | None = None) -> list[dict]:
        """Hourly forecast entries (HA Forecast key names, plain dicts).

        One entry per ``temperatureMean1h`` point. 3-hourly series are
        sampled by block (index ``i // 3``). The 1h precipitation series
        is shorter than the temperature series in the live payload
        (172 vs 192 values); it begins at the graph's
        ``startLowResolution`` point, which in every observed payload
        coincides with aligning it to the *end* of the window, i.e.
        its last value belongs to the last temperature hour (see the
        README's precipitation-alignment note).

        When ``now`` is given, entries before the current hour are
        dropped: the graph window starts at local midnight, so
        without filtering the hourly forecast would lead with hours
        that are already over. Each entry also carries the forecast
        sunshine minutes for its hour under ``sunshine`` (the HA
        Forecast dictionary has no sunshine key in HA 2026.11, so the
        weather entity does not forward it; it stays available here).
        """
        from .icons import icon_to_condition

        graph = self.graph
        temps = graph.get("temperatureMean1h")
        if not temps or graph.start is None:
            return []
        temps_min = graph.get("temperatureMin1h")
        temps_max = graph.get("temperatureMax1h")
        precip = graph.get("precipitation1h") or graph.get("precipitationMean1h")
        precip_offset = len(temps) - len(precip)
        icons3h = graph.get("weatherIcon3h")
        icons3h_v2 = graph.get("weatherIcon3hV2")
        prob3h = graph.get("precipitationProbability3h")
        wind1h = graph.get("windSpeed1h")
        gust1h = graph.get("gustSpeed1h")
        dir3h = graph.get("windDirection3h")
        sunshine1h = graph.get("sunshine1h")

        def at(series: list, idx: int):
            return series[idx] if series and 0 <= idx < len(series) else None

        first_index = 0
        if now is not None:
            current_hour = now.replace(minute=0, second=0, microsecond=0)
            elapsed_hours = (current_hour - graph.start).total_seconds() / 3600
            if elapsed_hours > 0:
                first_index = min(int(elapsed_hours), len(temps))

        entries: list[dict] = []
        for idx in range(first_index, len(temps)):
            icon = at(icons3h, idx // 3)
            entry = {
                "datetime": (graph.start + timedelta(hours=idx)).isoformat(),
                "condition": icon_to_condition(icon),
                "native_temperature": temps[idx],
                "native_templow": at(temps_min, idx),
                "native_apparent_temperature": at(temps_max, idx),
                "native_precipitation": at(precip, idx - precip_offset),
                "precipitation_probability": at(prob3h, idx // 3),
                "native_wind_speed": at(wind1h, idx),
                "native_wind_gust_speed": at(gust1h, idx),
                "wind_bearing": at(dir3h, idx // 3),
                "sunshine": at(sunshine1h, idx),
                "icon_code": icon,
                "icon_code_v2": at(icons3h_v2, idx // 3),
            }
            entries.append(entry)
        return entries

    def daily_forecast(self) -> list[dict]:
        """Daily forecast entries (HA Forecast key names, plain dicts)."""
        from .icons import icon_to_condition

        entries: list[dict] = []
        for idx, day in enumerate(self.days):
            wind = self.max_wind_for_day(day.day)
            entry = {
                "datetime": day.day.isoformat(),
                "condition": icon_to_condition(day.icon_day),
                "native_temperature": day.temperature_max,
                "native_templow": day.temperature_min,
                "native_precipitation": day.precipitation,
                "precipitation_probability": self.max_precipitation_probability_for_day(
                    day.day
                ),
                "native_wind_speed": wind["wind_speed_max"],
                "native_wind_gust_speed": wind["wind_gust_max"],
                "icon_code": day.icon_day,
                "icon_code_v2": day.icon_day_v2,
                "precipitation_min": day.precipitation_min,
                "precipitation_max": day.precipitation_max,
                "sunrise": (sr.isoformat() if (sr := self.graph.sunrise(idx)) else None),
                "sunset": (ss.isoformat() if (ss := self.graph.sunset(idx)) else None),
            }
            entries.append(entry)
        return entries


def warning_details(warning: dict) -> dict:
    """Normalised detail dict for one warning record.

    Used by the per-rank warning sensors: type/level names resolved,
    validity window as ISO strings, links and outlook passed through
    from the payload record.
    """
    level = _int(warning.get("warnLevel"))
    valid_from = to_datetime(warning.get("validFrom"))
    valid_to = to_datetime(warning.get("validTo"))
    return {
        "type_name": warning_type_name(warning.get("warnType")),
        "type_code": _int(warning.get("warnType")),
        "level": warning_level_name(level),
        "level_numeric": level,
        "text": warning.get("text"),
        "html_text": warning.get("htmlText"),
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "links": warning.get("links") or [],
        "outlook": bool(warning.get("outlook")),
        "icon_color": warning_level_color(level),
    }


@dataclass
class StationObservation:
    """One row of a SwissMetNet actual-values CSV."""

    code: str
    measured_at: datetime | None
    values: dict[str, float | None] = field(default_factory=dict)
    source: str = "VQHA80"

    def get(self, column: str) -> float | None:
        return self.values.get(column)


def present_station_columns(
    station: StationObservation | None,
) -> tuple[str, ...]:
    """Known station columns with a current measured value.

    SwissMetNet rows contain every CSV column, using None for ``-``.
    Only present values should produce sensor entities; otherwise a
    partial station acquires a permanent set of ``unknown`` sensors for
    instruments it does not have (or whose values are currently absent).
    """
    if station is None:
        return ()
    return tuple(
        column for column in STATION_COLUMNS if station.get(column) is not None
    )


def stale_station_sensor_unique_ids(
    unique_ids: Iterable[str],
    base_unique_id: str,
    current_columns: Iterable[str],
) -> tuple[str, ...]:
    """Station-sensor unique IDs that are no longer backed by data.

    This is the pure filtering logic used by sensor-platform registry
    cleanup. Only IDs under this entry's ``_station_`` namespace are
    considered; all other entities' IDs are returned untouched (that
    is, not included in the stale set).
    """
    prefix = f"{base_unique_id}_station_"
    current_unique_ids = {f"{prefix}{column}" for column in current_columns}
    return tuple(
        unique_id
        for unique_id in unique_ids
        if unique_id.startswith(prefix) and unique_id not in current_unique_ids
    )


def station_current_conditions(
    station: StationObservation | None,
) -> dict[str, float | int | None]:
    """Map a station row onto weather-entity current conditions.

    Keys match the fields consumed by the HA weather entity. Pressure
    prefers QNH (``pp0qnhs0``) and falls back to station pressure
    (``prestas0``). Missing ('-'/None) values stay None. Humidity keeps
    the key ``humidity`` because HA's ``WeatherEntity`` exposes a
    ``humidity`` property; unlike temperature/pressure/wind, it has no
    ``native_humidity`` property.
    """
    result: dict[str, float | int | None] = {
        "humidity": None,
        "pressure": None,
        "dew_point": None,
        "wind_speed": None,
        "wind_gust_speed": None,
        "wind_bearing": None,
    }
    if station is None:
        return result
    pressure = station.get("pp0qnhs0")
    if pressure is None:
        pressure = station.get("prestas0")
    bearing = station.get("dkl010z0")
    result.update(
        humidity=station.get("ure200s0"),
        pressure=pressure,
        dew_point=station.get("tde200s0"),
        wind_speed=station.get("fu3010z0"),
        wind_gust_speed=station.get("fu3010z1"),
        wind_bearing=int(bearing) if bearing is not None else None,
    )
    return result


@dataclass
class MeteoData:
    """Everything the coordinator fetches for one config entry."""

    place: PlaceForecast
    station: StationObservation | None = None
    # Pollen values for the entry's pollen station (a
    # pollen.PollenData), or None when pollen could not be fetched.
    # Typed loosely: pollen.py imports from this module, so a direct
    # reference would be circular.
    pollen: object | None = None
    # Set when the station was chosen automatically (no station code
    # configured): the selection distance and whether the chosen
    # station currently reports temperature.
    station_auto_selected: bool = False
    station_distance_km: float | None = None
    station_has_temperature: bool | None = None
