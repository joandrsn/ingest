"""Test database connection and display configuration."""

import sys
from config import Config
from utils.database import Database


def main():
    """Test database connection and show configuration."""
    print("=" * 80)
    print("Database Connection Test")
    print("=" * 80)

    # Validate configuration
    print("\n1. Validating configuration...")
    if not Config.validate():
        print("❌ Configuration validation failed")
        return 1
    print("✓ Configuration is valid")

    # Show configuration (without sensitive data)
    print("\n2. Database configuration:")
    print(f"   Host: {Config.DB_HOST}")
    print(f"   Port: {Config.DB_PORT}")
    print(f"   Database: {Config.DB_NAME}")
    print(f"   User: {Config.DB_USER}")
    print(f"   Password: {'*' * len(Config.DB_PASSWORD)}")

    # Test connection
    print("\n3. Testing database connection...")
    db = Database(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        database=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
    )

    if not db.connect():
        print("❌ Failed to connect to database")
        return 1
    print("✓ Successfully connected to database")

    # Test query - get sources
    print("\n4. Checking sources...")
    try:
        sources = db.fetch_all("SELECT source_id, name FROM source ORDER BY source_id")
        if sources:
            print(f"✓ Found {len(sources)} source(s):")
            for source in sources:
                print(f"   - {source['name']} (ID: {source['source_id']})")
        else:
            print("⚠ No sources found in database")
    except Exception as e:
        print(f"❌ Error querying sources: {e}")
        db.disconnect()
        return 1

    # Test query - get meters
    print("\n5. Checking meters...")
    try:
        query = """
            SELECT m.meter_id, m.identifier, m.resolution, 
                   u.name as utility, s.name as source
            FROM meter m
            JOIN utility u ON m.utility_id = u.utility_id
            JOIN source s ON m.source_id = s.source_id
            ORDER BY s.name, u.name
        """
        meters = db.fetch_all(query)
        if meters:
            print(f"✓ Found {len(meters)} meter(s):")
            for meter in meters:
                print(
                    f"   - {meter['source']}: {meter['utility']} - {meter['identifier']} ({meter['resolution']})"
                )
        else:
            print("⚠ No meters found in database")
    except Exception as e:
        print(f"❌ Error querying meters: {e}")
        db.disconnect()
        return 1

    # Test query - get credentials (without sensitive data)
    print("\n6. Checking credentials...")
    try:
        query = """
            SELECT c.credential_id, c.authtype, s.name as source_name,
                   CASE WHEN c.access_expiration > NOW() THEN 'Valid' ELSE 'Expired' END as token_status
            FROM credential c
            JOIN source s ON s.credential_id = c.credential_id
            ORDER BY c.credential_id
        """
        credentials = db.fetch_all(query)
        if credentials:
            print(f"✓ Found {len(credentials)} credential(s):")
            for cred in credentials:
                print(
                    f"   - {cred['source_name']}: {cred['authtype']} (Token: {cred.get('token_status', 'N/A')})"
                )
        else:
            print("⚠ No credentials found in database")
    except Exception as e:
        print(f"❌ Error querying credentials: {e}")
        db.disconnect()
        return 1

    # Cleanup
    db.disconnect()

    print("\n" + "=" * 80)
    print("✓ All tests passed successfully!")
    print("=" * 80)
    print("\nYou can now run: python main.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
