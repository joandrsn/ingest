"""Configuration management for the ingestion framework."""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Configuration class for database and application settings."""

    # Database configuration
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: str = os.getenv("DB_NAME", "ingest")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")

    # Eloverblik API configuration
    ELOVERBLIK_BASE_URL: str = os.getenv(
        "ELOVERBLIK_BASE_URL", "https://api.eloverblik.dk/customerapi/api"
    )

    # Techem API configuration (you'll need to provide the actual base URL)
    TECHEM_BASE_URL: str = os.getenv(
        "TECHEM_BASE_URL", "https://techemadmin.dk/analytics/graphql"
    )

    # Energidataservice API configuration
    ENERGIDATASERVICE_BASE_URL: str = os.getenv(
        "ENERGIDATASERVICE_BASE_URL", "https://api.energidataservice.dk"
    )

    # Logging configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def validate(cls) -> bool:
        """Validate that all required configuration is present.

        Returns:
            bool: True if configuration is valid, False otherwise
        """
        required_vars = [
            ("DB_HOST", cls.DB_HOST),
            ("DB_NAME", cls.DB_NAME),
            ("DB_USER", cls.DB_USER),
            ("DB_PASSWORD", cls.DB_PASSWORD),
        ]

        missing = []
        for var_name, var_value in required_vars:
            if not var_value:
                missing.append(var_name)

        if missing:
            print(f"Missing required configuration: {', '.join(missing)}")
            return False

        return True
