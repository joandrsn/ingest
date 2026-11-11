"""Energidataservice data provider implementation."""

import json
import time
import requests
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from providers.meter_reading_provider import MeterReadingProvider
from config import Config


class EnergidataserviceProvider(MeterReadingProvider):
    """Provider for Energidataservice electricity price data.

    This API requires no authentication.

    Each meter is one price component, stored in DKK/kWh excluding VAT.
    The meter identifier says what to fetch:

    - ``spot:<PriceArea>``                 e.g. ``spot:DK1``
      Day-ahead spot price (DayAheadPrices).
    - ``tariff:<GLN_Number>:<ChargeTypeCode>``  e.g. ``tariff:5790000432752:EA-001``
      A tariff from DatahubPricelist (grid tariff, Energinet tariffs, elafgift).
      Charge codes get renamed; list several separated by commas and the first
      one with a valid price is used, e.g. ``tariff:<GLN>:<new code>,<old code>``.

    Prices are stored per hour (spot averaged) before Config.QUARTERLY_FROM and
    per quarter-hour from that date, to line up with the consumption data.
    Tariffs are written for the intervals we have spot prices for, so a
    ``spot:`` meter must exist. Timestamps are stored in UTC (interval start).
    """

    def __init__(self, db_connection):
        """Initialize Energidataservice provider.

        Args:
            db_connection: Database connection object
        """
        super().__init__(db_connection, "Energidataservice")
        self.base_url = Config.ENERGIDATASERVICE_BASE_URL

    def authenticate(self) -> bool:
        """No authentication required for Energidataservice.

        Returns:
            bool: Always returns True
        """
        self.logger.debug("No authentication required for Energidataservice")
        return True

    def get_source_info(self) -> Optional[Dict[str, Any]]:
        """Get or create source information from the database.

        For Energidataservice, we may need to create the source if it doesn't exist
        since it doesn't require credentials.

        Returns:
            Dictionary containing source_id, or None if error
        """
        # Try to get existing source
        result = super().get_source_info()
        if result:
            return result

        # If source doesn't exist, create it
        self.logger.debug(f"Source '{self.source_name}' not found, creating it")

        try:
            query = """
                INSERT INTO source (name, credential_id)
                VALUES (%s, NULL)
                RETURNING source_id
            """
            result = self.db.fetch_one(query, (self.source_name,))
            if result:
                self.source_id = result["source_id"]
                self.credential_id = None
                return result
        except Exception as e:
            self.logger.error(f"Failed to create source: {e}")

        return None

    def fetch_data(
        self, start_date: datetime, end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch electricity price components from Energidataservice.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            List of dictionaries containing price readings
        """
        try:
            meters = self.get_meters()
            if not meters:
                self.logger.warning("No meters found for Energidataservice")
                return []

            spot_meters = []
            tariff_meters = []  # (meter, gln, charge_type_code)
            for meter in meters:
                parts = meter["identifier"].split(":")
                if parts[0] == "spot" and len(parts) == 2:
                    spot_meters.append((meter, parts[1]))
                elif parts[0] == "tariff" and len(parts) == 3:
                    tariff_meters.append((meter, parts[1], parts[2]))
                else:
                    self.logger.warning(
                        f"Skipping meter with unknown identifier '{meter['identifier']}' "
                        "(expected 'spot:<PriceArea>' or 'tariff:<GLN>:<ChargeTypeCode>')"
                    )

            if not spot_meters:
                self.logger.warning("No 'spot:<PriceArea>' meter found, nothing fetched")
                return []

            # Whole days in Danish time; a few days ahead to pick up tomorrow's prices
            date_from = start_date.strftime("%Y-%m-%dT00:00")
            date_to = (end_date + timedelta(days=3)).strftime("%Y-%m-%dT00:00")

            all_readings = []
            # Interval start in UTC -> interval start in Danish time
            intervals: Dict[str, str] = {}
            # Danish time from which prices are kept per quarter-hour
            quarterly_from = f"{Config.QUARTERLY_FROM}T00:00:00"

            for meter, price_area in spot_meters:
                records = self._get(
                    "DayAheadPrices",
                    {
                        "start": date_from,
                        "end": date_to,
                        "filter": json.dumps({"PriceArea": [price_area]}),
                        "sort": "TimeUTC ASC",
                        "limit": 0,
                    },
                )
                prices_by_interval = defaultdict(list)
                for record in records:
                    if record["TimeDK"] >= quarterly_from:
                        utc_start = record["TimeUTC"]
                    else:
                        # Before the switch: average the hour
                        utc_start = f"{record['TimeUTC'][:13]}:00:00"
                    prices_by_interval[utc_start].append(record["DayAheadPriceDKK"])
                    # Records are sorted, so the first one seen is the interval start
                    intervals.setdefault(utc_start, record["TimeDK"])

                for utc_start, prices in prices_by_interval.items():
                    # DKK/MWh -> DKK/kWh
                    value = sum(prices) / len(prices) / 1000
                    all_readings.append(self._reading(meter, utc_start, value))

            if tariff_meters:
                # One request for all tariffs: DatahubPricelist only allows
                # about one request per minute
                records = self._get(
                    "DatahubPricelist",
                    {
                        "filter": json.dumps(
                            {
                                "GLN_Number": sorted({g for _, g, _ in tariff_meters}),
                                "ChargeType": ["D03"],
                                "ChargeTypeCode": sorted(
                                    {
                                        code
                                        for _, _, codes in tariff_meters
                                        for code in codes.split(",")
                                    }
                                ),
                            }
                        ),
                        "sort": "ValidFrom DESC",
                        "limit": 0,
                    },
                )
            for meter, gln, codes in tariff_meters:
                # Codes in order of preference, each newest ValidFrom first
                tariffs = [
                    r
                    for code in codes.split(",")
                    for r in records
                    if r["GLN_Number"] == gln and r["ChargeTypeCode"] == code
                ]
                missing = 0
                for utc_start, dk_start in intervals.items():
                    value = self._tariff_price(tariffs, dk_start)
                    if value is None:
                        missing += 1
                        continue
                    all_readings.append(self._reading(meter, utc_start, value))
                if missing:
                    self.logger.warning(
                        f"No valid tariff for {missing} interval(s) for meter "
                        f"{meter['identifier']}"
                    )

            self.logger.debug(f"Fetched {len(all_readings)} price readings")
            return all_readings

        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error during data fetch: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error during data fetch: {e}", exc_info=True)
            raise

    def _get(self, dataset: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch all records of a dataset, waiting once if rate-limited."""
        url = f"{self.base_url}/dataset/{dataset}"
        response = requests.get(url, params=params, timeout=60)
        if response.status_code == 429:
            self.logger.debug(f"Rate limited on {dataset}, retrying in 60 seconds")
            time.sleep(60)
            response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json().get("records", [])

    @staticmethod
    def _reading(meter: Dict[str, Any], utc_start: str, value: float) -> Dict[str, Any]:
        return {
            "meter_id": meter["meter_id"],
            "timestamp": utc_start,
            # reading.value is DECIMAL(12,4)
            "value": round(value, 4),
        }

    @staticmethod
    def _tariff_price(tariffs: List[Dict[str, Any]], moment: str) -> Optional[float]:
        """Price in DKK/kWh at a Danish local time ("YYYY-MM-DDTHH:MM:SS").

        Args:
            tariffs: DatahubPricelist records for one charge, most preferred first
            moment: Danish local time

        Returns:
            The price, or None if no record is valid at that time
        """
        for tariff in tariffs:
            # ValidFrom/ValidTo are Danish local time; ValidTo is exclusive or open
            if tariff["ValidFrom"] > moment:
                continue
            if tariff["ValidTo"] is not None and tariff["ValidTo"] <= moment:
                continue
            # Price1..Price24 are per hour of day; flat tariffs only fill Price1
            price = tariff.get(f"Price{int(moment[11:13]) + 1}")
            return price if price is not None else tariff["Price1"]
        return None
