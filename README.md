# Data Ingestion Framework

A maintainable Python framework for ingesting historical data from multiple utility providers, and car usage, into a PostgreSQL database.

## Supported Providers

1. **Eloverblik** - Power consumption data (refresh token authentication, 24-hour token validity)
2. **Techem** - Hot water, cold water, and heating data (username/password authentication, 15-minute token validity)
3. **Energidataservice** - Electricity price data (no authentication required)
4. **ConnectedCars** - Car trips, routes and refuel events (email/password authentication, 1-hour token validity)

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
│   ├── base_provider.py           # Abstract base class: source, credentials, token
│   ├── meter_reading_provider.py  # Base class for providers that store meter readings
│   ├── eloverblik_provider.py     # Eloverblik implementation
│   ├── techem_provider.py         # Techem implementation
│   ├── energidataservice_provider.py  # Energidataservice implementation
│   ├── connectedcars_client.py    # ConnectedCars API client (HTTP only)
│   └── connectedcars_provider.py  # ConnectedCars implementation
├── tests/                 # Unit tests (python -m unittest discover tests)
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
2. Inherit from `MeterReadingProvider` if the data is one value per meter per
   timestamp. Otherwise inherit from `BaseProvider` and implement `run()` with
   your own tables, as `ConnectedCarsProvider` does
3. Implement `authenticate()` and `fetch_data()` methods
4. Add to `provider_classes` list in `main.py`
5. Add source and credentials to database

Example:

```python
from providers.meter_reading_provider import MeterReadingProvider

class NewProvider(MeterReadingProvider):
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
- Run `schema_electricity_price.sql` to set up the price meters and the `electricity_price` view
- Each meter is one price component (spot, grid tariff, grid discount, Energinet tariffs, elafgift),
  stored in DKK/kWh excluding VAT, with UTC timestamps: hourly before `QUARTERLY_FROM`
  (default 2025-12-01, when the meter switched to 15-minute readings) and per quarter-hour after
- Backfill from a date with `python main.py 2025-12-01`
- The meter identifier decides what is fetched: `spot:<PriceArea>` or `tariff:<GLN_Number>:<ChargeTypeCode>`
- The `electricity_price` view shows the breakdown per hour and the total including VAT and supplier markup
- The DatahubPricelist dataset allows roughly one request per minute
- `check_meter_resolution.py` shows whether your Eloverblik meter is read hourly or every 15 minutes

**ConnectedCars:**
- Run `schema_car.sql`, then set the email and password of your ConnectedCars account
  (the login of the Min Volkswagen app) on the credential row it creates; the file shows how
- `CONNECTEDCARS_NAMESPACE` in `.env` is the brand app: `minvolkswagen` (default), `minskoda`,
  `minseat` or `mitaudi`
- Stores `vehicle`, `car_trip`, `car_trip_position` (the route, with speed) and
  `car_refuel_event`; vehicles are created from the account. Rows are upserted on the
  provider's ids, so a period can be fetched again. Zero-distance trips are not fetched
- Backfill from a date with `python main.py 2022-08-01`
- `car_trip.fuel_used_l` is an estimate from the fuel gauge spread over the distance driven:
  trips on the same day get nearly the same km/l. Use it for totals, not to compare trips
- Refuel events are whole litres from the gauge, which tops out before the tank is full
- The `car_usage_monthly` view shows trips, distance, hours, fuel and long trips per month
- `probe_connectedcars.py` is a read-only tool for exploring the API. It reads
  `CONNECTEDCARS_EMAIL` and `CONNECTEDCARS_PASSWORD` from `.env`

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
