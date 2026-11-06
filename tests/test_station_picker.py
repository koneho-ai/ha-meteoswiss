"""Tests for the named station picker helpers (v0.2.2)."""

from __future__ import annotations

import asyncio

from koneho_meteoswiss import client as client_module
from koneho_meteoswiss.client import MeteoSwissClient
from koneho_meteoswiss.stations import build_station_options, parse_station_directory


def _directory_text(fixture_bytes) -> str:
    # The sample fixture on disk is UTF-8; the live file is latin-1
    # (the client fetch decodes that itself, tested below).
    return fixture_bytes("station_list_sample.csv").decode("utf-8")


def test_parse_station_directory(fixture_bytes):
    directory = parse_station_directory(_directory_text(fixture_bytes))
    assert directory == {
        "SMA": "Zürich / Fluntern",
        "UEB": "Uetliberg",
        "KLO": "Zürich / Kloten",
        "WAE": "Wädenswil",
        "EIN": "Einsiedeln",
    }


def test_build_station_options_automatic_first_then_by_name(fixture_bytes):
    directory = parse_station_directory(_directory_text(fixture_bytes))
    options = build_station_options(directory)

    # Automatic choice first, with the empty value stored for it.
    assert options[0] == ("", "Automatic (nearest station)")
    # Then every station as "Name (CODE)", sorted by name; values are
    # the plain codes exactly as stored in the entry data.
    assert options[1:] == [
        ("EIN", "Einsiedeln (EIN)"),
        ("UEB", "Uetliberg (UEB)"),
        ("WAE", "Wädenswil (WAE)"),
        ("SMA", "Zürich / Fluntern (SMA)"),
        ("KLO", "Zürich / Kloten (KLO)"),
    ]


def test_build_station_options_empty_directory():
    assert build_station_options({}) == [("", "Automatic (nearest station)")]


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
    def __init__(self, body: bytes) -> None:
        self._body = body

    def get(self, url: str, headers=None, timeout=None) -> _FakeContextManager:
        assert "messnetz" in url  # the station list URL
        return _FakeContextManager(_FakeResponse(self._body))


def test_client_fetch_station_directory(fixture_bytes):
    client_module._metadata_cache.clear()
    # Simulate the live wire format: the served file is latin-1.
    body = _directory_text(fixture_bytes).encode("latin-1")
    client = MeteoSwissClient(_FakeSession(body), "8808")
    directory = asyncio.run(client.async_fetch_station_directory())
    # Latin-1 names survive the fetch intact (e.g. "Zürich", "Wädenswil").
    assert directory["SMA"] == "Zürich / Fluntern"
    assert directory["WAE"] == "Wädenswil"
    assert len(directory) == 5
