"""Base class for providers that store meter readings."""

from abc import abstractmethod
from typing import Dict, Any, List
from datetime import datetime

from providers.base_provider import BaseProvider


class MeterReadingProvider(BaseProvider):
    """A provider whose data is one value per meter per timestamp.

    Subclasses implement authentication and data fetching; this class stores
    the result in the ``reading`` table.
    """

    @abstractmethod
    def fetch_data(
        self, start_date: datetime, end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch data from the provider for the specified date range.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            List of dictionaries containing the fetched data
        """
        pass

    def get_meters(self) -> List[Dict[str, Any]]:
        """Get all meters for this source from the database.

        Returns:
            List of dictionaries containing meter information
        """
        if not self.source_id:
            self.get_source_info()

        query = """
            SELECT m.meter_id, m.identifier, m.resolution, u.name as utility_name, u.unit
            FROM meter m
            JOIN utility u ON m.utility_id = u.utility_id
            WHERE m.source_id = %s
        """
        return self.db.fetch_all(query, (self.source_id,))

    def insert_readings(self, readings: List[Dict[str, Any]]) -> int:
        """Insert readings into the database with gapless sequential reading_id.

        Args:
            readings: List of dictionaries with keys: meter_id, timestamp, value

        Returns:
            Number of readings inserted
        """
        if not readings:
            return 0

        try:
            with self.db.transaction():
                # Step 1: Create temporary table
                create_temp_table = """
                    CREATE TEMPORARY TABLE reading_to_be_inserted (
                        meter_id INTEGER NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        value NUMERIC NOT NULL
                    ) ON COMMIT DROP
                """
                self.db.execute(create_temp_table)

                # Step 2: Insert all readings into temporary table
                insert_temp = """
                    INSERT INTO reading_to_be_inserted (meter_id, timestamp, value)
                    VALUES (%s, %s, %s)
                """
                values = [(r["meter_id"], r["timestamp"], r["value"]) for r in readings]
                self.db.execute_many(insert_temp, values)

                # Step 3: Update existing readings that match
                update_existing = """
                    UPDATE reading r
                    SET value = t.value
                    FROM reading_to_be_inserted t
                    WHERE r.meter_id = t.meter_id
                      AND r.timestamp = t.timestamp
                      AND r.value != t.value
                """
                updated_count = self.db.execute(update_existing)
                if updated_count > 0:
                    self.logger.debug(f"Updated {updated_count} existing readings")

                # Step 4: Insert new readings
                insert_new = """
                    INSERT INTO reading (meter_id, timestamp, value)
                    SELECT
                        t.meter_id,
                        t.timestamp,
                        t.value
                    FROM reading_to_be_inserted t
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM reading r
                        WHERE r.meter_id = t.meter_id
                          AND r.timestamp = t.timestamp
                    )
                    ORDER BY t.timestamp
                    ON CONFLICT (meter_id, timestamp) DO NOTHING
                """
                inserted_count = self.db.execute(insert_new)

                if inserted_count > 0:
                    self.logger.debug(f"Inserted {inserted_count} new readings")
                else:
                    self.logger.debug("All readings already exist in database")

                return inserted_count

        except Exception as e:
            self.logger.error(f"Error inserting readings: {e}", exc_info=True)
            raise

    def run(self, start_date: datetime, end_date: datetime) -> tuple[bool, int]:
        """Main execution method for the provider.

        Args:
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            tuple: (success: bool, inserted_count: int)
        """
        try:
            self.logger.debug(f"Starting data ingestion for {self.source_name}")

            # Get source information
            if not self.get_source_info():
                self.logger.error(f"Source '{self.source_name}' not found")
                return False, 0

            # Authenticate
            if not self.authenticate():
                self.logger.error(f"Authentication failed for {self.source_name}")
                return False, 0

            # Fetch data
            self.logger.debug(f"Fetching data from {start_date} to {end_date}")
            data = self.fetch_data(start_date, end_date)

            if not data:
                self.logger.debug(f"No data fetched for {self.source_name}")
                return True, 0

            # Insert data
            inserted = self.insert_readings(data)
            if inserted > 0:
                self.logger.info(
                    f"{self.source_name}: Inserted {inserted} new readings"
                )

            return True, inserted

        except Exception as e:
            self.logger.error(
                f"Error in {self.source_name} provider: {e}", exc_info=True
            )
            return False, 0
