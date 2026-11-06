"""Tests for SwissMetNet station CSV parsing."""

from __future__ import annotations

from datetime import datetime, timezone

from koneho_meteoswiss.client import merge_station_data, parse_station_csv
from koneho_meteoswiss.const import STATION_COLUMNS
from koneho_meteoswiss.models import (
    present_station_columns,
    stale_station_sensor_unique_ids,
)


def test_vqha80_parsing(fixture_text):
    stations = parse_station_csv(fixture_text("VQHA80.csv"), "VQHA80")
    assert len(stations) == 159

    sma = stations["SMA"]  # Zürich / Fluntern
    assert sma.measured_at == datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)
    assert sma.get("tre200s0") == 6.4
    assert sma.get("ure200s0") == 95.6
    assert sma.get("tde200s0") == 5.7
    assert sma.get("fu3010z0") == 4.3
    assert sma.get("fu3010z1") == 7.2
    assert sma.get("pp0qnhs0") == 1021.5
    assert sma.get("gre000z0") == 50.0


def test_missing_values_become_none(fixture_text):
    stations = parse_station_csv(fixture_text("VQHA80.csv"), "VQHA80")
    ueb = stations["UEB"]  # Uetliberg: 2 m sensors offline at capture time
    assert ueb.get("tre200s0") is None
    assert ueb.get("ure200s0") is None
    assert ueb.get("fu3010z0") is None
    # ...while its tower sensors reported fine.
    assert ueb.get("ta1tows0") == 3.7
    assert ueb.get("uretows0") == 98.4
    assert ueb.get("fu3towz1") == 29.5
    assert ueb.get("gre000z0") == 45.0


def test_station_sensor_columns_only_include_present_values(fixture_text):
    stations = parse_station_csv(fixture_text("VQHA80.csv"), "VQHA80")
    lac = stations["LAC"]  # Lachen: a deliberately partial station row

    columns = present_station_columns(lac)

    assert columns
    assert set(columns) <= set(STATION_COLUMNS)
    assert all(lac.get(column) is not None for column in columns)
    # The surface measurements present in this captured row are...
    assert "tre200s0" in columns
    assert "ure200s0" in columns
    assert "tde200s0" in columns
    # ...but instruments/values it does not report must not get sensors.
    for missing in (
        "fu3010z0",
        "fu3010z1",
        "prestas0",
        "pp0qnhs0",
        "gre000z0",
        "sre000z0",
        "fu3towz0",
        "ppz850s0",
        "ppz700s0",
    ):
        assert lac.get(missing) is None
        assert missing not in columns
    assert present_station_columns(None) == ()


def test_stale_station_sensor_unique_ids_for_registry_cleanup():
    existing = [
        "place_station_tre200s0",  # current -> keep
        "place_station_fu3010z0",  # no current value -> stale
        "place_station_ppz850s0",  # no current value -> stale
        "place_sunshine_today",  # not a station sensor -> untouched
        "other_station_fu3010z0",  # another entry -> untouched
    ]

    stale = stale_station_sensor_unique_ids(
        existing, "place", ("tre200s0", "ure200s0")
    )

    assert stale == (
        "place_station_fu3010z0",
        "place_station_ppz850s0",
    )


def test_vqha98_merge(fixture_text):
    stations80 = parse_station_csv(fixture_text("VQHA80.csv"), "VQHA80")
    stations98 = parse_station_csv(fixture_text("VQHA98.csv"), "VQHA98")
    assert len(stations98) == 142

    merged = merge_station_data(stations80, stations98)
    # A precipitation-only station from VQHA98 shows up merged.
    assert "AGATT" in merged
    assert merged["AGATT"].get("rre150z0") == 0.0
    # A '-' in VQHA98 stays None.
    assert merged["AGSTE"].get("rre150z0") is None
    # VQHA80 values are never overwritten by the merge.
    assert merged["SMA"].get("tre200s0") == 6.4
