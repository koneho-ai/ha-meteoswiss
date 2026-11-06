"""Tests for pollen parsing, levels and station selection (v0.3.0).

Fixtures are live captures from 2026-11-06 (trimmed to two stations
for the per-plant products): the OGD metadata CSV is the full file,
the birke/graeser products carry PZH (Zürich) and PBE (Bern).
November is outside the pollen season, so the live values are 0;
threshold behaviour is tested with synthetic concentrations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from koneho_meteoswiss.pollen import (
    POLLEN_PLANT_KEYS,
    build_pollen_station_options,
    parse_pollen_product,
    parse_pollen_stations,
    pollen_level,
    pollen_level_color,
    select_nearest_pollen_station,
)


def _stations(fixture_text):
    return parse_pollen_stations(fixture_text("pollen_meta_stations.csv"), "en")


def test_parse_pollen_stations(fixture_text):
    stations = _stations(fixture_text)
    assert len(stations) == 15
    zurich = stations["PZH"]
    assert zurich.name == "Zürich"
    assert zurich.canton == "ZH"
    assert zurich.coordinates is not None
    lat, lon = zurich.coordinates
    assert abs(lat - 47.378225) < 1e-6
    assert abs(lon - 8.565644) < 1e-6
    assert zurich.height_masl == 559.0


def test_parse_pollen_product(fixture_bytes):
    payload = json.loads(fixture_bytes("pollen_birke.json"))
    values = parse_pollen_product(payload)
    assert set(values) == {"PZH", "PBE"}
    value, measured_at = values["PZH"]
    assert value == 0.0
    assert measured_at == datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)


def test_parse_pollen_product_tolerates_bad_payloads():
    assert parse_pollen_product(None) == {}
    assert parse_pollen_product({"stations": "nope"}) == {}
    assert parse_pollen_product({"stations": [{"id": "PZH"}]}) == {}


def test_pollen_levels_use_official_thresholds():
    # Birch: 10/70/300.
    assert pollen_level(0, "birch") is None or pollen_level(0, "birch") == "None"
    assert pollen_level(5, "birch") == "Low"
    assert pollen_level(10, "birch") == "Low"
    assert pollen_level(11, "birch") == "Medium"
    assert pollen_level(70, "birch") == "Medium"
    assert pollen_level(71, "birch") == "Strong"
    assert pollen_level(300, "birch") == "Strong"
    assert pollen_level(301, "birch") == "Very Strong"
    # Grasses: 20/50/150.
    assert pollen_level(20, "grasses") == "Low"
    assert pollen_level(51, "grasses") == "Strong"
    assert pollen_level(151, "grasses") == "Very Strong"
    # Beech and oak share the higher 50/130/400 band.
    assert pollen_level(49, "beech") == "Low"
    assert pollen_level(50, "beech") == "Low"
    assert pollen_level(131, "beech") == "Strong"
    assert pollen_level(401, "oak") == "Very Strong"
    # Ash: 10/100/350. Alder and hazel: 10/70/250.
    assert pollen_level(101, "ash") == "Strong"
    assert pollen_level(251, "alder") == "Very Strong"
    assert pollen_level(71, "hazel") == "Strong"
    # No measurement -> unknown.
    assert pollen_level(None, "birch") is None
    # Unknown plant falls back to the default band.
    assert pollen_level(300, "unknown-plant") == "Very Strong"


def test_pollen_level_zero_is_none_class():
    assert pollen_level(0, "birch") == "None"
    assert pollen_level(0.0, "grasses") == "None"


def test_pollen_level_colors():
    assert pollen_level_color("None") == "gray"
    assert pollen_level_color("Low") == "gray"
    assert pollen_level_color("Medium") == "amber"
    assert pollen_level_color("Strong") == "red"
    assert pollen_level_color("Very Strong") == "red"
    assert pollen_level_color(None) == "gray"


def test_select_nearest_pollen_station(fixture_text):
    stations = _stations(fixture_text)
    # A point at Zürich HB must resolve to the PZH station itself.
    choice = select_nearest_pollen_station((47.378, 8.54), stations)
    assert choice is not None
    code, distance = choice
    assert code == "PZH"
    assert distance < 5.0
    # Bern city -> PBE.
    code, _ = select_nearest_pollen_station((46.95, 7.44), stations)
    assert code == "PBE"


def test_build_pollen_station_options(fixture_text):
    stations = _stations(fixture_text)
    options = build_pollen_station_options(stations)
    assert options[0] == ("", "Automatic (nearest pollen station)")
    assert len(options) == 16
    labels = [label for _, label in options[1:]]
    assert labels == sorted(labels, key=str.lower)
    assert "Zürich (PZH)" in labels


def test_build_pollen_station_options_with_home_distance(fixture_text):
    stations = _stations(fixture_text)
    options = build_pollen_station_options(stations, home=(47.378, 8.54))
    by_code = dict(options)
    assert by_code["PZH"].endswith(" km away")
    assert by_code["PZH"].startswith("Zürich (PZH) – 2 km away") or (
        by_code["PZH"].startswith("Zürich (PZH) – 1 km away")
        or by_code["PZH"].startswith("Zürich (PZH) – 3 km away")
    )


def test_pollen_plants_cover_seven_products():
    assert POLLEN_PLANT_KEYS == (
        "birch",
        "grasses",
        "alder",
        "hazel",
        "beech",
        "ash",
        "oak",
    )
