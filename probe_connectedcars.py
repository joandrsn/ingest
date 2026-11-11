"""Read-only probe of the ConnectedCars GraphQL API.

Logs in with CONNECTEDCARS_* from .env and prints what the API offers for the
account's vehicles. Sends only queries, never mutations. Addresses, coordinates,
VIN and licence plate are reported as present/absent, never printed.

Usage:
    python probe_connectedcars.py schema   # types and arguments (no personal data)
    python probe_connectedcars.py data     # what this account's car returns
"""

import os
import sys
from collections import Counter

import requests
from dotenv import load_dotenv

AUTH_URL = "https://auth-api.connectedcars.io/auth/login/email/password"
GRAPHQL_URL = "https://api.connectedcars.io/graphql"
SENSITIVE = ("address", "latitude", "longitude", "vin", "licenseplate", "note")

load_dotenv()
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "x-organization-namespace": f"semler:{os.environ['CONNECTEDCARS_NAMESPACE']}",
    "User-Agent": "ingest-probe/1.0",
}


def login():
    response = requests.post(
        AUTH_URL,
        json={
            "email": os.environ["CONNECTEDCARS_EMAIL"],
            "password": os.environ["CONNECTEDCARS_PASSWORD"],
        },
        headers=HEADERS,
        timeout=30,
    )
    body = response.json()
    if "token" not in body:
        sys.exit(f"Login failed: HTTP {response.status_code} {body.get('error', body)}")
    print(f"Login ok, token expires in {body['expires']} s")
    HEADERS["Authorization"] = f"Bearer {body['token']}"


def graphql(query):
    response = requests.post(
        GRAPHQL_URL, json={"query": query}, headers=HEADERS, timeout=60
    )
    body = response.json()
    for error in body.get("errors", []):
        print(f"  GraphQL error: {error.get('message')}")
    return body.get("data") or {}


TYPE_REF = "name kind ofType { name kind ofType { name kind ofType { name kind } } }"


def type_name(ref):
    """Render a type reference such as [VehicleTrip!]! as text."""
    if ref["kind"] == "NON_NULL":
        return type_name(ref["ofType"]) + "!"
    if ref["kind"] == "LIST":
        return "[" + type_name(ref["ofType"]) + "]"
    return ref["name"]


def show_type(name, only=None):
    data = graphql(
        """{ __type(name: "%s") { kind enumValues { name } fields {
             name description type { %s } args { name type { %s } } } } }"""
        % (name, TYPE_REF, TYPE_REF)
    )
    info = data.get("__type")
    if not info:
        print(f"\n== {name}: not found")
        return
    print(f"\n== {name} ({info['kind']})")
    for value in info.get("enumValues") or []:
        print(f"  {value['name']}")
    for field in info.get("fields") or []:
        if only and not any(word in field["name"].lower() for word in only):
            continue
        args = ", ".join(f"{a['name']}: {type_name(a['type'])}" for a in field["args"])
        description = (field.get("description") or "").replace("\n", " ")[:110]
        print(
            f"  {field['name']}{'(' + args + ')' if args else ''}: "
            f"{type_name(field['type'])}  {description}"
        )


def redact(key, value):
    if value is None:
        return None
    if any(word in key.lower() for word in SENSITIVE):
        return "<present>"
    return value


def show_schema(type_names):
    show_type(
        "Vehicle",
        only=("trip", "refuel", "fuel", "odometer", "position", "mileage"),
    )
    for name in type_names:
        show_type(name)


def show_data():
    data = graphql(
        """{ viewer { vehicles { primary vehicle {
             id vin licensePlate make model year fuelType fuelEconomy
             odometer { odometer time } fuelLevel { liter time }
             fuelPercentage { percent time } fuelTankSize(limit: 1)
             refuelEvents(limit: 10) { time litersBefore litersAfter }
           } } } }"""
    )
    for entry in (data.get("viewer") or {}).get("vehicles") or []:
        vehicle = entry["vehicle"]
        print("\n== Vehicle")
        for key, value in vehicle.items():
            print(f"  {key}: {redact(key, value)}")
        show_trips(vehicle["id"])


TRIP_FIELDS = """id startTime endTime time duration idleTime mileage gpsMileage
  odometerMileage startOdometer endOdometer fuelUsed electricityUsed
  startAddressString endAddressString startLatitude startLongitude
  endLatitude endLongitude tripType note"""


def show_trips(vehicle_id):
    newest = graphql(
        "{ vehicle(id: %s) { trips(last: 5, ignoreEmpty: true) { items { %s "
        "positions { time latitude longitude } } } } }" % (vehicle_id, TRIP_FIELDS)
    )
    items = ((newest.get("vehicle") or {}).get("trips") or {}).get("items") or []
    print(f"\n== Newest {len(items)} trips")
    for trip in items:
        positions = trip.pop("positions", None) or []
        print("  " + ", ".join(f"{k}={redact(k, v)}" for k, v in trip.items()))
        times = [p["time"] for p in positions]
        print(
            f"    positions: {len(positions)}"
            + (f", first {times[0]}, last {times[-1]}" if times else "")
        )

    oldest = graphql(
        "{ vehicle(id: %s) { trips(first: 1, ignoreEmpty: true) { items "
        "{ id startTime } } } }" % vehicle_id
    )
    print(f"\n== Oldest trip: {oldest}")

    year = graphql(
        '{ vehicle(id: %s) { trips(fromTime: "2026-01-01T00:00:00Z", first: 1000, '
        "ignoreEmpty: true) { items { id startTime fuelUsed mileage } } } }"
        % vehicle_id
    )
    items = ((year.get("vehicle") or {}).get("trips") or {}).get("items") or []
    print(f"\n== Trips returned for 2026 with first: 1000 -> {len(items)}")
    if items:
        print(f"  range {items[0]['startTime']} .. {items[-1]['startTime']}")
        print(f"  ids unique: {len({t['id'] for t in items}) == len(items)}")
        print(f"  fuelUsed populated: {sum(t['fuelUsed'] is not None for t in items)}")
        print(f"  trips per month: {dict(Counter(t['startTime'][:7] for t in items))}")


def trips_page(vehicle_id, arguments, fields="id startTime mileage fuelUsed"):
    data = graphql(
        "{ vehicle(id: %s) { trips(%s) { items { %s } pageInfo "
        "{ hasNextPage endCursor } } } }" % (vehicle_id, arguments, fields)
    )
    return (data.get("vehicle") or {}).get("trips") or {"items": [], "pageInfo": {}}


def show_history(vehicle_id):
    """How far back trips go, how paging behaves, and trip fuel vs refuel events."""
    oldest = trips_page(vehicle_id, 'fromTime: "2010-01-01T00:00:00Z", first: 1')
    print(f"Oldest trip: {[t['startTime'] for t in oldest['items']]}")

    trips, cursor, pages = [], None, 0
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        page = trips_page(
            vehicle_id, 'fromTime: "2010-01-01T00:00:00Z", first: 500' + after
        )
        trips += page["items"]
        pages += 1
        print(f"  page {pages}: {len(page['items'])} trips, {page['pageInfo']}")
        cursor = page["pageInfo"].get("endCursor")
        if not page["pageInfo"].get("hasNextPage") or not page["items"]:
            break
    print(f"Total trips: {len(trips)}, unique ids: {len({t['id'] for t in trips})}")
    print(f"Trips per year: {dict(Counter(t['startTime'][:4] for t in trips))}")

    data = graphql(
        "{ vehicle(id: %s) { refuelEvents(limit: 500, order: ASC) "
        "{ time litersBefore litersAfter litersDifference kilometersDifference } } }"
        % vehicle_id
    )
    refuels = (data.get("vehicle") or {}).get("refuelEvents") or []
    print(f"Refuel events: {len(refuels)}")
    if refuels:
        print(f"  first {refuels[0]['time']}, last {refuels[-1]['time']}")
    print("  between refuels: trip km, trip fuelUsed, gauge drop, event km/litres")
    for previous, current in list(zip(refuels, refuels[1:]))[-12:]:
        between = [
            t for t in trips if previous["time"] <= t["startTime"] < current["time"]
        ]
        km = sum(t["mileage"] or 0 for t in between)
        used = sum(t["fuelUsed"] or 0 for t in between)
        drop = previous["litersAfter"] - current["litersBefore"]
        print(
            f"  {current['time'][:10]}: {km:7.1f} km, {used:5.1f} l used, "
            f"gauge drop {drop} l, event {current['kilometersDifference']} km / "
            f"{current['litersDifference']} l"
        )


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "schema"
    login()
    if mode == "schema":
        show_schema(sys.argv[2:])
    elif mode == "history":
        show_history(sys.argv[2])
    else:
        show_data()
