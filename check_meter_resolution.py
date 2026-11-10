"""Check whether your Eloverblik metering points are read hourly or every 15 minutes,
and when the 15-minute readings started.

Standalone: needs no database. Set these environment variables (or put them in .env):

    ELOVERBLIK_REFRESH_TOKEN   refresh token from the Eloverblik portal (required)
    ELOVERBLIK_BASE_URL        optional, defaults to the public customer API

Usage (PowerShell):

    $env:ELOVERBLIK_REFRESH_TOKEN = "..."; python check_meter_resolution.py
"""

import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("ELOVERBLIK_BASE_URL", "https://api.eloverblik.dk/customerapi/api")


def main() -> int:
    refresh_token = os.getenv("ELOVERBLIK_REFRESH_TOKEN")
    if not refresh_token:
        print("Set ELOVERBLIK_REFRESH_TOKEN first.")
        return 1

    response = requests.get(
        f"{BASE_URL}/token",
        headers={"Authorization": f"Bearer {refresh_token}"},
        timeout=60,
    )
    response.raise_for_status()
    headers = {"Authorization": f"Bearer {response.json()['result']}"}

    response = requests.get(
        f"{BASE_URL}/meteringpoints/meteringpoints", headers=headers, timeout=60
    )
    response.raise_for_status()
    metering_points = response.json().get("result", [])
    if not metering_points:
        print("No metering points found for this token.")
        return 1

    # What the meter is registered as
    for mp in metering_points:
        print(
            f"{mp.get('meteringPointId')} ({mp.get('typeOfMP')}): "
            f"registered reading interval = {mp.get('meterReadingOccurrence')}"
        )
    print("PT15M = 15-minute intervals, PT1H = hourly.")

    # When did 15-minute readings start? "Actual" returns the data in the
    # resolution it was read in, one period per day. 720 days is the API maximum.
    quarterly = [
        mp["meteringPointId"]
        for mp in metering_points
        if mp.get("meterReadingOccurrence") == "PT15M"
    ]
    if not quarterly:
        print()
        print("No metering points are registered with 15-minute readings.")
        return 0

    date_to = date.today()
    date_from = date_to - timedelta(days=720)
    response = requests.post(
        f"{BASE_URL}/meterdata/gettimeseries/{date_from}/{date_to}/Actual",
        headers=headers,
        json={"meteringPoints": {"meteringPoint": quarterly}},
        timeout=300,
    )
    response.raise_for_status()

    print()
    print(f"Delivered data, {date_from} to {date_to}:")
    for item in response.json().get("result", []):
        document = item.get("MyEnergyData_MarketDocument") or {}
        for series in document.get("TimeSeries", []):
            # Danish date -> resolution
            days = {}
            for period in series.get("Period", []):
                start = datetime.fromisoformat(
                    period["timeInterval"]["start"].replace("Z", "+00:00")
                )
                # Periods start at Danish midnight = 22:00 or 23:00 UTC the day before
                days[(start + timedelta(hours=2)).date()] = period.get("resolution")

            print(f"{series.get('mRID')}:")
            if not days:
                print("  no data")
                continue
            for resolution, count in Counter(days.values()).items():
                print(f"  {resolution}: {count} day(s)")
            quarter_days = sorted(d for d, r in days.items() if r == "PT15M")
            other_days = sorted(d for d, r in days.items() if r != "PT15M")
            if not quarter_days:
                print("  no 15-minute data delivered yet")
            elif min(days) == quarter_days[0]:
                print(f"  15-minute readings since {quarter_days[0]} or earlier")
            else:
                print(f"  first day with 15-minute readings: {quarter_days[0]}")
                print(f"  last day with other readings:      {other_days[-1]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
