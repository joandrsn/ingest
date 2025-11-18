"""Database connection and query utilities."""

import psycopg2
import psycopg2.extras
from typing import Optional, List, Dict, Any, Tuple
import logging


class Database:
    """PostgreSQL database connection manager."""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        """Initialize database connection parameters.

        Args:
            host: Database host
            port: Database port
            database: Database name
            user: Database user
            password: Database password
        """
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.connection = None
        self.logger = logging.getLogger(__name__)

    def connect(self) -> bool:
        """Establish database connection.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
            )
            self.connection.autocommit = False
            self.logger.debug("Database connection established")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to database: {e}")
            return False

    def disconnect(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.logger.debug("Database connection closed")

    def fetch_one(
        self, query: str, params: Optional[Tuple] = None
    ) -> Optional[Dict[str, Any]]:
        """Execute a query and fetch one result.

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            Dictionary with column names as keys, or None if no results
        """
        try:
            with self.connection.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cursor:
                cursor.execute(query, params)
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            self.logger.error(f"Error executing query: {e}")
            self.connection.rollback()
            raise

    def fetch_all(
        self, query: str, params: Optional[Tuple] = None
    ) -> List[Dict[str, Any]]:
        """Execute a query and fetch all results.

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            List of dictionaries with column names as keys
        """
        try:
            with self.connection.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cursor:
                cursor.execute(query, params)
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            self.logger.error(f"Error executing query: {e}")
            self.connection.rollback()
            raise

    def execute(self, query: str, params: Optional[Tuple] = None) -> int:
        """Execute a query that modifies data (INSERT, UPDATE, DELETE).

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            Number of rows affected
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.rowcount
        except Exception as e:
            self.logger.error(f"Error executing query: {e}")
            self.connection.rollback()
            raise

    def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """Execute a query multiple times with different parameters.

        Args:
            query: SQL query to execute
            params_list: List of parameter tuples

        Returns:
            Number of rows affected
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.executemany(query, params_list)
                return cursor.rowcount
        except Exception as e:
            self.logger.error(f"Error executing batch query: {e}")
            self.connection.rollback()
            raise

    def begin_transaction(self):
        """Begin an explicit transaction."""
        # Connection already has autocommit=False, so we're always in a transaction
        pass

    def commit(self):
        """Commit the current transaction."""
        if self.connection:
            self.connection.commit()
            self.logger.debug("Transaction committed")

    def rollback(self):
        """Rollback the current transaction."""
        if self.connection:
            self.connection.rollback()
            self.logger.debug("Transaction rolled back")

    def transaction(self):
        """Context manager for transaction handling.

        Usage:
            with db.transaction():
                db.execute(query1)
                db.execute(query2)
        """
        return TransactionContext(self)

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


class TransactionContext:
    """Context manager for database transactions."""

    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.db.commit()
        else:
            self.db.rollback()
        return False  # Don't suppress exceptions
