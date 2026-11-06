"""Tests for the dead-manual-station Repairs decision logic (v0.2.2)."""

from __future__ import annotations

from koneho_meteoswiss.models import StationObservation
from koneho_meteoswiss.repairs import (
    MANUAL_STATION_MISSING_THRESHOLD,
    ManualStationWatch,
    issue_id_for_entry,
    station_data_missing,
)


def _obs(values: dict) -> StationObservation:
    return StationObservation(code="UEB", measured_at=None, values=values)


def test_station_data_missing():
    assert station_data_missing(None) is True  # code absent from the CSV
    assert station_data_missing(_obs({"tre200s0": None, "ure200s0": None})) is True
    assert station_data_missing(_obs({})) is True
    assert station_data_missing(_obs({"tre200s0": None, "ure200s0": 91.0})) is False
    assert station_data_missing(_obs({"tre200s0": 0.0})) is False  # 0.0 is a value


def test_issue_raised_only_at_threshold():
    watch = ManualStationWatch()
    threshold = MANUAL_STATION_MISSING_THRESHOLD
    for _ in range(threshold - 1):
        assert watch.observe(True) is None
        assert watch.issue_active is False
    assert watch.observe(True) == "raise"
    assert watch.issue_active is True
    # Further missing refreshes do not re-raise.
    assert watch.observe(True) is None


def test_issue_cleared_when_station_reports_again():
    watch = ManualStationWatch()
    for _ in range(MANUAL_STATION_MISSING_THRESHOLD):
        watch.observe(True)
    assert watch.issue_active is True
    assert watch.observe(False) == "clear"
    assert watch.issue_active is False
    assert watch.consecutive_missing == 0
    # A present refresh with no active issue is a no-op.
    assert watch.observe(False) is None


def test_counter_resets_before_threshold():
    watch = ManualStationWatch()
    watch.observe(True)
    watch.observe(True)
    assert watch.observe(False) is None  # resets the streak
    assert watch.consecutive_missing == 0
    # A fresh streak must again reach the full threshold.
    assert watch.observe(True) is None
    assert watch.observe(True) is None
    assert watch.observe(True) == "raise"


def test_issue_id_format():
    assert issue_id_for_entry("abc123") == "manual_station_no_data_abc123"
