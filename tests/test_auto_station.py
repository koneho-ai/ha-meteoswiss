"""Tests for automatic nearest-station selection (v0.2.0)."""

from __future__ import annotations

import asyncio
import copy

from koneho_meteoswiss.client import MeteoSwissClient, parse_station_csv
from koneho_meteoswiss.stations import (
    haversine_km,
    parse_meta_points,
    parse_station_list,
    select_nearest_station,
)


def _points(fixture_text):
    return parse_meta_points(fixture_text("meta_points_sample.csv"))


def _coords(fixture_text):
    return parse_station_list(fixture_text("station_list_sample.csv"))


def _observations(fixture_text):
    return parse_station_csv(fixture_text("VQHA80_sample.csv"), "VQHA80")


def test_parse_metadata(fixture_text):
    points = _points(fixture_text)
    assert points["804800"] == (47.388056, 8.485375)
    assert points["880800"] == (47.200142, 8.7806)

    coords = _coords(fixture_text)
    assert coords["SMA"] == (47.381003, 8.567194)
    assert coords["EIN"] == (47.133042, 8.756556)


def test_haversine_sanity(fixture_text):
    coords = _coords(fixture_text)
    distance = haversine_km(coords["SMA"], coords["UEB"])
    assert 5.0 < distance < 8.0  # Fluntern <-> Uetliberg is ~6.7 km


def test_select_8808_picks_nearby_station(fixture_text):
    point = _points(fixture_text)["880800"]
    choice = select_nearest_station(point, _coords(fixture_text), _observations(fixture_text))
    assert choice is not None
    # Einsiedeln (~7.7 km) edges out Wädenswil (~8.1 km) for Pfäffikon.
    assert choice.code in ("WAE", "EIN")
    assert choice.code == "EIN"
    assert choice.distance_km < 10.0
    assert choice.has_temperature is True


def test_select_8048_picks_nearest(fixture_text):
    point = _points(fixture_text)["804800"]
    choice = select_nearest_station(point, _coords(fixture_text), _observations(fixture_text))
    assert choice is not None
    assert choice.code == "UEB"  # ~4.1 km, temperature present in sample
    assert choice.distance_km < 5.0
    assert choice.has_temperature is True


def test_temperature_preference(fixture_text):
    point = _points(fixture_text)["804800"]
    observations = copy.deepcopy(_observations(fixture_text))
    observations["UEB"].values["tre200s0"] = None  # nearest loses temperature
    choice = select_nearest_station(point, _coords(fixture_text), observations)
    assert choice is not None
    # SMA (~6.2 km) reports temperature and is within the preference radius.
    assert choice.code == "SMA"
    assert choice.has_temperature is True


def test_nearest_accepted_without_temperature(fixture_text):
    point = _points(fixture_text)["804800"]
    observations = copy.deepcopy(_observations(fixture_text))
    for code in ("UEB", "SMA", "KLO"):
        observations[code].values["tre200s0"] = None
    choice = select_nearest_station(point, _coords(fixture_text), observations)
    assert choice is not None
    assert choice.code == "UEB"
    assert choice.has_temperature is False


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        pass

    async def read(self) -> bytes:
        return self._body


class _FakeContextManager:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *args) -> bool:
        return False


class _FakeSession:
    """Minimal aiohttp-session stand-in keyed by URL substring."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self._mapping = mapping

    def get(self, url: str, headers=None, timeout=None) -> _FakeContextManager:
        for key, body in self._mapping.items():
            if key in url:
                return _FakeContextManager(_FakeResponse(body))
        raise AssertionError(f"Unexpected URL requested: {url}")


def _session(fixture_bytes, fixture_text) -> _FakeSession:
    return _FakeSession(
        {
            "plzDetail": fixture_bytes("plzdetail_8808.json"),
            "VQHA80": fixture_text("VQHA80_sample.csv").encode("latin-1"),
            "VQHA98": b"Station/Location;Date;rre150z0\n",
            "meta_point": fixture_text("meta_points_sample.csv").encode("latin-1"),
            "messnetz": fixture_text("station_list_sample.csv").encode("latin-1"),
        }
    )


def test_client_auto_selects_station(fixture_bytes, fixture_text):
    client = MeteoSwissClient(_session(fixture_bytes, fixture_text), "8808")
    data = asyncio.run(client.async_get_data())
    assert data.station is not None
    assert data.station.code == "EIN"
    assert data.station_auto_selected is True
    assert data.station_distance_km is not None and data.station_distance_km < 10.0
    assert data.station_has_temperature is True


def test_client_manual_station_wins(fixture_bytes, fixture_text):
    client = MeteoSwissClient(_session(fixture_bytes, fixture_text), "8808", "WAE")
    data = asyncio.run(client.async_get_data())
    assert data.station is not None
    assert data.station.code == "WAE"
    assert data.station_auto_selected is False
