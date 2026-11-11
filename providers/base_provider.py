"""Base provider abstract class for all data ingestion providers."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime
import logging


class BaseProvider(ABC):
    """Abstract base class for all data providers.

    Handles what every provider needs: the source row, credentials and the
    cached access token. What is fetched and where it is stored is up to the
    subclass; see MeterReadingProvider for providers that store meter readings.
    """

    def __init__(self, db_connection, source_name: str):
        """Initialize the provider.

        Args:
            db_connection: Database connection object
            source_name: Name of the data source (e.g., 'Eloverblik', 'Techem')
        """
        self.db = db_connection
        self.source_name = source_name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.access_token: Optional[str] = None
        self.token_expiration: Optional[datetime] = None
        self.source_id: Optional[int] = None
        self.credential_id: Optional[int] = None

    @abstractmethod
    def authenticate(self) -> bool:
        """Authenticate with the provider and obtain an access token.

        Returns:
            bool: True if authentication successful, False otherwise
        """
        pass

    @abstractmethod
    def run(self, start_date: datetime, end_date: datetime) -> tuple[bool, int]:
        """Fetch and store data for the specified date range.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            tuple: (success: bool, inserted_count: int)
        """
        pass

    def is_token_valid(self) -> bool:
        """Check if the current access token is still valid.

        Returns:
            bool: True if token is valid, False otherwise
        """
        if not self.access_token or not self.token_expiration:
            return False
        return datetime.now() < self.token_expiration

    def get_source_info(self) -> Optional[Dict[str, Any]]:
        """Get source information from the database.

        Returns:
            Dictionary containing source_id and credential_id, or None if not found
        """
        query = """
            SELECT s.source_id, s.credential_id
            FROM source s
            WHERE s.name = %s
        """
        result = self.db.fetch_one(query, (self.source_name,))
        if result:
            self.source_id = result["source_id"]
            self.credential_id = result["credential_id"]
            return result
        return None

    def get_credentials(self) -> Optional[Dict[str, Any]]:
        """Get credentials from the database.

        Returns:
            Dictionary containing credential information, or None if not found
        """
        if not self.credential_id:
            source_info = self.get_source_info()
            if not source_info:
                self.logger.error(f"Source '{self.source_name}' not found in database")
                return None

        query = """
            SELECT credential_id, authtype, username, password, refreshtoken,
                   expirationdate, access_token, access_token_duration,
                   access_expiration
            FROM credential
            WHERE credential_id = %s
        """
        return self.db.fetch_one(query, (self.credential_id,))

    def update_access_token(self, access_token: str, expiration: datetime) -> bool:
        """Update the access token in the database.

        Args:
            access_token: The new access token
            expiration: When the token expires

        Returns:
            bool: True if update successful, False otherwise
        """
        query = """
            UPDATE credential
            SET access_token = %s, access_expiration = %s
            WHERE credential_id = %s
        """
        try:
            self.db.execute(query, (access_token, expiration, self.credential_id))
            self.db.commit()
            self.access_token = access_token
            self.token_expiration = expiration
            return True
        except Exception as e:
            self.logger.error(f"Failed to update access token: {e}")
            return False
