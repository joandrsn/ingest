"""Energidataservice data provider implementation."""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from providers.base_provider import BaseProvider
from config import Config


class EnergidataserviceProvider(BaseProvider):
    """Provider for Energidataservice electricity price data.

    This API requires no authentication.
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
        """Fetch electricity price data from Energidataservice.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            List of dictionaries containing price readings
        """
        try:
            # Get all meters for this source (if any are configured)
            meters = self.get_meters()
            if not meters:
                self.logger.warning("No meters found for Energidataservice")
                return []

            end_date = end_date + timedelta(days=7)  # For future prices

            all_readings = []
            url = 'https://api.energidataservice.dk/dataset/DayAheadPrices?start=2025-10-18T00:00&end=2025-10-25T00:00&filter={"PriceArea":["DK1"]}'

            for meter in meters:
                self.logger.debug(
                    f"Fetching price data for meter {meter['identifier']}"
                )

                # Format dates for API (ISO format)
                date_from = start_date.strftime("%Y-%m-%dT%H:%M")
                date_to = end_date.strftime("%Y-%m-%dT%H:%M")

                # Energidataservice API endpoint for electricity prices
                # Adjust based on actual API - common endpoints:
                # - /dataset/Elspotprices (spot prices)
                # - /dataset/DatahubPricelist (various price types)
                url = f"{self.base_url}/dataset/DayAheadPrices"

                params = {
                    "start": date_from,
                    "end": date_to,
                    "offset": 0,
                    "filter": '{"PriceArea":["DK1"]}',
                    "sort": "TimeUTC ASC",
                }

                headers = {"Content-Type": "application/json"}

                response = requests.get(url, params=params, headers=headers)
                response.raise_for_status()

                data = response.json()

                # Parse the response
                readings = self._parse_energidataservice_response(
                    data, meter["meter_id"]
                )
                all_readings.extend(readings)

                self.logger.debug(f"Fetched {len(readings)} price readings")

            return all_readings

        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error during data fetch: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error during data fetch: {e}", exc_info=True)
            raise

    def _parse_energidataservice_response(
        self, data: Dict[str, Any], meter_id: int
    ) -> List[Dict[str, Any]]:
        """Parse Energidataservice API response into readings.

        Args:
            data: Response data from Energidataservice API
            meter_id: Database meter ID

        Returns:
            List of reading dictionaries
        """
        readings = []

        try:
            # The API typically returns a 'records' list
            records = data.get("records", [])

            for record in records:
                timestamp = record.get("TimeUTC")
                readings.append(
                    {
                        "meter_id": meter_id,
                        "timestamp": timestamp,
                        "value": record.get("DayAheadPriceDKK"),
                    }
                )

        except Exception as e:
            self.logger.error(
                f"Error parsing Energidataservice response: {e}", exc_info=True
            )

        return readings
