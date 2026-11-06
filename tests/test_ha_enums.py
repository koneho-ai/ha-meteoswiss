"""Guard: every HA enum member referenced by the integration must be one
that actually exists in Home Assistant 2026.11.

Regression test for the 0.1.0 failure on a real HA install:
SensorDeviceClass.DEW_POINT and SensorDeviceClass.WIND_GUST_SPEED do not
exist (dew point -> TEMPERATURE, gusts -> WIND_SPEED). HA is not installed
in the test environment, so this checks the source statically against a
curated allowlist — extend it only after checking the HA source/docs.
"""
import re
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "koneho_meteoswiss"

VALID = {
    "SensorDeviceClass": {
        "TEMPERATURE", "HUMIDITY", "PRESSURE", "WIND_SPEED", "WIND_DIRECTION",
        "PRECIPITATION", "IRRADIANCE", "DURATION", "TIMESTAMP", "DATE",
        "ENERGY", "POWER", "BATTERY", "ILLUMINANCE", "AQI",
    },
    "BinarySensorDeviceClass": {"PROBLEM", "CONNECTIVITY", "PRESENCE", "MOTION"},
    "SensorStateClass": {"MEASUREMENT", "TOTAL", "TOTAL_INCREASING"},
    "WeatherEntityFeature": {"FORECAST_DAILY", "FORECAST_HOURLY", "FORECAST_TWICE_DAILY"},
}

def test_no_invented_ha_enum_members():
    bad = []
    for py in COMPONENT.glob("*.py"):
        src = py.read_text()
        for enum, valid in VALID.items():
            for member in re.findall(rf"(?<![A-Za-z]){enum}\.([A-Z_0-9]+)", src):
                if member not in valid:
                    bad.append(f"{py.name}: {enum}.{member}")
    assert not bad, f"HA enum members that do not exist in HA 2026.11: {bad}"
