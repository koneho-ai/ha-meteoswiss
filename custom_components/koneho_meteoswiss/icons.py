"""Mapping of MeteoSwiss weather-symbol codes to HA weather conditions.

Source for the symbol meanings: the MeteoSwiss weather-symbol set
(symbol files ``1``..``35`` for day and ``101``..``135`` for night on
meteoswiss.admin.ch), whose numbering and descriptions are also listed in
the Meteomatics API documentation "General Weather State"
(https://www.meteomatics.com/en/api/available-parameters/weather-parameter/general-weather-state/):
1 = clear sky, 2 = light clouds, 3 = partly cloudy, 4 = cloudy, 5 = rain,
6 = rain and snow, 7 = snow, 8 = rain shower, 9 = snow shower,
10 = rain/snow shower, 11 = light fog, 12 = dense fog, 13 = freezing rain,
14 = thunderstorms, 15 = drizzle, 16 = sandstorm. Codes >= 100 are the
night variants of the code minus 100. MeteoSwiss additionally uses
extended codes (17 and up in the app/OGD feed, e.g. 17 and 35 observed
live on 2026-11-06); those are mapped conservatively by their observed
meaning in the live feed, and any code without an entry maps to ``None``
(HA shows no condition) while the raw code stays available on the
diagnostic "Current icon code" sensor, so no information is lost.

``iconV2`` codes use the same numbering in the live payload and are
mapped through this same table.
"""

from __future__ import annotations

# Day codes (night code = day code + 100, handled in icon_to_condition).
_DAY_CODE_CONDITIONS: dict[int, str] = {
    1: "sunny",
    2: "partlycloudy",
    3: "partlycloudy",
    4: "cloudy",
    5: "rainy",
    6: "snowy-rainy",
    7: "snowy",
    8: "rainy",  # rain shower
    9: "snowy",  # snow shower
    10: "snowy-rainy",
    11: "fog",
    12: "fog",
    13: "rainy",  # freezing rain; HA has no freezing-rain condition
    14: "lightning-rainy",
    15: "rainy",  # drizzle
    16: "windy",  # sandstorm; closest HA condition
    17: "rainy",  # observed live as the rainy-day symbol in the app feed
    18: "rainy",
    19: "snowy",
    20: "snowy-rainy",
    21: "lightning-rainy",
    35: "fog",  # observed live in the hourly symbol series on foggy mornings
}


def icon_to_condition(icon: int | None) -> str | None:
    """Map a MeteoSwiss symbol code to an HA weather condition string.

    Night variants (>= 100) map like their day counterparts, except that
    the clear-sky night code 101 becomes HA's ``clear-night``.
    """
    if icon is None:
        return None
    try:
        code = int(icon)
    except (TypeError, ValueError):
        return None
    if code >= 100:
        day_code = code - 100
        if day_code == 1:
            return "clear-night"
        return _DAY_CODE_CONDITIONS.get(day_code)
    return _DAY_CODE_CONDITIONS.get(code)
