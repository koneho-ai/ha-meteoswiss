"""Decision logic for the "manual station not reporting" Repairs issue.

No Home Assistant imports; the coordinator feeds each successful
refresh's outcome into :class:`ManualStationWatch` and acts on the
returned action by creating/deleting the HA Repairs issue.

Only *manually configured* stations are watched: an auto-selected
station that stops reporting is silently replaced by the next-nearest
one on the following refresh, so it must never raise an issue. A
manual station that disappears from the SwissMetNet data (retired,
renamed, feed problem) otherwise degrades invisibly — the forecast
keeps working and only the current conditions go stale.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import StationObservation

# Consecutive successful refreshes with the station missing before the
# issue is raised. One refresh is ~15 minutes by default, so 3 strikes
# ≈ 45 minutes — long enough to ride out a single delayed CSV update.
MANUAL_STATION_MISSING_THRESHOLD = 3

ISSUE_TRANSLATION_KEY = "manual_station_no_data"


def issue_id_for_entry(entry_id: str) -> str:
    """Repairs issue id for a config entry's dead manual station."""
    return f"manual_station_no_data_{entry_id}"


def station_data_missing(station: StationObservation | None) -> bool:
    """Whether a fetched station observation counts as "not reporting".

    Missing means the station code was absent from the fetched
    SwissMetNet data altogether, or its row was present but every
    measured value was empty (``-`` in the CSV).
    """
    if station is None:
        return True
    return all(value is None for value in station.values.values())


@dataclass
class ManualStationWatch:
    """Tracks consecutive missing refreshes for one manual station."""

    consecutive_missing: int = 0
    issue_active: bool = False

    def observe(self, missing: bool) -> str | None:
        """Record one refresh outcome; return "raise", "clear" or None."""
        if not missing:
            self.consecutive_missing = 0
            if self.issue_active:
                self.issue_active = False
                return "clear"
            return None
        self.consecutive_missing += 1
        if (
            self.consecutive_missing >= MANUAL_STATION_MISSING_THRESHOLD
            and not self.issue_active
        ):
            self.issue_active = True
            return "raise"
        return None
