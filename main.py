"""Main script for ingesting data from multiple providers."""

import sys
import logging
from datetime import datetime, timedelta

from config import Config
from utils.database import Database
from providers.eloverblik_provider import EloverblikProvider
from providers.techem_provider import TechemProvider
from providers.energidataservice_provider import EnergidataserviceProvider


def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        format=Config.LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("ingest.log")],
    )


def main():
    """Main execution function."""
    logger = logging.getLogger(__name__)

    # Setup logging
    setup_logging()

    # Set default date range (last 7 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    logger.info(
        "Starting data ingestion: %s to %s",
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
    )

    # Validate configuration
    if not Config.validate():
        logger.error("Configuration validation failed. Please check your .env file.")
        return 1

    # Initialize database connection
    db = Database(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        database=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
    )

    if not db.connect():
        logger.error("Failed to connect to database")
        return 1

    # List of providers to run
    provider_classes = [EloverblikProvider, TechemProvider, EnergidataserviceProvider]

    # Track results
    results = {"success": [], "failed": [], "inserted": {}}

    # Run each provider
    for ProviderClass in provider_classes:
        provider_name = ProviderClass.__name__.replace("Provider", "")

        try:
            logger.debug("Processing provider: %s", provider_name)

            # Instantiate provider
            provider = ProviderClass(db)

            # Run provider
            success, inserted_count = provider.run(start_date, end_date)

            if success:
                results["success"].append(provider_name)
                results["inserted"][provider_name] = inserted_count
                if inserted_count > 0:
                    logger.info(
                        "✓ %s: inserted %d readings", provider_name, inserted_count
                    )
                else:
                    logger.debug("✓ %s: no new readings", provider_name)
            else:
                logger.warning("✗ %s completed with issues", provider_name)
                results["failed"].append(provider_name)

        except Exception as e:
            logger.error("✗ %s failed: %s", provider_name, str(e), exc_info=True)
            results["failed"].append(provider_name)
            continue

    # Cleanup
    db.disconnect()

    # Print summary
    total_inserted = sum(results["inserted"].values())
    if total_inserted > 0 or results["failed"]:
        logger.info(
            "Summary: %d providers succeeded, %d failed, %d total readings inserted",
            len(results["success"]),
            len(results["failed"]),
            total_inserted,
        )

        if results["failed"]:
            logger.warning("Failed providers: %s", ", ".join(results["failed"]))
    else:
        logger.debug("All providers completed successfully (no new data)")

    # Return exit code based on results
    return 0 if not results["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
