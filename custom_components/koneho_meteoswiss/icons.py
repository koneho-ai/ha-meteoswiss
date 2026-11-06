"""Mapping of MeteoSwiss weather-symbol codes to HA weather conditions.

The correspondence below follows MeteoSwiss's published weather-symbol
table (the symbol set used by the MeteoSwiss app and the OGD local
forecasts): day symbols are numbered 1-42 and the corresponding night
symbols 101-142. Each symbol number denotes a specific sky/precipitation
situation described in that table (e.g. 5 "very cloudy", 14 "very
cloudy, light rain", 20 "very overcast with rain"); the values here are
the Home Assistant weather condition for each numbered symbol.

The night table mirrors the day table (night code = day code + 100)
with two exceptions recorded in the published table: symbol 101 is the
clear night sky (HA ``clear-night`` instead of ``sunny``) and symbol
126 is high cloud at night, which the table classes as cloudy rather
than sunny.

``iconV2`` codes use the same numbering in the live payload and are
mapped through this same table. Codes outside 1-42 / 101-142 have no
published meaning and map to ``None`` (HA shows no condition); the raw
code stays available on the diagnostic "Current icon code" sensor, so
no information is lost.
"""

from __future__ import annotations

# Day symbols 1-42 -> HA condition, per the MeteoSwiss symbol table.
_DAY_CODE_CONDITIONS: dict[int, str] = {
    1: "sunny",
    2: "partlycloudy",
    3: "partlycloudy",
    4: "partlycloudy",
    5: "cloudy",
    6: "rainy",
    7: "snowy-rainy",
    8: "snowy",
    9: "rainy",
    10: "snowy-rainy",
    11: "snowy",
    12: "lightning",
    13: "lightning-rainy",
    14: "rainy",
    15: "snowy-rainy",
    16: "snowy",
    17: "rainy",
    18: "snowy-rainy",
    19: "snowy",
    20: "pouring",
    21: "snowy-rainy",
    22: "snowy",
    23: "lightning-rainy",
    24: "lightning-rainy",
    25: "lightning-rainy",
    26: "sunny",
    27: "fog",
    28: "fog",
    29: "rainy",
    30: "snowy",
    31: "snowy-rainy",
    32: "lightning-rainy",
    33: "rainy",
    34: "snowy",
    35: "cloudy",
    36: "lightning",
    37: "snowy",
    38: "lightning-rainy",
    39: "snowy-rainy",
    40: "lightning",
    41: "lightning",
    42: "snowy",
}

# Night symbols that differ from their day counterpart (code - 100);
# every other night symbol 102-142 matches the day table.
_NIGHT_OVERRIDES: dict[int, str] = {
    101: "clear-night",
    126: "cloudy",
}


def icon_to_condition(icon: int | None) -> str | None:
    """Map a MeteoSwiss symbol code to an HA weather condition string.

    Night symbols (101-142) map like their day counterparts except for
    the two published exceptions in ``_NIGHT_OVERRIDES``.
    """
    if icon is None:
        return None
    try:
        code = int(icon)
    except (TypeError, ValueError):
        return None
    if code in _NIGHT_OVERRIDES:
        return _NIGHT_OVERRIDES[code]
    if 101 <= code <= 142:
        return _DAY_CODE_CONDITIONS.get(code - 100)
    return _DAY_CODE_CONDITIONS.get(code)
