"""Techem data provider implementation."""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
from providers.base_provider import BaseProvider
from config import Config


class TechemProvider(BaseProvider):
    """Provider for Techem heating and water consumption data.

    Uses username/password authentication to obtain 15-minute access tokens.
    """

    def __init__(self, db_connection):
        """Initialize Techem provider.

        Args:
            db_connection: Database connection object
        """
        super().__init__(db_connection, "Techem")
        self.base_url = Config.TECHEM_BASE_URL

    def authenticate(self) -> bool:
        """Authenticate with Techem using username and password.

        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            # Check if we have a valid token in the database
            credentials = self.get_credentials()
            if not credentials:
                self.logger.error("No credentials found for Techem")
                return False

            # Check if existing access token is still valid
            if credentials.get("access_expiration"):
                now = datetime.now()
                if now < credentials["access_expiration"]:
                    self.access_token = credentials["access_token"]
                    self.token_expiration = credentials["access_expiration"]
                    self.logger.debug("Using existing valid access token")
                    return True

            # Get new access token using username and password
            username = credentials.get("username")
            password = credentials.get("password")

            if not username or not password:
                self.logger.error("Username or password not found")
                return False

            # Adjust the endpoint and payload based on actual Techem API
            url = self.base_url
            login_mutation = """
            mutation nucleolusLogin($credentials: CredentialsInput!) {
                loginWithEmailAndPassword(credentials: $credentials) {
                    ok {
                        token
                        refreshToken
                    }
                }
            }
            """

            payload = {
                "query": login_mutation,
                "variables": {
                    "credentials": {
                        "username": username,
                        "password": password,
                        "targetResource": "tenant",
                    }
                },
            }

            headers = {
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "en",
                "Accept": "*/*",
                "Connection": "keep-alive",
                "Content-Type": "application/json",
                "Origin": "https://app.techem.dk",
                "Priority": "u=4",
                "Referer": "https://app.techem.dk/",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
            }

            self.logger.debug("Requesting new access token")
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()

            # Adjust based on actual API response structure
            access_token = data["data"]["loginWithEmailAndPassword"]["ok"]["token"]
            self.logger.debug(f"Obtained access token: {access_token}")

            if not access_token:
                self.logger.error("No access token in response")
                return False

            # Access tokens are valid for 5 minutes
            duration = credentials.get("access_token_duration", timedelta(minutes=5))
            if isinstance(duration, str):
                # Parse duration string if needed
                duration = timedelta(minutes=5)

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
        """Fetch heating and water consumption data from Techem.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            List of dictionaries containing meter readings
        """
        tenant_graph_query = """
        query TenantGraph($graph: TenantGraphInput!) {
        tenantGraph(graph: $graph) {
            timestamps
            graphs {
            type
            consumption {
                quantityDescriptor {
                quantity
                normalized
                }
                values
                relatedValues {
                type
                values
                }
            }
            }
        }
        }
        """
        try:
            # Get all meters for this source
            meters = self.get_meters()
            if not meters:
                self.logger.warning("No meters found for Techem")
                return []

            all_readings = []

            date_from = start_date.strftime("%Y-%m-%d")
            date_to = end_date.strftime("%Y-%m-%d")
            url = self.base_url
            for meter in meters:
                self.logger.debug(
                    f"Fetching data for meter {meter['identifier']} ({meter['utility_name']})"
                )

                headers = {
                    "Accept-Language": "en",
                    "Accept": "application/graphql-response+json, application/json",
                    "Authorization": f"JWT {self.access_token}",
                    "Content-Type": "application/json",
                    "Referer": "https://app.techem.dk/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
                }

                payload = {
                    "query": tenant_graph_query,
                    "variables": {
                        "graph": {
                            "periodBegin": date_from,
                            "periodEnd": date_to,
                            "resolution": "DAY",
                            "consumption": {
                                "series": [
                                    {
                                        "quantityDescriptor": {
                                            "quantity": meter["identifier"],
                                            "normalized": False,
                                        }
                                    }
                                ]
                            },
                            "objectId": "cF9fMTU5NDAudV9fMjM1ODYx",
                        },
                    },
                    "operationName": "TenantGraph",
                }

                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()

                data = response.json()
                # Check for GraphQL errors
                if "errors" in data:
                    self.logger.error(
                        f"GraphQL errors for meter {meter['identifier']}: {data['errors']}"
                    )
                    continue

                # Parse the response (adjust based on actual API structure)
                readings = self._parse_techem_response(data, meter["meter_id"])
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

    def _parse_techem_response(
        self, data: Dict[str, Any], meter_id: int
    ) -> List[Dict[str, Any]]:
        """Parse Techem API response into readings.

        Args:
            data: Response data from Techem API
            meter_id: Database meter ID

        Returns:
            List of reading dictionaries
        """
        readings = []

        try:
            tenantgraph = data.get("data", {}).get("tenantGraph", {})
            timestamps = tenantgraph.get("timestamps", [])
            values = (
                tenantgraph.get("graphs", [])[0]
                .get("consumption", {})
                .get("values", [])
            )

            for timestamp, value in zip(timestamps, values):
                if value is not None and value > 0:
                    readings.append(
                        {
                            "meter_id": meter_id,
                            "timestamp": timestamp,
                            "value": round(value, 3),
                        }
                    )

        except Exception as e:
            self.logger.error(f"Error parsing Techem response: {e}", exc_info=True)

        return readings
