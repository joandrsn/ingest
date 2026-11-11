"""HTTP client for the ConnectedCars GraphQL API. Knows nothing about the database."""

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

TRIP_PAGE_SIZE = 100
REFUEL_EVENT_LIMIT = 1000

VEHICLES_QUERY = """
query Vehicles {
  viewer { vehicles { vehicle {
    id vin licensePlate make model year fuelType
  } } }
}
"""

# ignoreEmpty leaves out zero-distance trips (ignition on and off again).
TRIPS_QUERY = """
query Trips($id: ID, $from: Date, $to: Date, $first: Int, $after: Cursor) {
  vehicle(id: $id) {
    trips(fromTime: $from, toTime: $to, first: $first, after: $after,
          ignoreEmpty: true) {
      items {
        id startTime endTime duration idleTime
        mileage gpsMileage startOdometer endOdometer
        fuelUsed co2Emissions
        startAddressString endAddressString startAddress endAddress
        startLatitude startLongitude endLatitude endLongitude
        tripType note
        accelerationHigh accelerationMedium accelerationLow
        brakeHigh brakeMedium brakeLow
        turnHigh turnMedium turnLow
        profilings { type time gForce }
        positions { time latitude longitude speed direction }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

REFUEL_EVENTS_QUERY = """
query RefuelEvents($id: ID, $from: Date, $to: Date, $limit: Int) {
  vehicle(id: $id) {
    refuelEvents(first: $from, last: $to, order: ASC, limit: $limit) {
      id time litersBefore litersAfter
      latestPosition { latitude longitude }
      latestPositionAddressString
    }
  }
}
"""


class ConnectedCarsError(Exception):
    """The API refused the login or answered a query with an error."""


class ConnectedCarsClient:
    """Read-only access to the vehicles, trips and refuel events of one account."""

    def __init__(self, auth_url: str, graphql_url: str, namespace: str):
        """Initialize the client.

        Args:
            auth_url: Email/password login endpoint
            graphql_url: GraphQL endpoint
            namespace: Brand app the account belongs to, e.g. 'minvolkswagen'
        """
        self.auth_url = auth_url
        self.graphql_url = graphql_url
        self.access_token: Optional[str] = None
        self.headers = {
            "Accept": "application/json",
            "x-organization-namespace": f"semler:{namespace}",
            "User-Agent": "ingest/1.0",
        }

    def login(self, email: str, password: str) -> Tuple[str, int]:
        """Log in and keep the access token for later queries.

        Returns:
            The access token and its lifetime in seconds
        """
        response = requests.post(
            self.auth_url,
            json={"email": email, "password": password},
            headers=self.headers,
            timeout=30,
        )
        body = response.json()
        if "token" not in body:
            raise ConnectedCarsError(
                f"Login failed (HTTP {response.status_code}): "
                f"{body.get('error', body)}"
            )
        self.access_token = body["token"]
        return body["token"], int(body["expires"])

    def get_vehicles(self) -> List[Dict[str, Any]]:
        """Return the vehicles of the account."""
        data = self._query(VEHICLES_QUERY, {})
        return [entry["vehicle"] for entry in data["viewer"]["vehicles"]]

    def iter_trips(
        self, vehicle_id: str, from_time: datetime, to_time: datetime
    ) -> Iterator[Dict[str, Any]]:
        """Yield the completed trips that overlap the period, oldest first.

        A page can hold fewer trips than asked for, or none, while more remain,
        so only pageInfo says when to stop.
        """
        cursor = None
        while True:
            data = self._query(
                TRIPS_QUERY,
                {
                    "id": vehicle_id,
                    "from": from_time.isoformat(),
                    "to": to_time.isoformat(),
                    "first": TRIP_PAGE_SIZE,
                    "after": cursor,
                },
            )
            trips = data["vehicle"]["trips"]
            yield from trips["items"]
            cursor = trips["pageInfo"]["endCursor"]
            if not trips["pageInfo"]["hasNextPage"] or cursor is None:
                return

    def get_refuel_events(
        self, vehicle_id: str, from_time: datetime, to_time: datetime
    ) -> List[Dict[str, Any]]:
        """Return the refuel events in the period, oldest first."""
        data = self._query(
            REFUEL_EVENTS_QUERY,
            {
                "id": vehicle_id,
                "from": from_time.isoformat(),
                "to": to_time.isoformat(),
                "limit": REFUEL_EVENT_LIMIT,
            },
        )
        return data["vehicle"]["refuelEvents"] or []

    def _query(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            self.graphql_url,
            json={"query": query, "variables": variables},
            headers={**self.headers, "Authorization": f"Bearer {self.access_token}"},
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        # A field that fails comes back as null next to an error. Stop rather
        # than store the null as if it were the real value.
        if body.get("errors"):
            messages = "; ".join(str(e.get("message")) for e in body["errors"])
            raise ConnectedCarsError(f"GraphQL error: {messages}")
        return body["data"]
