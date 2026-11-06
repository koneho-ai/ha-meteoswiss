"""Tests for the official MeteoSwiss symbol-table mapping (v0.2.2)."""

from __future__ import annotations

from koneho_meteoswiss.icons import icon_to_condition

# Home Assistant's weather condition vocabulary.
HA_CONDITIONS = {
    "clear-night",
    "cloudy",
    "exceptional",
    "fog",
    "hail",
    "lightning",
    "lightning-rainy",
    "partlycloudy",
    "pouring",
    "rainy",
    "snowy",
    "snowy-rainy",
    "sunny",
    "windy",
    "windy-variant",
}


def test_every_published_code_maps_to_a_valid_condition():
    for code in list(range(1, 43)) + list(range(101, 143)):
        condition = icon_to_condition(code)
        assert condition is not None, f"code {code} unmapped"
        assert condition in HA_CONDITIONS, f"code {code} -> {condition!r}"


def test_official_table_spot_checks():
    # Deltas vs the pre-0.2.2 mapping, per the published symbol table:
    # 5 "very cloudy", 14 "very cloudy, light rain", 20 "very
    # overcast with rain".
    assert icon_to_condition(5) == "cloudy"
    assert icon_to_condition(14) == "rainy"
    assert icon_to_condition(20) == "pouring"
    # Night counterparts of the same symbols.
    assert icon_to_condition(105) == "cloudy"
    assert icon_to_condition(114) == "rainy"
    assert icon_to_condition(120) == "pouring"


def test_night_exceptions():
    # The only two night symbols that differ from their day symbol:
    # 101 is the clear night sky, 126 is high cloud (cloudy, not sunny).
    assert icon_to_condition(1) == "sunny"
    assert icon_to_condition(101) == "clear-night"
    assert icon_to_condition(26) == "sunny"
    assert icon_to_condition(126) == "cloudy"


def test_out_of_table_codes_map_to_none():
    assert icon_to_condition(0) is None
    assert icon_to_condition(43) is None
    assert icon_to_condition(100) is None
    assert icon_to_condition(143) is None
