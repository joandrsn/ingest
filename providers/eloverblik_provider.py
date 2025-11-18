"""Eloverblik data provider implementation."""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
from providers.base_provider import BaseProvider
from config import Config


class EloverblikProvider(BaseProvider):
    """Provider for Eloverblik electricity consumption data.

    Uses refresh token authentication to obtain 24-hour access tokens.
    """

    def __init__(self, db_connection):
        """Initialize Eloverblik provider.

        Args:
            db_connection: Database connection object
        """
        super().__init__(db_connection, "Eloverblik")
        self.base_url = Config.ELOVERBLIK_BASE_URL

    def authenticate(self) -> bool:
        """Authenticate with Eloverblik using refresh token.

        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            # Check if we have a valid token in the database
            credentials = self.get_credentials()
            if not credentials:
                self.logger.error("No credentials found for Eloverblik")
                return False

            # Check if existing access token is still valid
            if credentials.get("access_expiration"):
                if datetime.now() < credentials["access_expiration"]:
                    self.access_token = credentials["access_token"]
                    self.token_expiration = credentials["access_expiration"]
                    self.logger.debug("Using existing valid access token")
                    return True

            # Get new access token using refresh token
            refresh_token = credentials.get("refreshtoken")
            if not refresh_token:
                self.logger.error("No refresh token found")
                return False

            url = f"{self.base_url}/token"
            headers = {
                "Authorization": f"Bearer {refresh_token}",
                "Content-Type": "application/json",
            }

            self.logger.debug("Requesting new access token")
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            data = response.json()
            access_token = data.get("result")
            self.logger.debug(f"Obtained access token: {access_token}")

            if not access_token:
                self.logger.error("No access token in response")
                return False

            # Access tokens are valid for 24 hours
            duration = credentials.get("access_token_duration", timedelta(hours=24))
            if isinstance(duration, str):
                # Parse duration string if needed
                duration = timedelta(hours=24)

            expiration = datetime.now() + duration

            # Update token in database
            self.update_access_token(access_token, expiration)

            self.logger.debug("Successfully obtained new access token")
            return True

        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error during authentication: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error during authentication: {e}", exc_info=True)
            return False

    def fetch_data(
        self, start_date: datetime, end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch electricity consumption data from Eloverblik.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            List of dictionaries containing meter readings
        """
        try:
            # Get all meters for this source
            meters = self.get_meters()
            if not meters:
                self.logger.warning("No meters found for Eloverblik")
                return []

            all_readings = []

            for meter in meters:
                self.logger.debug(f"Fetching data for meter {meter['identifier']}")

                # Get metering points (in Eloverblik, the identifier is the metering point ID)
                metering_point_ids = [meter["identifier"]]

                # Format dates for API
                date_from = start_date.strftime("%Y-%m-%d")
                date_to = end_date.strftime("%Y-%m-%d")

                # Determine aggregation based on resolution
                aggregation = (
                    "Quarter" if meter["resolution"] == "quarterly" else "Hour"
                )

                url = f"{self.base_url}/meterdata/gettimeseries/{date_from}/{date_to}/{aggregation}"

                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                }

                payload = {"meteringPoints": {"meteringPoint": metering_point_ids}}

                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()

                data = response.json()

                # Parse the response
                readings = self._parse_eloverblik_response(data, meter["meter_id"])
                all_readings.extend(readings)

                self.logger.debug(
                    f"Fetched {len(readings)} readings for meter {meter['identifier']}"
                )

            return all_readings

        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error during data fetch: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error during data fetch: {e}", exc_info=True)
            raise

    def _parse_eloverblik_response(
        self, data: Dict[str, Any], meter_id: int
    ) -> List[Dict[str, Any]]:
        """Parse Eloverblik API response into readings.

        Args:
            data: Response data from Eloverblik API
            meter_id: Database meter ID

        Returns:
            List of reading dictionaries
        """
        readings = []

        try:
            result = data.get("result", [])

            for metering_point_data in result:
                my_energy_data_info = metering_point_data.get(
                    "MyEnergyData_MarketDocument", {}
                )
                time_series_list = my_energy_data_info.get("TimeSeries", [])

                for time_series in time_series_list:
                    periods = time_series.get("Period", [])

                    for period in periods:
                        points = period.get("Point", [])

                        for point in points:
                            # Position is 1-indexed in the API
                            position = int(point.get("position", 0))
                            value = float(point.get("out_Quantity.quantity", 0))

                            # Get the start time from the period
                            time_interval = period.get("timeInterval", {})
                            start_str = time_interval.get("start")

                            if start_str:
                                # Parse ISO format timestamp
                                timestamp = datetime.fromisoformat(
                                    start_str.replace("Z", "+00:00")
                                )

                                # Add hours based on position (position 1 = hour 0-1, etc.)
                                timestamp = timestamp + timedelta(hours=position - 1)

                                readings.append(
                                    {
                                        "meter_id": meter_id,
                                        "timestamp": timestamp,
                                        "value": value,
                                    }
                                )

        except Exception as e:
            self.logger.error(f"Error parsing Eloverblik response: {e}", exc_info=True)

        return readings
