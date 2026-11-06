"""Tests for dual-format (JSON/XML) payload parsing and normalisation."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from koneho_meteoswiss.client import parse_payload
from koneho_meteoswiss.models import PlaceForecast

EPOCH_KEYS = {"time", "start", "startLowResolution", "validFrom"}


def dict_to_xml(data: dict, root_tag: str = "PLZDetail") -> str:
    """Serialise a JSON payload to the XML form the API serves.

    Mirrors the observed XML conventions: lists become a wrapper element
    whose children repeat the wrapper's tag, scalars become element
    text, and epoch-millisecond times become ISO-8601 strings.
    """

    def add(parent: ET.Element, key: str, value: object) -> None:
        element = ET.SubElement(parent, key)
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                add(element, sub_key, sub_value)
        elif isinstance(value, list):
            for item in value:
                add(element, key, item)
        elif isinstance(value, bool):
            element.text = "true" if value else "false"
        elif value is None:
            element.text = ""
        elif key in EPOCH_KEYS or (key in ("sunrise", "sunset")):
            moment = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            element.text = moment.strftime("%Y-%m-%dT%H:%M:%S.") + (
                f"{value % 1000:03d}Z"
            )
        else:
            element.text = str(value)

    root = ET.Element(root_tag)
    for key, value in data.items():
        add(root, key, value)
    return ET.tostring(root, encoding="unicode")


def test_plzdetail_json_parsing(fixture_bytes):
    payload = parse_payload(fixture_bytes("plzdetail_8808.json"))
    place = PlaceForecast.from_payload(payload, "8808", "plzDetail")

    assert place.plz == "8808"
    assert place.current.temperature == 8.2
    assert place.current.icon == 5
    assert place.current.icon_v2 == 5
    assert place.current.time == datetime(2026, 11, 6, 13, 40, tzinfo=timezone.utc)

    assert len(place.days) == 8
    day0 = place.days[0]
    assert day0.day.isoformat() == "2026-11-06"
    assert day0.icon_day == 14
    assert day0.temperature_max == 8
    assert day0.temperature_min == 6
    assert day0.precipitation == 3.3
    assert day0.precipitation_min == 1.4
    assert day0.precipitation_max == 7.8

    graph = place.graph
    assert graph.start == datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)
    assert len(graph.get("temperatureMean1h")) == 192
    assert len(graph.get("weatherIcon3h")) == 64
    assert len(graph.get("precipitation1h")) == 172
    assert len(graph.get("precipitation10m")) == 121
    assert len(graph.get("sunrise")) == 8
    assert graph.sunrise(0) == datetime(
        2026, 11, 6, 6, 15, 21, 158000, tzinfo=timezone.utc
    )

    assert len(place.warnings) == 1
    assert place.warnings[0]["warnType"] == 10
    assert place.warnings[0]["warnLevel"] == 2
    assert place.warnings_overview == [{"warnType": 10, "warnLevel": 2}]

    assert place.climate is not None
    assert place.climate.plz == 880800
    assert len(place.climate.temperature["norm"]) == 24
    assert place.climate.temperature["norm"][0] == 5.4


def test_forecast_json_parsing(fixture_bytes):
    payload = parse_payload(fixture_bytes("forecast_8808.json"))
    place = PlaceForecast.from_payload(payload, "8808", "forecast")
    assert place.current.icon == 5
    assert len(place.days) == 8
    assert len(place.graph.get("temperatureMean1h")) == 216
    assert place.graph.get("precipitationMean1h")


def test_forecast_xml_parsing(fixture_bytes):
    payload = parse_payload(fixture_bytes("forecast_8048.xml"))
    assert payload["currentWeather"]["icon"] == 17
    place = PlaceForecast.from_payload(payload, "8048", "forecast")

    assert place.plz == "8048"
    assert place.current.icon == 17
    assert place.current.temperature == 8.2
    # XML carries ISO times; they must normalise to the same instants
    # the JSON form would give as epoch milliseconds.
    assert place.current.time == datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)
    assert place.graph.start == datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)

    assert len(place.days) == 8
    day0 = place.days[0]
    assert day0.day.isoformat() == "2026-11-06"
    assert day0.icon_day == 17
    assert day0.temperature_max == 8
    assert day0.temperature_min == 6
    assert day0.precipitation == 5.3
    assert day0.precipitation_min == 3.6
    assert day0.precipitation_max == 9.5
    assert len(place.graph.get("temperatureMean1h")) == 216
    assert len(place.graph.get("precipitation10m")) == 120


def test_json_xml_equivalence(fixture_bytes):
    """The same logical payload in JSON and XML normalises identically."""
    raw = fixture_bytes("plzdetail_8808.json")
    json_payload = parse_payload(raw)
    xml_text = dict_to_xml(json.loads(raw.decode("utf-8")))
    xml_payload = parse_payload(xml_text.encode("utf-8"))

    from_json = PlaceForecast.from_payload(json_payload, "8808", "plzDetail")
    from_xml = PlaceForecast.from_payload(xml_payload, "8808", "plzDetail")

    # Compare the typed model fields. The `raw` echo dicts legitimately
    # differ in representation (epoch ms vs ISO string) and are excluded.
    import dataclasses

    def stripped(place: PlaceForecast):
        current = dataclasses.replace(place.current, raw={})
        days = [dataclasses.replace(d, raw={}) for d in place.days]
        climate = (
            dataclasses.replace(place.climate, raw={}) if place.climate else None
        )
        return dataclasses.replace(
            place, current=current, days=days, climate=climate, raw={}
        )

    # Time-valued raw entries (sunrise/sunset series, warning validFrom)
    # differ in representation only; compare them after normalisation.
    from koneho_meteoswiss.models import to_datetime

    def normalised_series(place: PlaceForecast) -> dict:
        series = dict(place.graph.series)
        for key in ("sunrise", "sunset"):
            series[key] = [to_datetime(v) for v in series.get(key, [])]
        return series

    assert normalised_series(from_xml) == normalised_series(from_json)
    assert [
        {**w, "validFrom": to_datetime(w.get("validFrom"))} for w in from_xml.warnings
    ] == [
        {**w, "validFrom": to_datetime(w.get("validFrom"))} for w in from_json.warnings
    ]
    stripped_xml = stripped(from_xml)
    stripped_json = stripped(from_json)
    assert dataclasses.replace(
        stripped_xml,
        graph=dataclasses.replace(stripped_xml.graph, series={}),
        warnings=[],
    ) == dataclasses.replace(
        stripped_json,
        graph=dataclasses.replace(stripped_json.graph, series={}),
        warnings=[],
    )
    assert from_xml.graph.start == from_json.graph.start
    assert (
        from_xml.graph.start_low_resolution == from_json.graph.start_low_resolution
    )
    assert from_xml.warnings_overview == from_json.warnings_overview


def test_parse_payload_rejects_garbage():
    import pytest

    from koneho_meteoswiss.client import MeteoSwissApiError

    with pytest.raises(MeteoSwissApiError):
        parse_payload(b"")
    with pytest.raises(MeteoSwissApiError):
        parse_payload(b"<Forecast><unclosed>")
