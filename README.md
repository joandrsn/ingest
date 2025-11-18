# Data Ingestion Framework

A maintainable Python framework for ingesting historical data from multiple utility providers into a PostgreSQL database.

## Supported Providers

1. **Eloverblik** - Power consumption data (refresh token authentication, 24-hour token validity)
2. **Techem** - Hot water, cold water, and heating data (username/password authentication, 15-minute token validity)
3. **Energidataservice** - Electricity price data (no authentication required)

## Features

- **Modular architecture** - Easy to add new providers
- **Automatic token management** - Tokens are cached in the database and refreshed when needed
- **Error isolation** - If one provider fails, others continue to run
- **Database-first design** - Configuration is stored in the database
- **Comprehensive logging** - All operations are logged to console and file

## Project Structure

```
ingest/
├── main.py                  # Main orchestration script
├── config.py               # Configuration management
├── requirements.txt        # Python dependencies
├── schema.sql             # Database schema
├── .env.example           # Example environment variables
├── providers/             # Provider implementations
│   ├── __init__.py
│   ├── base_provider.py           # Abstract base class
│   ├── eloverblik_provider.py     # Eloverblik implementation
│   ├── techem_provider.py         # Techem implementation
│   └── energidataservice_provider.py  # Energidataservice implementation
└── utils/                 # Utility modules
    ├── __init__.py
    └── database.py        # Database connection manager
```

## Setup Instructions

### 1. Prerequisites

- Python 3.8 or later
- PostgreSQL database
- API credentials:
  - Eloverblik: Refresh token (generate from Eloverblik portal)
  - Techem: Username and password
  - Energidataservice: No credentials needed

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Database Setup

Create your database and run the schema:

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE ingest;

# Connect to the database
\c ingest

# Run the schema
\i schema.sql
```

The schema will create:
- Credentials storage with automatic token caching
- Source definitions (Eloverblik, Techem, Energidataservice)
- Meter configurations
- Reading storage with automatic deduplication

### 4. Configure Environment Variables

Copy the example file and edit with your values:

```bash
cp .env.example .env
```

Edit `.env` with your database credentials:

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ingest
DB_USER=postgres
DB_PASSWORD=your_password
```

### 5. Configure Credentials in Database

Your credentials are already in the database from the schema.sql file. Update them if needed:

```sql
-- Update Eloverblik refresh token
UPDATE credential 
SET refreshtoken = 'your_actual_refresh_token'
WHERE credential_id = 1;

-- Update Techem credentials
UPDATE credential 
SET username = 'your_username', password = 'your_password'
WHERE credential_id = 2;
```

### 6. Configure Meters

Update the meter identifiers in the database to match your actual meters:

```sql
-- Update meter identifiers
UPDATE meter SET identifier = 'your_actual_meter_id' WHERE utility_id = 1;  -- Electricity
UPDATE meter SET identifier = 'your_heating_meter_id' WHERE utility_id = 2;  -- Heating
-- etc.
```

## Usage

Run the main ingestion script:

```bash
python main.py
```

By default, this fetches data for the last 7 days. You can modify the date range in `main.py`.

### What Happens

1. **Database Connection** - Connects to PostgreSQL
2. **For Each Provider**:
   - Authenticates (or skips if no auth required)
   - Fetches meters from database
   - Retrieves data for configured date range
   - Inserts readings into database (duplicates are automatically handled)
3. **Error Handling** - If one provider fails, others continue
4. **Logging** - Results are logged to console and `ingest.log`

## Adding a New Provider

To add a new data provider:

1. Create a new file in `providers/` (e.g., `newprovider_provider.py`)
2. Inherit from `BaseProvider`
3. Implement `authenticate()` and `fetch_data()` methods
4. Add to `provider_classes` list in `main.py`
5. Add source and credentials to database

Example:

```python
from providers.base_provider import BaseProvider

class NewProvider(BaseProvider):
    def __init__(self, db_connection):
        super().__init__(db_connection, 'NewProvider')
        
    def authenticate(self) -> bool:
        # Implement authentication logic
        pass
        
    def fetch_data(self, start_date, end_date):
        # Implement data fetching logic
        pass
```

## Configuration

### Environment Variables

See `.env.example` for all available configuration options.

### Database Configuration

All provider-specific configuration (credentials, meters) is stored in the database:

- **credential** table - Authentication information and token caching
- **source** table - Provider definitions
- **meter** table - Meter configurations with identifiers and resolutions
- **utility** table - Utility types (electricity, heating, water)

## Logging

Logs are written to:
- Console (stdout)
- `ingest.log` file

Log level can be configured via `LOG_LEVEL` environment variable (DEBUG, INFO, WARNING, ERROR).

## Notes

### API-Specific Details

**Eloverblik:**
- Access tokens are valid for 24 hours
- API has rate limits (120 calls/minute per IP)
- Can fetch up to 730 days of data per request

**Techem:**
- Access tokens are valid for 15 minutes
- The implementation includes placeholder URLs - update with actual Techem API endpoints
- Adjust the authentication and data parsing logic based on actual API documentation

**Energidataservice:**
- No authentication required
- The implementation includes placeholder for price area (DK1/DK2) - adjust as needed
- Prices are converted from MWh to kWh

## Troubleshooting

**Connection errors:**
- Verify database credentials in `.env`
- Ensure PostgreSQL is running
- Check network connectivity

**Authentication errors:**
- Verify credentials in database are correct
- Check token expiration dates
- Review API rate limits

**No data fetched:**
- Verify meter identifiers match your actual meters
- Check date range is within provider limits
- Review logs for specific error messages

## License

This project is for personal use.
