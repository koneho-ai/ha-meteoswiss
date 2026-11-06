"""Tests for station -> weather-entity current-conditions mapping."""

from __future__ import annotations

import copy

from koneho_meteoswiss.client import parse_station_csv
from koneho_meteoswiss.models import station_current_conditions


def _sma(fixture_text):
    stations = parse_station_csv(fixture_text("VQHA80_sample.csv"), "VQHA80")
    return stations["SMA"]


def test_full_mapping(fixture_text):
    conditions = station_current_conditions(_sma(fixture_text))
    assert conditions["humidity"] == 95.6  # ure200s0
    assert conditions["pressure"] == 1021.5  # pp0qnhs0 (QNH preferred)
    assert conditions["dew_point"] == 5.7  # tde200s0
    assert conditions["wind_speed"] == 4.3  # fu3010z0
    assert conditions["wind_gust_speed"] == 7.2  # fu3010z1
    assert conditions["wind_bearing"] == 220  # dkl010z0, as int


def test_pressure_fallback_to_station_pressure(fixture_text):
    obs = copy.deepcopy(_sma(fixture_text))
    obs.values["pp0qnhs0"] = None
    conditions = station_current_conditions(obs)
    assert conditions["pressure"] == 955.1  # prestas0


def test_missing_values_stay_none(fixture_text):
    stations = parse_station_csv(fixture_text("VQHA80_sample.csv"), "VQHA80")
    ueb = stations["UEB"]  # sample row has no pressure values at all
    conditions = station_current_conditions(ueb)
    assert conditions["pressure"] is None
    assert conditions["humidity"] == 98.0


def test_no_station():
    conditions = station_current_conditions(None)
    assert all(value is None for value in conditions.values())
