"""Client tests for v0.3.0: language, pollen, partial failures.

Uses the same fake-session pattern as test_auto_station: responses
keyed by URL substring, with per-request headers recorded so the
Accept-Language behaviour can be asserted.
"""

from __future__ import annotations

import asyncio

import pytest

from koneho_meteoswiss import client as client_module
from koneho_meteoswiss.client import MeteoSwissApiError, MeteoSwissClient
from koneho_meteoswiss.const import normalize_language


@pytest.fixture(autouse=True)
def _clear_caches():
    client_module._pollen_cache.clear()
    client_module._metadata_cache.clear()
    yield
    client_module._pollen_cache.clear()
    client_module._metadata_cache.clear()


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        pass

    async def read(self) -> bytes:
        return self._body


class _FakeContextManager:
    def __init__(self, response) -> None:
        self._response = response

    async def __aenter__(self):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def __aexit__(self, *args) -> bool:
        return False


class _RecordingSession:
    """Fake session: maps URL substrings to bodies or exceptions."""

    def __init__(self, mapping) -> None:
        self._mapping = mapping
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, headers=None, timeout=None):
        self.requests.append((url, headers))
        for key, body in self._mapping.items():
            if key in url:
                if isinstance(body, Exception):
                    return _FakeContextManager(body)
                return _FakeContextManager(_FakeResponse(body))
        raise AssertionError(f"Unexpected URL requested: {url}")


def _session(fixture_bytes, fixture_text, overrides=None) -> _RecordingSession:
    mapping = {
        "plzDetail": fixture_bytes("plzdetail_8808.json"),
        "VQHA80": fixture_text("VQHA80_sample.csv").encode("latin-1"),
        "VQHA98": b"Station/Location;Date;rre150z0\n",
        "meta_point": fixture_text("meta_points_sample.csv").encode("latin-1"),
        "messnetz": fixture_text("station_list_sample.csv").encode("latin-1"),
        "ogd-pollen": fixture_bytes("pollen_meta_stations.csv"),
        "messwerte-pollen-birke": fixture_bytes("pollen_birke.json"),
        "messwerte-pollen-graeser": fixture_bytes("pollen_graeser.json"),
        "messwerte-pollen": fixture_bytes("pollen_birke.json"),
    }
    if overrides:
        mapping.update(overrides)
    return _RecordingSession(mapping)


# --- Language ---------------------------------------------------------------


def test_normalize_language():
    assert normalize_language("de") == "de"
    assert normalize_language("de-CH") == "de"
    assert normalize_language("de_CH") == "de"
    assert normalize_language("fr-CA") == "fr"
    assert normalize_language("it") == "it"
    assert normalize_language("en-GB") == "en"
    assert normalize_language("pt-BR") == "en"
    assert normalize_language("es") == "en"
    assert normalize_language(None) == "en"
    assert normalize_language("") == "en"
    assert normalize_language(42) == "en"


def test_client_sends_accept_language(fixture_bytes, fixture_text):
    session = _session(fixture_bytes, fixture_text)
    client = MeteoSwissClient(session, "8808", "WAE", language="de-CH")
    assert client.language == "de"
    asyncio.run(client.async_get_data())
    place_calls = [h for url, h in session.requests if "plzDetail" in url]
    assert place_calls and place_calls[0]["Accept-Language"] == "de"
    pollen_calls = [url for url, _ in session.requests if "messwerte-pollen" in url]
    assert pollen_calls and all(url.endswith(".de.json") for url in pollen_calls)


def test_client_defaults_to_english(fixture_bytes, fixture_text):
    session = _session(fixture_bytes, fixture_text)
    client = MeteoSwissClient(session, "8808", "WAE")
    asyncio.run(client.async_fetch_place())
    headers = session.requests[0][1]
    assert headers["Accept-Language"] == "en"


# --- Pollen -----------------------------------------------------------------


def test_client_fetches_pollen_for_manual_station(fixture_bytes, fixture_text):
    session = _session(fixture_bytes, fixture_text)
    client = MeteoSwissClient(session, "8808", "WAE", pollen_station="PZH")
    data = asyncio.run(client.async_get_data())
    assert data.pollen is not None
    assert data.pollen.station_code == "PZH"
    assert data.pollen.station_name == "Zürich"
    assert data.pollen.values["birch"] == 0.0
    assert data.pollen.values["grasses"] == 0.0
    # Plants without a dedicated fixture route fall back to the
    # generic product body in the fake session; all seven are present.
    assert set(data.pollen.values) == {
        "birch", "grasses", "alder", "hazel", "beech", "ash", "oak"
    }
    assert data.pollen.measured_at is not None


def test_client_auto_selects_nearest_pollen_station(fixture_bytes, fixture_text):
    session = _session(fixture_bytes, fixture_text)
    client = MeteoSwissClient(session, "8808")
    data = asyncio.run(client.async_get_data())
    assert data.pollen is not None
    # 8808's OGD point is near Wollerau; Zürich is the nearest pollen
    # station with data in the fixtures.
    assert data.pollen.station_code == "PZH"


def test_pollen_responses_are_cached_for_an_hour(fixture_bytes, fixture_text):
    session = _session(fixture_bytes, fixture_text)
    client = MeteoSwissClient(session, "8808", "WAE", pollen_station="PZH")
    asyncio.run(client.async_get_data())
    first_count = len(
        [url for url, _ in session.requests if "pollen" in url]
    )
    asyncio.run(client.async_get_data())
    second_count = len(
        [url for url, _ in session.requests if "pollen" in url]
    )
    assert first_count == 8  # meta + 7 plant products
    assert second_count == first_count  # second update served from cache


def test_pollen_failure_does_not_fail_update(fixture_bytes, fixture_text):
    session = _session(
        fixture_bytes,
        fixture_text,
        overrides={"ogd-pollen": MeteoSwissApiError("boom")},
    )
    client = MeteoSwissClient(session, "8808", "WAE")
    data = asyncio.run(client.async_get_data())
    assert data.pollen is None
    assert data.station is not None  # the rest of the update succeeded


def test_single_plant_failure_is_tolerated(fixture_bytes, fixture_text):
    # The oak product stem is "eiche". Route keys match in insertion
    # order and the generic "messwerte-pollen" key would shadow a
    # specific one appended later, so build the mapping explicitly:
    # the oak route (matched by its ".en" file suffix) comes first.
    session = _session(fixture_bytes, fixture_text)
    session._mapping = {
        "eiche-1h.en": MeteoSwissApiError("boom"),
        **session._mapping,
    }
    client = MeteoSwissClient(session, "8808", "WAE", pollen_station="PZH")
    data = asyncio.run(client.async_get_data())
    assert data.pollen is not None
    assert data.pollen.values["oak"] is None
    assert data.pollen.values["birch"] == 0.0


# --- Partial station failure --------------------------------------------------


def test_station_csv_failure_does_not_fail_update(fixture_bytes, fixture_text):
    session = _session(
        fixture_bytes,
        fixture_text,
        overrides={
            "VQHA80": MeteoSwissApiError("boom"),
            "VQHA98": MeteoSwissApiError("boom"),
        },
    )
    client = MeteoSwissClient(session, "8808", "WAE")
    data = asyncio.run(client.async_get_data())
    assert data.station is None  # no station data this cycle
    assert data.place is not None  # but the forecast updated fine
    assert data.place.plz == "8808"  # payload parsed


def test_vqha98_failure_still_uses_vqha80(fixture_bytes, fixture_text):
    session = _session(
        fixture_bytes,
        fixture_text,
        overrides={"VQHA98": MeteoSwissApiError("boom")},
    )
    client = MeteoSwissClient(session, "8808", "WAE")
    data = asyncio.run(client.async_get_data())
    assert data.station is not None
    assert data.station.code == "WAE"
