"""Tests for the configurable update interval (v0.2.2)."""

from __future__ import annotations

from datetime import timedelta

from koneho_meteoswiss.const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    resolve_update_interval,
    update_interval_minutes,
)


def test_default_when_missing():
    # Entries created before v0.2.2 have no stored value: 15 minutes,
    # exactly the pre-existing fixed cadence.
    assert update_interval_minutes({}) == DEFAULT_UPDATE_INTERVAL_MINUTES == 15
    assert resolve_update_interval({}) == timedelta(minutes=15)
    assert update_interval_minutes(None) == 15


def test_stored_value_is_used():
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: 5}) == 5
    assert resolve_update_interval({CONF_UPDATE_INTERVAL: 30}) == timedelta(minutes=30)
    # NumberSelector in HA may deliver floats / numeric strings.
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: 45.0}) == 45
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: "10"}) == 10


def test_out_of_range_is_clamped():
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: 0}) == 1
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: -3}) == 1
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: 9999}) == 180


def test_unparsable_falls_back_to_default():
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: "soon"}) == 15
    assert update_interval_minutes({CONF_UPDATE_INTERVAL: object()}) == 15
