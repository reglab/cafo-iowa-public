# cafo_iowa Package

This directory contains the main Python package for processing and analyzing CAFO data in Iowa.

## Directory Structure

- `data/`: Data ingestion and processing scripts
  - `ingest.py`: Scripts for importing raw data into the database
  - `img_ingest.py`: Scripts for downloading and processing satellite imagery
  - `process.py`: Data cleaning and processing scripts
  - `img_process.py`: Image processing and tiling scripts
  - `helpers/`: Helper functions for data and image processing
  - `cfg/`: Configuration files

- `db/`: Database management
  - `models.py`: SQLAlchemy models for database tables
  - `session.py`: Database session management
  - `funs.py`: Database utility functions
  - `migrations/`: Alembic migration scripts

- `utils/`: Utility functions
  - `utils.py`: General utility functions
  - Other utility modules

- `estimate/`: Animal capacity estimation code
  - Functions for calculating animal capacity based on barn footprints

## Key Components

### Data Storage

While raw data files are stored in the project's `data/` directory, all processed data is stored in a PostgreSQL database. This includes:
- Raw data after ingestion
- Processed and cleaned data
- Relationships between different data sources
- Analysis results

The database must be set up and configured before running any data processing scripts. See the main README.md for setup instructions.

### Data Processing

The data processing pipeline consists of three main stages:

1. **Data Ingestion** (`data/ingest.py`):
   - Imports raw data from various sources (permits, parcels, NAIP tiles)
   - Standardizes coordinate systems and formats
   - Stores data in raw database tables

2. **Image Processing** (`data/img_process.py`):
   - Downloads NAIP satellite imagery from Google Cloud Storage
   - Processes and tiles images
   - Masks urban areas
   - Converts to appropriate formats for analysis

3. **Data Processing** (`data/process.py`):
   - Cleans and standardizes data
   - Creates relationships between permits, parcels, and facilities
   - Processes hand-labeled annotations
   - Generates final processed tables

### Database Structure

The database is organized into two main schemas:
- `raw`: Contains unprocessed data from various sources
- `processed`: Contains cleaned and processed data with established relationships

Database migrations are managed using Alembic, with migration scripts located in `db/migrations/`. To apply migrations:

```bash
alembic upgrade head
```

Key tables include:
- `permits`: CAFO permit information
- `parcels`: Land parcel records
- `facilities`: CAFO facilities
- `barns`: Individual barn structures
- `barn_clusters`: Groups of related barns
- `cf_annotations`: Hand-labeled barn annotations

## Usage

See the main README.md for detailed usage instructions.
