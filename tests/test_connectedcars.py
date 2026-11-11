"""Tests for the ConnectedCars client paging and row mapping. No network or database.

Run with: python -m unittest discover tests
"""

import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.connectedcars_client import ConnectedCarsClient
from providers.connectedcars_provider import (
    position_rows,
    refuel_event_row,
    trip_row,
)

TRIP = {
    "id": "abc",
    "startTime": "2026-01-01T10:00:00.000Z",
    "endTime": "2026-01-01T10:20:00.000Z",
    "duration": 20,
    "idleTime": 60,
    "mileage": 12.5,
    "startOdometer": 1000,
    "endOdometer": 1013,
    "fuelUsed": 0.9,
    "startAddressString": "A Street 1",
    "endAddressString": "B Street 2",
    "startLatitude": 55.1,
    "startLongitude": 9.1,
    "endLatitude": 55.2,
    "endLongitude": 9.2,
    "brakeHigh": 1,
    "positions": [
        {"time": "t1", "latitude": 55.1, "longitude": 9.1, "speed": 0, "direction": 90},
        {"time": "t2", "latitude": None, "longitude": None, "speed": 5, "direction": 90},
        {"time": "t3", "latitude": 55.0, "longitude": 9.0, "speed": 40, "direction": 91},
        {"time": "t3", "latitude": 55.2, "longitude": 9.2, "speed": 50, "direction": 92},
    ],
}


class MappingTest(unittest.TestCase):
    def test_trip_row_maps_columns_and_keeps_the_rest_in_raw(self):
        row = trip_row(7, TRIP)
        self.assertEqual(row["vehicle_id"], 7)
        self.assertEqual(row["external_id"], "abc")
        self.assertEqual(row["mileage_km"], 12.5)
        self.assertEqual(row["end_address"], "B Street 2")
        raw = json.loads(row["raw"])
        self.assertEqual(raw["brakeHigh"], 1)
        self.assertNotIn("positions", raw)

    def test_trip_row_accepts_missing_measurements(self):
        row = trip_row(7, {"id": "x", "startTime": "s", "endTime": "e"})
        self.assertIsNone(row["mileage_km"])
        self.assertIsNone(row["fuel_used_l"])

    def test_position_rows_skip_points_without_position_and_repeated_times(self):
        rows = position_rows(TRIP)
        self.assertEqual([r["time"] for r in rows], ["t1", "t3"])
        self.assertEqual(rows[1]["speed"], 50)

    def test_position_rows_without_route(self):
        self.assertEqual(position_rows({"positions": None}), [])

    def test_refuel_event_row_without_position(self):
        row = refuel_event_row(
            7, {"id": "r", "time": "t", "litersBefore": 6, "litersAfter": 48}
        )
        self.assertEqual(row["liters_before"], 6)
        self.assertIsNone(row["latitude"])


class PagingTest(unittest.TestCase):
    def test_iter_trips_follows_page_info_past_short_and_empty_pages(self):
        pages = [
            {"items": [{"id": 1}], "pageInfo": {"hasNextPage": True, "endCursor": "a"}},
            {"items": [], "pageInfo": {"hasNextPage": True, "endCursor": "b"}},
            {"items": [{"id": 2}], "pageInfo": {"hasNextPage": False, "endCursor": "c"}},
        ]
        cursors = []
        client = ConnectedCarsClient("auth", "graphql", "minvolkswagen")

        def fake_query(query, variables):
            cursors.append(variables["after"])
            return {"vehicle": {"trips": pages[len(cursors) - 1]}}

        client._query = fake_query
        moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trips = list(client.iter_trips("17", moment, moment))
        self.assertEqual([t["id"] for t in trips], [1, 2])
        self.assertEqual(cursors, [None, "a", "b"])


if __name__ == "__main__":
    unittest.main()
