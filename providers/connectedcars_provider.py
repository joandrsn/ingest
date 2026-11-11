"""ConnectedCars provider: trips, routes and refuel events for the account's cars."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from config import Config
from providers.base_provider import BaseProvider
from providers.connectedcars_client import ConnectedCarsClient

# Log in again this long before the cached token runs out.
TOKEN_MARGIN = timedelta(minutes=2)

UPSERT_VEHICLE = """
    INSERT INTO vehicle (source_id, external_id, vin, license_plate, make, model,
                         year, fuel_type)
    VALUES (%(source_id)s, %(external_id)s, %(vin)s, %(license_plate)s, %(make)s,
            %(model)s, %(year)s, %(fuel_type)s)
    ON CONFLICT (source_id, external_id) DO UPDATE SET
        vin = EXCLUDED.vin, license_plate = EXCLUDED.license_plate,
        make = EXCLUDED.make, model = EXCLUDED.model, year = EXCLUDED.year,
        fuel_type = EXCLUDED.fuel_type
    RETURNING vehicle_id
"""

# xmax is 0 for a row that was inserted rather than updated.
UPSERT_TRIP = """
    INSERT INTO car_trip (vehicle_id, external_id, start_time, end_time,
        duration_min, idle_time_s, mileage_km, start_odometer_km, end_odometer_km,
        fuel_used_l, start_address, end_address, start_latitude, start_longitude,
        end_latitude, end_longitude, raw)
    VALUES (%(vehicle_id)s, %(external_id)s, %(start_time)s, %(end_time)s,
        %(duration_min)s, %(idle_time_s)s, %(mileage_km)s, %(start_odometer_km)s,
        %(end_odometer_km)s, %(fuel_used_l)s, %(start_address)s, %(end_address)s,
        %(start_latitude)s, %(start_longitude)s, %(end_latitude)s,
        %(end_longitude)s, %(raw)s)
    ON CONFLICT (vehicle_id, external_id) DO UPDATE SET
        start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time,
        duration_min = EXCLUDED.duration_min, idle_time_s = EXCLUDED.idle_time_s,
        mileage_km = EXCLUDED.mileage_km,
        start_odometer_km = EXCLUDED.start_odometer_km,
        end_odometer_km = EXCLUDED.end_odometer_km,
        fuel_used_l = EXCLUDED.fuel_used_l,
        start_address = EXCLUDED.start_address, end_address = EXCLUDED.end_address,
        start_latitude = EXCLUDED.start_latitude,
        start_longitude = EXCLUDED.start_longitude,
        end_latitude = EXCLUDED.end_latitude, end_longitude = EXCLUDED.end_longitude,
        raw = EXCLUDED.raw, updated_at = now()
    RETURNING trip_id, (xmax = 0) AS inserted
"""

DELETE_POSITIONS = "DELETE FROM car_trip_position WHERE trip_id = %s"

# One statement per trip: the route is passed as a JSON array.
INSERT_POSITIONS = """
    INSERT INTO car_trip_position (trip_id, time, latitude, longitude, speed_kmh,
                                   direction)
    SELECT %s, p.time, p.latitude, p.longitude, p.speed, p.direction
    FROM jsonb_to_recordset(%s::jsonb) AS p(
        time timestamptz, latitude numeric, longitude numeric, speed int,
        direction int)
"""

UPSERT_REFUEL_EVENT = """
    INSERT INTO car_refuel_event (vehicle_id, external_id, time, liters_before,
        liters_after, address, latitude, longitude)
    VALUES (%(vehicle_id)s, %(external_id)s, %(time)s, %(liters_before)s,
        %(liters_after)s, %(address)s, %(latitude)s, %(longitude)s)
    ON CONFLICT (vehicle_id, external_id) DO UPDATE SET
        time = EXCLUDED.time, liters_before = EXCLUDED.liters_before,
        liters_after = EXCLUDED.liters_after, address = EXCLUDED.address,
        latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
        updated_at = now()
    RETURNING (xmax = 0) AS inserted
"""


def vehicle_row(source_id: int, vehicle: Dict[str, Any]) -> Dict[str, Any]:
    """Map a vehicle from the API to a row of the vehicle table."""
    return {
        "source_id": source_id,
        "external_id": str(vehicle["id"]),
        "vin": vehicle.get("vin"),
        "license_plate": vehicle.get("licensePlate"),
        "make": vehicle.get("make"),
        "model": vehicle.get("model"),
        "year": vehicle.get("year"),
        "fuel_type": vehicle.get("fuelType"),
    }


def trip_row(vehicle_id: int, trip: Dict[str, Any]) -> Dict[str, Any]:
    """Map a trip from the API to a row of car_trip.

    The route is left out of ``raw``; it is stored in car_trip_position.
    """
    raw = {key: value for key, value in trip.items() if key != "positions"}
    return {
        "vehicle_id": vehicle_id,
        "external_id": trip["id"],
        "start_time": trip["startTime"],
        "end_time": trip["endTime"],
        "duration_min": trip.get("duration"),
        "idle_time_s": trip.get("idleTime"),
        "mileage_km": trip.get("mileage"),
        "start_odometer_km": trip.get("startOdometer"),
        "end_odometer_km": trip.get("endOdometer"),
        "fuel_used_l": trip.get("fuelUsed"),
        "start_address": trip.get("startAddressString"),
        "end_address": trip.get("endAddressString"),
        "start_latitude": trip.get("startLatitude"),
        "start_longitude": trip.get("startLongitude"),
        "end_latitude": trip.get("endLatitude"),
        "end_longitude": trip.get("endLongitude"),
        "raw": json.dumps(raw),
    }


def position_rows(trip: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the route points of a trip that have a position, one per time."""
    by_time = {
        point["time"]: point
        for point in trip.get("positions") or []
        if point.get("latitude") is not None and point.get("longitude") is not None
    }
    return list(by_time.values())


def refuel_event_row(vehicle_id: int, event: Dict[str, Any]) -> Dict[str, Any]:
    """Map a refuel event from the API to a row of car_refuel_event."""
    position = event.get("latestPosition") or {}
    return {
        "vehicle_id": vehicle_id,
        "external_id": event["id"],
        "time": event["time"],
        "liters_before": event.get("litersBefore"),
        "liters_after": event.get("litersAfter"),
        "address": event.get("latestPositionAddressString"),
        "latitude": position.get("latitude"),
        "longitude": position.get("longitude"),
    }


class ConnectedCarsProvider(BaseProvider):
    """Stores trips, their routes and refuel events for each car of the account.

    Every row is upserted on the provider's own id, so a period can be fetched
    again without creating duplicates.
    """

    def __init__(self, db_connection):
        """Initialize ConnectedCars provider.

        Args:
            db_connection: Database connection object
        """
        super().__init__(db_connection, "ConnectedCars")
        self.client = ConnectedCarsClient(
            Config.CONNECTEDCARS_AUTH_URL,
            Config.CONNECTEDCARS_GRAPHQL_URL,
            Config.CONNECTEDCARS_NAMESPACE,
        )

    def authenticate(self) -> bool:
        """Use the cached access token, or log in with email and password.

        Returns:
            bool: True if authentication successful, False otherwise
        """
        credentials = self.get_credentials()
        if not credentials:
            self.logger.error("No credentials found for ConnectedCars")
            return False

        now = datetime.now(timezone.utc)
        expiration = credentials.get("access_expiration")
        if credentials.get("access_token") and expiration and now < expiration:
            self.access_token = credentials["access_token"]
            self.token_expiration = expiration
            self.client.access_token = self.access_token
            self.logger.debug("Using existing valid access token")
            return True

        try:
            token, lifetime = self.client.login(
                credentials.get("username"), credentials.get("password")
            )
        except Exception as e:
            self.logger.error(f"Error during authentication: {e}")
            return False

        expiration = now + timedelta(seconds=lifetime) - TOKEN_MARGIN
        return self.update_access_token(token, expiration)

    def run(self, start_date: datetime, end_date: datetime) -> tuple[bool, int]:
        """Fetch and store trips and refuel events for the specified date range.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            tuple: (success: bool, number of new trips and refuel events)
        """
        try:
            if not self.get_source_info():
                self.logger.error(f"Source '{self.source_name}' not found")
                return False, 0

            if not self.authenticate():
                self.logger.error(f"Authentication failed for {self.source_name}")
                return False, 0

            # The API takes instants; naive datetimes are local time.
            from_time = start_date.astimezone(timezone.utc)
            to_time = end_date.astimezone(timezone.utc)

            inserted = 0
            for vehicle in self.client.get_vehicles():
                vehicle_id = self._store_vehicle(vehicle)
                trips = refuels = 0
                for trip in self.client.iter_trips(vehicle["id"], from_time, to_time):
                    trips += self._store_trip(vehicle_id, trip)
                for event in self.client.get_refuel_events(
                    vehicle["id"], from_time, to_time
                ):
                    refuels += self._store_refuel_event(vehicle_id, event)
                if trips or refuels:
                    self.logger.info(
                        f"{self.source_name}: {vehicle.get('make')} "
                        f"{vehicle.get('model')}: {trips} new trips, "
                        f"{refuels} new refuel events"
                    )
                inserted += trips + refuels

            return True, inserted

        except Exception as e:
            self.logger.error(
                f"Error in {self.source_name} provider: {e}", exc_info=True
            )
            return False, 0

    def _store_vehicle(self, vehicle: Dict[str, Any]) -> int:
        with self.db.transaction():
            row = self.db.fetch_one(
                UPSERT_VEHICLE, vehicle_row(self.source_id, vehicle)
            )
        return row["vehicle_id"]

    def _store_trip(self, vehicle_id: int, trip: Dict[str, Any]) -> int:
        """Store a trip and replace its route. Returns 1 if the trip is new."""
        with self.db.transaction():
            row = self.db.fetch_one(UPSERT_TRIP, trip_row(vehicle_id, trip))
            self.db.execute(DELETE_POSITIONS, (row["trip_id"],))
            positions = position_rows(trip)
            if positions:
                self.db.execute(
                    INSERT_POSITIONS, (row["trip_id"], json.dumps(positions))
                )
        return int(row["inserted"])

    def _store_refuel_event(self, vehicle_id: int, event: Dict[str, Any]) -> int:
        """Store a refuel event. Returns 1 if the event is new."""
        with self.db.transaction():
            row = self.db.fetch_one(
                UPSERT_REFUEL_EVENT, refuel_event_row(vehicle_id, event)
            )
        return int(row["inserted"])
